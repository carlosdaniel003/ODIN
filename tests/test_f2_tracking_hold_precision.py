import unittest
from types import SimpleNamespace

import src.platform.f2_object_tracking_hold_reacquire as hold_reacquire
import src.platform.f2_object_tracking_multiview as multiview
from src.platform.f2_object_tracking import F2BoardObjectTracker


class F2TrackingHoldPrecisionTests(unittest.TestCase):
    def test_hold_e_reconhecido_como_pose_provisoria(self):
        tracker = SimpleNamespace(_f2_tracking_last_method="HOLD")
        result = SimpleNamespace(locked=True, reason="grace_lock")
        self.assertTrue(hold_reacquire._resultado_e_hold(tracker, result))

    def test_lock_fresco_nao_e_classificado_como_hold(self):
        tracker = SimpleNamespace(_f2_tracking_last_method="ORB-MV")
        result = SimpleNamespace(locked=True, reason="locked_multiview")
        self.assertFalse(hold_reacquire._resultado_e_hold(tracker, result))

    def test_reaquisicao_multiview_substitui_hold_quando_encontra_pose_fresca(self):
        original_align = F2BoardObjectTracker.align
        original_try = multiview._tentar_multiview
        original_installed = hold_reacquire._PATCH_INSTALADO

        hold_result = SimpleNamespace(locked=True, reason="grace_lock")
        fresh_result = SimpleNamespace(locked=True, reason="locked_multiview")

        try:
            def fake_align(self, frame, frame_id=None):
                self._f2_tracking_last_method = "HOLD"
                return hold_result

            def fake_multiview(self, frame, frame_id=None):
                self._f2_tracking_last_method = "ORB-MV"
                return fresh_result

            F2BoardObjectTracker.align = fake_align
            multiview._tentar_multiview = fake_multiview
            hold_reacquire._PATCH_INSTALADO = False
            hold_reacquire.instalar_reaquisicao_durante_hold_f2()

            tracker = F2BoardObjectTracker.__new__(F2BoardObjectTracker)
            result = tracker.align(object(), frame_id=77)
            self.assertIs(fresh_result, result)
            self.assertEqual("ORB-MV", tracker._f2_tracking_last_method)
        finally:
            F2BoardObjectTracker.align = original_align
            multiview._tentar_multiview = original_try
            hold_reacquire._PATCH_INSTALADO = original_installed


if __name__ == "__main__":
    unittest.main()
