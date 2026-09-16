from __future__ import annotations

import inspect
import unittest

import cv2
import numpy as np

from src.platform.f2_object_tracking import F2BoardObjectTracker
from src.platform.f2_object_tracking_runtime_fix import (
    _preparar_referencia_ecc,
    _tentar_ecc,
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

    def test_patch_publica_status_travado_ou_procurando_sem_f3(self):
        instalar_correcao_runtime_rastreamento_f2()
        import src.platform.f2_object_tracking_runtime_fix as module

        source = inspect.getsource(module)
        self.assertIn("RASTREAMENTO ATIVO • TRAVADO", source)
        self.assertIn("RASTREAMENTO ATIVO • PROCURANDO", source)
        self.assertIn("cv2.findTransformECC", source)
        self.assertNotIn("display_f3", source)


if __name__ == "__main__":
    unittest.main()
