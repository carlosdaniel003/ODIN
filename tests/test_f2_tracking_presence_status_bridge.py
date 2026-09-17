import unittest
from types import SimpleNamespace

from src.platform.f2_tracking_orientation_references import (
    F2_ORIENTATION_90,
    F2_ORIENTATION_180,
)
from src.platform.f2_tracking_presence_status_bridge import (
    F2_BOARD_STATUS_PRESENT,
    evidencia_presenca_orientacao_real_f2,
    status_visual_presenca_angular_f2,
)


class _FakeApp:
    def __init__(self, *, enabled=True, status=None, tracker=None):
        self.rastreamento_automatico_f2 = bool(enabled)
        self._f2_object_tracking_last_status = dict(status or {})
        self._f2_object_tracker = tracker

    def _f2_tracking_enabled(self):
        return self.rastreamento_automatico_f2


class F2TrackingPresenceStatusBridgeTests(unittest.TestCase):
    def _app_orientacao_90(self, *, enabled=True):
        tracker = SimpleNamespace(
            _f2_tracking_last_method="ORB-REAL",
            _f2_real_orientation_slots={F2_ORIENTATION_90},
            _f2_real_orientation_candidate_results={},
            last_result=None,
        )
        return _FakeApp(
            enabled=enabled,
            tracker=tracker,
            status={
                "locked": True,
                "reference": F2_ORIENTATION_90,
                "reason": "locked_real_orientation",
                "matches": 20,
                "inliers": 15,
                "inlier_ratio": 0.75,
            },
        )

    def test_referencia_real_vencedora_confirma_presenca(self):
        app = self._app_orientacao_90()

        evidence = evidencia_presenca_orientacao_real_f2(app)
        self.assertIsNotNone(evidence)
        self.assertEqual(evidence["slot"], F2_ORIENTATION_90)
        self.assertEqual(evidence["angle_deg"], 90.0)

    def test_orientacao_real_sem_estado_eletrico_publica_placa_presente(self):
        app = self._app_orientacao_90()
        self.assertEqual(
            status_visual_presenca_angular_f2(app, "unknown"),
            F2_BOARD_STATUS_PRESENT,
        )

    def test_rotacao_preserva_ligada_quando_estado_ja_era_conhecido(self):
        app = self._app_orientacao_90()
        self.assertEqual(
            status_visual_presenca_angular_f2(app, "board_on"),
            "board_on",
        )

    def test_rotacao_preserva_desligada_quando_estado_ja_era_conhecido(self):
        app = self._app_orientacao_90()
        self.assertEqual(
            status_visual_presenca_angular_f2(app, "board_off"),
            "board_off",
        )

    def test_tracking_desativado_nao_altera_presenca(self):
        app = self._app_orientacao_90(enabled=False)
        self.assertIsNone(evidencia_presenca_orientacao_real_f2(app))
        self.assertIsNone(status_visual_presenca_angular_f2(app, "unknown"))

    def test_hold_nao_e_prova_de_presenca(self):
        tracker = SimpleNamespace(
            _f2_tracking_last_method="HOLD",
            _f2_real_orientation_slots={F2_ORIENTATION_180},
            _f2_real_orientation_candidate_results={},
            last_result=None,
        )
        app = _FakeApp(
            enabled=True,
            tracker=tracker,
            status={
                "locked": True,
                "reference": F2_ORIENTATION_180,
                "reason": "grace_lock",
            },
        )
        self.assertIsNone(evidencia_presenca_orientacao_real_f2(app))
        self.assertIsNone(status_visual_presenca_angular_f2(app, "board_on"))

    def test_candidato_real_valido_confirma_mesmo_se_outra_vista_venceu(self):
        tracker = SimpleNamespace(
            _f2_tracking_last_method="ORB",
            _f2_real_orientation_slots={F2_ORIENTATION_90},
            _f2_real_orientation_candidate_results={
                F2_ORIENTATION_90: {
                    "score": 18.0,
                    "matches": 17,
                    "inliers": 12,
                    "ratio": 0.70,
                }
            },
            last_result=None,
        )
        app = _FakeApp(
            enabled=True,
            tracker=tracker,
            status={
                "locked": True,
                "reference": "board_on",
                "reason": "locked",
            },
        )

        evidence = evidencia_presenca_orientacao_real_f2(app)
        self.assertIsNotNone(evidence)
        self.assertEqual(evidence["slot"], F2_ORIENTATION_90)
        self.assertEqual(evidence["source"], "validated_candidate")

    def test_slot_nao_carregado_nao_e_usado(self):
        tracker = SimpleNamespace(
            _f2_tracking_last_method="ORB",
            _f2_real_orientation_slots=set(),
            _f2_real_orientation_candidate_results={},
            last_result=None,
        )
        app = _FakeApp(
            enabled=True,
            tracker=tracker,
            status={
                "locked": True,
                "reference": F2_ORIENTATION_90,
                "reason": "locked",
            },
        )
        self.assertIsNone(evidencia_presenca_orientacao_real_f2(app))


if __name__ == "__main__":
    unittest.main()
