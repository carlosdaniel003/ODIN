from __future__ import annotations

from concurrent.futures import Future
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch

import numpy as np

import src.platform.display_f3_object_tracking as tracking


class DisplayF3PipelineLatencyTests(unittest.TestCase):
    def test_semantic_age_includes_queue_wait_and_compute(self):
        class _Analyzer:
            @staticmethod
            def analyze_tracking_snapshot(**kwargs):
                return {
                    "ready": True,
                    "project_name": kwargs["project_name"],
                    "check_id": kwargs["check_id"],
                }

        frame = np.zeros((20, 30, 3), dtype=np.uint8)
        raw_frame = np.full((20, 30, 3), 37, dtype=np.uint8)
        geometry = {
            "locked": True,
            "resolution": (30, 20),
            "masks": [{"id": "MASK_001", "type": "circle", "cx": 9, "cy": 8}],
        }
        submitted_at = time.perf_counter() - 0.05
        payload = tracking._run_live_semantic_job(
            _Analyzer(),
            frame,
            raw_frame,
            geometry,
            {"project_name": "DISPLAY A", "check_id": "CHECK_001"},
            0,
            3,
            ("camera", 100),
            300.0,
            submitted_at,
        )

        self.assertGreaterEqual(payload["queue_age_ms"], 45.0)
        self.assertGreaterEqual(payload["queue_wait_ms"], 0.0)
        self.assertGreaterEqual(payload["semantic_elapsed_ms"], 0.0)
        self.assertGreaterEqual(
            payload["age_ms"],
            300.0 + payload["queue_age_ms"] - 1.0,
        )
        np.testing.assert_array_equal(payload["raw_frame"], raw_frame)
        self.assertEqual(9, payload["tracking_geometry"]["masks"][0]["cx"])
        geometry["masks"][0]["cx"] = 999
        self.assertEqual(
            9,
            payload["tracking_geometry"]["masks"][0]["cx"],
        )

    def test_tracking_worker_reports_stage_timings(self):
        frame = np.zeros((24, 32, 3), dtype=np.uint8)
        matrix = np.asarray(
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            dtype=np.float32,
        )
        result = tracking.F3TrackingResult(
            locked=True,
            frame=frame.copy(),
            reference="test",
            current_to_canonical=matrix,
            source_type="test",
            evidence_current=True,
        )
        app = SimpleNamespace(
            _display_f3_tracking_live_geometry=None,
            _display_f3_tracking_job_generation=7,
        )

        def _set_geometry(owner, raw, tracked):
            owner._display_f3_tracking_live_geometry = {
                "locked": True,
                "resolution": (32, 24),
                "masks": [],
            }

        with (
            patch.object(
                tracking,
                "align_frame_for_f3",
                return_value=(frame.copy(), result),
            ),
            patch.object(
                tracking,
                "_update_tracking_live_geometry",
                side_effect=_set_geometry,
            ),
            patch.object(
                tracking,
                "_analysis_alignment_for_current_check",
                return_value=(frame.copy(), matrix),
            ),
        ):
            payload = tracking._run_live_tracking_heavy_job(
                app,
                frame,
                7,
                ("camera", 50),
                time.perf_counter(),
            )

        stages = payload["stage_elapsed_ms"]
        self.assertEqual(
            {"align", "geometry_projection", "analysis_warp"},
            set(stages),
        )
        self.assertTrue(all(float(value) >= 0.0 for value in stages.values()))

    def test_semantic_in_flight_prefetches_one_latest_tracking(self):
        semantic = Future()
        queued = Future()
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        app = SimpleNamespace(
            _display_f3_semantic_future=semantic,
            _display_f3_tracking_future=None,
            _display_f3_tracking_queued_frame_token=None,
            _display_f3_tracking_prefetch_submissions=0,
            _display_f3_tracking_prefetch_replacements=0,
            _display_auto_frame_token=lambda _frame: ("camera", 10),
        )

        def _submit(owner, raw):
            owner._display_f3_tracking_future = queued
            owner._display_f3_tracking_queued_frame_token = ("camera", 10)
            return queued

        with patch.object(
            tracking,
            "_submit_live_tracking_job",
            side_effect=_submit,
        ) as submit:
            accepted = tracking._queue_latest_tracking_behind_semantic(
                app,
                frame,
                heavy_due=True,
            )

        self.assertTrue(accepted)
        submit.assert_called_once()
        self.assertEqual(1, app._display_f3_tracking_prefetch_submissions)
        self.assertEqual(0, app._display_f3_tracking_prefetch_replacements)

    def test_newer_frame_replaces_only_pending_tracking(self):
        semantic = Future()
        old_tracking = Future()
        new_tracking = Future()
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        app = SimpleNamespace(
            _display_f3_semantic_future=semantic,
            _display_f3_tracking_future=old_tracking,
            _display_f3_tracking_queued_frame_token=("camera", 10),
            _display_f3_tracking_prefetch_submissions=1,
            _display_f3_tracking_prefetch_replacements=0,
            _display_auto_frame_token=lambda _frame: ("camera", 11),
        )

        def _submit(owner, raw):
            owner._display_f3_tracking_future = new_tracking
            owner._display_f3_tracking_queued_frame_token = ("camera", 11)
            return new_tracking

        with patch.object(
            tracking,
            "_submit_live_tracking_job",
            side_effect=_submit,
        ) as submit:
            accepted = tracking._queue_latest_tracking_behind_semantic(
                app,
                frame,
                heavy_due=True,
            )

        self.assertTrue(accepted)
        submit.assert_called_once()
        self.assertEqual(2, app._display_f3_tracking_prefetch_submissions)
        self.assertEqual(1, app._display_f3_tracking_prefetch_replacements)

    def test_same_frame_does_not_duplicate_pending_tracking(self):
        semantic = Future()
        pending_tracking = Future()
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        app = SimpleNamespace(
            _display_f3_semantic_future=semantic,
            _display_f3_tracking_future=pending_tracking,
            _display_f3_tracking_queued_frame_token=("camera", 12),
            _display_f3_tracking_prefetch_submissions=1,
            _display_f3_tracking_prefetch_replacements=0,
            _display_auto_frame_token=lambda _frame: ("camera", 12),
        )

        with patch.object(
            tracking,
            "_submit_live_tracking_job",
        ) as submit:
            accepted = tracking._queue_latest_tracking_behind_semantic(
                app,
                frame,
                heavy_due=True,
            )

        self.assertFalse(accepted)
        submit.assert_not_called()

    def test_running_tracking_is_never_duplicated(self):
        semantic = Future()
        running_tracking = Future()
        running_tracking.set_running_or_notify_cancel()
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        app = SimpleNamespace(
            _display_f3_semantic_future=semantic,
            _display_f3_tracking_future=running_tracking,
            _display_f3_tracking_queued_frame_token=("camera", 12),
            _display_auto_frame_token=lambda _frame: ("camera", 13),
        )

        with patch.object(
            tracking,
            "_submit_live_tracking_job",
        ) as submit:
            accepted = tracking._queue_latest_tracking_behind_semantic(
                app,
                frame,
                heavy_due=True,
            )

        self.assertFalse(accepted)
        submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
