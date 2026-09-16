from __future__ import annotations

import unittest

import numpy as np

from src.models.led_selection import LedSelection
from src.platform.f2_board_presence_mask_preview import (
    F2_BOARD_MASK_PREVIEW_TITLES,
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
        # O contorno deve estar na ROI configurada, não deslocado para outra área.
        self.assertGreater(int(np.max(annotated[95:145, 135:185])), 0)
        self.assertEqual(0, int(np.max(annotated[0:40, 0:40])))

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


if __name__ == "__main__":
    unittest.main()
