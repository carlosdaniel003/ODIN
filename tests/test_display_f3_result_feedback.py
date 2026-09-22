from __future__ import annotations

import unittest

from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin
from src.platform.display_production_f3_window import DisplayProductionF3Window
from src.platform.display_result_feedback import (
    DISPLAY_F3_RESULT_HOLD_MS,
    DISPLAY_F3_VISUAL_THEMES,
    obter_feedback_espera_display_f3,
    obter_tema_visual_display_f3,
)


class DisplayF3ResultFeedbackTests(unittest.TestCase):
    def test_result_screen_is_held_for_two_seconds(self):
        self.assertEqual(2000, DISPLAY_F3_RESULT_HOLD_MS)
        self.assertEqual(
            2000,
            DisplayAutomaticCheckF3Mixin.DISPLAY_F3_RESULT_HOLD_MS,
        )

    def test_ok_waiting_feedback_matches_f2_dark_green(self):
        feedback = obter_feedback_espera_display_f3(
            {
                "current_index": 0,
                "completed_ids": (),
                "last_result": "OK",
            }
        )
        self.assertEqual(
            ("OK", "Última placa: OK • aguardando H1 da próxima placa"),
            feedback,
        )
        self.assertEqual("#14532D", DisplayProductionF3Window.COLOR_WAITING_AFTER_OK)
        self.assertEqual(
            "#14532D",
            obter_tema_visual_display_f3("ok_waiting")["panel_bg"],
        )

    def test_ng_waiting_feedback_matches_f2_dark_red(self):
        feedback = obter_feedback_espera_display_f3(
            {
                "current_index": 0,
                "completed_ids": (),
                "last_result": "NG",
            }
        )
        self.assertEqual(
            ("NG", "Última placa: NG • aguardando H1 da próxima placa"),
            feedback,
        )
        self.assertEqual("#7F1D1D", DisplayProductionF3Window.COLOR_WAITING_AFTER_NG)
        self.assertEqual(
            "#7F1D1D",
            obter_tema_visual_display_f3("ng_waiting")["panel_bg"],
        )

    def test_previous_result_feedback_stops_after_h1_is_completed(self):
        feedback = obter_feedback_espera_display_f3(
            {
                "current_index": 1,
                "completed_ids": ("CHECK_H1",),
                "last_result": "OK",
            }
        )
        self.assertIsNone(feedback)

    def test_without_previous_result_waiting_state_stays_neutral(self):
        self.assertIsNone(
            obter_feedback_espera_display_f3(
                {
                    "current_index": 0,
                    "completed_ids": (),
                    "last_result": None,
                }
            )
        )

    def test_visual_themes_cover_surrounding_camera_and_secondary_panels(self):
        required = {
            "window_bg",
            "panel_bg",
            "panel_border",
            "surface_bg",
            "surface_border",
            "preview_bg",
            "preview_border",
            "camera_surround_bg",
            "footer_bg",
            "action_bg",
            "pending_bg",
            "current_bg",
            "completed_bg",
        }
        for name in ("neutral", "ok_result", "ok_waiting", "ng_result", "ng_waiting"):
            self.assertTrue(required.issubset(DISPLAY_F3_VISUAL_THEMES[name]))

    def test_strong_result_themes_keep_original_f2_result_colors(self):
        self.assertEqual(
            DisplayProductionF3Window.COLOR_OK,
            obter_tema_visual_display_f3("ok_result")["panel_bg"],
        )
        self.assertEqual(
            DisplayProductionF3Window.COLOR_NG,
            obter_tema_visual_display_f3("ng_result")["panel_bg"],
        )

    def test_camera_surround_reacts_without_using_same_color_as_image_canvas_neutral(self):
        neutral = obter_tema_visual_display_f3("neutral")
        ok = obter_tema_visual_display_f3("ok_waiting")
        ng = obter_tema_visual_display_f3("ng_waiting")
        self.assertEqual("#020617", neutral["camera_surround_bg"])
        self.assertNotEqual(neutral["camera_surround_bg"], ok["camera_surround_bg"])
        self.assertNotEqual(neutral["camera_surround_bg"], ng["camera_surround_bg"])
        self.assertNotEqual(ok["camera_surround_bg"], ng["camera_surround_bg"])

    def test_tema_ng_preserva_status_e_cards_do_frame_congelado(self):
        import inspect
        from src.platform import display_result_feedback as feedback_module

        source = inspect.getsource(feedback_module.aplicar_tema_visual_display_f3)
        self.assertIn("_display_ng_evidence_frozen", source)
        self.assertIn("_display_frozen_check_snapshot", source)
        self.assertIn("restore_frozen_analysis_statuses", source)

    def test_f3_window_received_feedback_extension(self):
        self.assertTrue(DisplayProductionF3Window._odin_display_result_feedback)
        self.assertTrue(DisplayProductionF3Window._odin_display_full_result_theme)


if __name__ == "__main__":
    unittest.main()
