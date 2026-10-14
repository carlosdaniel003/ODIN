import inspect
import queue
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

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

    def test_selecao_da_primeira_camera_interrompe_descoberta_e_libera_handle(self):
        class Capture:
            def __init__(self):
                self.release_calls = 0

            def release(self):
                self.release_calls += 1

        stop = threading.Event()
        released = threading.Event()
        capture = Capture()
        opened = []
        previews = {}

        class QueueSelecao(queue.Queue):
            def put(self, item, *args, **kwargs):
                super().put(item, *args, **kwargs)
                if item[0] == "encontrada":
                    stop.set()

        eventos = QueueSelecao()

        def abrir(indice):
            opened.append(indice)
            return capture, "Media Foundation", SimpleNamespace(
                shape=(1080, 1920, 3), size=1920 * 1080 * 3,
            )

        with patch.object(responsive.sys, "platform", "win32"), patch.object(
            responsive, "abrir_camera_preview", side_effect=abrir,
        ), patch.object(responsive, "_codificar_preview", return_value="preview"):
            responsive.executar_busca_camera_em_background(
                stop, eventos, previews, threading.RLock(), released,
            )

        self.assertEqual([0], opened)
        self.assertTrue(released.is_set())
        self.assertEqual(1, capture.release_calls)
        encontrados = [item for item in list(eventos.queue) if item[0] == "encontrada"]
        self.assertEqual(("encontrada", 0, "Media Foundation", (1920, 1080)), encontrados[0])

    def test_windows_preserva_janela_curta_de_escolha_antes_de_outro_probe(self):
        self.assertGreaterEqual(
            responsive.CAMERA_SELECTOR_WINDOWS_FIRST_CHOICE_GRACE_S, 0.5,
        )
        self.assertLessEqual(
            responsive.CAMERA_SELECTOR_WINDOWS_FIRST_CHOICE_GRACE_S, 2.0,
        )

    def test_worker_libera_camera_em_background(self):
        fonte = inspect.getsource(responsive.executar_busca_camera_em_background)
        self.assertIn("capture.release()", fonte)
        self.assertIn("released_event.set()", fonte)


if __name__ == "__main__":
    unittest.main()
