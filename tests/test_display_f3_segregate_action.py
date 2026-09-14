from __future__ import annotations

import inspect
import unittest

import src.platform.display_f3_segregate_action as segregate_module
from src.platform.display_production_f3_window import DisplayProductionF3Window


class DisplayF3SegregateActionTests(unittest.TestCase):
    def test_interface_produtiva_usa_segregar_placa(self):
        self.assertEqual("SEGREGAR PLACA  [1]", segregate_module.SEGREGATE_BUTTON_TEXT)
        self.assertIn("SEGREGAR PLACA", segregate_module.SEGREGATE_FOOTER_TEXT)
        self.assertEqual("PLACA SEGREGADA", segregate_module.SEGREGATE_RESULT_TEXT)
        self.assertNotIn("DESCARTAR", segregate_module.SEGREGATE_BUTTON_TEXT)
        self.assertNotIn("DESCARTAR", segregate_module.SEGREGATE_FOOTER_TEXT)
        self.assertNotIn("DESCARTADA", segregate_module.SEGREGATE_RESULT_TEXT)

    def test_instalador_altera_somente_a_apresentacao_da_janela_f3(self):
        segregate_module.instalar_acao_segregar_placa_display_f3()
        self.assertTrue(DisplayProductionF3Window._odin_display_f3_segregate_action)

        init_source = inspect.getsource(DisplayProductionF3Window.__init__)
        result_source = inspect.getsource(DisplayProductionF3Window.show_plate_result)
        self.assertIn("SEGREGATE_BUTTON_TEXT", init_source)
        self.assertIn("SEGREGATE_FOOTER_TEXT", init_source)
        self.assertIn("SEGREGATE_RESULT_TEXT", result_source)
        self.assertIn("discarded", result_source)

    def test_extensao_de_segregacao_nao_importa_f2(self):
        source = inspect.getsource(segregate_module)
        self.assertNotIn("src.platform.f2_", source)
        self.assertNotIn("operacao_total", source)
        self.assertNotIn("operacao_ok", source)
        self.assertNotIn("operacao_ng", source)


if __name__ == "__main__":
    unittest.main()
