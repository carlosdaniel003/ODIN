from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import patch

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

    def test_preview_classico_luminoso_pinta_verde_mesmo_com_gate_off(self):
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
            "classifications": {"MASK_001": "off"},
            "live_luminous_only": True,
            "luminous_mask_ids": ("MASK_001",),
            "power_confirmed": False,
            "power_off_confirmed": True,
            "energy_state": "off",
        }

        rendered = clarity.renderizar_preview_claro_display_f3(
            frame,
            context,
        )

        center = rendered[50, 50]
        self.assertGreater(int(center[1]), int(center[2]))
        self.assertGreater(int(center[1]), int(center[0]))

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

    @staticmethod
    def _live_visual_test_context():
        return {
            "project_name": "P1",
            "check_id": "CHECK_001",
            "resolution": (160, 80),
            "masks": (
                {
                    "id": "MASK_001",
                    "type": "polygon",
                    "points": [[8, 28], [32, 28], [32, 52], [8, 52]],
                },
                {
                    "id": "MASK_002",
                    "type": "polygon",
                    "points": [[48, 28], [72, 28], [72, 52], [48, 52]],
                },
                {
                    "id": "MASK_003",
                    "type": "polygon",
                    "points": [[88, 28], [112, 28], [112, 52], [88, 52]],
                },
                {
                    "id": "MASK_004",
                    "type": "polygon",
                    "points": [[128, 28], [152, 28], [152, 52], [128, 52]],
                },
            ),
            "live_luminous_only": True,
        }

    def test_amostra_visual_latest_frame_detecta_emissao_sem_worker_semantico(self):
        frame = np.zeros((80, 160, 3), dtype=np.uint8)
        frame[30:51, 50:71] = 255
        frame[30:51, 130:151] = 255

        result = clarity.detectar_emissao_visual_ao_vivo_f3(
            frame,
            self._live_visual_test_context(),
        )

        self.assertTrue(result["ready"])
        self.assertEqual(
            {"MASK_002", "MASK_004"},
            set(result["mask_ids"]),
        )
        self.assertGreater(result["dynamic_range"], 100.0)

    def test_amostra_visual_detecta_maioria_acesa_com_contraste_moderado(self):
        frame = np.full((80, 160, 3), 100, dtype=np.uint8)
        frame[30:51, 50:71] = 180
        frame[30:51, 90:111] = 180
        frame[30:51, 130:151] = 180

        result = clarity.detectar_emissao_visual_ao_vivo_f3(
            frame,
            self._live_visual_test_context(),
        )

        self.assertTrue(result["ready"])
        self.assertEqual(
            {"MASK_002", "MASK_003", "MASK_004"},
            set(result["mask_ids"]),
        )
        self.assertGreaterEqual(result["cluster_gap"], 70.0)

    def test_amostra_visual_detecta_todos_acesos_por_evidencia_absoluta(self):
        frame = np.full((80, 160, 3), 40, dtype=np.uint8)
        frame[30:51, 10:31] = 185
        frame[30:51, 50:71] = 185
        frame[30:51, 90:111] = 185
        frame[30:51, 130:151] = 185

        result = clarity.detectar_emissao_visual_ao_vivo_f3(
            frame,
            self._live_visual_test_context(),
        )

        self.assertTrue(result["ready"])
        self.assertEqual(
            {"MASK_001", "MASK_002", "MASK_003", "MASK_004"},
            set(result["mask_ids"]),
        )

    def test_classificacao_fisica_visual_nao_depende_do_check_logico(self):
        frame = np.zeros((80, 160, 3), dtype=np.uint8)

        class _App:
            def __init__(self):
                self._display_auto_last_analysis = {
                    "project_name": "P1",
                    "check_id": "CHECK_AUX",
                    "mask_results": [
                        {
                            "mask_id": "MASK_001",
                            "classified": "on",
                        },
                        {
                            "mask_id": "MASK_002",
                            "classified": "off",
                        },
                        {
                            "mask_id": "MASK_003",
                            "classified": "low_light",
                        },
                    ],
                }

            def configure_display(self):
                return None

        app = _App()
        window = SimpleNamespace(
            on_configure=app.configure_display,
        )

        physical = clarity._latest_physical_visual_classifications(
            window,
            project_name="P1",
        )

        self.assertEqual(
            {
                "MASK_001": "on",
                "MASK_002": "off",
                "MASK_003": "low_light",
            },
            physical,
        )

        context = self._live_visual_test_context()
        context["check_id"] = "CHECK_USB"
        context["visual_physical_classifications"] = physical

        with patch.object(
            clarity,
            "detectar_emissao_visual_ao_vivo_f3",
            return_value={
                "ready": True,
                "mask_ids": (),
                "reason": "ok",
                "sampled_mask_count": 4,
                "threshold": 200.0,
                "baseline": 100.0,
                "peak": 120.0,
            },
        ):
            mirrored = clarity.aplicar_emissao_visual_ao_vivo_f3(
                window,
                frame,
                context,
                frame_token=("camera", 77),
                geometry_token=("fixed", "P1"),
            )

        self.assertEqual(("MASK_001",), mirrored["live_visual_mask_ids"])
        self.assertEqual(
            "on",
            mirrored["live_visual_classifications"]["MASK_001"],
        )
        self.assertEqual(
            "off",
            mirrored["live_visual_classifications"]["MASK_002"],
        )
        self.assertEqual(
            "low_light",
            mirrored["live_visual_classifications"]["MASK_003"],
        )

    def test_renderer_visual_pinta_on_fisico_mesmo_se_detector_latest_frame_vazio(self):
        frame = np.zeros((80, 160, 3), dtype=np.uint8)
        context = self._live_visual_test_context()
        context.update(
            live_visual_sample_ready=True,
            live_visual_mask_ids=(),
            live_visual_classifications={
                "MASK_001": "off",
                "MASK_002": "on",
                "MASK_003": "off",
                "MASK_004": "off",
            },
            power_confirmed=False,
            power_off_confirmed=True,
            energy_state="off",
        )

        rendered = clarity.renderizar_preview_claro_display_f3(
            frame,
            context,
        )

        on_pixel = rendered[40, 60]
        off_pixel = rendered[40, 20]
        self.assertGreater(int(on_pixel[1]), int(on_pixel[2]))
        self.assertGreater(int(on_pixel[1]), int(on_pixel[0]))
        self.assertGreater(int(off_pixel.sum()), 0)

    def test_amostra_visual_latest_frame_apaga_visor_na_fase_escura(self):
        frame = np.zeros((80, 160, 3), dtype=np.uint8)

        result = clarity.detectar_emissao_visual_ao_vivo_f3(
            frame,
            self._live_visual_test_context(),
        )

        self.assertTrue(result["ready"])
        self.assertEqual((), result["mask_ids"])

    def test_amostra_visual_e_calculada_uma_vez_por_frame_e_reutilizada(self):
        frame = np.zeros((80, 160, 3), dtype=np.uint8)
        window = SimpleNamespace()
        context = self._live_visual_test_context()
        sample = {
            "ready": True,
            "mask_ids": ("MASK_002",),
            "reason": "ok",
            "sampled_mask_count": 4,
            "baseline": 10.0,
            "peak": 240.0,
            "threshold": 150.0,
        }

        with patch.object(
            clarity,
            "detectar_emissao_visual_ao_vivo_f3",
            return_value=sample,
        ) as detect:
            first = clarity.aplicar_emissao_visual_ao_vivo_f3(
                window,
                frame,
                context,
                frame_token=("camera", 10),
                geometry_token=123,
            )
            second = clarity.aplicar_emissao_visual_ao_vivo_f3(
                window,
                frame,
                context,
                frame_token=("camera", 10),
                geometry_token=123,
            )

        self.assertEqual(1, detect.call_count)
        self.assertEqual(("MASK_002",), first["live_visual_mask_ids"])
        self.assertEqual(
            first["live_visual_mask_ids"],
            second["live_visual_mask_ids"],
        )
        self.assertEqual(
            "latest_preview_frame_core_v",
            first["live_visual_sample_source"],
        )

    def test_preview_classico_usa_amostra_do_mesmo_frame_mesmo_antes_do_gate(self):
        frame = np.zeros((80, 160, 3), dtype=np.uint8)
        context = self._live_visual_test_context()
        context.update(
            live_visual_sample_ready=True,
            live_visual_mask_ids=("MASK_003",),
            power_confirmed=False,
            power_off_confirmed=True,
            energy_state="off",
        )

        rendered = clarity.renderizar_preview_claro_display_f3(
            frame,
            context,
        )

        lit = rendered[40, 100]
        dark = rendered[40, 60]
        self.assertGreater(int(lit[1]), int(lit[2]))
        self.assertGreater(int(lit[1]), int(lit[0]))
        self.assertLess(int(dark[0]) + int(dark[1]) + int(dark[2]), 20)

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

    def test_blue_validacao_amarela_e_ng_confirmado_vermelho(self):
        classifications = {
            "MASK_010": "on",
            "MASK_027": "off",
        }
        expected = {
            "MASK_010": "on",
            "MASK_027": "on",
        }
        failed = {"MASK_027"}

        self.assertEqual(
            "on",
            clarity._presentation_for_effective_mask(
                "MASK_010",
                classifications,
                expected,
                failed,
                set(),
                {"MASK_027"},
                has_any_on=True,
                intermittent=True,
                effective_authority=True,
            ),
        )
        self.assertEqual(
            "warning",
            clarity._presentation_for_effective_mask(
                "MASK_027",
                classifications,
                expected,
                failed,
                set(),
                {"MASK_027"},
                has_any_on=True,
                intermittent=True,
                effective_authority=True,
            ),
        )
        self.assertEqual(
            "alert",
            clarity._presentation_for_effective_mask(
                "MASK_027",
                classifications,
                expected,
                failed,
                {"MASK_027"},
                set(),
                has_any_on=True,
                intermittent=True,
                effective_authority=True,
            ),
        )

    def test_tracking_off_usa_todas_as_mascaras_no_espelho_visual(self):
        source = inspect.getsource(clarity._project_preview_context)
        fixed_pos = source.index("# Modo legado/desligado")
        fixed_source = source[fixed_pos:]

        self.assertIn(
            "for mask in mascaras_geometria_check_display(project, check)",
            fixed_source,
        )
        self.assertIn('"tracking_active": False', fixed_source)
        self.assertIn('"live_luminous_only": True', fixed_source)
        self.assertNotIn("active_masks", fixed_source)

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
