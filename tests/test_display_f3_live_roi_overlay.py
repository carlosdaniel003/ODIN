from __future__ import annotations

import inspect
import unittest

import numpy as np

import src.platform.display_live_roi_overlay as overlay_module
from src.platform.display_live_roi_overlay import (
    DISPLAY_ROI_OVERLAY_ALPHA,
    renderizar_overlay_rois_display_f3,
)
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

    def test_overlay_foi_instalado_somente_na_janela_f3(self):
        self.assertTrue(
            getattr(DisplayProductionF3Window, "_odin_display_live_roi_overlay", False)
        )


if __name__ == "__main__":
    unittest.main()
