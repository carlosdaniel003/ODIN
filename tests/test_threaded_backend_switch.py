import unittest
from unittest.mock import patch

import cv2
import numpy as np

from src.platform.linux_camera_backend import (
    LinuxCameraBackendCandidate,
)
from src.platform.threaded_camera_service import (
    ThreadedDesktopCameraService,
)


class FakeCapture:
    def __init__(self):
        self.released = False

    def release(self):
        self.released = True

    def read(self):
        return True, np.zeros((480, 640, 3), dtype=np.uint8)

    def get(self, propriedade):
        if propriedade == cv2.CAP_PROP_FPS:
            return 30.0
        return 0.0

    def set(self, _propriedade, _valor):
        return True


class CameraServiceTeste(ThreadedDesktopCameraService):
    def __init__(self):
        super().__init__(
            indice_camera=0,
            largura=640,
            altura=480,
            fps=30,
            configuracoes_camera={
                "resolution_mode": "custom",
                "width": 640,
                "height": 480,
                "fps_mode": "manual",
                "fps": 30,
                "format": "MJPG",
                "exposure_auto": False,
                "focus_auto": False,
                "white_balance_auto": False,
            },
        )
        self._candidatos_teste = (
            LinuxCameraBackendCandidate(
                key="gstreamer:teste:MJPG:640x480",
                nome="GStreamer MJPG 640x480",
                tipo="gstreamer",
                origem="pipeline",
                backend=cv2.CAP_GSTREAMER,
                dispositivo="/dev/video0",
                formato="MJPG",
                largura=640,
                altura=480,
                indice=0,
            ),
            LinuxCameraBackendCandidate(
                key="v4l2:0:YUY2:640x480",
                nome="V4L2 YUY2 640x480",
                tipo="v4l2",
                origem=0,
                backend=cv2.CAP_V4L2,
                dispositivo="/dev/video0",
                formato="YUY2",
                largura=640,
                altura=480,
                indice=0,
            ),
        )

    def _candidatos_linux(self):
        return self._candidatos_teste

    def _abrir_candidato_linux(self, _candidato):
        return FakeCapture()


class ThreadedBackendSwitchTests(unittest.TestCase):
    def test_troca_pipeline_sem_apagar_ultimo_frame(self):
        service = CameraServiceTeste()

        with patch(
            "src.platform.threaded_camera_service.sys.platform",
            "linux",
        ):
            self.assertTrue(service._abrir_camera())
            self.assertEqual(
                "GStreamer MJPG 640x480",
                service._backend_name,
            )

            service._ultimo_frame = np.zeros(
                (4, 4, 3),
                dtype=np.uint8,
            )
            service._trocar_backend_linux("pipeline instável")

            self.assertEqual(
                service.ESTADO_CONECTADA,
                service._estado,
            )
            self.assertEqual(1, service._backend_linux_cursor)
            self.assertTrue(service._abrir_camera())
            self.assertEqual(
                "V4L2 YUY2 640x480",
                service._backend_name,
            )


if __name__ == "__main__":
    unittest.main()
