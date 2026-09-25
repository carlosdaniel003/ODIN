import contextlib
import inspect
import io
import os
import unittest
from unittest.mock import patch

import src.platform.windows_camera_debug as debug
from src.platform.desktop_production_app import DesktopProductionApp


class WindowsCameraDebugTests(unittest.TestCase):
    def test_debug_desligado_no_linux_mesmo_com_variavel(self):
        with patch.object(debug.sys, "platform", "linux"), patch.dict(
            os.environ,
            {"ODIN_CAMERA_DEBUG": "1"},
            clear=False,
        ):
            self.assertFalse(debug.camera_debug_enabled())

    def test_debug_ligado_no_windows_somente_por_opt_in(self):
        with patch.object(debug.sys, "platform", "win32"), patch.dict(
            os.environ,
            {"ODIN_CAMERA_DEBUG": "1"},
            clear=False,
        ):
            self.assertTrue(debug.camera_debug_enabled())

        with patch.object(debug.sys, "platform", "win32"), patch.dict(
            os.environ,
            {},
            clear=True,
        ):
            self.assertFalse(debug.camera_debug_enabled())

    def test_linha_debug_tem_prefixo_evento_e_flush_no_stdout(self):
        saida = io.StringIO()
        with patch.object(debug.sys, "platform", "win32"), patch.dict(
            os.environ,
            {"ODIN_CAMERA_DEBUG": "1"},
            clear=False,
        ), patch.object(debug.Path, "open", side_effect=OSError("sem arquivo")):
            with contextlib.redirect_stdout(saida):
                debug.camera_debug("teste_evento", indice=0, backend="MSMF")

        texto = saida.getvalue()
        self.assertIn("[ODIN-CAMERA]", texto)
        self.assertIn('"event": "teste_evento"', texto)
        self.assertIn('"indice": 0', texto)
        self.assertIn('"backend": "MSMF"', texto)

    def test_instrumentacao_cobre_etapas_criticas(self):
        fonte = inspect.getsource(debug.instalar_debug_camera_windows)
        for evento in (
            "selector_probe_inicio",
            "selector_probe_fim",
            "selector_confirmar",
            "videocapture_inicio",
            "videocapture_fim",
            "perfil_capture_inicio",
            "perfil_capture_fim",
            "capture_release_inicio",
            "capture_release_fim",
            "service_open_inicio",
            "service_open_fim",
            "probe_inicial_inicio",
            "probe_inicial_fim",
            "capture_loop_inicio",
            "capture_loop_fim",
            "frame_publicado",
            "reconexao_agendada",
        ):
            self.assertIn(evento, fonte)

    def test_debug_distingue_construtor_perfil_e_probe(self):
        fonte = inspect.getsource(debug.instalar_debug_camera_windows)
        self.assertLess(
            fonte.index('"videocapture_inicio"'),
            fonte.index('"videocapture_fim"'),
        )
        self.assertLess(
            fonte.index('"perfil_capture_inicio"'),
            fonte.index('"perfil_capture_fim"'),
        )
        self.assertLess(
            fonte.index('"service_open_inicio"'),
            fonte.index('"probe_inicial_inicio"'),
        )

    def test_app_instala_debug_apos_handoff_e_agenda_snapshot_depois_do_init(self):
        fonte = inspect.getsource(DesktopProductionApp.__init__)
        self.assertIn("instalar_handoff_camera_windows()", fonte)
        self.assertIn("instalar_debug_camera_windows()", fonte)
        self.assertIn("iniciar_debug_periodico_camera_windows(self)", fonte)
        self.assertLess(
            fonte.index("instalar_handoff_camera_windows()"),
            fonte.index("instalar_debug_camera_windows()"),
        )
        self.assertLess(
            fonte.index("super().__init__(root)"),
            fonte.index("iniciar_debug_periodico_camera_windows(self)"),
        )

    def test_modulo_nao_habilita_debug_automaticamente(self):
        fonte = inspect.getsource(debug.camera_debug_enabled)
        self.assertIn("ODIN_CAMERA_DEBUG", fonte)
        self.assertIn('sys.platform.startswith("win")', fonte)


if __name__ == "__main__":
    unittest.main()
