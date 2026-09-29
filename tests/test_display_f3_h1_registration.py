import unittest
from unittest.mock import patch

import cv2
import numpy as np

import src.platform.display_f3_h1_registration as h1reg
import src.platform.display_f3_object_tracking as tracking


class DisplayF3H1RegistrationExperimentTests(unittest.TestCase):
    @staticmethod
    def _h1_roi(width=320, height=120):
        image = np.full((height, width, 3), 15, dtype=np.uint8)
        cv2.rectangle(image, (66, 28), (76, 92), (250, 250, 250), -1)
        cv2.rectangle(image, (104, 28), (114, 92), (250, 250, 250), -1)
        cv2.rectangle(image, (70, 55), (110, 65), (250, 250, 250), -1)
        cv2.rectangle(image, (216, 28), (226, 92), (250, 250, 250), -1)
        return image

    @staticmethod
    def _warp_roi(frame, roi, quad):
        height, width = roi.shape[:2]
        source = np.asarray(
            [
                [0.0, 0.0],
                [float(width - 1), 0.0],
                [float(width - 1), float(height - 1)],
                [0.0, float(height - 1)],
            ],
            dtype=np.float32,
        )
        target = np.asarray(quad, dtype=np.float32)
        matrix = cv2.getPerspectiveTransform(source, target)
        warped = cv2.warpPerspective(
            roi,
            matrix,
            (frame.shape[1], frame.shape[0]),
        )
        mask = cv2.warpPerspective(
            np.full((height, width), 255, dtype=np.uint8),
            matrix,
            (frame.shape[1], frame.shape[0]),
        )
        result = frame.copy()
        result[mask > 0] = warped[mask > 0]
        return result

    @classmethod
    def _scene(cls):
        roi = cls._h1_roi()
        reference = np.full((480, 640, 3), 160, dtype=np.uint8)
        current = np.full((480, 640, 3), 160, dtype=np.uint8)

        reference_quad = np.asarray(
            [
                [160.0, 180.0],
                [480.0, 180.0],
                [480.0, 300.0],
                [160.0, 300.0],
            ],
            dtype=np.float32,
        )
        current_quad = np.asarray(
            [
                [118.0, 154.0],
                [503.0, 174.0],
                [486.0, 321.0],
                [103.0, 296.0],
            ],
            dtype=np.float32,
        )
        reference = cls._warp_roi(reference, roi, reference_quad)

        height, width = roi.shape[:2]
        internal = cv2.getRotationMatrix2D(
            (float(width) / 2.0, float(height) / 2.0),
            2.2,
            1.0,
        ).astype(np.float32)
        internal[0, 2] += 18.0
        internal[1, 2] -= 7.0
        moved_roi = cv2.warpAffine(
            roi,
            internal,
            (width, height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(15, 15, 15),
        )
        current = cls._warp_roi(current, moved_roi, current_quad)

        # Máscaras ON desenhadas no frame de referência. Elas ficam fixas depois
        # que o frame atual é normalizado para o espaço retificado da referência.
        masks = [
            {
                "id": "MASK_001",
                "type": "polygon",
                "points": [[226, 208], [238, 208], [238, 272], [226, 272]],
            },
            {
                "id": "MASK_002",
                "type": "polygon",
                "points": [[264, 208], [276, 208], [276, 272], [264, 272]],
            },
            {
                "id": "MASK_003",
                "type": "polygon",
                "points": [[230, 235], [270, 235], [270, 247], [230, 247]],
            },
            {
                "id": "MASK_004",
                "type": "polygon",
                "points": [[376, 208], [388, 208], [388, 272], [376, 272]],
            },
        ]
        return reference, current, reference_quad, current_quad, masks

    def test_homography_plus_whole_h1_registration_recovers_internal_motion(self):
        reference, current, reference_quad, current_quad, masks = self._scene()

        result = h1reg.register_h1_with_filter_homography(
            reference,
            reference_quad,
            current,
            current_quad,
            reference_masks=masks,
            expected_on_mask_ids={mask["id"] for mask in masks},
        )

        self.assertTrue(result["available"], result)
        self.assertTrue(result["quality_ok"], result)
        self.assertGreater(result["ecc_score"], 0.90)
        self.assertLess(abs(abs(result["rotation_deg"]) - 2.2), 1.0)

        before = result["metrics_before"]
        after = result["metrics_after"]
        self.assertTrue(before["available"])
        self.assertTrue(after["available"])
        self.assertGreater(after["dice"], before["dice"] + 0.20)
        self.assertGreater(after["correlation"], before["correlation"] + 0.20)
        self.assertLess(after["mean_error_px"], before["mean_error_px"])
        self.assertLess(after["p95_error_px"], 2.5)

        mask_before = result["mask_overlap_before"]
        mask_after = result["mask_overlap_after"]
        self.assertTrue(mask_after["available"], mask_after)
        self.assertGreater(
            mask_after["emission_inside_fraction"],
            mask_before["emission_inside_fraction"] + 0.15,
        )

    def test_filter_homography_removes_external_perspective_before_h1_fit(self):
        reference, current, reference_quad, current_quad, _masks = self._scene()
        reference_rect = h1reg.rectify_filter_homography(
            reference,
            reference_quad,
        )
        current_rect = h1reg.rectify_filter_homography(
            current,
            current_quad,
            output_size=reference_rect["size"],
        )

        self.assertTrue(reference_rect["available"])
        self.assertTrue(current_rect["available"])
        self.assertEqual(
            reference_rect["image"].shape,
            current_rect["image"].shape,
        )

        registration = h1reg.register_rectified_h1(
            reference_rect["image"],
            current_rect["image"],
        )
        self.assertTrue(registration["available"], registration)
        self.assertGreater(registration["ecc_score"], 0.90)
        self.assertLess(
            registration["metrics_after"]["mean_error_px"],
            1.5,
        )

    def test_object_tracking_experiment_uses_existing_filter_detector_only_as_locator(self):
        reference, current, reference_quad, current_quad, masks = self._scene()
        bad_quad = np.asarray(
            [
                [20.0, 20.0],
                [180.0, 20.0],
                [180.0, 80.0],
                [20.0, 80.0],
            ],
            dtype=np.float32,
        )
        candidates = [
            {
                "points": bad_quad.tolist(),
                "score": 2.0,
                "source": "dark_filter_detector",
            },
            {
                "points": current_quad.tolist(),
                "score": 4.0,
                "source": "dark_filter_detector",
            },
        ]

        with patch.object(
            tracking,
            "_detect_dark_filter_candidates",
            return_value=candidates,
        ):
            result = tracking.experiment_h1_filter_registration(
                reference,
                reference_quad,
                current,
                canonical_resolution=(640, 480),
                reference_masks=masks,
                expected_on_mask_ids={mask["id"] for mask in masks},
            )

        self.assertTrue(result["available"], result)
        self.assertTrue(result["experimental"])
        self.assertFalse(result["production_authority"])
        self.assertEqual(2, result["filter_candidate_count"])
        self.assertGreater(result["ecc_score"], 0.90)
        self.assertGreater(
            result["metrics_after"]["dice"],
            result["metrics_before"]["dice"],
        )

    def test_no_emission_does_not_claim_segment_lock(self):
        reference, _current, reference_quad, current_quad, _masks = self._scene()
        dark_current = np.full((480, 640, 3), 160, dtype=np.uint8)
        dark_roi = np.full((120, 320, 3), 15, dtype=np.uint8)
        dark_current = self._warp_roi(dark_current, dark_roi, current_quad)

        result = h1reg.register_h1_with_filter_homography(
            reference,
            reference_quad,
            dark_current,
            current_quad,
        )

        self.assertFalse(result["available"])
        self.assertIn("dynamic_range_insufficient", result["reason"])


if __name__ == "__main__":
    unittest.main()
