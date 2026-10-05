from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace

from src.platform.display_editor_performance import (
    DISPLAY_EDITOR_DRAG_INTERVAL_S,
    DISPLAY_EDITOR_POINTER_INTERVAL_S,
    interaction_redraw_due,
    viewport_render_cache_key,
)
from src.platform.display_check_editor import DisplayCheckMaskEditorWindow
from src.platform.display_mask_editor import DisplayMaskEditorWindow
from src.platform.display_f3_tracking_orientation_ui import (
    F3GeometryEditorInteractionBase,
    reference_editor_background_cache_key,
)


class DisplayF3EditorPerformanceTests(unittest.TestCase):
    def test_pointer_cadence_matches_lightweight_f2_magnifier(self):
        self.assertEqual(0.040, DISPLAY_EDITOR_POINTER_INTERVAL_S)
        self.assertGreaterEqual(DISPLAY_EDITOR_DRAG_INTERVAL_S, 1.0 / 120.0)
        self.assertLessEqual(DISPLAY_EDITOR_DRAG_INTERVAL_S, 1.0 / 45.0)

    def test_continuous_redraw_is_throttled_without_losing_final_state(self):
        self.assertFalse(interaction_redraw_due(10.0, 10.01, 0.04))
        self.assertTrue(interaction_redraw_due(10.0, 10.04, 0.04))
        self.assertTrue(interaction_redraw_due(0.0, 1.0, 0.04))

    def test_viewport_cache_key_changes_only_when_visible_background_changes(self):
        frame = SimpleNamespace(shape=(1080, 1920, 3))
        viewport = SimpleNamespace(
            origem_visual_x=10,
            origem_visual_y=20,
            fim_visual_x=1010,
            fim_visual_y=620,
            largura_render=1000,
            altura_render=600,
            deslocamento_render_x=0,
            deslocamento_render_y=0,
        )
        key_a = viewport_render_cache_key(viewport, frame)
        key_b = viewport_render_cache_key(viewport, frame)
        self.assertEqual(key_a, key_b)

        viewport_zoomed = SimpleNamespace(**vars(viewport))
        viewport_zoomed.origem_visual_x = 30
        self.assertNotEqual(
            key_a,
            viewport_render_cache_key(viewport_zoomed, frame),
        )

    def test_mask_and_reference_base_editor_received_performance_patch(self):
        self.assertTrue(DisplayMaskEditorWindow._odin_display_editor_performance)

    def test_check_editor_received_incremental_performance_patch(self):
        self.assertTrue(
            DisplayCheckMaskEditorWindow._odin_display_check_editor_performance
        )
        self.assertTrue(hasattr(DisplayCheckMaskEditorWindow, "_odin_update_segment_button"))

    def test_reference_editor_background_cache_changes_only_with_view(self):
        image = SimpleNamespace(shape=(1080, 1920, 3))
        key_a = reference_editor_background_cache_key(
            image,
            1280,
            720,
            0.666667,
            0.0,
            0.0,
        )
        key_b = reference_editor_background_cache_key(
            image,
            1280,
            720,
            0.666667,
            0.0,
            0.0,
        )
        self.assertEqual(key_a, key_b)

        key_zoomed = reference_editor_background_cache_key(
            image,
            1280,
            720,
            0.8,
            -120.0,
            -60.0,
        )
        self.assertNotEqual(key_a, key_zoomed)

    def test_reference_editor_render_keeps_full_frame_processing_out_of_pointer_hot_path(self):
        source = inspect.getsource(F3GeometryEditorInteractionBase.render)
        self.assertIn("_reference_background_photo_for_view", source)
        self.assertIn("_draw_reference_geometry_overlay", source)
        self.assertNotIn("draw_reference_geometry(", source)
        self.assertNotIn("cv2.warpAffine(", source)

        background_source = inspect.getsource(
            F3GeometryEditorInteractionBase._reference_background_photo_for_view
        )
        self.assertIn("reference_editor_background_cache_key", background_source)
        self.assertIn("cv2.warpAffine(", background_source)


if __name__ == "__main__":
    unittest.main()
