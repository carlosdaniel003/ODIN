from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace

import numpy as np

from src.models.led_selection import LedSelection
from src.platform.f2_board_presence_mask_preview import (
    F2_BOARD_MASK_PREVIEW_TITLES,
    _leds_do_projeto,
    criar_imagem_preview_presenca_com_mascaras_f2,
    sobrepor_mascaras_preview_f2,
)
from src.platform.f2_board_presence_references import (
    F2_BOARD_REF_BOARD_OFF,
    F2_BOARD_REF_BOARD_ON,
    F2_BOARD_REF_EMPTY,
)


class F2BoardPresenceMaskPreviewTests(unittest.TestCase):
    def test_masks_are_shown_only_on_board_on_and_board_off_previews(self):
        self.assertEqual(
            {
                F2_BOARD_REF_BOARD_ON,
                F2_BOARD_REF_BOARD_OFF,
            },
            set(F2_BOARD_MASK_PREVIEW_TITLES),
        )
        self.assertNotIn(F2_BOARD_REF_EMPTY, F2_BOARD_MASK_PREVIEW_TITLES)

    def test_overlay_keeps_original_image_untouched_and_marks_same_coordinates(self):
        image = np.zeros((240, 320, 3), dtype=np.uint8)
        original = image.copy()
        led = LedSelection(
            id="LED_001",
            centro_x=160,
            centro_y=120,
            raio=22,
        )

        annotated = sobrepor_mascaras_preview_f2(image, [led])

        self.assertTrue(np.array_equal(image, original))
        self.assertFalse(np.array_equal(annotated, original))
        self.assertGreater(int(np.max(annotated[95:145, 135:185])), 0)
        self.assertEqual(0, int(np.max(annotated[0:40, 0:40])))

    def test_small_mask_survives_640x480_to_presence_preview_reduction(self):
        image = np.zeros((480, 640, 3), dtype=np.uint8)
        led = LedSelection(
            id="LED_001",
            centro_x=320,
            centro_y=240,
            raio=9,
        )

        preview = criar_imagem_preview_presenca_com_mascaras_f2(image, [led])

        self.assertEqual((104, 139, 3), preview.shape)
        self.assertGreater(int(np.max(preview[45:60, 62:78])), 0)

    def test_segment_mask_geometry_is_supported(self):
        image = np.zeros((240, 320, 3), dtype=np.uint8)
        segment = LedSelection(
            id="LED_002",
            centro_x=160,
            centro_y=120,
            raio=30,
            tipo_roi="segmento",
            largura=70,
            altura=18,
            angulo=25.0,
        )

        annotated = sobrepor_mascaras_preview_f2(image, [segment])
        self.assertGreater(int(np.max(annotated[80:160, 110:210])), 0)

    def test_runtime_fixed_leds_are_preferred_for_active_project_preview(self):
        led = LedSelection(
            id="LED_RUNTIME",
            centro_x=100,
            centro_y=80,
            raio=10,
        )
        app = SimpleNamespace(
            leds_fixos_configurados=[led],
            config_repository=None,
        )
        controller = SimpleNamespace(app=app)

        self.assertEqual([led], _leds_do_projeto(controller, "PROJETO"))

    def test_settings_preview_uses_tk_canvas_vector_overlay(self):
        import src.platform.f2_board_presence_mask_preview as module

        source = inspect.getsource(module)
        self.assertIn("tk.Canvas", source)
        self.assertIn("canvas.create_oval", source)
        self.assertIn("canvas.create_polygon", source)
        self.assertIn("_odin_f2_mask_count", source)
        self.assertIn("0 ROIs do projeto", source)


if __name__ == "__main__":
    unittest.main()
