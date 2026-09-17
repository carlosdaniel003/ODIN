from __future__ import annotations

import inspect
import unittest

from src.models.led_selection import LedSelection
from src.platform.f2_board_shape_editor import (
    F2_BOARD_SHAPE_KEY,
    _contexto_editor_placa_ativo,
    _filtrar_rois_contorno_placa,
    definir_contorno_placa_projeto,
    obter_contorno_placa_projeto,
)


class F2BoardShapeEditorTests(unittest.TestCase):
    @staticmethod
    def _polygon_dict():
        return {
            "id": "BOARD_001",
            "centro_x": 320,
            "centro_y": 240,
            "raio": 200,
            "tipo_roi": "segmento",
            "pontos_segmento_livre": [
                [-180.0, -120.0],
                [180.0, -120.0],
                [180.0, 120.0],
                [-180.0, 120.0],
            ],
            "base_resolution": {"width": 640, "height": 480},
        }

    def test_shape_is_project_scoped_and_single_polygon(self):
        config = {
            "led_projects": {
                "P": {
                    "name": "P",
                    "fixed_leds": [],
                }
            }
        }
        updated = definir_contorno_placa_projeto(
            config,
            "P",
            [self._polygon_dict()],
            640,
            480,
        )
        shape = obter_contorno_placa_projeto(updated, "P")

        self.assertIn(F2_BOARD_SHAPE_KEY, updated["led_projects"]["P"])
        self.assertEqual(1, len(shape["rois"]))
        self.assertEqual(640, shape["base_resolution"]["width"])
        self.assertEqual(480, shape["base_resolution"]["height"])

    def test_legacy_led_masks_are_not_accepted_as_board_shape(self):
        config = {
            "led_projects": {
                "P": {
                    "name": "P",
                    "fixed_leds": [],
                    F2_BOARD_SHAPE_KEY: {
                        "rois": [
                            {
                                "id": f"LED_{index:03d}",
                                "centro_x": 100 + index,
                                "centro_y": 100,
                                "raio": 8,
                                "tipo_roi": "circulo",
                            }
                            for index in range(42)
                        ],
                        "base_resolution": {"width": 640, "height": 480},
                    },
                }
            }
        }
        shape = obter_contorno_placa_projeto(config, "P")
        self.assertEqual([], shape["rois"])

    def test_working_shape_keeps_only_latest_freeform_polygon(self):
        first = LedSelection.from_dict(self._polygon_dict())
        second_data = self._polygon_dict()
        second_data["id"] = "BOARD_002"
        second_data["centro_x"] = 300
        second = LedSelection.from_dict(second_data)
        circle = LedSelection(id="LED_001", centro_x=20, centro_y=20, raio=5)

        result = _filtrar_rois_contorno_placa([first, circle, second])
        self.assertEqual(1, len(result))
        self.assertEqual("BOARD_002", result[0].id)
        self.assertTrue(result[0].eh_segmento_livre)

    def test_editor_defaults_to_point_by_point_and_uses_dedicated_working_set(self):
        import src.platform.f2_board_shape_editor as module

        source = inspect.getsource(module)
        self.assertIn("_abrir_selecao_tela_cheia", source)
        self.assertIn("_selecionar_segmento_livre_toolbar", source)
        self.assertIn("Segmento por pontos", source)
        self.assertIn("working_rois", source)
        self.assertIn("_rois_trabalho_editor_placa", source)
        self.assertIn("_definir_rois_trabalho_editor_placa", source)

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

        self.assertNotIn("empty_support", module.F2_BOARD_SHAPE_ALLOWED_SLOTS)

    def test_board_editor_context_is_authoritative_even_if_global_mode_changes(self):
        class App:
            modo_atual = "ocioso"
            _f2_board_shape_edit_context = {
                "project": "P",
                "width": 640,
                "height": 480,
                "working_rois": [],
            }

        self.assertIsNotNone(_contexto_editor_placa_ativo(App()))

    def test_save_reads_working_rois_not_global_led_selection(self):
        import src.platform.f2_board_shape_editor as module

        source = inspect.getsource(module._salvar_e_fechar_editor_placa)
        self.assertIn("_rois_trabalho_editor_placa(app)", source)
        self.assertNotIn('getattr(app, "leds_selecionados", [])', source)
        self.assertIn("quantidade_salva != 1", source)
        self.assertIn("_invalidar_cache_rastreamento_f2", source)

    def test_confirm_hook_patches_final_app_editor_collection(self):
        import src.platform.f2_board_shape_editor as module

        source = inspect.getsource(module.instalar_editor_contorno_placa_f2)
        self.assertIn("RaspberryPi3ProductionApp._leds_editaveis", source)
        self.assertIn("RaspberryPi3ProductionApp._substituir_leds_editaveis", source)
        self.assertIn("_contexto_editor_placa_ativo(self)", source)


if __name__ == "__main__":
    unittest.main()
