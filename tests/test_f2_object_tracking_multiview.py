from __future__ import annotations

import inspect
import unittest

import cv2
import numpy as np

from src.platform.f2_object_tracking import F2BoardObjectTracker
from src.platform.f2_object_tracking_multiview import (
    F2_MULTIVIEW_ANGLES_DEG,
    _candidato_vista,
    _mapear_keypoints_para_canonico,
    instalar_banco_multivista_rastreamento_f2,
)


class F2ObjectTrackingMultiviewTests(unittest.TestCase):
    def test_banco_cobre_orientacoes_amplas_sem_novas_fotos(self):
        self.assertIn(90.0, F2_MULTIVIEW_ANGLES_DEG)
        self.assertIn(-90.0, F2_MULTIVIEW_ANGLES_DEG)
        self.assertIn(180.0, F2_MULTIVIEW_ANGLES_DEG)
        self.assertIn(30.0, F2_MULTIVIEW_ANGLES_DEG)
        self.assertIn(-30.0, F2_MULTIVIEW_ANGLES_DEG)

    def test_keypoint_da_vista_volta_para_coordenada_canonica(self):
        center = (160.0, 120.0)
        rotation = cv2.getRotationMatrix2D(center, 90.0, 1.0).astype(np.float32)
        canonical = np.asarray([95.0, 72.0, 1.0], dtype=np.float32)
        rotated = rotation @ canonical
        keypoint = cv2.KeyPoint(float(rotated[0]), float(rotated[1]), 9.0)

        mapped = _mapear_keypoints_para_canonico([keypoint], rotation)
        self.assertEqual(1, len(mapped))
        self.assertAlmostEqual(95.0, float(mapped[0].pt[0]), delta=0.01)
        self.assertAlmostEqual(72.0, float(mapped[0].pt[1]), delta=0.01)

    def test_candidato_multiview_recupera_pose_rotacionada(self):
        tracker = F2BoardObjectTracker()
        tracker.width = 320
        tracker.height = 240

        canonical_points = []
        for y in (55.0, 90.0, 130.0, 170.0):
            for x in (70.0, 115.0, 160.0, 205.0, 250.0):
                canonical_points.append((x, y))

        rng = np.random.default_rng(1234)
        descriptors = rng.integers(
            0,
            256,
            size=(len(canonical_points), 32),
            dtype=np.uint8,
        )
        ref_kp = [cv2.KeyPoint(x, y, 12.0) for x, y in canonical_points]
        tracker.references = {"board_off": (ref_kp, descriptors.copy())}

        canonical_to_current = cv2.getRotationMatrix2D(
            (160.0, 120.0),
            72.0,
            1.0,
        ).astype(np.float32)
        canonical_to_current[:, 2] += np.asarray([18.0, -11.0], dtype=np.float32)
        current_points = []
        for x, y in canonical_points:
            point = canonical_to_current @ np.asarray([x, y, 1.0], dtype=np.float32)
            current_points.append((float(point[0]), float(point[1])))
        current_kp = [cv2.KeyPoint(x, y, 12.0) for x, y in current_points]

        view = {
            "angle": 60.0,
            "keypoints": ref_kp,
            "descriptors": descriptors.copy(),
        }
        candidate = _candidato_vista(
            tracker,
            current_kp,
            descriptors.copy(),
            "board_off",
            view,
        )
        self.assertIsNotNone(candidate)
        self.assertGreaterEqual(int(candidate["inliers"]), 18)
        self.assertGreater(float(candidate["ratio"]), 0.90)
        self.assertGreater(abs(float(candidate["rotation_deg"])), 60.0)

    def test_instalador_so_entra_depois_do_pipeline_normal_e_nao_toca_f3(self):
        source = inspect.getsource(instalar_banco_multivista_rastreamento_f2)
        self.assertIn("align_anterior", source)
        self.assertIn("if bool(getattr(result, \"locked\", False))", source)
        self.assertIn("_tentar_multiview", source)
        self.assertNotIn("display_f3", source)


if __name__ == "__main__":
    unittest.main()
