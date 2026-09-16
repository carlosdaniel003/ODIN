from __future__ import annotations

import inspect
import time
import unittest

import cv2
import numpy as np

from src.platform.f2_object_tracking import F2BoardObjectTracker, F2TrackingResult
from src.platform.f2_object_tracking_runtime_fix import (
    _candidate_robusto,
    _pose_matriz_rastreamento,
    _preparar_referencia_ecc,
    _tentar_ecc,
    _tentar_grace_lock,
    instalar_correcao_runtime_rastreamento_f2,
)


class F2ObjectTrackingRuntimeFixTests(unittest.TestCase):
    def _reference(self):
        rng = np.random.default_rng(17)
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        frame[:] = (24, 29, 34)
        cv2.rectangle(frame, (48, 38), (272, 202), (62, 91, 72), -1)
        for _ in range(120):
            x = int(rng.integers(62, 258))
            y = int(rng.integers(52, 188))
            radius = int(rng.integers(1, 4))
            color = tuple(int(v) for v in rng.integers(70, 235, size=3))
            cv2.circle(frame, (x, y), radius, color, -1)
        cv2.putText(
            frame,
            "PCB",
            (105, 132),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (245, 245, 245),
            2,
            cv2.LINE_AA,
        )
        return frame

    def test_ecc_recupera_movimento_quando_ha_referencia_visual(self):
        reference = self._reference()
        tracker = F2BoardObjectTracker()
        tracker.width = 320
        tracker.height = 240

        mask = np.zeros((240, 320), dtype=np.uint8)
        cv2.rectangle(mask, (48, 38), (272, 202), 255, -1)
        prepared = _preparar_referencia_ecc(tracker, reference, mask)
        self.assertIsNotNone(prepared)

        tracker._f2_ecc_ready = True
        tracker._f2_ecc_references = {"board_off": prepared}
        tracker._f2_ecc_last_compute_s = 0.0

        transform = cv2.getRotationMatrix2D((160, 120), 2.0, 1.0)
        transform[:, 2] += np.array([16.0, -9.0])
        current = cv2.warpAffine(
            reference,
            transform,
            (320, 240),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(24, 29, 34),
        )

        fallback = _tentar_ecc(tracker, current, previous_matrix=None)
        self.assertIsNotNone(fallback)
        result, _matrix, score = fallback
        self.assertTrue(result.locked)
        self.assertEqual("locked_ecc", result.reason)
        self.assertGreater(score, 0.58)

        raw_error = float(np.mean(cv2.absdiff(current, reference)))
        aligned_error = float(np.mean(cv2.absdiff(result.frame, reference)))
        self.assertLess(aligned_error, raw_error * 0.55)

    def test_ecc_nao_inventa_lock_em_frame_sem_placa(self):
        reference = self._reference()
        tracker = F2BoardObjectTracker()
        tracker.width = 320
        tracker.height = 240

        mask = np.zeros((240, 320), dtype=np.uint8)
        cv2.rectangle(mask, (48, 38), (272, 202), 255, -1)
        tracker._f2_ecc_ready = True
        tracker._f2_ecc_references = {
            "board_off": _preparar_referencia_ecc(tracker, reference, mask)
        }
        tracker._f2_ecc_last_compute_s = 0.0

        empty = np.zeros_like(reference)
        empty[:] = (24, 29, 34)
        self.assertIsNone(_tentar_ecc(tracker, empty, previous_matrix=None))

    def test_rotacao_180_no_centro_nao_vira_translacao_falsa(self):
        tracker = F2BoardObjectTracker()
        tracker.width = 320
        tracker.height = 240
        matrix = cv2.getRotationMatrix2D((160, 120), 180.0, 1.0).astype(
            np.float32
        )

        scale, rotation, dx, dy = _pose_matriz_rastreamento(
            tracker,
            matrix,
        )
        self.assertAlmostEqual(1.0, scale, delta=0.01)
        self.assertGreater(abs(rotation), 179.0)
        self.assertAlmostEqual(0.0, dx, delta=0.5)
        self.assertAlmostEqual(0.0, dy, delta=0.5)

    def test_orb_aceita_placa_girada_180_graus(self):
        reference = self._reference()
        tracker = F2BoardObjectTracker()
        tracker.width = 320
        tracker.height = 240

        gray_ref = tracker._prepare_gray(reference)
        mask = np.zeros((240, 320), dtype=np.uint8)
        cv2.rectangle(mask, (48, 38), (272, 202), 255, -1)
        orb = cv2.ORB_create(
            nfeatures=1200,
            scaleFactor=1.2,
            nlevels=8,
            edgeThreshold=15,
            fastThreshold=9,
        )
        ref_kp, ref_desc = orb.detectAndCompute(gray_ref, mask)
        tracker.references = {"board_off": (ref_kp, ref_desc)}

        rotation = cv2.getRotationMatrix2D((160, 120), 180.0, 1.0)
        current = cv2.warpAffine(
            reference,
            rotation,
            (320, 240),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(24, 29, 34),
        )
        current_gray = tracker._prepare_gray(current)
        current_kp, current_desc = orb.detectAndCompute(current_gray, None)

        candidate = _candidate_robusto(
            tracker,
            current_gray,
            current_kp,
            current_desc,
            "board_off",
        )
        self.assertIsNotNone(candidate)
        self.assertGreater(abs(float(candidate["rotation_deg"])), 170.0)
        self.assertLess(abs(float(candidate["dx"])), 35.0)
        self.assertLess(abs(float(candidate["dy"])), 35.0)

    def test_grace_lock_segura_falha_curta_sem_inventar_nova_pose(self):
        tracker = F2BoardObjectTracker()
        tracker.width = 320
        tracker.height = 240
        tracker._f2_tracking_last_good_s = time.monotonic()
        tracker._f2_tracking_miss_count = 0
        previous = F2TrackingResult(
            True,
            np.zeros((240, 320, 3), dtype=np.uint8),
            reference="board_off",
            matches=24,
            inliers=18,
            inlier_ratio=0.75,
            reason="locked",
        )
        tracker._f2_tracking_last_good_result = previous
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        matrix = np.float32([[1.0, 0.0, -12.0], [0.0, 1.0, 7.0]])

        held = _tentar_grace_lock(
            tracker,
            frame,
            2,
            matrix,
            previous,
        )
        self.assertIsNotNone(held)
        self.assertTrue(held.locked)
        self.assertEqual("grace_lock", held.reason)
        self.assertEqual("HOLD", tracker._f2_tracking_last_method)

    def test_patch_publica_status_travado_ou_procurando_sem_f3(self):
        instalar_correcao_runtime_rastreamento_f2()
        import src.platform.f2_object_tracking_runtime_fix as module

        source = inspect.getsource(module)
        self.assertIn("RASTREAMENTO ATIVO • TRAVADO", source)
        self.assertIn("RASTREAMENTO ATIVO • PROCURANDO", source)
        self.assertIn("cv2.findTransformECC", source)
        self.assertIn("F2_TRACKING_LOSS_GRACE_S", source)
        self.assertIn("F2_TRACKING_WIDE_ROTATION_DEG", source)
        self.assertNotIn("display_f3", source)


if __name__ == "__main__":
    unittest.main()
