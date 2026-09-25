from __future__ import annotations

from dataclasses import dataclass
import sys
import time

from src.platform.linux_camera_backend import (
    construir_candidatos_linux,
    descobrir_dispositivos_video,
    opencv_tem_gstreamer,
)
from src.platform.native_camera_mode import (
    NativeCameraMode,
    get_native_camera_mode,
    raspberry_safe_resolution_limit,
)
from src.platform.desktop_settings import CAMERA_SCAN_MAX_INDEX
from src.platform.threaded_camera_service import (
    ThreadedDesktopCameraService,
)


@dataclass(frozen=True)
class _IntegrityAccepted:
    valido: bool = True
    motivo: str = ""


class _DisabledFrameIntegrityValidator:
    """Mantém a interface esperada sem rejeitar frames por heurística."""

    def reset(self) -> None:
        return None

    def avaliar(self, _frame) -> _IntegrityAccepted:
        return _IntegrityAccepted()


class RelaxedNativeCameraService(ThreadedDesktopCameraService):
    """Perfil temporariamente tolerante e com resolução nativa no Linux."""

    READ_FAILURES_BEFORE_RECOVERY = 150
    DISCONNECTION_WARNING_GRACE_S = 8.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.falhas_antes_reconexao = max(
            int(self.falhas_antes_reconexao),
            self.READ_FAILURES_BEFORE_RECOVERY,
        )
        self._validador_integridade = _DisabledFrameIntegrityValidator()
        self._stream_failure_started_s: float | None = None
        self._native_mode: NativeCameraMode | None = None

    def iniciar(self) -> None:
        self._stream_failure_started_s = None
        super().iniciar()

    def parar(self) -> None:
        self._stream_failure_started_s = None
        super().parar()

    def _candidatos_linux(self):
        dispositivos = descobrir_dispositivos_video(
            indice_solicitado=self._indice_camera_solicitado,
            indice_ativo=self._indice_camera_ativo,
            indice_maximo=CAMERA_SCAN_MAX_INDEX,
        )

        self._native_mode = None
        if dispositivos:
            device, _index = dispositivos[0]
            self._native_mode = get_native_camera_mode(
                device=device,
                target_fps=max(1, int(self.fps or 30)),
                max_resolution=raspberry_safe_resolution_limit(),
            )

        if self._native_mode is not None:
            self.largura = int(self._native_mode.width)
            self.altura = int(self._native_mode.height)
            if self._native_mode.fps > 0:
                self.fps = max(
                    1,
                    min(
                        int(self.fps or 30),
                        int(round(self._native_mode.fps)),
                    ),
                )
            self._resolucao_solicitada = (
                self.largura,
                self.altura,
            )
            self._fps_solicitado = self.fps

        candidatos = construir_candidatos_linux(
            dispositivos=dispositivos,
            largura=self.largura,
            altura=self.altura,
            fps=max(1, int(self.fps or 30)),
            gstreamer_disponivel=opencv_tem_gstreamer(),
        )

        preferred_format = ""
        if self._native_mode is not None:
            preferred_format = self._native_mode.format.upper()
            if preferred_format in ("YUYV", "YUY2"):
                preferred_format = "YUY2"
            elif preferred_format in ("MJPG", "JPEG"):
                preferred_format = "MJPG"

        if not preferred_format:
            return candidatos

        return tuple(
            sorted(
                candidatos,
                key=lambda candidate: (
                    candidate.formato != preferred_format,
                    candidate.tipo != "gstreamer",
                ),
            )
        )

    def _agendar_reconexao(self, motivo: str) -> None:
        self._liberar_camera()
        agora = time.monotonic()
        if self._stream_failure_started_s is None:
            self._stream_failure_started_s = agora

        self._proxima_reconexao_em = agora + self.intervalo_reconexao_s
        elapsed = agora - self._stream_failure_started_s

        with self._lock:
            has_last_frame = self._ultimo_frame is not None

        if has_last_frame and elapsed < self.DISCONNECTION_WARNING_GRACE_S:
            self._definir_estado(
                self.ESTADO_CONECTADA,
                f"{motivo} Recuperando fluxo sem apagar a última imagem...",
            )
            return

        self._definir_estado(
            self.ESTADO_DESCONECTADA,
            f"{motivo} Reconectando automaticamente...",
        )

    def _publicar_frame_otimizado(self, frame, estavel: bool) -> None:
        self._stream_failure_started_s = None
        super()._publicar_frame_otimizado(frame, estavel=estavel)

    def obter_diagnostico_fluxo(self) -> dict:
        diagnostico = super().obter_diagnostico_fluxo()
        native_mode = self._native_mode
        diagnostico.update(
            {
                "frame_integrity_filter_enabled": False,
                "read_failures_before_recovery": int(
                    self.falhas_antes_reconexao
                ),
                "native_resolution": (
                    None
                    if native_mode is None
                    else (native_mode.width, native_mode.height)
                ),
                "native_format": (
                    None if native_mode is None else native_mode.format
                ),
                "native_fps": (
                    None if native_mode is None else native_mode.fps
                ),
                "linux_native_mode_active": bool(
                    sys.platform.startswith("linux")
                    and native_mode is not None
                ),
            }
        )
        return diagnostico
