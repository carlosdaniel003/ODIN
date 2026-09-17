import unittest
from types import SimpleNamespace

import src.platform.f2_tracking_analysis_rois as tracking_analysis
import src.platform.f2_tracking_hold_analysis_guard as hold_guard


class F2TrackingHoldAnalysisGuardTests(unittest.TestCase):
    def test_hold_nao_e_aceito_como_pose_de_julgamento(self):
        original = tracking_analysis._tracking_com_lock
        original_installed = hold_guard._PATCH_INSTALADO
        try:
            tracking_analysis._tracking_com_lock = lambda app: True
            hold_guard._PATCH_INSTALADO = False
            hold_guard.instalar_guarda_analise_pose_fresca_f2()

            app = SimpleNamespace(
                _f2_object_tracking_last_status={
                    "locked": True,
                    "reason": "grace_lock",
                },
                _f2_object_tracker=SimpleNamespace(
                    last_matrix=object(),
                    _f2_tracking_last_method="HOLD",
                    last_result=SimpleNamespace(reason="grace_lock"),
                ),
            )
            self.assertFalse(tracking_analysis._tracking_com_lock(app))
        finally:
            tracking_analysis._tracking_com_lock = original
            hold_guard._PATCH_INSTALADO = original_installed

    def test_pose_fresca_continua_liberada_para_analise(self):
        original = tracking_analysis._tracking_com_lock
        original_installed = hold_guard._PATCH_INSTALADO
        try:
            tracking_analysis._tracking_com_lock = lambda app: True
            hold_guard._PATCH_INSTALADO = False
            hold_guard.instalar_guarda_analise_pose_fresca_f2()

            app = SimpleNamespace(
                _f2_object_tracking_last_status={
                    "locked": True,
                    "reason": "locked_multiview",
                },
                _f2_object_tracker=SimpleNamespace(
                    last_matrix=object(),
                    _f2_tracking_last_method="ORB-MV",
                    last_result=SimpleNamespace(reason="locked_multiview"),
                ),
            )
            self.assertTrue(tracking_analysis._tracking_com_lock(app))
        finally:
            tracking_analysis._tracking_com_lock = original
            hold_guard._PATCH_INSTALADO = original_installed


if __name__ == "__main__":
    unittest.main()
