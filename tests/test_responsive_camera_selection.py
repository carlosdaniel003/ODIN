import inspect
import threading
import unittest

import src.platform.responsive_camera_selection as responsive
from src.platform.camera_selection import CameraSelectionMixin
from src.platform.desktop_production_app import DesktopProductionApp


class ResponsiveCameraSelectionTests(unittest.TestCase):
    def test_perfil_final_recebe_patch_responsivo(self):
        self.assertIn(CameraSelectionMixin, DesktopProductionApp.__mro__)
        self.assertTrue(
            getattr(CameraSelectionMixin, "_odin_responsive_selector_installed", False)
        )
        self.assertIs(
            CameraSelectionMixin.abrir_seletor_camera,
            responsive.ResponsiveCameraSelectionMixin.abrir_seletor_camera,
        )

    def test_video_capture_nao_e_lido_na_thread_da_interface(self):
        fonte_ui = inspect.getsource(
            responsive.ResponsiveCameraSelectionMixin._atualizar_previews_seletor_camera
        )
        fonte_worker = inspect.getsource(
            responsive.executar_busca_camera_em_background
        )
        self.assertNotIn("capture.read", fonte_ui)
        self.assertIn("capture.read", fonte_worker)

    def test_busca_usa_worker_daemon(self):
        fonte = inspect.getsource(
            responsive.ResponsiveCameraSelectionMixin.abrir_seletor_camera
        )
        self.assertIn("threading.Thread", fonte)
        self.assertIn("daemon=True", fonte)
        self.assertIn("worker.start()", fonte)

    def test_fechamento_nao_faz_join_bloqueante(self):
        fonte = inspect.getsource(
            responsive.ResponsiveCameraSelectionMixin._fechar_seletor_camera
        )
        self.assertNotIn(".join(", fonte)
        self.assertIn("stop_event.set()", fonte)

    def test_loading_e_botoes_maiores_estao_presentes(self):
        fonte = inspect.getsource(responsive.ResponsiveCameraSelectionMixin)
        self.assertGreaterEqual(responsive.SELECTOR_WINDOW_HEIGHT, 500)
        self.assertIn("CARREGANDO CÂMERAS", fonte)
        self.assertIn("SELECIONAR CÂMERA", fonte)
        self.assertIn('font=("Segoe UI", 11, "bold")', fonte)
        self.assertIn("pady=12", fonte)

    def test_worker_libera_camera_em_background(self):
        fonte = inspect.getsource(responsive.executar_busca_camera_em_background)
        self.assertIn("capture.release()", fonte)
        self.assertIn("released_event.set()", fonte)


if __name__ == "__main__":
    unittest.main()
