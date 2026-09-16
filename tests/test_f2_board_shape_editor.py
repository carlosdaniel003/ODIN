from __future__ import annotations

import inspect
import unittest

from src.platform.f2_board_shape_editor import (
    F2_BOARD_SHAPE_KEY,
    definir_contorno_placa_projeto,
    obter_contorno_placa_projeto,
)


class F2BoardShapeEditorTests(unittest.TestCase):
    def test_shape_is_project_scoped_and_not_slot_scoped(self):
        config = {
            "led_projects": {
                "P": {
                    "name": "P",
                    "fixed_leds": [],
                }
            }
        }
        roi = {
            "id": "SEG_001",
            "centro_x": 320,
            "centro_y": 240,
            "raio": 30,
            "tipo_roi": "segmento",
            "largura": 120,
            "altura": 80,
            "angulo": 0,
            "base_resolution": {"width": 640, "height": 480},
        }

        updated = definir_contorno_placa_projeto(config, "P", [roi], 640, 480)
        shape = obter_contorno_placa_projeto(updated, "P")

        self.assertIn(F2_BOARD_SHAPE_KEY, updated["led_projects"]["P"])
        self.assertEqual(1, len(shape["rois"]))
        self.assertEqual(640, shape["base_resolution"]["width"])
        self.assertEqual(480, shape["base_resolution"]["height"])

    def test_editor_defaults_to_point_by_point_but_keeps_fullscreen_editor(self):
        import src.platform.f2_board_shape_editor as module

        source = inspect.getsource(module)
        self.assertIn("_abrir_selecao_tela_cheia", source)
        self.assertIn("_selecionar_segmento_livre_toolbar", source)
        self.assertIn("Segmento por pontos", source)
        self.assertIn("BulkRoiEditorMixin.MODOS_EDICAO.add", source)

    def test_presence_renderer_exposes_shared_button_in_on_and_off_cards(self):
        import src.platform.f2_board_presence_mask_preview_native as module

        source = inspect.getsource(module)
        self.assertIn('text="Desenhar placa"', source)
        self.assertIn("abrir_editor_contorno_placa_f2", source)
        self.assertIn("F2_BOARD_REF_BOARD_ON", source)
        self.assertIn("F2_BOARD_REF_BOARD_OFF", source)
        self.assertIn("carregar_contorno_placa_leds", source)
        self.assertIn("ciano = placa", source)

    def test_empty_support_is_not_part_of_board_shape_editor_allowed_slots(self):
        import src.platform.f2_board_shape_editor as module

        self.assertNotIn(
            module.F2_BOARD_REF_EMPTY if hasattr(module, "F2_BOARD_REF_EMPTY") else "empty_support",
            module.F2_BOARD_SHAPE_ALLOWED_SLOTS,
        )


if __name__ == "__main__":
    unittest.main()
