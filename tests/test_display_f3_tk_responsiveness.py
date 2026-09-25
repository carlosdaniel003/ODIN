from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import src.platform.display_f3_tk_responsiveness as responsiveness


class _Root:
    def __init__(self):
        self.cancelled = []

    def after_cancel(self, token):
        self.cancelled.append(token)


class _App:
    def __init__(self):
        self.root = _Root()
        self.display_f3_ativo = True
        self.display_f3_after_id = None
        self._display_f3_last_idle_slice_ms = 12
        self.scheduled = []

    def _atualizar_preview_display_f3(self):
        self.display_f3_after_id = "old-after"
        return "ok"

    def _agendar_preview_display_f3(self, delay):
        self.scheduled.append(int(delay))
        self.display_f3_after_id = f"after-{delay}"


class DisplayF3TkResponsivenessTests(unittest.TestCase):
    def test_heavy_cycle_reserves_mainloop_time(self):
        app = _App()
        responsiveness.instalar_responsividade_tk_display_f3(app)

        with patch.object(
            responsiveness.time,
            "perf_counter",
            side_effect=[10.0, 10.100],
        ):
            self.assertEqual("ok", app._atualizar_preview_display_f3())

        self.assertEqual(["old-after"], app.root.cancelled)
        self.assertTrue(app.scheduled)
        self.assertGreaterEqual(
            app.scheduled[-1],
            responsiveness.F3_TK_VERY_HEAVY_IDLE_MS,
        )

    def test_light_cycle_keeps_existing_cadence(self):
        app = _App()
        responsiveness.instalar_responsividade_tk_display_f3(app)

        with patch.object(
            responsiveness.time,
            "perf_counter",
            side_effect=[20.0, 20.010],
        ):
            app._atualizar_preview_display_f3()

        self.assertEqual([], app.root.cancelled)
        self.assertEqual([], app.scheduled)
        self.assertEqual("old-after", app.display_f3_after_id)

    def test_installer_is_idempotent(self):
        app = _App()
        responsiveness.instalar_responsividade_tk_display_f3(app)
        first = app._atualizar_preview_display_f3
        responsiveness.instalar_responsividade_tk_display_f3(app)
        self.assertIs(first, app._atualizar_preview_display_f3)

    def test_tracking_and_analysis_are_split_between_tk_callbacks(self):
        source = Path(
            "src/platform/display_f3_object_tracking.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_display_f3_tracking_analysis_pending", source)
        self.assertIn("_display_f3_tracking_pending_raw_frame", source)
        self.assertIn(
            "_display_f3_skip_auto_analysis_this_preview = bool(use_tracking)",
            source,
        )
        self.assertIn("rearm_pending", source)


if __name__ == "__main__":
    unittest.main()
