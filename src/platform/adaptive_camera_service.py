from __future__ import annotations

import sys
import time

from src.platform.camera_performance_profile import (
    CameraPerformanceResult,
    calculate_camera_performance,
)
from src.platform.frame_integrity import FrameIntegrityValidator
from src.platform.linux_camera_backend import LinuxCameraBackendCandidate
from src.platform.native_threaded_camera_service import (
    NativeResolutionThreadedCameraService,
)
from src.platform.desktop_settings import (
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_WIDTH,
)


class BalancedAdaptiveCameraService(
    NativeResolutionThreadedCameraService
):
    """Mantém o perfil escolhido confortável também durante o uso real."""

    RUNTIME_WARMUP_S = 8.0
    RUNTIME_EVALUATION_INTERVAL_S = 5.0
    RUNTIME_MIN_FPS = 24.0
    RUNTIME_LOW_FPS_WINDOWS = 2

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._runtime_opened_s = 0.0
        self._runtime_last_evaluation_s = 0.0
        self._runtime_low_fps_windows = 0
        self._runtime_downgrades = 0

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

        largura_real = max(0, int(candidato.largura))
        altura_real = max(0, int(candidato.altura))
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
                    altura_real, largura_real = frame.shape[:2]
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

                altura_real, largura_real = frame.shape[:2]
                timestamps.append(agora)
                integridade = validador.avaliar(frame)
                corrupted_flags.append(not integridade.valido)
                brightness_values.append(self._brilho_medio(frame))

            motivo = ""
            if (
                candidato.largura > 0
                and candidato.altura > 0
                and (
                    largura_real != candidato.largura
                    or altura_real != candidato.altura
                )
            ):
                motivo = (
                    f"driver entregou {largura_real}x{altura_real} em vez de "
                    f"{candidato.largura}x{candidato.altura}"
                )

            return calculate_camera_performance(
                candidate_key=candidato.key,
                width=largura_real,
                height=altura_real,
                timestamps=timestamps,
                valid_flags=valid_flags,
                corrupted_flags=corrupted_flags,
                brightness_values=brightness_values,
                target_fps=max(1, int(self.fps or CAMERA_FPS)),
                target_resolution=(CAMERA_WIDTH, CAMERA_HEIGHT),
                reason=motivo,
            )
        finally:
            try:
                capture.release()
            except Exception:
                pass

    def _avaliar_grupo(
        self,
        candidatos: list[LinuxCameraBackendCandidate],
        limite: int,
        resultados: list[CameraPerformanceResult],
    ) -> None:
        pixels_alvo = CAMERA_WIDTH * CAMERA_HEIGHT
        for candidato in candidatos[:max(1, int(limite))]:
            self._definir_estado(
                self.ESTADO_ESTABILIZANDO,
                f"Avaliando {candidato.nome}: fluidez e estabilidade...",
            )
            resultado = self._avaliar_candidato(candidato)
            resultados.append(resultado)

            pixels_resultado = resultado.width * resultado.height
            if pixels_resultado > pixels_alvo:
                if resultado.excellent:
                    break
            elif resultado.comfortable:
                break

    def _abrir_camera(self) -> bool:
        abriu = super()._abrir_camera()
        if abriu:
            agora = time.monotonic()
            self._runtime_opened_s = agora
            self._runtime_last_evaluation_s = agora
            self._runtime_low_fps_windows = 0
        return abriu

    def _publicar_frame_otimizado(self, frame, estavel: bool) -> None:
        super()._publicar_frame_otimizado(frame, estavel=estavel)
        self._avaliar_desempenho_runtime()

    def _avaliar_desempenho_runtime(self) -> None:
        if not sys.platform.startswith("linux") or self._capture is None:
            return

        agora = time.monotonic()
        if agora - self._runtime_opened_s < self.RUNTIME_WARMUP_S:
            return
        if (
            agora - self._runtime_last_evaluation_s
            < self.RUNTIME_EVALUATION_INTERVAL_S
        ):
            return
        self._runtime_last_evaluation_s = agora

        fps_real = float(self._fps_real or 0.0)
        if fps_real >= self.RUNTIME_MIN_FPS:
            self._runtime_low_fps_windows = 0
            return

        self._runtime_low_fps_windows += 1
        if (
            self._runtime_low_fps_windows
            < self.RUNTIME_LOW_FPS_WINDOWS
        ):
            return

        candidatos = self._candidatos_linux()
        if self._backend_linux_cursor >= len(candidatos) - 1:
            self._runtime_low_fps_windows = 0
            return

        self._runtime_low_fps_windows = 0
        self._runtime_downgrades += 1
        self._trocar_backend_linux(
            f"O perfil atual sustentou apenas {fps_real:.1f} FPS."
        )

    def obter_diagnostico_fluxo(self) -> dict:
        diagnostico = super().obter_diagnostico_fluxo()
        diagnostico.update(
            {
                "runtime_min_fps": self.RUNTIME_MIN_FPS,
                "runtime_low_fps_windows": int(
                    self._runtime_low_fps_windows
                ),
                "runtime_downgrades": int(self._runtime_downgrades),
            }
        )
        return diagnostico
