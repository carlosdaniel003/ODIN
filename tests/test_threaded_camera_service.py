import time
import unittest

import cv2
import numpy as np

from src.platform.threaded_camera_service import (
    ThreadedDesktopCameraService,
)


class FakeCapture:
    def __init__(self, frames):
        self.frames = list(frames)
        self.indice = 0
        self.ativo = True

    def read(self):
        time.sleep(0.005)
        if not self.ativo:
            return False, None
        if self.indice < len(self.frames):
            frame = self.frames[self.indice]
            self.indice += 1
        else:
            frame = self.frames[-1]
        return True, frame.copy()

    def release(self):
        self.ativo = False

    def get(self, propriedade):
        if propriedade == cv2.CAP_PROP_FPS:
            return 30.0
        if propriedade == cv2.CAP_PROP_FOURCC:
            return float(cv2.VideoWriter_fourcc(*"MJPG"))
        return 0.0

    def set(self, _propriedade, _valor):
        return True


class CameraServiceTeste(ThreadedDesktopCameraService):
    def __init__(self, frames):
        self._frames_teste = list(frames)
        super().__init__(
            indice_camera=0,
            largura=640,
            altura=480,
            fps=30,
            frames_aquecimento=3,
            falhas_antes_reconexao=3,
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

    def _abrir_camera(self):
        self._liberar_camera()
        self._capture = FakeCapture(self._frames_teste)
        self._backend_name = "teste"
        self._controles_pendentes = False
        self._falhas_consecutivas = 0
        self._definir_estado(
            self.ESTADO_ESTABILIZANDO,
            "Câmera simulada aberta.",
        )
        return True


class ThreadedCameraServiceTests(unittest.TestCase):
    def test_descarta_banda_e_mantem_frame_estavel(self):
        base = np.full((480, 640, 3), 80, dtype=np.uint8)
        cv2.circle(base, (320, 240), 40, (0, 0, 255), -1)

        corrompido = base.copy()
        corrompido[100:130] = 220
        corrompido[260:290] = 10

        service = CameraServiceTeste(
            [base, base, base, corrompido, base, base, base]
        )
        service.iniciar()

        limite = time.monotonic() + 1.0
        estavel = None
        diagnostico = {}
        while time.monotonic() < limite:
            estavel = service.obter_ultimo_frame_estavel()
            diagnostico = service.obter_diagnostico_fluxo()
            if (
                estavel is not None
                and diagnostico["frames_corrompidos_total"] >= 1
            ):
                break
            time.sleep(0.01)

        self.assertIsNotNone(estavel)
        self.assertGreaterEqual(
            diagnostico.get("frames_corrompidos_total", 0),
            1,
        )
        self.assertTrue(diagnostico.get("thread_ativa", False))

        service.parar()
        diagnostico_final = service.obter_diagnostico_fluxo()
        self.assertFalse(diagnostico_final["thread_ativa"])


if __name__ == "__main__":
    unittest.main()
