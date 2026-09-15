from __future__ import annotations

import unittest

import numpy as np

from src.platform.display_f3_rearm_live_refresh_fix import (
    detectar_suporte_vazio_relativo_rearme_f3,
    estado_scores_presenca_rearme_f3,
    status_visual_rearme_f3,
)


class _Store:
    def __init__(self, values):
        self.values = values

    def get_all(self, project_name):
        return dict(self.values.get(project_name, {}))

    def get(self, project_name, key):
        return self.values.get(project_name, {}).get(key)


class _Repository:
    @staticmethod
    def listar_checks(_project_name):
        return [
            {"id": "CHECK_001", "name": "H1"},
            {"id": "CHECK_002", "name": "BLUE"},
            {"id": "CHECK_004", "name": "USB"},
            {"id": "CHECK_003", "name": "AUX"},
        ]


class _Matcher:
    def __init__(self, scores):
        self.repository = _Repository()
        self.project_store = _Store(
            {
                "CM-550-L": {
                    "empty_support": {"score": scores["empty"], "threshold": 0.72},
                    "board_off": {"score": scores["off"], "threshold": 0.72},
                }
            }
        )
        self.check_store = _Store(
            {
                "CM-550-L": {
                    "CHECK_001": {"score": scores["check:CHECK_001"], "threshold": 0.72},
                    "CHECK_002": {"score": scores["check:CHECK_002"], "threshold": 0.72},
                    "CHECK_004": {"score": scores["check:CHECK_004"], "threshold": 0.72},
                    "CHECK_003": {"score": scores["check:CHECK_003"], "threshold": 0.72},
                }
            }
        )

    @staticmethod
    def _score(_current_small, metadata):
        return float(metadata["score"])

    @staticmethod
    def _threshold(metadata):
        return float(metadata.get("threshold", 0.72))


class DisplayF3RearmLiveRefreshFixTests(unittest.TestCase):
    @staticmethod
    def _frame():
        return np.zeros((40, 60, 3), dtype=np.uint8)

    def test_debug_real_confirma_empty_mesmo_abaixo_threshold_absoluto(self):
        matcher = _Matcher(
            {
                "empty": 0.5876,
                "off": 0.3898,
                "check:CHECK_001": 0.4047,
                "check:CHECK_002": 0.3868,
                "check:CHECK_004": 0.3874,
                "check:CHECK_003": 0.3909,
            }
        )
        state = estado_scores_presenca_rearme_f3(matcher, self._frame(), "CM-550-L")
        self.assertAlmostEqual(0.5876, state["reference_scores"]["empty"], places=4)
        self.assertAlmostEqual(0.4047, state["reference_scores"]["check:CHECK_001"], places=4)

        result = detectar_suporte_vazio_relativo_rearme_f3(
            matcher,
            self._frame(),
            "CM-550-L",
        )
        self.assertIsInstance(result, dict)
        self.assertEqual("empty", result["kind"])
        self.assertTrue(result["rearm_empty_relative"])
        self.assertFalse(result["allow_auto"])
        self.assertTrue(result["board_presence_evidence"]["empty_confirmed"])

    def test_cena_ocupada_nao_e_promovida_para_empty(self):
        matcher = _Matcher(
            {
                "empty": 0.40,
                "off": 0.78,
                "check:CHECK_001": 0.81,
                "check:CHECK_002": 0.80,
                "check:CHECK_004": 0.79,
                "check:CHECK_003": 0.78,
            }
        )
        result = detectar_suporte_vazio_relativo_rearme_f3(
            matcher,
            self._frame(),
            "CM-550-L",
        )
        self.assertIsNone(result)

    def test_status_visual_nao_pode_ficar_no_check_antigo_durante_rearme(self):
        text, _color = status_visual_rearme_f3(
            {
                "final_rearm_guard": True,
                "cycle_rearm_waiting": True,
                "rearm_underlying_kind": "check",
                "rearm_underlying_text": "DISPLAY EM BLUE",
            }
        )
        self.assertIn("aguardando retirada", text)
        self.assertNotIn("77%", text)
        self.assertNotIn("CHECK BLUE", text)

    def test_status_visual_mostra_suporte_vazio_apos_confirmacao(self):
        text, _color = status_visual_rearme_f3(
            {
                "final_rearm_guard": True,
                "cycle_rearmed_waiting_new_board": True,
                "rearm_underlying_kind": "empty",
            }
        )
        self.assertIn("PLACA FORA DO SUPORTE", text)
        self.assertIn("suporte vazio confirmado", text)


if __name__ == "__main__":
    unittest.main()
