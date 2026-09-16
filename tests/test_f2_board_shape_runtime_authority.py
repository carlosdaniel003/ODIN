from __future__ import annotations

import inspect
import unittest

import src.platform.f2_board_shape_runtime_authority as module


class F2BoardShapeRuntimeAuthorityTests(unittest.TestCase):
    def test_editor_uses_save_label_not_ok_for_board_context(self):
        source = inspect.getsource(module._personalizar_editor_final)
        self.assertIn('texto == "OK"', source)
        self.assertIn('widget.configure(text="SALVAR")', source)

    def test_empty_shape_cannot_close_as_success(self):
        source = inspect.getsource(module._salvar_por_autoridade_final)
        self.assertIn("leds_selecionados", source)
        self.assertIn("if not rois", source)
        self.assertIn("_mostrar_erro_sem_forma", source)

    def test_status_is_injected_before_three_card_grid(self):
        source = inspect.getsource(module._injetar_status_contorno_visivel)
        self.assertIn("Contorno da placa:", source)
        self.assertIn("before=grid", source)
        self.assertIn("SALVO", source)

    def test_installer_wraps_final_app_and_final_presence_renderer(self):
        source = inspect.getsource(module.instalar_autoridade_final_editor_contorno_f2)
        self.assertIn("RaspberryPi3ProductionApp._confirmar_selecao_tela_cheia", source)
        self.assertIn("RaspberryPi3ProductionApp._criar_interface_selecao_tela_cheia", source)
        self.assertIn("F2BoardPresenceReferenceController.render_settings", source)
        self.assertNotIn("display_f3", source)


if __name__ == "__main__":
    unittest.main()
