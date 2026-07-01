from __future__ import annotations

import cv2

from src.infra.camera_service import CameraService


class RaspberryPi3CameraService(CameraService):
    """CameraService para webcam USB usando V4L2 no Raspberry Pi OS."""

    def iniciar(self) -> None:
        if self._ativo:
            return

        self._ativo = True
        self._falhas_consecutivas = 0
        self._proxima_reconexao_em = 0.0
        self._definir_estado(
            self.ESTADO_CONECTANDO,
            f"Conectando câmera {self.indice_camera} via V4L2...",
        )
        self._abrir_camera()

    def _abrir_camera(self) -> bool:
        self._liberar_camera()
        self._definir_estado(
            self.ESTADO_ESTABILIZANDO,
            f"Abrindo câmera {self.indice_camera} via V4L2...",
        )

        capture = None
        backend_name = "V4L2"

        for backend, candidate_name in (
            (cv2.CAP_V4L2, "V4L2"),
            (cv2.CAP_ANY, "automático Linux"),
        ):
            try:
                candidate = cv2.VideoCapture(
                    self.indice_camera,
                    backend,
                )
            except Exception:
                candidate = None

            if candidate is not None and candidate.isOpened():
                capture = candidate
                backend_name = candidate_name
                break

            if candidate is not None:
                try:
                    candidate.release()
                except Exception:
                    pass

        if capture is None:
            self._capture = None
            self._agendar_reconexao(
                f"Câmera {self.indice_camera} não abriu via V4L2."
            )
            return False

        self._capture = capture
        self._backend_name = backend_name
        self._aplicar_perfil_capture(capture)

        try:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        self._controles_pendentes = True
        self._falhas_consecutivas = 0
        self._definir_estado(
            self.ESTADO_ESTABILIZANDO,
            (
                f"Câmera {self.indice_camera} aberta via "
                f"{backend_name}. Aguardando primeiro frame..."
            ),
        )
        return True

    def _publicar_frame(self, frame) -> None:
        frame_height, frame_width = frame.shape[:2]
        backend_name = getattr(self, "_backend_name", "V4L2")

        with self._lock:
            self._ultimo_frame = frame.copy()
            self._frame_id += 1
            self._resolucao = (frame_width, frame_height)
            self._estado = self.ESTADO_CONECTADA
            self._mensagem = (
                f"Câmera conectada via {backend_name}. "
                f"Resolução real: {frame_width}x{frame_height}."
            )
