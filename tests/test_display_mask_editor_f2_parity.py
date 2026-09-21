from __future__ import annotations

import inspect
import math
import tempfile
import unittest
from pathlib import Path

from src.core.roi_geometry import (
    SEGMENTO_ALTURA_PADRAO,
    SEGMENTO_LARGURA_PADRAO,
)
from src.platform.display_mask_editor import (
    DISPLAY_MASK_F2_PARITY_TOOLS,
    DisplayMaskEditorWindow,
    bbox_mascara_display,
    converter_mascara_legada_para_editor,
    criar_segmento_display_por_arrasto,
    mascara_display_contem_ponto,
)
from src.platform.display_f3_reference_geometry_editor import (
    F3_REFERENCE_HISTORY_LIMIT,
    _mask_display_number,
    _mask_geometry_bounds,
    _next_available_mask_id,
    _segment_polygon_from_drag,
    _transform_mask_geometry,
)
from src.platform.display_project_repository import DisplayProjectRepository


class DisplayMaskEditorF2ParityTests(unittest.TestCase):
    def test_editor_expoe_as_mesmas_quatro_ferramentas_operacionais_do_f2(self):
        self.assertEqual(
            ("segment", "circle", "freeform", "mass"),
            DISPLAY_MASK_F2_PARITY_TOOLS,
        )

    def test_segmento_horizontal_reutiliza_geometria_do_f2(self):
        mask = criar_segmento_display_por_arrasto(100, 100, 200, 100)
        self.assertEqual("segment", mask["type"])
        self.assertEqual((150, 100), (mask["cx"], mask["cy"]))
        self.assertEqual(100, mask["width"])
        self.assertEqual(SEGMENTO_ALTURA_PADRAO, mask["height"])
        self.assertAlmostEqual(0.0, mask["angle"])
        self.assertTrue(mascara_display_contem_ponto(mask, 150, 100))
        self.assertFalse(mascara_display_contem_ponto(mask, 150, 140))

    def test_segmento_vertical_recebe_rotacao_de_90_graus(self):
        mask = criar_segmento_display_por_arrasto(300, 200, 300, 300)
        self.assertEqual((300, 250), (mask["cx"], mask["cy"]))
        self.assertEqual(100, mask["width"])
        self.assertAlmostEqual(90.0, mask["angle"])
        x1, y1, x2, y2 = bbox_mascara_display(mask)
        self.assertLessEqual(x1, 300)
        self.assertGreaterEqual(x2, 300)
        self.assertLessEqual(y1, 200)
        self.assertGreaterEqual(y2, 300)

    def test_arrasto_curto_usa_dimensao_padrao_do_segmento_f2(self):
        mask = criar_segmento_display_por_arrasto(100, 100, 102, 101)
        self.assertEqual(SEGMENTO_LARGURA_PADRAO, mask["width"])
        self.assertEqual(SEGMENTO_ALTURA_PADRAO, mask["height"])
        self.assertEqual((100, 100), (mask["cx"], mask["cy"]))
        self.assertAlmostEqual(0.0, mask["angle"])

    def test_mascara_retangulo_legada_vira_segmento_sem_trocar_id(self):
        legacy = {
            "id": "MASK_007",
            "type": "rectangle",
            "x": 10,
            "y": 20,
            "width": 80,
            "height": 16,
        }
        converted = converter_mascara_legada_para_editor(legacy)
        self.assertEqual("MASK_007", converted["id"])
        self.assertEqual("segment", converted["type"])
        self.assertEqual((50, 28), (converted["cx"], converted["cy"]))
        self.assertEqual((80, 16), (converted["width"], converted["height"]))
        self.assertEqual(0.0, converted["angle"])

    def test_repositorio_display_faz_round_trip_do_segmento_sem_tocar_f2(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = DisplayProjectRepository(Path(temp_dir) / "display.json")
            self.assertTrue(repository.adicionar_projeto("DISPLAY SEG", (1920, 1080)))
            mask = criar_segmento_display_por_arrasto(
                300, 400, 500, 500, id_mascara="MASK_001"
            )
            self.assertTrue(repository.salvar_mascaras("DISPLAY SEG", [mask]))
            reloaded = DisplayProjectRepository(Path(temp_dir) / "display.json")
            project = reloaded.carregar_projeto("DISPLAY SEG")
            self.assertEqual([mask], project["masks"])

    def test_editor_tem_zoom_pan_massa_teclado_rotacao_e_segmento_livre(self):
        editor_module = __import__(
            "src.platform.display_mask_editor",
            fromlist=["DisplayMaskEditorWindow"],
        )
        geometry_module = __import__(
            "src.platform.display_mask_geometry",
            fromlist=["criar_segmento_display_por_arrasto"],
        )
        interaction_module = __import__(
            "src.platform.display_mask_editor_interactions",
            fromlist=["DisplayMaskEditorInteractionMixin"],
        )
        source = "\n".join(
            inspect.getsource(module)
            for module in (editor_module, geometry_module, interaction_module)
        )
        required = (
            "calcular_viewport_zoom_selecao",
            "calcular_centro_zoom_ancorado",
            "proximo_fator_zoom_selecao",
            '"<Button-2>"',
            '"<B2-Motion>"',
            '"<Control-a>"',
            '"<Delete>"',
            '"<Left>"',
            '"<Right>"',
            '"<Up>"',
            '"<Down>"',
            'TOOL_FREEFORM = "freeform"',
            'TOOL_MASS = "mass"',
            '"rotate"',
            "MAGNIFIER_SIZE_PX",
        )
        for token in required:
            self.assertIn(token, source)

    def test_editor_display_nao_depende_de_estado_mutavel_do_f2(self):
        modules = (
            __import__("src.platform.display_mask_editor", fromlist=["DisplayMaskEditorWindow"]),
            __import__("src.platform.display_mask_geometry", fromlist=["criar_segmento_display_por_arrasto"]),
            __import__("src.platform.display_mask_editor_interactions", fromlist=["DisplayMaskEditorInteractionMixin"]),
        )
        source = "\n".join(inspect.getsource(module) for module in modules)
        for forbidden in (
            "leds_selecionados",
            "leds_fixos_configurados",
            "config_repository",
            "operacao_engine",
            "operacao_ativa",
            "LedSelection",
        ):
            self.assertNotIn(forbidden, source)

    def test_editor_f3_segmento_inferior_usa_barra_real_mesmo_em_arrasto_horizontal(self):
        mask = _segment_polygon_from_drag(
            100,
            200,
            220,
            200,
            "MASK_031",
        )
        self.assertEqual("MASK_031", mask["id"])
        self.assertEqual("polygon", mask["type"])
        self.assertGreaterEqual(len(mask["points"]), 4)
        xs = [float(point[0]) for point in mask["points"]]
        ys = [float(point[1]) for point in mask["points"]]
        self.assertLessEqual(min(xs), 100.0)
        self.assertGreaterEqual(max(xs), 220.0)
        self.assertGreater(max(ys) - min(ys), 0.0)

    def test_editor_f3_exibe_numero_humano_da_mascara(self):
        self.assertEqual("1", _mask_display_number({"id": "MASK_001"}, 7))
        self.assertEqual("27", _mask_display_number({"id": "MASK_027"}, 1))
        self.assertEqual("4", _mask_display_number({"id": "SEM_NUMERO"}, 4))

    def test_editor_f3_reutiliza_menor_numero_livre_ao_criar_mascara(self):
        masks = [
            {"id": "MASK_002", "type": "circle"},
            {"id": "MASK_003", "type": "circle"},
        ]
        self.assertEqual("MASK_001", _next_available_mask_id(masks))
        masks.insert(0, {"id": "MASK_001", "type": "circle"})
        self.assertEqual("MASK_004", _next_available_mask_id(masks))

    def test_editor_f3_tem_historico_operacional_maior(self):
        self.assertGreaterEqual(F3_REFERENCE_HISTORY_LIMIT, 30)

    def test_editor_f3_transforma_mascara_individual_sem_mudar_id(self):
        mask = {
            "id": "MASK_007",
            "type": "polygon",
            "points": [[10, 10], [30, 10], [30, 20], [10, 20]],
        }
        moved = _transform_mask_geometry(
            mask,
            center_x=20,
            center_y=15,
            dx=5,
            dy=-2,
        )
        self.assertEqual("MASK_007", moved["id"])
        self.assertEqual([15.0, 8.0], moved["points"][0])
        self.assertEqual((15.0, 8.0, 35.0, 18.0), _mask_geometry_bounds(moved))

    def test_editor_f3_esticar_circulo_vira_poligono_compativel(self):
        mask = {
            "id": "MASK_003",
            "type": "circle",
            "cx": 100,
            "cy": 100,
            "radius": 20,
        }
        stretched = _transform_mask_geometry(
            mask,
            center_x=100,
            center_y=100,
            scale_x=1.5,
            scale_y=1.0,
        )
        self.assertEqual("MASK_003", stretched["id"])
        self.assertEqual("polygon", stretched["type"])
        self.assertEqual(32, len(stretched["points"]))

    def test_editor_f3_referencia_tem_pan_exclusao_e_numeracao_visual(self):
        module = __import__(
            "src.platform.display_f3_reference_geometry_editor",
            fromlist=["F3ReferenceGeometryEditor"],
        )
        source = inspect.getsource(module)
        for token in (
            '"<ButtonPress-2>"',
            '"<B2-Motion>"',
            '"<ButtonRelease-2>"',
            '"<Delete>"',
            '"<BackSpace>"',
            '"<Shift-Left>"',
            '"<Shift-Right>"',
            '"EXCLUIR MÁSCARA"',
            "delete_selected_mask",
            "_draw_mask_numbers",
            "_draw_selected_mask_outline",
            "_nearest_mask_body_canvas",
            "_next_available_mask_id",
            "_polygon_close_target_hit",
            "_finish_polygon_mask",
            "selected_mask_ids",
            "select_all_masks",
            "clear_mask_selection",
            "transform_selected",
            "_selection_handles_canvas",
            "_drag_selection_handle",
            '"<Control-a>"',
            '"SELECIONAR TUDO"',
            '"EDIÇÃO DA SELEÇÃO"',
            '"● {base_text}"',
            '"FECHAR"',
            "mask_draw_buttons",
        ):
            self.assertIn(token, source)
        self.assertNotIn("CÍRCULO → SEGMENTO", source)
        self.assertNotIn("replace_selected_circle_with_segment", source)
        self.assertIn("clique vazio nunca move tudo", source)
        self.assertIn("as setas não movem o conjunto", source)
        self.assertIn("keep_drawing", source)
        self.assertIn("tk.SUNKEN if enabled else tk.FLAT", source)
        self.assertIn("clique no PRIMEIRO PONTO para fechar", source)
        self.assertIn("return self._finish_polygon_mask()", source)
        self.assertIn('self.drag_target = ("mask_group", mask_id)', source)
        self.assertIn('"selection_handle"', source)
        self.assertNotIn("keep_drawing", source)
        self.assertIn("continua ativa", source)

    def test_classe_publica_continua_sendo_display_mask_editor_window(self):
        self.assertTrue(hasattr(DisplayMaskEditorWindow, "save"))
        self.assertTrue(hasattr(DisplayMaskEditorWindow, "set_tool"))
        self.assertTrue(hasattr(DisplayMaskEditorWindow, "_wheel"))
        self.assertTrue(hasattr(DisplayMaskEditorWindow, "_start_pan"))
        self.assertTrue(hasattr(DisplayMaskEditorWindow, "_select_all"))


if __name__ == "__main__":
    unittest.main()
