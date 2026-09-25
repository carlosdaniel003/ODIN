from __future__ import annotations

from collections import deque
import math
import sys
import threading
import time

import cv2

from src.infra.camera_service import CameraService, CameraSnapshot
from src.platform.frame_integrity import FrameIntegrityValidator
from src.platform.linux_camera_backend import (
    LinuxCameraBackendCandidate,
    construir_candidatos_linux,
    descobrir_dispositivos_video,
    opencv_tem_gstreamer,
)
from src.platform.raspberry_camera_service import RaspberryPi3CameraService
from src.platform.raspberry_pi3_settings import CAMERA_SCAN_MAX_INDEX
from src.platform.v4l2_controls import V4L2ControlManager


class ThreadedRaspberryPi3CameraService(RaspberryPi3CameraService):
    """Câmera contínua com último frame íntegro, sem bloquear o Tkinter."""

    FRAMES_CORROMPIDOS_ANTES_RECONEXAO = 15
    FRAMES_ESTAVEIS_MINIMOS = 2
    MOVIMENTO_ESTAVEL_MAXIMO = 10.0
    VARIACAO_BRILHO_ESTAVEL_MAXIMA = 8.0
    ESPERA_THREAD_PARAR_S = 1.2
    ATRASO_TROCA_BACKEND_S = 0.03
    FRAMES_TESTE_BACKEND = 3

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._stop_event = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._frame_condition = threading.Condition(self._lock)
        self._validador_integridade = FrameIntegrityValidator()

        self._frames_validos_sessao = 0
        self._frames_corrompidos_consecutivos = 0
        self._frames_corrompidos_total = 0
        self._frames_lidos_total = 0
        self._leituras_falhas_total = 0
        self._ultimo_motivo_descarte = ""
        self._miniatura_estabilidade = None
        self._brilho_estabilidade: float | None = None
        self._frames_estaveis_consecutivos = 0
        self._ultimo_frame_estavel = None
        self._ultimo_frame_estavel_id = -1
        self._controles_automaticos_travados = False

        self._backend_linux_cursor = 0
        self._backend_trocas_total = 0
        self._backend_ativo_key = ""
        self._backend_ativo_tipo = ""
        self._backend_ativo_dispositivo = ""
        self._backend_ativo_formato = ""
        self._timestamps_frames: deque[float] = deque(maxlen=61)

    def iniciar(self) -> None:
        if self._ativo:
            return

        self._ativo = True
        self._falhas_consecutivas = 0
        self._proxima_reconexao_em = 0.0
        self._stop_event.clear()
        self._definir_estado(
            self.ESTADO_CONECTANDO,
            "Procurando câmera disponível...",
        )
        self._capture_thread = threading.Thread(
            target=self._loop_captura,
            name="odin-camera-capture",
            daemon=True,
        )
        self._capture_thread.start()

    def parar(self) -> None:
        self._ativo = False
        self._stop_event.set()
        with self._frame_condition:
            self._frame_condition.notify_all()

        thread = self._capture_thread
        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=self.ESPERA_THREAD_PARAR_S)

        if thread is not None and thread.is_alive():
            self._liberar_camera()
            thread.join(timeout=0.35)

        self._capture_thread = None
        self._liberar_camera()
        self._reiniciar_estado_fluxo()
        self._definir_estado(self.ESTADO_PARADA, "Câmera parada.")

    def atualizar_configuracoes_camera(
        self,
        configuracoes_camera: dict | None,
    ) -> None:
        CameraService.atualizar_configuracoes_camera(
            self,
            configuracoes_camera,
        )
        self._controles_automaticos_travados = False

    def obter_snapshot(
        self,
        ultimo_frame_id: int = -1,
    ) -> CameraSnapshot:
        with self._lock:
            frame = None
            if (
                self._ultimo_frame is not None
                and self._frame_id != ultimo_frame_id
            ):
                frame = self._ultimo_frame

            return CameraSnapshot(
                estado=self._estado,
                mensagem=self._mensagem,
                frame_id=self._frame_id,
                frame=frame,
                resolucao=self._resolucao,
                resolucao_solicitada=self._resolucao_solicitada,
                fps_solicitado=self._fps_solicitado,
                fps_real=self._fps_real,
                formato_solicitado=self._formato_solicitado,
                formato_real=self._formato_real,
            )

    def obter_ultimo_frame_estavel(self):
        with self._lock:
            if self._ultimo_frame_estavel is None:
                return None
            return (
                int(self._ultimo_frame_estavel_id),
                self._ultimo_frame_estavel.copy(),
            )

    def aguardar_proximo_frame_estavel(
        self,
        depois_frame_id: int = -1,
        timeout_s: float = 0.30,
    ):
        limite = time.monotonic() + max(0.0, float(timeout_s))
        with self._frame_condition:
            while self._ativo and not self._stop_event.is_set():
                if (
                    self._ultimo_frame_estavel is not None
                    and self._ultimo_frame_estavel_id > int(depois_frame_id)
                ):
                    return (
                        int(self._ultimo_frame_estavel_id),
                        self._ultimo_frame_estavel.copy(),
                    )

                restante = limite - time.monotonic()
                if restante <= 0:
                    return None
                self._frame_condition.wait(timeout=restante)
        return None

    def obter_diagnostico_fluxo(self) -> dict:
        with self._lock:
            return {
                "frames_lidos_total": int(self._frames_lidos_total),
                "leituras_falhas_total": int(self._leituras_falhas_total),
                "frames_corrompidos_total": int(
                    self._frames_corrompidos_total
                ),
                "frames_corrompidos_consecutivos": int(
                    self._frames_corrompidos_consecutivos
                ),
                "ultimo_motivo_descarte": self._ultimo_motivo_descarte,
                "frames_estaveis_consecutivos": int(
                    self._frames_estaveis_consecutivos
                ),
                "ultimo_frame_estavel_id": int(
                    self._ultimo_frame_estavel_id
                ),
                "backend_ativo": getattr(
                    self,
                    "_backend_name",
                    "",
                ),
                "backend_tipo": self._backend_ativo_tipo,
                "backend_dispositivo": self._backend_ativo_dispositivo,
                "backend_formato": self._backend_ativo_formato,
                "backend_trocas_total": int(self._backend_trocas_total),
                "fps_medido": self._fps_real,
                "gstreamer_disponivel": opencv_tem_gstreamer(),
                "thread_ativa": bool(
                    self._capture_thread is not None
                    and self._capture_thread.is_alive()
                ),
            }

    def _reiniciar_estado_fluxo(self) -> None:
        self._validador_integridade.reset()
        self._frames_validos_sessao = 0
        self._frames_corrompidos_consecutivos = 0
        self._miniatura_estabilidade = None
        self._brilho_estabilidade = None
        self._frames_estaveis_consecutivos = 0
        self._timestamps_frames.clear()
        with self._lock:
            self._ultimo_frame_estavel = None
            self._ultimo_frame_estavel_id = -1
        self._controles_automaticos_travados = False

    def _candidatos_linux(
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
            fps=max(1, int(self.fps or 30)),
            gstreamer_disponivel=opencv_tem_gstreamer(),
        )

    def _configurar_capture_direto(
        self,
        capture,
        candidato: LinuxCameraBackendCandidate,
    ) -> None:
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

        for propriedade, valor in (
            (cv2.CAP_PROP_FRAME_WIDTH, self.largura),
            (cv2.CAP_PROP_FRAME_HEIGHT, self.altura),
            (cv2.CAP_PROP_FPS, max(1, int(self.fps or 30))),
        ):
            try:
                capture.set(propriedade, valor)
            except Exception:
                pass

        try:
            # O serviço já drena a câmera continuamente em thread própria.
            # Buffer 1 evita apresentar frames antigos quando a UI sofre pico de CPU.
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

    def _abrir_candidato_linux(
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

        frames_validos = 0
        for _ in range(self.FRAMES_TESTE_BACKEND):
            try:
                sucesso, frame = capture.read()
            except Exception:
                sucesso, frame = False, None
            frame = self._normalizar_frame(frame) if sucesso else None
            if self._frame_basico_valido(frame):
                frames_validos += 1

        if frames_validos <= 0:
            try:
                capture.release()
            except Exception:
                pass
            return None
        return capture

    def _abrir_camera(self) -> bool:
        if not sys.platform.startswith("linux"):
            return super()._abrir_camera()

        self._liberar_camera()
        candidatos = self._candidatos_linux()
        if not candidatos:
            self._agendar_reconexao(
                "Nenhum dispositivo de vídeo Linux foi encontrado."
            )
            return False

        inicio = self._backend_linux_cursor % len(candidatos)
        ordem = [
            (inicio + deslocamento) % len(candidatos)
            for deslocamento in range(len(candidatos))
        ]
        nomes = ", ".join(
            candidatos[indice].nome
            for indice in ordem[:4]
        )
        self._definir_estado(
            self.ESTADO_ESTABILIZANDO,
            f"Abrindo câmera. Pipelines preferidas: {nomes}...",
        )

        for indice in ordem:
            candidato = candidatos[indice]
            capture = self._abrir_candidato_linux(candidato)
            if capture is None:
                continue

            self._capture = capture
            self._backend_linux_cursor = indice
            self._backend_ativo_key = candidato.key
            self._backend_ativo_tipo = candidato.tipo
            self._backend_ativo_dispositivo = candidato.dispositivo
            self._backend_ativo_formato = candidato.formato
            self._backend_name = candidato.nome
            self._formato_real = candidato.formato
            if candidato.indice is not None:
                self.indice_camera = int(candidato.indice)
                self._indice_camera_ativo = int(candidato.indice)

            self._controles_pendentes = True
            self._falhas_consecutivas = 0
            self._definir_estado(
                self.ESTADO_ESTABILIZANDO,
                (
                    f"Câmera aberta via {candidato.nome} em "
                    f"{candidato.dispositivo}. Estabilizando..."
                ),
            )
            return True

        self._backend_linux_cursor = (inicio + 1) % len(candidatos)
        self._agendar_reconexao(
            "Nenhuma pipeline de câmera entregou frames válidos."
        )
        return False

    def _trocar_backend_linux(self, motivo: str) -> None:
        candidatos = self._candidatos_linux()
        if candidatos:
            self._backend_linux_cursor = (
                self._backend_linux_cursor + 1
            ) % len(candidatos)
        self._backend_trocas_total += 1
        self._liberar_camera()
        self._proxima_reconexao_em = (
            time.monotonic() + self.ATRASO_TROCA_BACKEND_S
        )
        self._reiniciar_estado_fluxo()
        estado = (
            self.ESTADO_CONECTADA
            if self._ultimo_frame is not None
            else self.ESTADO_ESTABILIZANDO
        )
        self._definir_estado(
            estado,
            f"{motivo} Alternando pipeline da câmera...",
        )

    def _loop_captura(self) -> None:
        try:
            while self._ativo and not self._stop_event.is_set():
                if self._capture is None:
                    espera = (
                        self._proxima_reconexao_em
                        - time.monotonic()
                    )
                    if espera > 0:
                        self._stop_event.wait(min(espera, 0.10))
                        continue
                    if not self._abrir_camera():
                        self._stop_event.wait(0.05)
                        continue
                    self._reiniciar_estado_fluxo()

                capture = self._capture
                if capture is None:
                    continue

                try:
                    sucesso, frame = capture.read()
                except Exception:
                    sucesso, frame = False, None

                self._frames_lidos_total += 1
                frame = (
                    self._normalizar_frame(frame)
                    if sucesso
                    else None
                )
                if not self._frame_basico_valido(frame):
                    self._leituras_falhas_total += 1
                    self._falhas_consecutivas += 1
                    if (
                        self._falhas_consecutivas
                        >= self.falhas_antes_reconexao
                    ):
                        if sys.platform.startswith("linux"):
                            self._trocar_backend_linux(
                                "A câmera parou de entregar "
                                "frames válidos."
                            )
                        else:
                            self._agendar_reconexao(
                                "A câmera parou de entregar "
                                "frames válidos."
                            )
                            self._reiniciar_estado_fluxo()
                    else:
                        self._stop_event.wait(0.005)
                    continue

                self._falhas_consecutivas = 0
                primeiro_frame = self._frames_validos_sessao == 0
                if primeiro_frame:
                    self._registrar_parametros_reais(
                        capture,
                        frame,
                    )
                    if self._backend_ativo_formato:
                        self._formato_real = (
                            self._backend_ativo_formato
                        )
                    self._aplicar_configuracoes_hardware()
                elif self._controles_pendentes:
                    self._aplicar_configuracoes_hardware()
                    self._controles_automaticos_travados = False

                frame_processado = self._aplicar_rotacao(frame)
                integridade = self._validador_integridade.avaliar(
                    frame_processado
                )
                if not integridade.valido:
                    self._frames_corrompidos_total += 1
                    self._frames_corrompidos_consecutivos += 1
                    self._ultimo_motivo_descarte = integridade.motivo
                    if (
                        self._frames_corrompidos_consecutivos
                        >= self.FRAMES_CORROMPIDOS_ANTES_RECONEXAO
                    ):
                        if sys.platform.startswith("linux"):
                            self._trocar_backend_linux(
                                "A pipeline produziu "
                                "frames corrompidos."
                            )
                        else:
                            self._agendar_reconexao(
                                "Frames com bandas horizontais "
                                "foram descartados."
                            )
                            self._reiniciar_estado_fluxo()
                    continue

                self._frames_corrompidos_consecutivos = 0
                self._frames_validos_sessao += 1
                estavel = self._avaliar_estabilidade(
                    frame_processado
                )
                self._publicar_frame_otimizado(
                    frame_processado,
                    estavel=estavel,
                )

                if (
                    not self._controles_automaticos_travados
                    and self._frames_validos_sessao
                    >= max(8, int(self.frames_aquecimento))
                    and self._frames_estaveis_consecutivos
                    >= self.FRAMES_ESTAVEIS_MINIMOS
                ):
                    self._travar_controles_automaticos_atuais()
        finally:
            self._liberar_camera()
            with self._frame_condition:
                self._frame_condition.notify_all()

    @staticmethod
    def _miniatura_cinza(frame):
        cinza = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.resize(
            cinza,
            (160, 120),
            interpolation=cv2.INTER_AREA,
        )

    def _avaliar_estabilidade(self, frame) -> bool:
        miniatura = self._miniatura_cinza(frame)
        brilho = float(miniatura.mean())
        anterior = self._miniatura_estabilidade
        brilho_anterior = self._brilho_estabilidade
        self._miniatura_estabilidade = miniatura
        self._brilho_estabilidade = brilho

        if anterior is None or brilho_anterior is None:
            self._frames_estaveis_consecutivos = 1
            return False

        movimento = float(
            cv2.absdiff(miniatura, anterior).mean()
        )
        variacao_brilho = abs(brilho - brilho_anterior)
        estavel = (
            movimento <= self.MOVIMENTO_ESTAVEL_MAXIMO
            and variacao_brilho
            <= self.VARIACAO_BRILHO_ESTAVEL_MAXIMA
        )
        if estavel:
            self._frames_estaveis_consecutivos += 1
        else:
            self._frames_estaveis_consecutivos = 0

        return (
            self._frames_estaveis_consecutivos
            >= self.FRAMES_ESTAVEIS_MINIMOS
        )

    def _publicar_frame_otimizado(
        self,
        frame,
        estavel: bool,
    ) -> None:
        altura, largura = frame.shape[:2]
        backend_name = getattr(
            self,
            "_backend_name",
            "automático",
        )
        agora = time.monotonic()
        self._timestamps_frames.append(agora)
        fps_medido = None
        if len(self._timestamps_frames) >= 2:
            duracao = (
                self._timestamps_frames[-1]
                - self._timestamps_frames[0]
            )
            if duracao > 0:
                fps_medido = (
                    len(self._timestamps_frames) - 1
                ) / duracao

        with self._frame_condition:
            self._ultimo_frame = frame
            self._frame_id += 1
            frame_id = int(self._frame_id)
            self._resolucao = (largura, altura)
            if (
                fps_medido is not None
                and math.isfinite(fps_medido)
            ):
                self._fps_real = round(float(fps_medido), 2)
            self._estado = self.ESTADO_CONECTADA
            self._mensagem = (
                f"Câmera conectada via {backend_name}. "
                f"Resolução real: {largura}x{altura}."
            )
            if estavel:
                self._ultimo_frame_estavel = frame
                self._ultimo_frame_estavel_id = frame_id
            self._frame_condition.notify_all()

    @staticmethod
    def _ler_propriedade_finita(
        capture,
        propriedade: int | None,
    ):
        if propriedade is None:
            return None
        try:
            valor = float(capture.get(propriedade))
        except Exception:
            return None
        return valor if math.isfinite(valor) else None

    @staticmethod
    def _definir_propriedade(
        capture,
        propriedade: int | None,
        valor,
    ) -> bool:
        if propriedade is None or valor is None:
            return False
        try:
            return bool(
                capture.set(
                    propriedade,
                    float(valor),
                )
            )
        except Exception:
            return False

    def _travar_controles_v4l2(
        self,
        configuracoes: dict,
    ) -> set[str]:
        if (
            not sys.platform.startswith("linux")
            or not self._backend_ativo_dispositivo
        ):
            return set()

        manager = V4L2ControlManager(
            self._backend_ativo_dispositivo
        )
        resultados = manager.congelar_automaticos(
            configuracoes
        )
        mapa = {
            "exposure_auto": (
                "exposure_auto",
                "auto_exposure",
            ),
            "exposure_absolute": (
                "exposure_auto",
                "exposure",
            ),
            "focus_auto": (
                "focus_auto",
                "autofocus",
            ),
            "focus_absolute": (
                "focus_auto",
                "focus",
            ),
            "white_balance_temperature_auto": (
                "white_balance_auto",
                "auto_white_balance",
            ),
            "white_balance_temperature": (
                "white_balance_auto",
                "white_balance",
            ),
        }
        travados: set[str] = set()
        for controle, resultado in resultados.items():
            chave_config, nome_status = mapa.get(
                controle,
                ("", controle),
            )
            if not resultado.aplicado:
                continue
            if chave_config:
                travados.add(chave_config)
            self._registrar_status_controle(
                nome_status,
                "travado_producao_v4l2",
                valor_solicitado=resultado.valor,
                valor_lido=resultado.valor,
            )
        return travados

    def _travar_controles_automaticos_atuais(self) -> None:
        capture = self._capture
        if capture is None:
            return
        configuracoes = self.obter_configuracoes_camera()
        travados_v4l2 = self._travar_controles_v4l2(
            configuracoes
        )

        controles = (
            (
                "exposure_auto",
                "auto_exposure",
                getattr(cv2, "CAP_PROP_AUTO_EXPOSURE", None),
                self._valor_auto_exposure(False),
                "exposure",
                getattr(cv2, "CAP_PROP_EXPOSURE", None),
            ),
            (
                "focus_auto",
                "autofocus",
                getattr(cv2, "CAP_PROP_AUTOFOCUS", None),
                0.0,
                "focus",
                getattr(cv2, "CAP_PROP_FOCUS", None),
            ),
            (
                "white_balance_auto",
                "auto_white_balance",
                getattr(cv2, "CAP_PROP_AUTO_WB", None),
                0.0,
                "white_balance",
                getattr(
                    cv2,
                    "CAP_PROP_WB_TEMPERATURE",
                    None,
                ),
            ),
        )

        for (
            chave_auto,
            nome_auto,
            propriedade_auto,
            valor_auto_desligado,
            nome_manual,
            propriedade_manual,
        ) in controles:
            if (
                not bool(configuracoes.get(chave_auto, True))
                or chave_auto in travados_v4l2
            ):
                continue

            valor_atual = self._ler_propriedade_finita(
                capture,
                propriedade_manual,
            )
            auto_desligado = self._definir_propriedade(
                capture,
                propriedade_auto,
                valor_auto_desligado,
            )
            valor_fixado = self._definir_propriedade(
                capture,
                propriedade_manual,
                valor_atual,
            )
            self._registrar_status_controle(
                nome_auto,
                (
                    "travado_producao"
                    if auto_desligado
                    else "nao_suportado"
                ),
                valor_solicitado=valor_auto_desligado,
                valor_lido=valor_atual,
            )
            if valor_fixado:
                self._registrar_status_controle(
                    nome_manual,
                    "travado_producao",
                    valor_solicitado=valor_atual,
                    valor_lido=valor_atual,
                )

        self._controles_automaticos_travados = True


# Nome canônico desktop; implementação única preservada.
ThreadedDesktopCameraService = ThreadedRaspberryPi3CameraService
