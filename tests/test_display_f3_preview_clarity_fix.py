from __future__ import annotations

import inspect
import unittest

import numpy as np

import src.platform.display_f3_preview_clarity_fix as clarity
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
)


class DisplayF3PreviewClarityFixTests(unittest.TestCase):
    def test_aceso_correto_fica_verde(self):
        self.assertEqual(
            DISPLAY_CHECK_STATE_ON,
            clarity.estado_visual_mascara_f3(
                DISPLAY_CHECK_STATE_ON,
                DISPLAY_CHECK_STATE_ON,
                has_any_on=True,
            ),
        )

    def test_apagado_correto_fica_vermelho_quando_placa_ja_acendeu(self):
        self.assertEqual(
            DISPLAY_CHECK_STATE_OFF,
            clarity.estado_visual_mascara_f3(
                DISPLAY_CHECK_STATE_OFF,
                DISPLAY_CHECK_STATE_OFF,
                has_any_on=True,
            ),
        )

    def test_pouca_luz_fica_amarela(self):
        self.assertEqual(
            "warning",
            clarity.estado_visual_mascara_f3(
                "low_light",
                DISPLAY_CHECK_STATE_ON,
                has_any_on=False,
            ),
        )

    def test_aceso_quando_deveria_apagado_fica_amarelo(self):
        self.assertEqual(
            "alert",
            clarity.estado_visual_mascara_f3(
                DISPLAY_CHECK_STATE_ON,
                DISPLAY_CHECK_STATE_OFF,
                has_any_on=True,
            ),
        )

    def test_apagado_quando_deveria_aceso_fica_amarelo_so_apos_placa_acender(self):
        self.assertEqual(
            "alert",
            clarity.estado_visual_mascara_f3(
                DISPLAY_CHECK_STATE_OFF,
                DISPLAY_CHECK_STATE_ON,
                has_any_on=True,
            ),
        )
        self.assertIsNone(
            clarity.estado_visual_mascara_f3(
                DISPLAY_CHECK_STATE_OFF,
                DISPLAY_CHECK_STATE_ON,
                has_any_on=False,
            )
        )

    def test_blue_intermitente_parcial_destaca_segmento_apagado_com_outro_on(self):
        self.assertEqual(
            "alert",
            clarity.estado_visual_mascara_f3(
                DISPLAY_CHECK_STATE_OFF,
                DISPLAY_CHECK_STATE_ON,
                has_any_on=True,
                intermittent=True,
            ),
        )
        self.assertEqual(
            DISPLAY_CHECK_STATE_OFF,
            clarity.estado_visual_mascara_f3(
                DISPLAY_CHECK_STATE_OFF,
                DISPLAY_CHECK_STATE_ON,
                has_any_on=False,
                intermittent=True,
            ),
        )

    def test_startup_todo_apagado_nao_pinta_h1_inteiro_de_vermelho(self):
        self.assertIsNone(
            clarity.estado_visual_mascara_f3(
                DISPLAY_CHECK_STATE_OFF,
                DISPLAY_CHECK_STATE_OFF,
                has_any_on=False,
            )
        )

    def test_preview_final_prioriza_legibilidade_e_falha_real(self):
        colors = clarity.F3_PREVIEW_CLEAR_COLORS
        self.assertEqual({"on", "off", "warning", "alert"}, set(colors))
        self.assertEqual(colors["warning"], (21, 204, 250))
        self.assertEqual(colors["alert"], (68, 68, 239))
        self.assertEqual(colors["off"], (139, 116, 100))
        self.assertLessEqual(clarity.F3_PREVIEW_CLEAR_ALPHA, 0.08)
        self.assertLessEqual(clarity.F3_PREVIEW_CLEAR_CONTOUR_THICKNESS, 1)
        self.assertGreater(
            clarity.F3_PREVIEW_ALERT_ALPHA,
            clarity.F3_PREVIEW_CLEAR_ALPHA,
        )
        self.assertGreater(
            clarity.F3_PREVIEW_ALERT_CONTOUR_THICKNESS,
            clarity.F3_PREVIEW_CLEAR_CONTOUR_THICKNESS,
        )
        self.assertIn("AZUL/CINZA: APAGADO", clarity.F3_PREVIEW_CLEAR_LEGEND)
        self.assertIn("VERMELHO: FALHA CONFIRMADA", clarity.F3_PREVIEW_CLEAR_LEGEND)

    def test_renderer_produtivo_ignora_falso_on_sem_energia_confirmada(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        context = {
            "resolution": (100, 100),
            "masks": (
                {
                    "id": "MASK_001",
                    "type": "segment",
                    "cx": 50,
                    "cy": 50,
                    "width": 30,
                    "height": 12,
                    "angle": 0.0,
                },
            ),
            "classifications": {"MASK_001": "on"},
            "expected_states": {"MASK_001": "on"},
            "failed_mask_ids": ("MASK_001",),
            "has_any_on": True,
            "power_confirmed": False,
            "power_off_confirmed": False,
            "energy_state": "unconfirmed",
        }

        rendered = clarity.renderizar_preview_claro_display_f3(frame, context)

        self.assertEqual(0, int(rendered.sum()))

    def test_guia_de_tracking_sem_energia_e_cinza_neutra(self):
        b, g, r = clarity.F3_PREVIEW_TRACKING_GUIDE_BGR
        self.assertLess(abs(int(b) - int(g)), 30)
        self.assertLess(abs(int(g) - int(r)), 30)

    def test_renderer_realmente_altera_pixels_quando_mascara_tem_classificacao(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        context = {
            "resolution": (100, 100),
            "masks": (
                {
                    "id": "MASK_001",
                    "type": "segment",
                    "cx": 50,
                    "cy": 50,
                    "width": 30,
                    "height": 12,
                    "angle": 0.0,
                },
            ),
            "classifications": {"MASK_001": "on"},
            "expected_states": {"MASK_001": "on"},
            "has_any_on": True,
        }

        rendered = clarity.renderizar_preview_claro_display_f3(frame, context)

        self.assertGreater(int(rendered.sum()), 0)
        self.assertTrue(np.any(rendered[50, 50] != frame[50, 50]))

    def test_mascara_divergente_recebe_destaque_amarelo_muito_mais_forte(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        mask = {
            "id": "MASK_026",
            "type": "segment",
            "cx": 50,
            "cy": 50,
            "width": 30,
            "height": 12,
            "angle": 0.0,
        }
        normal = clarity.renderizar_preview_claro_display_f3(
            frame,
            {
                "resolution": (100, 100),
                "masks": (mask,),
                "classifications": {"MASK_026": "on"},
                "expected_states": {"MASK_026": "on"},
                "failed_mask_ids": (),
                "has_any_on": True,
            },
        )
        failed = clarity.renderizar_preview_claro_display_f3(
            frame,
            {
                "resolution": (100, 100),
                "masks": (mask,),
                "classifications": {"MASK_026": "off"},
                "expected_states": {"MASK_026": "on"},
                "failed_mask_ids": ("MASK_026",),
                "has_any_on": True,
            },
        )

        self.assertGreater(int(failed.sum()), int(normal.sum()))
        center = failed[50, 50]
        self.assertGreater(int(center[2]), int(center[0]))
        self.assertGreater(int(center[2]), int(center[1]))

    def test_falha_nao_e_superdestacada_antes_de_existir_segmento_aceso(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        rendered = clarity.renderizar_preview_claro_display_f3(
            frame,
            {
                "resolution": (100, 100),
                "masks": (
                    {
                        "id": "MASK_001",
                        "type": "segment",
                        "cx": 50,
                        "cy": 50,
                        "width": 30,
                        "height": 12,
                        "angle": 0.0,
                    },
                ),
                "classifications": {"MASK_001": "off"},
                "expected_states": {"MASK_001": "on"},
                "failed_mask_ids": ("MASK_001",),
                "has_any_on": False,
            },
        )

        self.assertEqual(0, int(rendered.sum()))

    def test_fallback_de_classificacao_aceita_somente_o_check_atual(self):
        right = clarity._classifications_from_analysis(
            {
                "project_name": "P1",
                "check_id": "CHECK_002",
                "mask_results": [
                    {"mask_id": "MASK_001", "classified": "on"},
                    {"mask_id": "MASK_002", "classified": "off"},
                ],
            },
            project_name="P1",
            check_id="CHECK_002",
        )
        wrong = clarity._classifications_from_analysis(
            {
                "project_name": "P1",
                "check_id": "CHECK_001",
                "mask_results": [
                    {"mask_id": "MASK_001", "classified": "on"},
                ],
            },
            project_name="P1",
            check_id="CHECK_002",
        )

        self.assertEqual({"MASK_001": "on", "MASK_002": "off"}, right)
        self.assertEqual({}, wrong)

    def test_falha_explicitamente_vem_de_matched_false_do_check_atual(self):
        analysis = {
            "project_name": "P1",
            "check_id": "CHECK_002",
            "mask_results": [
                {"mask_id": "MASK_025", "classified": "on", "matched": True},
                {"mask_id": "MASK_026", "classified": "off", "matched": False},
            ],
        }
        self.assertEqual(
            {"MASK_026"},
            clarity._failed_mask_ids_from_analysis(
                analysis,
                project_name="P1",
                check_id="CHECK_002",
            ),
        )
        self.assertEqual(
            set(),
            clarity._failed_mask_ids_from_analysis(
                analysis,
                project_name="P1",
                check_id="CHECK_001",
            ),
        )

    def test_falha_intermitente_parcial_entra_no_failed_ids_mesmo_matched_true(self):
        analysis = {
            "project_name": "P1",
            "check_id": "CHECK_002",
            "mask_results": [
                {
                    "mask_id": "MASK_001",
                    "expected": "on",
                    "classified": "on",
                    "matched": True,
                },
                {
                    "mask_id": "MASK_027",
                    "expected": "on",
                    "classified": "off",
                    "matched": True,
                },
            ],
        }
        self.assertEqual(
            {"MASK_027"},
            clarity._failed_mask_ids_from_analysis(
                analysis,
                project_name="P1",
                check_id="CHECK_002",
            ),
        )

    def test_preview_prefere_estado_efetivo_e_nao_recria_falso_mask_010(self):
        analysis = {
            "project_name": "P1",
            "check_id": "CHECK_002",
            "effective_classifications": {
                "MASK_010": "on",
                "MASK_027": "off",
            },
            "effective_failed_mask_ids": ("MASK_027",),
            "mask_results": [
                {
                    "mask_id": "MASK_010",
                    "expected": "on",
                    "classified": "off",
                    "matched": False,
                },
                {
                    "mask_id": "MASK_027",
                    "expected": "on",
                    "classified": "off",
                    "matched": False,
                },
            ],
        }
        self.assertEqual(
            {"MASK_010": "on", "MASK_027": "off"},
            clarity._classifications_from_analysis(
                analysis,
                project_name="P1",
                check_id="CHECK_002",
            ),
        )
        self.assertEqual(
            {"MASK_027"},
            clarity._failed_mask_ids_from_analysis(
                analysis,
                project_name="P1",
                check_id="CHECK_002",
            ),
        )

    def test_renderer_ao_vivo_tem_zoom_e_badge_somente_para_falha(self):
        source = inspect.getsource(clarity.renderizar_preview_claro_display_f3)
        self.assertIn("_draw_display_zoom_inset", source)
        self.assertIn("_draw_failure_badge", source)
        self.assertIn("debug_detailed", source)
        self.assertNotIn("NG ", source)

    def test_renderer_final_e_reaplicavel_sem_duplicar_contexto(self):
        source = inspect.getsource(clarity._aplicar_render_final)
        self.assertIn("_display_f3_clear_preview_context_installed", source)
        self.assertIn("renderizar_preview_claro_display_f3", source)

    def test_render_nao_escreve_ng_sobre_segmento(self):
        source = inspect.getsource(clarity.renderizar_preview_claro_display_f3)
        self.assertNotIn("putText", source)
        self.assertNotIn("NG ", source)

    def test_modulo_permanece_isolado_de_f2(self):
        source = inspect.getsource(clarity)
        self.assertNotIn("src.platform.f2_", source)
        self.assertNotIn("F2Automatic", source)


if __name__ == "__main__":
    unittest.main()
