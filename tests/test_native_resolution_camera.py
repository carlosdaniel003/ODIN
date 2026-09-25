import unittest
from unittest.mock import patch

import cv2

from src.platform.fixed_full_hd_camera_service import (
    FixedFullHdCameraService,
)
from src.platform.linux_camera_backend import LinuxCameraBackendCandidate
from src.platform.desktop_settings import (
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_RESOLUTION_FALLBACKS,
    CAMERA_WIDTH,
    FRAME_INTERVAL_MS,
)


class FakeCapture:
    def __init__(self):
        self.definicoes = []

    def set(self, propriedade, valor):
        self.definicoes.append((propriedade, valor))
        return True


class FixedResolutionCameraTests(unittest.TestCase):
    def test_perfil_fixo_e_1080p20(self):
        self.assertEqual((1920, 1080), (CAMERA_WIDTH, CAMERA_HEIGHT))
        self.assertEqual(20, CAMERA_FPS)
        self.assertEqual(((1920, 1080),), CAMERA_RESOLUTION_FALLBACKS)
        self.assertEqual(50, FRAME_INTERVAL_MS)

    def test_configuracao_linux_ignora_resolucao_e_fps_diferentes(self):
        configuracoes = FixedFullHdCameraService._fixed_settings(
            {
                "resolution_mode": "uhd",
                "width": 3840,
                "height": 2160,
                "fps_mode": "manual",
                "fps": 30,
                "format": "YUY2",
                "rotation": 180,
            }
        )

        self.assertEqual("full_hd", configuracoes["resolution_mode"])
        self.assertEqual(1920, configuracoes["width"])
        self.assertEqual(1080, configuracoes["height"])
        self.assertEqual(20, configuracoes["fps"])
        self.assertEqual("MJPG", configuracoes["format"])
        self.assertEqual(180, configuracoes["rotation"])

    def test_windows_usa_transporte_nativo_negociado(self):
        configuracoes = FixedFullHdCameraService._windows_native_settings(
            {
                "resolution_mode": "full_hd",
                "fps_mode": "manual",
                "fps": 20,
                "format": "MJPG",
                "rotation": 180,
            }
        )
        self.assertEqual("auto", configuracoes["resolution_mode"])
        self.assertEqual("auto", configuracoes["fps_mode"])
        self.assertEqual(0, configuracoes["fps"])
        self.assertEqual("AUTO", configuracoes["format"])
        self.assertEqual(180, configuracoes["rotation"])

    def test_windows_sem_controle_manual_deixa_driver_intacto(self):
        configuracoes = {
            "exposure_auto": True,
            "focus_auto": True,
            "white_balance_auto": True,
        }
        self.assertFalse(
            FixedFullHdCameraService._windows_tem_controle_manual_explicito(
                configuracoes
            )
        )

    def test_windows_respeita_controle_manual_explicito(self):
        configuracoes = {
            "exposure_auto": False,
            "exposure_enabled": True,
            "focus_auto": True,
            "white_balance_auto": True,
        }
        self.assertTrue(
            FixedFullHdCameraService._windows_tem_controle_manual_explicito(
                configuracoes
            )
        )

    def test_instancia_windows_nao_exige_1080p_e_tolera_hiccups(self):
        with patch(
            "src.platform.fixed_full_hd_camera_service.sys.platform",
            "win32",
        ):
            service = FixedFullHdCameraService(indice_camera=1)

        self.assertTrue(service._windows_native_mode)
        self.assertTrue(service.perfil_automatico)
        self.assertEqual(0, service.fps)
        self.assertEqual("AUTO", service.formato_camera)
        self.assertGreaterEqual(service.falhas_antes_reconexao, 60)
        self.assertGreaterEqual(
            service.FRAMES_CORROMPIDOS_ANTES_RECONEXAO,
            60,
        )

    def test_linux_oferece_somente_candidatos_1080p(self):
        service = object.__new__(FixedFullHdCameraService)
        service._indice_camera_solicitado = 0
        service._indice_camera_ativo = None

        with patch(
            "src.platform.fixed_full_hd_camera_service."
            "descobrir_dispositivos_video",
            return_value=(("/dev/video0", 0),),
        ), patch(
            "src.platform.fixed_full_hd_camera_service."
            "opencv_tem_gstreamer",
            return_value=True,
        ):
            candidatos = service._candidatos_linux()

        self.assertTrue(candidatos)
        self.assertTrue(
            all(
                (item.largura, item.altura) == (1920, 1080)
                for item in candidatos
            )
        )
        self.assertFalse(any(item.tipo == "auto" for item in candidatos))
        self.assertEqual(
            {"gstreamer", "v4l2"},
            {item.tipo for item in candidatos},
        )

    def test_v4l2_aplica_1920x1080_a_20_fps(self):
        service = object.__new__(FixedFullHdCameraService)
        service.largura = CAMERA_WIDTH
        service.altura = CAMERA_HEIGHT
        service.fps = CAMERA_FPS
        capture = FakeCapture()
        candidato = LinuxCameraBackendCandidate(
            key="v4l2:0:MJPG:1920x1080",
            nome="V4L2 MJPG 1920x1080",
            tipo="v4l2",
            origem=0,
            backend=cv2.CAP_V4L2,
            dispositivo="/dev/video0",
            formato="MJPG",
            largura=1920,
            altura=1080,
            indice=0,
        )

        service._configurar_capture_direto(capture, candidato)
        definicoes = dict(capture.definicoes)
        self.assertEqual(1920, definicoes[cv2.CAP_PROP_FRAME_WIDTH])
        self.assertEqual(1080, definicoes[cv2.CAP_PROP_FRAME_HEIGHT])
        self.assertEqual(20, definicoes[cv2.CAP_PROP_FPS])


if __name__ == "__main__":
    unittest.main()
