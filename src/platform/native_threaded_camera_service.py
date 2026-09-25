from __future__ import annotations

from collections import defaultdict
import sys
import time

import cv2

from src.platform.camera_performance_profile import (
    CameraPerformanceResult,
    calculate_camera_performance,
    select_best_camera_performance,
)
from src.platform.frame_integrity import FrameIntegrityValidator
from src.platform.linux_camera_backend import (
    LinuxCameraBackendCandidate,
    construir_candidatos_linux,
    descobrir_dispositivos_video,
    opencv_tem_gstreamer,
)
from src.platform.desktop_settings import (
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_RESOLUTION_FALLBACKS,
    CAMERA_SCAN_MAX_INDEX,
    CAMERA_WIDTH,
)
from src.platform.threaded_camera_service import (
    ThreadedDesktopCameraService,
)


class NativeResolutionThreadedCameraService(
    ThreadedDesktopCameraService
):
    """Seleciona o maior perfil confortável, usando 1080p30 como referência."""

    BENCHMARK_WARMUP_FRAMES = 5
    BENCHMARK_SAMPLE_FRAMES = 16
    BENCHMARK_WARMUP_TIMEOUT_S = 0.35
    BENCHMARK_SAMPLE_TIMEOUT_S = 0.85
    BENCHMARK_CANDIDATES_PER_RESOLUTION = 2
    BENCHMARK_TARGET_CANDIDATES = 3

    def __init__(self, *args, **kwargs) -> None:
        self._candidato_aberto: LinuxCameraBackendCandidate | None = None
        self._benchmark_concluido = False
        self._candidatos_ordenados: tuple[
            LinuxCameraBackendCandidate, ...
        ] = ()
        self._resultados_benchmark: tuple[
            CameraPerformanceResult, ...
        ] = ()
        self._resultado_selecionado: CameraPerformanceResult | None = None
        super().__init__(*args, **kwargs)

    @staticmethod
    def _prioridade_backend(
        candidato: LinuxCameraBackendCandidate,
    ) -> tuple[int, int]:
        tipo = str(candidato.tipo).lower()
        formato = str(candidato.formato).upper()
        prioridade = {
            ("gstreamer", "MJPG"): 0,
            ("v4l2", "MJPG"): 1,
            ("gstreamer", "YUY2"): 2,
            ("v4l2", "YUY2"): 3,
            ("auto", "AUTO"): 4,
        }.get((tipo, formato), 5)
        return prioridade, int(candidato.indice or 0)

    def _candidatos_linux_brutos(
        self,
    ) -> tuple[LinuxCameraBackendCandidate, ...]:
        dispositivos = descobrir_dispositivos_video(
            indice_solicitado=self._indice_camera_solicitado,
            indice_ativo=self._indice_camera_ativo,
            indice_maximo=CAMERA_SCAN_MAX_INDEX,
        )
        return construir_candidatos_linux(
            dispositivos=dispositivos,
            largura=self.largura,
            altura=self.altura,
            fps=max(1, int(self.fps or CAMERA_FPS)),
            gstreamer_disponivel=opencv_tem_gstreamer(),
            resolucoes_preferidas=CAMERA_RESOLUTION_FALLBACKS,
        )

    def _candidatos_linux(
        self,
    ) -> tuple[LinuxCameraBackendCandidate, ...]:
        if self._candidatos_ordenados:
            return self._candidatos_ordenados
        return self._candidatos_linux_brutos()

    def _configurar_capture_direto(
        self,
        capture,
        candidato: LinuxCameraBackendCandidate,
    ) -> None:
        if candidato.tipo == "auto":
            return

        if candidato.formato in ("MJPG", "YUY2"):
            fourcc = (
                "MJPG"
                if candidato.formato == "MJPG"
                else "YUYV"
            )
            try:
                capture.set(
                    cv2.CAP_PROP_FOURCC,
                    cv2.VideoWriter_fourcc(*fourcc),
                )
            except Exception:
                pass

        largura = max(1, int(candidato.largura or self.largura))
        altura = max(1, int(candidato.altura or self.altura))
        fps = max(1, int(self.fps or CAMERA_FPS))

        for propriedade, valor in (
            (cv2.CAP_PROP_FRAME_WIDTH, largura),
            (cv2.CAP_PROP_FRAME_HEIGHT, altura),
            (cv2.CAP_PROP_FPS, fps),
        ):
            try:
                capture.set(propriedade, valor)
            except Exception:
                pass

        try:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 2)
        except Exception:
            pass

    def _criar_capture_benchmark(
        self,
        candidato: LinuxCameraBackendCandidate,
    ):
        try:
            capture = cv2.VideoCapture(
                candidato.origem,
                candidato.backend,
            )
        except Exception:
            return None

        if capture is None or not capture.isOpened():
            if capture is not None:
                try:
                    capture.release()
                except Exception:
                    pass
            return None

        if candidato.tipo != "gstreamer":
            self._configurar_capture_direto(capture, candidato)
        return capture

    @staticmethod
    def _brilho_medio(frame) -> float:
        cinza = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        miniatura = cv2.resize(
            cinza,
            (160, 90),
            interpolation=cv2.INTER_AREA,
        )
        return float(miniatura.mean())

    def _avaliar_candidato(
        self,
        candidato: LinuxCameraBackendCandidate,
    ) -> CameraPerformanceResult:
        capture = self._criar_capture_benchmark(candidato)
        if capture is None:
            return calculate_camera_performance(
                candidate_key=candidato.key,
                width=candidato.largura,
                height=candidato.altura,
                timestamps=[],
                valid_flags=[],
                corrupted_flags=[],
                brightness_values=[],
                target_fps=max(1, int(self.fps or CAMERA_FPS)),
                target_resolution=(CAMERA_WIDTH, CAMERA_HEIGHT),
                reason="não abriu",
            )

        try:
            inicio_aquecimento = time.monotonic()
            aquecidos = 0
            while (
                aquecidos < self.BENCHMARK_WARMUP_FRAMES
                and time.monotonic() - inicio_aquecimento
                < self.BENCHMARK_WARMUP_TIMEOUT_S
            ):
                try:
                    sucesso, frame = capture.read()
                except Exception:
                    sucesso, frame = False, None
                frame = self._normalizar_frame(frame) if sucesso else None
                if self._frame_basico_valido(frame):
                    aquecidos += 1

            validador = FrameIntegrityValidator()
            timestamps: list[float] = []
            valid_flags: list[bool] = []
            corrupted_flags: list[bool] = []
            brightness_values: list[float] = []
            inicio_amostra = time.monotonic()

            while (
                len(valid_flags) < self.BENCHMARK_SAMPLE_FRAMES
                and time.monotonic() - inicio_amostra
                < self.BENCHMARK_SAMPLE_TIMEOUT_S
            ):
                try:
                    sucesso, frame = capture.read()
                except Exception:
                    sucesso, frame = False, None
                agora = time.monotonic()
                frame = self._normalizar_frame(frame) if sucesso else None
                valido = self._frame_basico_valido(frame)
                valid_flags.append(bool(valido))
                if not valido:
                    continue

                timestamps.append(agora)
                integridade = validador.avaliar(frame)
                corrupted_flags.append(not integridade.valido)
                brightness_values.append(self._brilho_medio(frame))

            return calculate_camera_performance(
                candidate_key=candidato.key,
                width=candidato.largura,
                height=candidato.altura,
                timestamps=timestamps,
                valid_flags=valid_flags,
                corrupted_flags=corrupted_flags,
                brightness_values=brightness_values,
                target_fps=max(1, int(self.fps or CAMERA_FPS)),
                target_resolution=(CAMERA_WIDTH, CAMERA_HEIGHT),
            )
        finally:
            try:
                capture.release()
            except Exception:
                pass

    def _agrupar_candidatos_benchmark(
        self,
        candidatos: tuple[LinuxCameraBackendCandidate, ...],
    ) -> dict[tuple[int, int], list[LinuxCameraBackendCandidate]]:
        grupos: dict[
            tuple[int, int], list[LinuxCameraBackendCandidate]
        ] = defaultdict(list)
        chaves: set[tuple[int, int, str, str]] = set()
        for candidato in candidatos:
            if candidato.largura <= 0 or candidato.altura <= 0:
                continue
            chave = (
                int(candidato.largura),
                int(candidato.altura),
                str(candidato.tipo),
                str(candidato.formato),
            )
            if chave in chaves:
                continue
            chaves.add(chave)
            grupos[(chave[0], chave[1])].append(candidato)

        for grupo in grupos.values():
            grupo.sort(key=self._prioridade_backend)
        return grupos

    @staticmethod
    def _ordem_resolucoes(
        grupos: dict[tuple[int, int], list[LinuxCameraBackendCandidate]],
    ) -> tuple[
        tuple[int, int],
        tuple[tuple[int, int], ...],
        tuple[tuple[int, int], ...],
    ]:
        alvo = (CAMERA_WIDTH, CAMERA_HEIGHT)
        pixels_alvo = alvo[0] * alvo[1]
        resolucoes = tuple(grupos.keys())
        superiores = tuple(
            sorted(
                (
                    resolucao
                    for resolucao in resolucoes
                    if resolucao[0] * resolucao[1] > pixels_alvo
                ),
                key=lambda item: item[0] * item[1],
            )
        )
        inferiores = tuple(
            sorted(
                (
                    resolucao
                    for resolucao in resolucoes
                    if resolucao[0] * resolucao[1] < pixels_alvo
                ),
                key=lambda item: item[0] * item[1],
                reverse=True,
            )
        )
        return alvo, superiores, inferiores

    def _avaliar_grupo(
        self,
        candidatos: list[LinuxCameraBackendCandidate],
        limite: int,
        resultados: list[CameraPerformanceResult],
    ) -> None:
        for candidato in candidatos[:max(1, int(limite))]:
            self._definir_estado(
                self.ESTADO_ESTABILIZANDO,
                f"Avaliando {candidato.nome}: fluidez e estabilidade...",
            )
            resultado = self._avaliar_candidato(candidato)
            resultados.append(resultado)
            if resultado.comfortable:
                break

    def _ordenar_fallbacks(
        self,
        candidatos: tuple[LinuxCameraBackendCandidate, ...],
        selecionado: CameraPerformanceResult,
        resultados: tuple[CameraPerformanceResult, ...],
    ) -> tuple[LinuxCameraBackendCandidate, ...]:
        resultados_por_chave = {
            resultado.candidate_key: resultado
            for resultado in resultados
        }
        pixels_selecionados = selecionado.pixels

        def chave(candidato: LinuxCameraBackendCandidate):
            pixels = max(0, candidato.largura * candidato.altura)
            resultado = resultados_por_chave.get(candidato.key)
            if candidato.key == selecionado.candidate_key:
                faixa = 0
            elif pixels == pixels_selecionados:
                faixa = 1
            elif 0 < pixels < pixels_selecionados:
                faixa = 2
            else:
                faixa = 3

            medido_confortavel = int(
                resultado is not None and resultado.comfortable
            )
            pontuacao = resultado.score if resultado is not None else -999.0
            resolucao_ordem = -pixels if faixa == 2 else pixels
            return (
                faixa,
                -medido_confortavel,
                -pontuacao,
                resolucao_ordem,
                self._prioridade_backend(candidato),
            )

        return tuple(sorted(candidatos, key=chave))

    def _executar_benchmark_linux(self) -> None:
        candidatos = self._candidatos_linux_brutos()
        if not candidatos:
            self._benchmark_concluido = True
            return

        grupos = self._agrupar_candidatos_benchmark(candidatos)
        alvo, superiores, inferiores = self._ordem_resolucoes(grupos)
        resultados: list[CameraPerformanceResult] = []

        if alvo in grupos:
            self._avaliar_grupo(
                grupos[alvo],
                self.BENCHMARK_TARGET_CANDIDATES,
                resultados,
            )

        alvo_confortavel = any(
            resultado.comfortable
            and (resultado.width, resultado.height) == alvo
            for resultado in resultados
        )

        if alvo_confortavel:
            for resolucao in superiores:
                self._avaliar_grupo(
                    grupos[resolucao],
                    self.BENCHMARK_CANDIDATES_PER_RESOLUTION,
                    resultados,
                )
        else:
            for resolucao in inferiores:
                self._avaliar_grupo(
                    grupos[resolucao],
                    self.BENCHMARK_CANDIDATES_PER_RESOLUTION,
                    resultados,
                )
                if any(
                    resultado.comfortable
                    and (resultado.width, resultado.height) == resolucao
                    for resultado in resultados
                ):
                    break

        resultados_tuple = tuple(resultados)
        selecionado = select_best_camera_performance(
            resultados_tuple,
            target_resolution=alvo,
        )
        self._resultados_benchmark = resultados_tuple
        self._resultado_selecionado = selecionado

        if selecionado is not None:
            self._candidatos_ordenados = self._ordenar_fallbacks(
                candidatos,
                selecionado,
                resultados_tuple,
            )
            self._backend_linux_cursor = 0
            self._definir_estado(
                self.ESTADO_ESTABILIZANDO,
                (
                    f"Perfil escolhido: {selecionado.width}x"
                    f"{selecionado.height} a {selecionado.measured_fps:.1f} FPS. "
                    "Abrindo fluxo definitivo..."
                ),
            )
        else:
            self._candidatos_ordenados = candidatos

        self._benchmark_concluido = True

    def _abrir_candidato_linux(
        self,
        candidato: LinuxCameraBackendCandidate,
    ):
        capture = super()._abrir_candidato_linux(candidato)
        if capture is not None:
            self._candidato_aberto = candidato
        return capture

    def _abrir_camera(self) -> bool:
        self._candidato_aberto = None
        if (
            sys.platform.startswith("linux")
            and not self._benchmark_concluido
        ):
            self._executar_benchmark_linux()

        abriu = super()._abrir_camera()
        if not abriu or not sys.platform.startswith("linux"):
            return abriu

        candidato = self._candidato_aberto
        if candidato is None:
            return abriu

        if candidato.largura > 0 and candidato.altura > 0:
            self._resolucao_solicitada = (
                int(candidato.largura),
                int(candidato.altura),
            )
        else:
            self._resolucao_solicitada = None

        self._fps_solicitado = max(1, int(self.fps or CAMERA_FPS))
        self._formato_solicitado = candidato.formato
        return abriu

    def obter_diagnostico_fluxo(self) -> dict:
        diagnostico = super().obter_diagnostico_fluxo()
        selecionado = self._resultado_selecionado
        diagnostico.update(
            {
                "benchmark_concluido": bool(self._benchmark_concluido),
                "perfil_equilibrio": (CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS),
                "perfil_selecionado": (
                    None
                    if selecionado is None
                    else {
                        "resolucao": (
                            selecionado.width,
                            selecionado.height,
                        ),
                        "fps": selecionado.measured_fps,
                        "comfortable": selecionado.comfortable,
                        "excellent": selecionado.excellent,
                        "score": selecionado.score,
                    }
                ),
                "benchmark_resultados": tuple(
                    {
                        "key": resultado.candidate_key,
                        "resolucao": (
                            resultado.width,
                            resultado.height,
                        ),
                        "fps": resultado.measured_fps,
                        "valid_ratio": resultado.valid_ratio,
                        "corrupted_ratio": resultado.corrupted_ratio,
                        "flicker_ratio": resultado.flicker_ratio,
                        "jitter_ratio": resultado.jitter_ratio,
                        "comfortable": resultado.comfortable,
                        "excellent": resultado.excellent,
                        "score": resultado.score,
                    }
                    for resultado in self._resultados_benchmark
                ),
            }
        )
        return diagnostico
