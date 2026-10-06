from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import src.platform.display_f3_neural_tracking as neural_tracking
import src.platform.display_f3_object_tracking as tracking
from scripts.treinar_f3_tracking_neural import (
    _orientation_selection_metrics,
)


class DisplayF3NeuralTrackingTests(unittest.TestCase):
    def test_model_path_stays_local_to_f3_tracking(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = SimpleNamespace(
                config_file=Path(directory) / "data" / "config" / "odin_display_projects.json"
            )
            path = neural_tracking.f3_neural_tracking_model_path(
                repository,
                "CM 500 L",
            )
            self.assertEqual("cm_500_l_pose.onnx", path.name)
            self.assertEqual("f3_tracking", path.parent.name)

    def test_canonical_pose_anchors_are_stable_quad(self):
        board = [
            [100, 80],
            [500, 90],
            [510, 300],
            [90, 290],
        ]
        first = neural_tracking.canonical_pose_anchors(board)
        second = neural_tracking.canonical_pose_anchors(board)
        self.assertEqual((4, 2), first.shape)
        self.assertTrue(np.allclose(first, second))
        self.assertEqual(
            neural_tracking.canonical_pose_anchor_digest(board),
            neural_tracking.canonical_pose_anchor_digest(board),
        )

    def test_missing_model_fails_closed_without_touching_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = SimpleNamespace(
                config_file=Path(directory) / "odin_display_projects.json"
            )
            detector = neural_tracking.F3NeuralPoseDetector(repository)
            result = detector.predict(
                np.zeros((1080, 1920, 3), dtype=np.uint8),
                project_name="CM_500_L",
                canonical_board=[
                    [100, 100],
                    [1800, 100],
                    [1800, 500],
                    [100, 500],
                ],
            )
            self.assertFalse(result["ready"])
            self.assertEqual(
                "neural_tracking_model_missing",
                result["reason"],
            )

        source = inspect.getsource(neural_tracking)
        self.assertNotIn("F3HybridCheckAnalyzer", source)
        self.assertNotIn("DISPLAY_CHECK_STATE_ON", source)
        self.assertNotIn("DISPLAY_CHECK_STATE_OFF", source)

    def test_neural_prior_only_selects_structural_filter_pose(self):
        repository = SimpleNamespace()
        runtime = tracking.F3DisplayObjectTracker(repository)
        runtime.project = "CM_500_L"
        runtime.width = 640
        runtime.height = 480
        runtime.ready = True
        runtime.canonical_board = [
            [100.0, 100.0],
            [540.0, 100.0],
            [540.0, 300.0],
            [100.0, 300.0],
        ]

        canonical = neural_tracking.canonical_pose_anchors(
            runtime.canonical_board
        )
        current = canonical + np.asarray([20.0, 12.0], dtype=np.float32)

        runtime.neural_pose_detector = SimpleNamespace(
            predict=lambda *args, **kwargs: {
                "ready": True,
                "reason": "neural_tracking_pose_prior_ready",
                "current_anchors": current,
                "anchor_fit_mean_px": 1.0,
                "anchor_fit_max_px": 2.0,
                "inference_ms": 3.2,
                "validation": {
                    "runtime_max_snap_error_px": 90.0,
                },
            }
        )

        with patch.object(
            tracking,
            "_detect_dark_filter_candidates",
            return_value=[
                {
                    "points": current.tolist(),
                    "score": 3.5,
                    "source": "dark_filter_detector",
                }
            ],
        ):
            candidate = runtime._neural_filter_pose_candidate(
                np.zeros((480, 640, 3), dtype=np.uint8)
            )

        self.assertIsNotNone(candidate)
        self.assertEqual(
            "neural_filter_pose",
            candidate["source_type"],
        )
        self.assertEqual(
            "neural_filter_pose",
            candidate["fallback"],
        )
        matrix = np.asarray(candidate["matrix"], dtype=np.float32)
        projected = cv2.transform(
            current.reshape(-1, 1, 2),
            matrix,
        ).reshape(-1, 2)
        self.assertTrue(np.allclose(projected, canonical, atol=2.0))

    def test_align_attempts_neural_before_orb_when_pose_is_absent(self):
        source = inspect.getsource(
            tracking.F3DisplayObjectTracker.align
        )
        neural_pos = source.index("_neural_filter_pose_candidate")
        orb_pos = source.index("cv2.ORB_create")
        akaze_pos = source.index("cv2.AKAZE_create")
        self.assertLess(neural_pos, orb_pos)
        self.assertLess(neural_pos, akaze_pos)
        self.assertIn("locked_neural_filter_pose", source)
        self.assertIn("_temporal_candidate", source)

    def test_training_gate_accepts_correct_filter_correspondence(self):
        canonical = np.asarray(
            [
                [100.0, 90.0],
                [540.0, 90.0],
                [540.0, 300.0],
                [100.0, 300.0],
            ],
            dtype=np.float32,
        )
        current = canonical + np.asarray(
            [24.0, 17.0],
            dtype=np.float32,
        )
        predictions = (
            current
            / np.asarray([640.0, 480.0], dtype=np.float32)
        ).reshape(1, 8)
        targets = predictions.copy()

        metrics = _orientation_selection_metrics(
            predictions,
            targets,
            canonical_anchors=canonical,
            master_width=640,
            master_height=480,
        )

        self.assertEqual(1, metrics["valid_sample_count"])
        self.assertEqual(1, metrics["correct_count"])
        self.assertEqual(0, metrics["wrong_count"])
        self.assertEqual(1.0, metrics["accuracy"])
        self.assertGreater(
            metrics["min_selection_margin_px"],
            50.0,
        )

    def test_training_gate_rejects_180_degree_correspondence(self):
        canonical = np.asarray(
            [
                [100.0, 90.0],
                [540.0, 90.0],
                [540.0, 300.0],
                [100.0, 300.0],
            ],
            dtype=np.float32,
        )
        current = canonical + np.asarray(
            [24.0, 17.0],
            dtype=np.float32,
        )
        target = (
            current
            / np.asarray([640.0, 480.0], dtype=np.float32)
        ).reshape(1, 8)
        wrong_prediction = (
            np.roll(current, 2, axis=0)
            / np.asarray([640.0, 480.0], dtype=np.float32)
        ).reshape(1, 8)

        metrics = _orientation_selection_metrics(
            wrong_prediction,
            target,
            canonical_anchors=canonical,
            master_width=640,
            master_height=480,
        )

        self.assertEqual(1, metrics["valid_sample_count"])
        self.assertEqual(0, metrics["correct_count"])
        self.assertEqual(1, metrics["wrong_count"])
        self.assertEqual(0.0, metrics["accuracy"])


if __name__ == "__main__":
    unittest.main()
