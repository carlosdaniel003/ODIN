from __future__ import annotations

import unittest

import numpy as np

from src.platform.display_live_roi_overlay import (
    DISPLAY_ROI_OVERLAY_ALPHA,
    renderizar_overlay_rois_display_f3,
)
from src.platform.display_production_f3_window import DisplayProductionF3Window


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

    def test_overlay_foi_instalado_somente_na_janela_f3(self):
        self.assertTrue(
            getattr(DisplayProductionF3Window, "_odin_display_live_roi_overlay", False)
        )


if __name__ == "__main__":
    unittest.main()
