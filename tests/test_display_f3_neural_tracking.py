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
        self.assertIsNotNone(candidate.get("homography"))
        self.assertTrue(runtime._last_neural_pose_debug["projective_pose_ready"])

    def test_neural_snap_recovers_pose_when_strict_quad_fit_returns_zero(self):
        canonical = np.asarray(
            [
                [0.0, 0.0],
                [600.0, 0.0],
                [600.0, 200.0],
                [0.0, 200.0],
            ],
            dtype=np.float32,
        )
        # Trapézio plausível de câmera: o fit estrutural estrito rejeita,
        # mas a CNN ainda pode selecionar a orientação correta.
        current = np.asarray(
            [
                [100.0, 100.0],
                [700.0, 70.0],
                [620.0, 350.0],
                [150.0, 290.0],
            ],
            dtype=np.float32,
        )

        strict = tracking._filter_board_matrix_candidates(
            current.tolist(),
            canonical.tolist(),
        )
        relaxed, mode = tracking._neural_filter_board_matrix_candidates(
            current.tolist(),
            canonical.tolist(),
        )

        self.assertEqual([], strict)
        self.assertGreater(len(relaxed), 0)
        self.assertEqual("relaxed_similarity_lmeds", mode)

    def test_neural_runtime_uses_relaxed_quad_candidates_without_semantic_authority(self):
        repository = SimpleNamespace()
        runtime = tracking.F3DisplayObjectTracker(repository)
        runtime.project = "CM_500_L"
        runtime.width = 800
        runtime.height = 480
        runtime.ready = True
        runtime.canonical_board = [
            [0.0, 0.0],
            [600.0, 0.0],
            [600.0, 200.0],
            [0.0, 200.0],
        ]
        current = np.asarray(
            [
                [100.0, 100.0],
                [700.0, 70.0],
                [620.0, 350.0],
                [150.0, 290.0],
            ],
            dtype=np.float32,
        )

        runtime.neural_pose_detector = SimpleNamespace(
            predict=lambda *args, **kwargs: {
                "ready": True,
                "reason": "neural_tracking_pose_prior_ready",
                "current_anchors": current.copy(),
                "anchor_fit_mean_px": 4.0,
                "anchor_fit_max_px": 8.0,
                "inference_ms": 2.0,
                "validation": {
                    "runtime_max_snap_error_px": 180.0,
                },
            }
        )

        with patch.object(
            tracking,
            "_detect_dark_filter_candidates",
            return_value=[
                {
                    "points": current.tolist(),
                    "score": 3.2,
                    "source": "dark_filter_detector",
                }
            ],
        ):
            candidate = runtime._neural_filter_pose_candidate(
                np.zeros((480, 800, 3), dtype=np.uint8)
            )

        self.assertIsNotNone(candidate)
        debug = runtime._last_neural_pose_debug
        self.assertTrue(debug["available"])
        self.assertEqual(
            "relaxed_similarity_lmeds",
            debug["attempts"][0]["candidate_mode"],
        )
        self.assertGreater(
            debug["attempts"][0]["pose_candidates"],
            0,
        )

    def test_base_core_emission_does_not_prove_alignment_with_large_anchor_residual(self):
        details = [
            {
                "mask_id": "MASK_001",
                "center": [100.0, 100.0],
                "predicted_center": [99.0, 100.0],
            },
            {
                "mask_id": "MASK_002",
                "center": [200.0, 100.0],
                "predicted_center": [198.0, 100.0],
            },
            {
                "mask_id": "MASK_003",
                "center": [300.0, 100.0],
                "predicted_center": [284.0, 100.0],
            },
        ]

        residual = tracking._base_core_alignment_residual(
            details,
            ["MASK_001", "MASK_002", "MASK_003"],
        )

        self.assertTrue(residual["available"])
        self.assertFalse(residual["precise"])
        self.assertGreater(
            residual["max_error_px"],
            tracking.F3_TRACKING_LUMINOUS_FINE_MAX_MEDIAN_ERROR_PX,
        )

    def test_base_core_can_preserve_pose_only_when_all_anchor_centers_are_precise(self):
        details = [
            {
                "mask_id": "MASK_001",
                "center": [100.0, 100.0],
                "predicted_center": [99.0, 100.0],
            },
            {
                "mask_id": "MASK_002",
                "center": [200.0, 100.0],
                "predicted_center": [198.0, 100.0],
            },
            {
                "mask_id": "MASK_003",
                "center": [300.0, 100.0],
                "predicted_center": [297.0, 100.0],
            },
        ]

        residual = tracking._base_core_alignment_residual(
            details,
            ["MASK_001", "MASK_002", "MASK_003"],
        )

        self.assertTrue(residual["available"])
        self.assertTrue(residual["precise"])
        self.assertLessEqual(
            residual["max_error_px"],
            tracking.F3_TRACKING_LUMINOUS_FINE_MAX_MEDIAN_ERROR_PX,
        )

    def test_projective_filter_pose_maps_trapezoid_to_canonical_quad(self):
        canonical = np.asarray(
            [
                [0.0, 0.0],
                [600.0, 0.0],
                [600.0, 200.0],
                [0.0, 200.0],
            ],
            dtype=np.float32,
        )
        current = np.asarray(
            [
                [100.0, 100.0],
                [700.0, 70.0],
                [620.0, 350.0],
                [150.0, 290.0],
            ],
            dtype=np.float32,
        )
        hint, _inliers = cv2.estimateAffinePartial2D(
            current.reshape(-1, 1, 2),
            canonical.reshape(-1, 1, 2),
            method=cv2.LMEDS,
        )

        pose = tracking._projective_filter_pose_from_affine_hint(
            current.tolist(),
            canonical.tolist(),
            hint,
        )

        self.assertIsNotNone(pose)
        homography = np.asarray(
            pose["homography"],
            dtype=np.float32,
        ).reshape(3, 3)
        projected = cv2.perspectiveTransform(
            current.reshape(-1, 1, 2),
            homography,
        ).reshape(-1, 2)
        self.assertTrue(np.allclose(projected, canonical, atol=1e-3))
        self.assertLess(pose["max_reprojection_px"], 0.01)

    def test_quad_from_points_preserves_real_trapezoid_corners(self):
        trapezoid = [
            [100.0, 100.0],
            [700.0, 70.0],
            [620.0, 350.0],
            [150.0, 290.0],
        ]

        quad = tracking._quad_from_points(trapezoid)

        self.assertEqual(4, len(quad))
        expected = neural_tracking.canonical_pose_anchors(trapezoid)
        self.assertIsNotNone(expected)
        self.assertTrue(
            np.allclose(
                np.asarray(quad, dtype=np.float32),
                expected,
                atol=1e-3,
            )
        )

        min_rect = cv2.boxPoints(
            cv2.minAreaRect(
                np.asarray(trapezoid, dtype=np.float32).reshape(-1, 1, 2)
            )
        )
        min_rect = neural_tracking.canonical_pose_anchors(min_rect.tolist())
        self.assertGreater(
            float(
                np.max(
                    np.linalg.norm(
                        np.asarray(quad, dtype=np.float32) - min_rect,
                        axis=1,
                    )
                )
            ),
            20.0,
        )

    def test_dark_filter_detector_extracts_physical_perspective_quad(self):
        frame = np.full((480, 800, 3), 245, dtype=np.uint8)
        physical_quad = np.asarray(
            [
                [110, 105],
                [690, 72],
                [625, 345],
                [155, 305],
            ],
            dtype=np.int32,
        )
        cv2.fillConvexPoly(frame, physical_quad, (18, 18, 18))
        canonical_board = [
            [100.0, 100.0],
            [700.0, 100.0],
            [700.0, 300.0],
            [100.0, 300.0],
        ]

        candidates = tracking._detect_dark_filter_candidates(
            frame,
            canonical_board,
            (800, 480),
        )

        self.assertGreater(len(candidates), 0)
        best = candidates[0]
        self.assertEqual("contour_quad", best["corner_source"])
        expected = neural_tracking.canonical_pose_anchors(
            physical_quad.astype(np.float32).tolist()
        )
        got = np.asarray(best["points"], dtype=np.float32)
        self.assertTrue(np.allclose(got, expected, atol=5.0), (got, expected))

    def test_min_area_rect_fallback_cannot_publish_projective_pose(self):
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
                "inference_ms": 2.0,
                "validation": {"runtime_max_snap_error_px": 90.0},
            }
        )

        with patch.object(
            tracking,
            "_detect_dark_filter_candidates",
            return_value=[
                {
                    "points": current.tolist(),
                    "score": 3.0,
                    "source": "dark_filter_detector",
                    "corner_source": "min_area_rect_fallback",
                }
            ],
        ):
            candidate = runtime._neural_filter_pose_candidate(
                np.zeros((480, 640, 3), dtype=np.uint8)
            )

        self.assertIsNotNone(candidate)
        self.assertIsNone(candidate.get("homography"))
        self.assertEqual(
            "min_area_rect_fallback",
            candidate["filter_corner_source"],
        )
        debug = runtime._last_neural_pose_debug
        self.assertFalse(debug["projective_pose_ready"])
        self.assertEqual(
            "min_area_rect_fallback",
            debug["filter_corner_source"],
        )

    def test_neural_projective_debug_exposes_physical_corners_and_cnn_error(self):
        repository = SimpleNamespace()
        runtime = tracking.F3DisplayObjectTracker(repository)
        runtime.project = "CM_500_L"
        runtime.width = 800
        runtime.height = 480
        runtime.ready = True
        runtime.canonical_board = [
            [100.0, 100.0],
            [700.0, 100.0],
            [700.0, 300.0],
            [100.0, 300.0],
        ]
        canonical = neural_tracking.canonical_pose_anchors(
            runtime.canonical_board
        )
        physical = np.asarray(
            [
                [115.0, 112.0],
                [688.0, 82.0],
                [630.0, 340.0],
                [158.0, 302.0],
            ],
            dtype=np.float32,
        )
        predicted = physical + np.asarray([8.0, -4.0], dtype=np.float32)
        predicted = neural_tracking.canonical_pose_anchors(predicted.tolist())
        runtime.neural_pose_detector = SimpleNamespace(
            predict=lambda *args, **kwargs: {
                "ready": True,
                "reason": "neural_tracking_pose_prior_ready",
                "current_anchors": predicted,
                "anchor_fit_mean_px": 3.0,
                "anchor_fit_max_px": 6.0,
                "inference_ms": 2.0,
                "validation": {"runtime_max_snap_error_px": 180.0},
            }
        )

        with patch.object(
            tracking,
            "_detect_dark_filter_candidates",
            return_value=[
                {
                    "points": physical.tolist(),
                    "score": 3.2,
                    "source": "dark_filter_detector",
                    "corner_source": "contour_quad",
                }
            ],
        ):
            candidate = runtime._neural_filter_pose_candidate(
                np.zeros((480, 800, 3), dtype=np.uint8)
            )

        self.assertIsNotNone(candidate)
        debug = runtime._last_neural_pose_debug
        self.assertTrue(debug["projective_pose_ready"])
        self.assertEqual("contour_quad", debug["filter_corner_source"])
        self.assertEqual(4, len(debug["filter_points"]))
        self.assertEqual(4, len(debug["neural_anchor_points"]))
        self.assertEqual(4, len(debug["filter_corner_errors_to_neural_px"]))
        self.assertIsNotNone(debug["filter_corner_error_mean_px"])
        self.assertIsNotNone(debug["filter_corner_error_max_px"])
    def test_projective_pose_rejects_geometry_that_only_affine_snap_accepts(self):
        repository = SimpleNamespace()
        runtime = tracking.F3DisplayObjectTracker(repository)
        runtime.project = "CM_500_L"
        runtime.width = 800
        runtime.height = 700
        runtime.ready = True
        runtime.canonical_board = [
            [0.0, 0.0],
            [600.0, 0.0],
            [600.0, 200.0],
            [0.0, 200.0],
        ]
        neural_anchors = neural_tracking.canonical_pose_anchors(
            runtime.canonical_board
        )
        physical_quad = np.asarray(
            [
                [0.0, 0.0],
                [600.0, 0.0],
                [600.0, 600.0],
                [0.0, 600.0],
            ],
            dtype=np.float32,
        )
        runtime.neural_pose_detector = SimpleNamespace(
            predict=lambda *args, **kwargs: {
                "ready": True,
                "reason": "neural_tracking_pose_prior_ready",
                "current_anchors": neural_anchors.copy(),
                "anchor_fit_mean_px": 2.0,
                "anchor_fit_max_px": 4.0,
                "inference_ms": 2.0,
                "validation": {"runtime_max_snap_error_px": 180.0},
            }
        )
        identity = np.asarray(
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            dtype=np.float32,
        )

        with (
            patch.object(
                tracking,
                "_detect_dark_filter_candidates",
                return_value=[
                    {
                        "points": physical_quad.tolist(),
                        "score": 3.2,
                        "source": "dark_filter_detector",
                        "corner_source": "contour_quad",
                    }
                ],
            ),
            patch.object(
                tracking,
                "_neural_filter_board_matrix_candidates",
                return_value=([identity], "forced_affine"),
            ),
        ):
            candidate = runtime._neural_filter_pose_candidate(
                np.zeros((700, 800, 3), dtype=np.uint8)
            )

        self.assertIsNone(candidate)
        debug = runtime._last_neural_pose_debug
        self.assertFalse(debug["available"])
        self.assertEqual(
            "neural_pose_projective_snap_rejected",
            debug["reason"],
        )
        self.assertEqual(
            "projective_corners",
            debug["selected_snap_source"],
        )
        self.assertAlmostEqual(
            0.0,
            debug["selected_affine_snap_error_px"],
            places=3,
        )
        self.assertGreater(
            debug["selected_snap_error_px"],
            debug["max_snap_error_px"],
        )
        self.assertGreater(
            debug["attempts"][0]["projective_snap_error_px"],
            debug["max_snap_error_px"],
        )
        self.assertEqual(
            "projective_corners",
            debug["attempts"][0]["snap_source"],
        )

    def test_projective_luminous_residual_preserves_homography(self):
        canonical_board = [
            [0.0, 0.0],
            [600.0, 0.0],
            [600.0, 200.0],
            [0.0, 200.0],
        ]
        current_board = np.asarray(
            [
                [100.0, 100.0],
                [700.0, 70.0],
                [620.0, 350.0],
                [150.0, 290.0],
            ],
            dtype=np.float32,
        )
        canonical = np.asarray(canonical_board, dtype=np.float32)
        true_h = cv2.getPerspectiveTransform(current_board, canonical)
        offset = np.asarray(
            [
                [1.0, 0.0, 8.0],
                [0.0, 1.0, 5.0],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float32,
        )
        coarse_h = offset @ true_h

        expected_rows = [
            {"mask_id": "MASK_001", "center": [120.0, 70.0]},
            {"mask_id": "MASK_002", "center": [300.0, 120.0]},
            {"mask_id": "MASK_003", "center": [500.0, 160.0]},
        ]
        inverse_true = np.linalg.inv(true_h).astype(np.float32)
        current_centers = cv2.perspectiveTransform(
            np.asarray(
                [row["center"] for row in expected_rows],
                dtype=np.float32,
            ).reshape(-1, 1, 2),
            inverse_true,
        ).reshape(-1, 2)
        details = [
            {
                "mask_id": row["mask_id"],
                "center": current_centers[index].tolist(),
                "projected_mask_support": True,
            }
            for index, row in enumerate(expected_rows)
        ]
        diagnostics = {}

        fit = tracking._fit_id_anchored_luminous_projective_pose(
            canonical_board,
            expected_rows,
            details,
            coarse_h,
            diagnostics=diagnostics,
        )

        self.assertIsNotNone(fit, diagnostics)
        self.assertIsNotNone(fit.get("projective_matrix"))
        self.assertLess(fit["median_error_px"], 0.5)
        self.assertGreater(fit["fine_alignment_gain_px"], 5.0)
        self.assertIn(
            fit["fine_fit_mode"],
            {"projective_similarity", "projective_translation"},
        )

    def test_live_geometry_projects_masks_with_projective_filter_pose(self):
        canonical_board = [
            [0.0, 0.0],
            [600.0, 0.0],
            [600.0, 200.0],
            [0.0, 200.0],
        ]
        current_board = np.asarray(
            [
                [100.0, 100.0],
                [700.0, 70.0],
                [620.0, 350.0],
                [150.0, 290.0],
            ],
            dtype=np.float32,
        )
        canonical = np.asarray(canonical_board, dtype=np.float32)
        homography = cv2.getPerspectiveTransform(current_board, canonical)
        affine = tracking._affine_approximation_from_projective(
            homography,
            canonical_board,
        )
        masks = [
            {
                "id": f"MASK_{index:03d}",
                "type": "polygon",
                "points": [
                    [100.0 + index * 40.0, 60.0],
                    [120.0 + index * 40.0, 60.0],
                    [120.0 + index * 40.0, 90.0],
                    [100.0 + index * 40.0, 90.0],
                ],
            }
            for index in range(1, 4)
        ]
        project = {
            "name": "CM_500_L",
            "masks": masks,
            "checks": [],
        }
        repository = SimpleNamespace(
            obter_projeto_ativo=lambda: "CM_500_L",
            carregar_projeto=lambda _name: project,
        )
        runtime = SimpleNamespace(
            store=SimpleNamespace(),
            _force_absolute_reacquire=False,
        )
        app = SimpleNamespace(display_project_repository=repository)
        result = tracking.F3TrackingResult(
            True,
            np.zeros((480, 800, 3), dtype=np.uint8),
            reference="neural_pose:CM_500_L",
            current_to_canonical=affine,
            current_to_canonical_homography=homography,
            source_type="neural_filter_pose",
            evidence_current=True,
        )
        current = {
            "id": "CHECK_001",
            "mask_states": {
                "MASK_001": "on",
                "MASK_002": "on",
                "MASK_003": "on",
            },
        }

        with (
            patch.object(tracking, "get_tracking_runtime", return_value=runtime),
            patch.object(
                tracking,
                "canonical_board_points",
                return_value=canonical_board,
            ),
            patch.object(tracking, "_current_check", return_value=current),
        ):
            tracking._update_tracking_live_geometry(
                app,
                np.zeros((480, 800, 3), dtype=np.uint8),
                result,
            )

        geometry = app._display_f3_tracking_live_geometry
        self.assertEqual("homography_3x3", geometry["geometry_transform_type"])
        self.assertEqual("canonical_projective", geometry["geometry_space"])
        self.assertFalse(geometry["spatial_alignment_ready"])
        self.assertTrue(geometry["absolute_reacquire_required"])
        self.assertTrue(runtime._force_absolute_reacquire)

        inverse = np.linalg.inv(homography).astype(np.float32)
        expected = tracking.transform_points(
            masks[0]["points"],
            inverse,
        )
        actual = geometry["masks"][0]["points"]
        self.assertTrue(
            np.allclose(
                np.asarray(actual, dtype=np.float32),
                np.asarray(expected, dtype=np.float32),
                atol=1e-3,
            )
        )

    def test_alignment_pending_forces_absolute_neural_reacquisition(self):
        runtime = tracking.F3DisplayObjectTracker(SimpleNamespace())
        runtime.ready = True
        runtime.reason = "ready"
        runtime.width = 640
        runtime.height = 480
        runtime.canonical_board = [
            [0.0, 0.0],
            [639.0, 0.0],
            [639.0, 300.0],
            [0.0, 300.0],
        ]
        runtime.canonical_masks = []
        runtime.last_matrix = np.asarray(
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            dtype=np.float32,
        )
        runtime.last_homography = np.eye(3, dtype=np.float32)
        runtime.last_result = tracking.F3TrackingResult(
            True,
            np.zeros((480, 640, 3), dtype=np.uint8),
            reference="neural_pose:CM_500_L",
            current_to_canonical=runtime.last_matrix.copy(),
            current_to_canonical_homography=runtime.last_homography.copy(),
            source_type="neural_filter_pose",
            evidence_current=True,
        )
        runtime.last_compute_s = tracking.time.monotonic()
        runtime.last_verified_rotation_deg = 0.0
        runtime._last_reference = "neural_pose:CM_500_L"
        runtime._force_absolute_reacquire = True

        candidate = {
            "reference": "neural_pose:CM_500_L",
            "matrix": runtime.last_matrix.copy(),
            "homography": runtime.last_homography.copy(),
            "matches": 4,
            "inliers": 4,
            "ratio": 0.9,
            "rotation_deg": 0.0,
            "scale": 1.0,
            "score": 49.0,
            "source_type": "neural_filter_pose",
            "fallback": "neural_filter_pose",
        }
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with (
            patch.object(
                runtime,
                "_temporal_candidate",
                side_effect=AssertionError(
                    "LK não deve prender pose enquanto alinhamento está pendente"
                ),
            ),
            patch.object(
                runtime,
                "_neural_filter_pose_candidate",
                return_value=candidate,
            ) as neural,
            patch.object(
                runtime,
                "_available_reference_keys",
                return_value=[],
            ),
        ):
            result = runtime.align(frame, frame_id=101)

        neural.assert_called_once()
        self.assertTrue(result.locked)
        self.assertEqual("locked_neural_filter_pose", result.reason)
        self.assertIsNotNone(result.current_to_canonical_homography)

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
