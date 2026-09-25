import inspect
import unittest
from unittest.mock import patch

from src.platform.desktop_production_app import DesktopProductionApp
from src.platform.windows_camera_handoff import (
    WINDOWS_POST_RELEASE_SETTLE_MS,
    _instalar_preferencia_backend_na_classe,
    ordenar_backends_servico_windows,
    pode_iniciar_camera_apos_preview,
    priorizar_backend_windows,
)


BACKENDS = (
    (100, "Media Foundation"),
    (200, "DirectShow"),
    (300, "Automático"),
)


class _FakeCameraService:
    _odin_windows_backend_handoff_instalado = False

    def __init__(self):
        self._resolucao_solicitada = (1920, 1080)
        self.perfil_automatico = False

    @staticmethod
    def _backends_preferidos():
        return BACKENDS


class WindowsCameraHandoffTests(unittest.TestCase):
    def test_windows_nao_forca_inicio_enquanto_preview_nao_liberou(self):
        self.assertFalse(
            pode_iniciar_camera_apos_preview(
                liberada=False,
                espera_ms=2200,
                limite_ms=2200,
                plataforma="win32",
            )
        )
        self.assertFalse(
            pode_iniciar_camera_apos_preview(
                liberada=False,
                espera_ms=15000,
                limite_ms=2200,
                plataforma="win32",
            )
        )
        self.assertTrue(
            pode_iniciar_camera_apos_preview(
                liberada=True,
                espera_ms=0,
                limite_ms=2200,
                plataforma="win32",
            )
        )

    def test_windows_aguarda_assentamento_do_driver_apos_release(self):
        self.assertGreaterEqual(WINDOWS_POST_RELEASE_SETTLE_MS, 1200)

    def test_linux_preserva_limite_legado_do_handoff(self):
        self.assertFalse(
            pode_iniciar_camera_apos_preview(
                liberada=False,
                espera_ms=2100,
                limite_ms=2200,
                plataforma="linux",
            )
        )
        self.assertTrue(
            pode_iniciar_camera_apos_preview(
                liberada=False,
                espera_ms=2200,
                limite_ms=2200,
                plataforma="linux",
            )
        )

    def test_backend_comprovado_no_preview_vai_para_primeiro_no_windows_generico(self):
        ordenados = priorizar_backend_windows(
            BACKENDS,
            "DirectShow",
            plataforma="win32",
        )
        self.assertEqual("DirectShow", ordenados[0][1])
        self.assertEqual(3, len(ordenados))
        self.assertEqual(set(BACKENDS), set(ordenados))

    def test_1080p_explicito_prioriza_directshow_mesmo_se_preview_usou_msmf(self):
        ordenados = ordenar_backends_servico_windows(
            BACKENDS,
            "Media Foundation",
            resolucao_solicitada=(1920, 1080),
            perfil_automatico=False,
            plataforma="win32",
        )
        self.assertEqual("DirectShow", ordenados[0][1])
        self.assertEqual("Automático", ordenados[1][1])
        self.assertEqual("Media Foundation", ordenados[2][1])
        self.assertEqual(set(BACKENDS), set(ordenados))

    def test_baixa_resolucao_continua_respeitando_backend_do_preview(self):
        ordenados = ordenar_backends_servico_windows(
            BACKENDS,
            "Media Foundation",
            resolucao_solicitada=(640, 480),
            perfil_automatico=False,
            plataforma="win32",
        )
        self.assertEqual("Media Foundation", ordenados[0][1])

    def test_perfil_automatico_continua_respeitando_backend_do_preview(self):
        ordenados = ordenar_backends_servico_windows(
            BACKENDS,
            "Media Foundation",
            resolucao_solicitada=(1920, 1080),
            perfil_automatico=True,
            plataforma="win32",
        )
        self.assertEqual("Media Foundation", ordenados[0][1])

    def test_backend_linux_nao_e_reordenado(self):
        self.assertEqual(
            BACKENDS,
            ordenar_backends_servico_windows(
                BACKENDS,
                "DirectShow",
                resolucao_solicitada=(1920, 1080),
                plataforma="linux",
            ),
        )
        self.assertEqual(
            BACKENDS,
            priorizar_backend_windows(
                BACKENDS,
                "DirectShow",
                plataforma="linux",
            ),
        )

    def test_preferencia_e_instalada_somente_quando_plataforma_e_windows(self):
        class CameraWindows(_FakeCameraService):
            _odin_windows_backend_handoff_instalado = False

        with patch(
            "src.platform.windows_camera_handoff.sys.platform",
            "win32",
        ):
            _instalar_preferencia_backend_na_classe(
                CameraWindows,
                "Media Foundation",
            )
            self.assertEqual(
                "DirectShow",
                CameraWindows()._backends_preferidos()[0][1],
            )

        class CameraLinux(_FakeCameraService):
            _odin_windows_backend_handoff_instalado = False

        original = CameraLinux._backends_preferidos
        with patch(
            "src.platform.windows_camera_handoff.sys.platform",
            "linux",
        ):
            _instalar_preferencia_backend_na_classe(
                CameraLinux,
                "DirectShow",
            )
        self.assertIs(original, CameraLinux._backends_preferidos)
        self.assertEqual(BACKENDS, CameraLinux._backends_preferidos())

    def test_perfil_final_instala_handoff_antes_de_construir_aplicacao(self):
        fonte = inspect.getsource(DesktopProductionApp.__init__)
        self.assertIn("instalar_handoff_camera_windows()", fonte)
        self.assertLess(
            fonte.index("instalar_handoff_camera_windows()"),
            fonte.index("super().__init__(root)"),
        )

    def test_modulo_documenta_e_isola_linux(self):
        import src.platform.windows_camera_handoff as modulo

        fonte = inspect.getsource(modulo.instalar_handoff_camera_windows)
        self.assertIn('if not sys.platform.startswith("win")', fonte)
        self.assertIn("return confirmar_original", fonte)
        self.assertNotIn("_trocar_backend_linux", fonte)
        self.assertNotIn("LinuxCameraCompatibilityMixin", fonte)


if __name__ == "__main__":
    unittest.main()
