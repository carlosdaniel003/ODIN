from __future__ import annotations

import inspect
import unittest

import numpy as np

import src.platform.display_live_roi_overlay as overlay_module
from src.platform.display_live_roi_overlay import (
    DISPLAY_ROI_OVERLAY_ALPHA,
    renderizar_overlay_rois_display_f3,
)
from src.platform.display_production_f3 import DisplayProductionF3Mixin
from src.platform.display_production_f3_window import DisplayProductionF3Window
import src.platform.display_f3_preview_clarity_fix as preview_clarity


class DisplayF3LiveRoiOverlayTests(unittest.TestCase):
    def test_overlay_colore_estados_sem_modificar_frame_original(self):
        frame = np.zeros((80, 180, 3), dtype=np.uint8)
        original = frame.copy()
        context = {
            "resolution": (180, 80),
            "masks": (
                {"id": "ON", "type": "circle", "cx": 30, "cy": 40, "radius": 12},
                {"id": "OFF", "type": "circle", "cx": 90, "cy": 40, "radius": 12},
                {"id": "LOW", "type": "circle", "cx": 150, "cy": 40, "radius": 12},
            ),
            "classifications": {
                "ON": "on",
                "OFF": "off",
                "LOW": "low_light",
            },
        }

        rendered = renderizar_overlay_rois_display_f3(frame, context)

        np.testing.assert_array_equal(frame, original)
        self.assertFalse(np.shares_memory(frame, rendered))

        on_pixel = rendered[40, 30]
        off_pixel = rendered[40, 90]
        low_pixel = rendered[40, 150]

        self.assertGreater(int(on_pixel[1]), int(on_pixel[2]))
        self.assertGreater(int(on_pixel[1]), int(on_pixel[0]))
        self.assertGreater(int(off_pixel[2]), int(off_pixel[1]))
        self.assertGreater(int(off_pixel[2]), int(off_pixel[0]))
        self.assertGreater(int(low_pixel[1]), int(low_pixel[0]))
        self.assertGreater(int(low_pixel[2]), int(low_pixel[0]))

    def test_overlay_tem_preenchimento_leve(self):
        self.assertGreater(DISPLAY_ROI_OVERLAY_ALPHA, 0.0)
        self.assertLessEqual(DISPLAY_ROI_OVERLAY_ALPHA, 0.15)

    def test_visor_88_88_marca_ng_no_segmento_off_durante_fase_on_intermitente(self):
        state = DisplayProductionF3Window._display_readout_semantic_state(
            "off",
            "on",
            ready=True,
            intermittent=True,
            has_any_on=True,
        )
        self.assertEqual("ng", state)

        dark_phase = DisplayProductionF3Window._display_readout_semantic_state(
            "off",
            "on",
            ready=True,
            intermittent=True,
            has_any_on=False,
        )
        self.assertEqual("off", dark_phase)

    def test_visor_efetivo_distingue_validacao_de_ng_confirmado(self):
        validating = DisplayProductionF3Window._display_readout_semantic_state(
            "off",
            "on",
            failed=False,
            ready=True,
            intermittent=True,
            has_any_on=True,
            validating=True,
            effective_authority=True,
        )
        confirmed = DisplayProductionF3Window._display_readout_semantic_state(
            "off",
            "on",
            failed=True,
            ready=True,
            intermittent=True,
            has_any_on=True,
            validating=False,
            effective_authority=True,
        )
        conform = DisplayProductionF3Window._display_readout_semantic_state(
            "on",
            "on",
            failed=False,
            ready=True,
            intermittent=True,
            has_any_on=True,
            validating=False,
            effective_authority=True,
        )
        self.assertEqual("warning", validating)
        self.assertEqual("ng", confirmed)
        self.assertEqual("on", conform)

    def test_preview_operacional_classico_so_pinta_luz_em_verde(self):
        frame = np.zeros((80, 180, 3), dtype=np.uint8)
        context = {
            "resolution": (180, 80),
            "masks": (
                {"id": "LIT", "type": "circle", "cx": 45, "cy": 40, "radius": 12},
                {"id": "DARK", "type": "circle", "cx": 135, "cy": 40, "radius": 12},
            ),
            "classifications": {
                "LIT": "off",
                "DARK": "low_light",
            },
            "live_luminous_only": True,
            "luminous_mask_ids": ("LIT",),
            "board_points": (),
        }

        rendered = preview_clarity.renderizar_preview_claro_display_f3(
            frame,
            context,
        )

        lit = rendered[40, 45]
        dark = rendered[40, 135]
        self.assertGreater(int(lit[1]), int(lit[2]))
        self.assertGreater(int(lit[1]), int(lit[0]))
        # O centro da máscara sem luz não recebe preenchimento vermelho/amarelo.
        self.assertLess(int(dark[0]) + int(dark[1]) + int(dark[2]), 20)

    def test_visor_luminoso_so_mostra_segmentos_identificados_com_luz(self):
        source = inspect.getsource(
            DisplayProductionF3Window._draw_fixed_semantic_digit
        )
        self.assertIn('context.get("live_luminous_only")', source)
        self.assertIn('context.get("live_visual_sample_ready")', source)
        self.assertIn('context.get("live_visual_mask_ids")', source)
        self.assertIn('context.get("luminous_mask_ids")', source)
        self.assertIn("live_display_ids", source)
        self.assertIn("mask_id in live_display_ids", source)

    def test_visor_luminoso_ignora_gate_e_classificacao_assincrona(self):
        class _Canvas:
            def __init__(self):
                self.polygons = []

            def create_polygon(self, *args, **kwargs):
                self.polygons.append(dict(kwargs))

            def create_text(self, *args, **kwargs):
                return None

        window = DisplayProductionF3Window.__new__(
            DisplayProductionF3Window
        )
        window.display_readout_canvas = _Canvas()
        window._draw_fixed_segment_number = lambda *args, **kwargs: None
        mask_ids = [f"MASK_{index:03d}" for index in range(1, 8)]
        context = {
            "classifications": {
                mask_id: "on"
                for mask_id in mask_ids
            },
            "expected_states": {
                mask_id: "on"
                for mask_id in mask_ids
            },
            "failed_mask_ids": set(),
            "validating_mask_ids": set(),
            "ui_mask_authority": "effective_mask_results_v1",
            "live_luminous_only": True,
            "luminous_mask_ids": {"MASK_002"},
            "live_visual_sample_ready": True,
            "live_visual_mask_ids": {"MASK_005"},
            "power_confirmed": False,
            "power_off_confirmed": True,
            "energy_state": "off",
        }

        window._draw_fixed_semantic_digit(
            0.0,
            0.0,
            80.0,
            140.0,
            mask_ids,
            context,
            ready=False,
        )

        fills = [
            item.get("fill")
            for item in window.display_readout_canvas.polygons
        ]
        self.assertEqual(
            1,
            fills.count(DisplayProductionF3Window.DISPLAY_READOUT_ACTIVE),
        )
        self.assertEqual(
            6,
            fills.count(DisplayProductionF3Window.DISPLAY_READOUT_INACTIVE),
        )

    def test_resultado_ok_terminal_nao_congela_espelho_visual_live(self):
        source = inspect.getsource(
            DisplayProductionF3Window.update_camera_preview
        )
        self.assertIn("_display_ng_evidence_frozen", source)
        self.assertNotIn("_display_terminal_waiting_removal", source)
        self.assertNotIn('_display_terminal_result_kind == "ok"', source)

    def test_tracking_off_tambem_amostra_emissao_do_frame_atual(self):
        frame = np.full((80, 160, 3), 35, dtype=np.uint8)
        frame[30:51, 10:31] = 210

        class _Repository:
            pass

        class _App:
            def __init__(self):
                self.camera_frame_atual = frame
                self.camera_ultimo_frame_id = 77
                self.display_project_repository = _Repository()
                self._display_f3_live_visual_mirror_debug = None

            def configure_display(self):
                return None

            def _display_auto_frame_token(self, _frame):
                return ("camera", self.camera_ultimo_frame_id)

        app = _App()

        class _Window:
            def __init__(self):
                self.on_configure = app.configure_display

        window = _Window()
        masks = (
            {"id": "MASK_001", "type": "circle", "cx": 20, "cy": 40, "radius": 10},
            {"id": "MASK_002", "type": "circle", "cx": 60, "cy": 40, "radius": 10},
            {"id": "MASK_003", "type": "circle", "cx": 100, "cy": 40, "radius": 10},
            {"id": "MASK_004", "type": "circle", "cx": 140, "cy": 40, "radius": 10},
        )
        context = {
            "project_name": "DISPLAY",
            "check_id": "CHECK_001",
            "resolution": (160, 80),
            "masks": masks,
            "readout_mask_ids": tuple(mask["id"] for mask in masks),
            "readout_slot_mask_ids": (),
            "tracking_active": False,
            "tracking_locked": False,
            "live_luminous_only": True,
            "luminous_mask_ids": (),
        }

        result = overlay_module._prepare_live_visual_mirror_context(
            window,
            frame,
            context,
            0,
        )

        self.assertTrue(result["live_visual_sample_ready"])
        self.assertEqual(
            ("MASK_001",),
            result["live_visual_mask_ids"],
        )
        self.assertEqual(
            "fixed_latest_frame_live_visual",
            app._display_f3_live_visual_mirror_debug["render_path"],
        )
        self.assertFalse(
            app._display_f3_live_visual_mirror_debug["tracking_enabled"]
        )

    def test_tracking_off_atualiza_visor_depois_da_amostra_visual(self):
        source = inspect.getsource(
            overlay_module.instalar_overlay_rois_ao_vivo_display_f3
        )
        sample_pos = source.index("_prepare_live_visual_mirror_context(")
        readout_pos = source.index("set_display_readout_context(context)")
        render_pos = source.index("renderizar_overlay_rois_display_f3(")

        self.assertGreater(readout_pos, sample_pos)
        self.assertGreater(render_pos, readout_pos)

    def test_visor_mostra_classificacao_fisica_mesmo_com_live_ids_vazios(self):
        class _Canvas:
            def __init__(self):
                self.polygons = []

            def create_polygon(self, *args, **kwargs):
                self.polygons.append(dict(kwargs))

            def create_text(self, *args, **kwargs):
                return None

        window = DisplayProductionF3Window.__new__(
            DisplayProductionF3Window
        )
        window.display_readout_canvas = _Canvas()
        window._draw_fixed_segment_number = lambda *args, **kwargs: None
        mask_ids = [f"MASK_{index:03d}" for index in range(1, 8)]
        context = {
            "classifications": {},
            "expected_states": {},
            "failed_mask_ids": set(),
            "validating_mask_ids": set(),
            "ui_mask_authority": "",
            "live_luminous_only": True,
            "luminous_mask_ids": set(),
            "live_visual_sample_ready": True,
            "live_visual_mask_ids": set(),
            "live_visual_classifications": {
                "MASK_001": "on",
                "MASK_002": "off",
                "MASK_003": "low_light",
            },
            "power_confirmed": False,
            "power_off_confirmed": True,
            "energy_state": "off",
        }

        window._draw_fixed_semantic_digit(
            0.0,
            0.0,
            80.0,
            140.0,
            mask_ids,
            context,
            ready=False,
        )

        fills = [
            item.get("fill")
            for item in window.display_readout_canvas.polygons
        ]
        self.assertEqual(
            1,
            fills.count(DisplayProductionF3Window.DISPLAY_READOUT_ACTIVE),
        )
        self.assertEqual(
            1,
            fills.count(DisplayProductionF3Window.DISPLAY_READOUT_OFF),
        )
        self.assertEqual(
            1,
            fills.count(DisplayProductionF3Window.DISPLAY_READOUT_WARNING),
        )

    def test_ng_confirmado_pinta_somente_mascara_defeituosa_vermelha_no_preview_classico(self):
        frame = np.zeros((80, 180, 3), dtype=np.uint8)
        context = {
            "resolution": (180, 80),
            "masks": (
                {"id": "MASK_001", "type": "circle", "cx": 30, "cy": 40, "radius": 12},
                {"id": "MASK_024", "type": "circle", "cx": 90, "cy": 40, "radius": 12},
                {"id": "MASK_028", "type": "circle", "cx": 150, "cy": 40, "radius": 12},
            ),
            "live_luminous_only": True,
            "live_visual_sample_ready": True,
            "live_visual_mask_ids": ("MASK_001",),
            "live_visual_classifications": {
                "MASK_001": "on",
                "MASK_024": "off",
                "MASK_028": "off",
            },
            "effective_confirmed_failed_mask_ids": ("MASK_024",),
            "board_points": (),
        }

        rendered = preview_clarity.renderizar_preview_claro_display_f3(
            frame,
            context,
        )

        on_pixel = rendered[40, 30]
        ng_pixel = rendered[40, 90]
        off_pixel = rendered[40, 150]

        self.assertGreater(int(on_pixel[1]), int(on_pixel[2]))
        self.assertGreater(int(on_pixel[1]), int(on_pixel[0]))
        self.assertGreater(int(ng_pixel[2]), int(ng_pixel[1]))
        self.assertGreater(int(ng_pixel[2]), int(ng_pixel[0]))
        self.assertGreater(int(off_pixel[1]), int(off_pixel[2]))
        self.assertGreater(int(off_pixel[1]), int(off_pixel[0]))
        self.assertNotEqual(tuple(ng_pixel), tuple(off_pixel))

    def test_visor_live_prioriza_falha_confirmada_em_vermelho(self):
        class _Canvas:
            def __init__(self):
                self.polygons = []

            def create_polygon(self, *args, **kwargs):
                self.polygons.append(dict(kwargs))

            def create_text(self, *args, **kwargs):
                return None

        window = DisplayProductionF3Window.__new__(
            DisplayProductionF3Window
        )
        window.display_readout_canvas = _Canvas()
        window._draw_fixed_segment_number = lambda *args, **kwargs: None
        mask_ids = [f"MASK_{index:03d}" for index in range(1, 8)]
        context = {
            "classifications": {},
            "expected_states": {},
            "failed_mask_ids": {"MASK_004"},
            "validating_mask_ids": set(),
            "ui_mask_authority": "effective_mask_results_v1",
            "live_luminous_only": True,
            "luminous_mask_ids": set(mask_ids),
            "live_visual_sample_ready": True,
            "live_visual_mask_ids": set(mask_ids),
            "live_visual_classifications": {
                mask_id: "on" for mask_id in mask_ids
            },
            "power_confirmed": True,
            "power_off_confirmed": False,
            "energy_state": "powered",
        }

        window._draw_fixed_semantic_digit(
            0.0,
            0.0,
            80.0,
            140.0,
            mask_ids,
            context,
            ready=True,
        )

        segment_polygons = [
            item
            for item in window.display_readout_canvas.polygons
            if "display-readout-segment"
            in tuple(item.get("tags") or ())
        ]
        fills = [item.get("fill") for item in segment_polygons]
        self.assertEqual(
            1,
            fills.count(DisplayProductionF3Window.DISPLAY_READOUT_NG),
        )
        self.assertEqual(
            6,
            fills.count(DisplayProductionF3Window.DISPLAY_READOUT_ACTIVE),
        )

    def test_contexto_do_visor_prefere_falha_confirmada_ao_failed_bruto(self):
        window = DisplayProductionF3Window.__new__(
            DisplayProductionF3Window
        )
        window._display_readout_frozen = False
        window._redraw_display_readout = lambda: None

        window.set_display_readout_context(
            {
                "readout_mask_ids": ("MASK_004", "MASK_007", "MASK_024"),
                "effective_classifications": {
                    "MASK_004": "off",
                    "MASK_007": "off",
                    "MASK_024": "off",
                },
                "effective_failed_mask_ids": (
                    "MASK_004",
                    "MASK_007",
                    "MASK_024",
                ),
                "effective_confirmed_failed_mask_ids": ("MASK_024",),
                "effective_validating_mask_ids": (
                    "MASK_004",
                    "MASK_007",
                ),
                "live_luminous_only": True,
            }
        )

        self.assertEqual(
            {"MASK_024"},
            window._display_readout_context["failed_mask_ids"],
        )
        self.assertEqual(
            {"MASK_004", "MASK_007"},
            window._display_readout_context["validating_mask_ids"],
        )

    def test_snapshot_tracking_preserva_geometria_do_mesmo_frame_ng(self):
        project = {
            "name": "DISPLAY",
            "master_resolution": (180, 80),
            "masks": [
                {
                    "id": "MASK_024",
                    "type": "circle",
                    "cx": 30,
                    "cy": 40,
                    "radius": 10,
                }
            ],
            "checks": [
                {
                    "id": "CHECK_002",
                    "name": "BLUE",
                    "intermittent": True,
                    "mask_states": {"MASK_024": "on"},
                }
            ],
        }

        class _Repository:
            @staticmethod
            def carregar_projeto(_name):
                return project

        geometry = {
            "locked": True,
            "resolution": (180, 80),
            "reference": "luminous:CHECK_002",
            "geometry_space": "canonical_projective",
            "board_points": (
                (80.0, 10.0),
                (170.0, 10.0),
                (170.0, 70.0),
                (80.0, 70.0),
            ),
            "masks": (
                {
                    "id": "MASK_024",
                    "type": "circle",
                    "cx": 120,
                    "cy": 40,
                    "radius": 10,
                },
            ),
        }
        analysis = {
            "effective_classifications": {"MASK_024": "off"},
            "effective_failed_mask_ids": ("MASK_024",),
            "effective_confirmed_failed_mask_ids": ("MASK_024",),
            "effective_validating_mask_ids": (),
            "ui_mask_authority": "effective_mask_results_v1",
        }

        context = overlay_module.montar_contexto_overlay_snapshot_display_f3(
            _Repository(),
            "DISPLAY",
            "CHECK_002",
            analysis,
            0,
            tracking_geometry=geometry,
        )

        self.assertEqual(
            "tracking_geometry_snapshot",
            context["snapshot_geometry_source"],
        )
        self.assertTrue(context["tracking_active"])
        self.assertEqual(120, int(context["masks"][0]["cx"]))
        self.assertNotEqual(30, int(context["masks"][0]["cx"]))
        self.assertEqual("off", context["effective_classifications"]["MASK_024"])
        self.assertEqual(
            ("MASK_024",),
            context["effective_confirmed_failed_mask_ids"],
        )

    def test_freeze_ng_prefere_contexto_atomico_ao_ultimo_overlay_live(self):
        window = DisplayProductionF3Window.__new__(
            DisplayProductionF3Window
        )
        window._display_readout_context = {
            "failed_mask_ids": set(),
            "classifications": {"MASK_024": "off"},
        }
        window._display_last_overlay_context = {
            "snapshot_geometry_source": "stale_live_overlay",
            "masks": ({"id": "STALE"},),
            "effective_confirmed_failed_mask_ids": (),
        }
        atomic = {
            "snapshot_geometry_source": "tracking_geometry_snapshot",
            "masks": ({"id": "MASK_024"},),
            "effective_confirmed_failed_mask_ids": ("MASK_024",),
        }
        window._check_snapshot = {}
        window._display_frozen_ng_visual_debug = {}
        window.display_readout_canvas = None
        window._capture_analysis_statuses = lambda: {}
        window._set_segregation_action_enabled = lambda _enabled: None
        window.restore_frozen_analysis_statuses = lambda: None
        window._redraw_display_readout = lambda: None

        window.freeze_ng_evidence(
            confirmed_failed_mask_ids=("MASK_024",),
            overlay_context=atomic,
        )

        self.assertEqual(
            "tracking_geometry_snapshot",
            window._display_frozen_overlay_context[
                "snapshot_geometry_source"
            ],
        )
        self.assertEqual(
            "MASK_024",
            window._display_frozen_overlay_context["masks"][0]["id"],
        )

    def test_freeze_ng_reafirma_falha_confirmada_no_contexto_do_visor(self):
        window = DisplayProductionF3Window.__new__(
            DisplayProductionF3Window
        )
        window._display_readout_context = {
            "failed_mask_ids": set(),
            "classifications": {"MASK_024": "off"},
        }
        window._display_last_overlay_context = {
            "effective_confirmed_failed_mask_ids": (),
        }
        window._check_snapshot = {}
        window._display_frozen_ng_visual_debug = {}
        window.display_readout_canvas = None
        window._capture_analysis_statuses = lambda: {}
        window._set_segregation_action_enabled = lambda _enabled: None
        window.restore_frozen_analysis_statuses = lambda: None
        redraws = []
        window._redraw_display_readout = lambda: redraws.append(
            set(window._display_readout_context["failed_mask_ids"])
        )

        window.freeze_ng_evidence(
            confirmed_failed_mask_ids=("MASK_024",)
        )

        self.assertEqual(
            {"MASK_024"},
            window._display_readout_context["failed_mask_ids"],
        )
        self.assertEqual(
            {"MASK_024"},
            window._display_frozen_readout_context["failed_mask_ids"],
        )
        self.assertEqual(
            ("MASK_024",),
            window._display_frozen_overlay_context[
                "effective_confirmed_failed_mask_ids"
            ],
        )
        self.assertEqual([{"MASK_024"}], redraws)
        self.assertTrue(
            window._display_frozen_ng_visual_debug["readout_repainted"]
        )

    def test_repaint_pos_freeze_pinta_mask_024_vermelha_no_frame_terminal(self):
        frame = np.zeros((80, 180, 3), dtype=np.uint8)

        class _Window:
            def __init__(self):
                self._display_frozen_overlay_context = {
                    "resolution": (180, 80),
                    "masks": (
                        {
                            "id": "MASK_001",
                            "type": "circle",
                            "cx": 30,
                            "cy": 40,
                            "radius": 12,
                        },
                        {
                            "id": "MASK_024",
                            "type": "circle",
                            "cx": 90,
                            "cy": 40,
                            "radius": 12,
                        },
                        {
                            "id": "MASK_028",
                            "type": "circle",
                            "cx": 150,
                            "cy": 40,
                            "radius": 12,
                        },
                    ),
                    "live_luminous_only": True,
                    "live_visual_sample_ready": True,
                    # Simula o repaint live anterior ao debounce final:
                    # as cores abaixo são deliberadamente antigas/incorretas.
                    "live_visual_mask_ids": ("MASK_024", "MASK_028"),
                    "live_visual_classifications": {
                        "MASK_001": "off",
                        "MASK_024": "on",
                        "MASK_028": "on",
                    },
                    "board_points": (),
                    "check_id": "CHECK_002",
                }
                self._display_frozen_ng_visual_debug = {}
                self.rendered = None

            def update_preview(self, rendered, leds=()):
                self.rendered = rendered.copy()
                return True

        window = _Window()
        owner = DisplayProductionF3Mixin.__new__(
            DisplayProductionF3Mixin
        )
        analysis = {
            "project_name": "DISPLAY",
            "check_id": "CHECK_002",
            "effective_classifications": {
                "MASK_001": "on",
                "MASK_024": "off",
                "MASK_028": "off",
            },
            "effective_failed_mask_ids": ("MASK_024",),
            "effective_confirmed_failed_mask_ids": ("MASK_024",),
            "effective_validating_mask_ids": (),
            "ui_mask_authority": "effective_mask_results_v1",
        }

        rendered = owner._repaint_frozen_ng_evidence_display_f3(
            window,
            frame,
            0,
            analysis,
        )

        self.assertTrue(rendered)
        self.assertIsNotNone(window.rendered)
        on_pixel = window.rendered[40, 30]
        ng_pixel = window.rendered[40, 90]
        off_pixel = window.rendered[40, 150]
        self.assertGreater(int(on_pixel[1]), int(on_pixel[2]))
        self.assertGreater(int(ng_pixel[2]), int(ng_pixel[1]))
        self.assertGreater(int(ng_pixel[2]), int(ng_pixel[0]))
        self.assertGreater(int(off_pixel[1]), int(off_pixel[2]))
        self.assertEqual(
            ("MASK_024",),
            window._display_frozen_ng_visual_debug[
                "confirmed_failed_mask_ids"
            ],
        )
        self.assertTrue(
            window._display_frozen_ng_visual_debug["camera_repainted"]
        )

    def test_visor_live_usa_verde_escuro_para_segmento_apagado(self):
        self.assertEqual(
            "#22C55E",
            DisplayProductionF3Window.DISPLAY_READOUT_ACTIVE,
        )
        self.assertEqual(
            "#14532D",
            DisplayProductionF3Window.DISPLAY_READOUT_OFF,
        )
        self.assertEqual(
            "#166534",
            DisplayProductionF3Window.DISPLAY_READOUT_OFF_OUTLINE,
        )
        self.assertNotEqual(
            DisplayProductionF3Window.DISPLAY_READOUT_OFF,
            DisplayProductionF3Window.DISPLAY_READOUT_INACTIVE,
        )

    def test_overlay_foi_instalado_somente_na_janela_f3(self):
        self.assertTrue(
            getattr(DisplayProductionF3Window, "_odin_display_live_roi_overlay", False)
        )


if __name__ == "__main__":
    unittest.main()
