from __future__ import annotations

import unittest

from src.platform.display_f3_presence_relative_empty_fix import (
    F3_RELATIVE_EMPTY_PRESENCE_SOURCE,
    aplicar_status_visual_suporte_vazio_f3,
    avaliar_suporte_vazio_relativo_f3,
)


class DisplayF3RelativeEmptyPresenceTests(unittest.TestCase):
    def _debug_state(self):
        # Valores do snapshot real em que a placa foi retirada durante BLUE.
        return {
            "kind": "unknown",
            "text": "IDENTIFICANDO PRESENÇA DA PLACA...",
            "reference_scores": {
                "empty": 0.5867,
                "check:CHECK_001": 0.4130,
                "check:CHECK_003": 0.3985,
                "off": 0.3973,
                "check:CHECK_004": 0.3947,
                "check:CHECK_002": 0.3938,
            },
        }

    def test_debug_real_confirma_suporte_vazio_por_separacao_forte(self):
        result = avaliar_suporte_vazio_relativo_f3(self._debug_state())

        self.assertTrue(result["empty_confirmed"])
        self.assertTrue(result["presence_confirmed"])
        self.assertFalse(result["board_present"])
        self.assertEqual("check:CHECK_001", result["best_board_reference"])
        self.assertAlmostEqual(0.1737, result["empty_over_best_board_margin"], places=4)
        self.assertEqual(
            "relative_empty_strong_separation",
            result["decision_mode"],
        )

    def test_scores_proximos_continuam_unknown(self):
        state = {
            "kind": "unknown",
            "reference_scores": {
                "empty": 0.5867,
                "off": 0.55,
                "check:CHECK_002": 0.56,
            },
        }
        result = avaliar_suporte_vazio_relativo_f3(state)

        self.assertFalse(result["empty_confirmed"])
        self.assertFalse(result["presence_confirmed"])
        self.assertEqual(
            "relative_empty_insufficient_separation",
            result["decision_mode"],
        )

    def test_empty_com_score_muito_baixo_nao_e_confirmado(self):
        state = {
            "kind": "unknown",
            "reference_scores": {
                "empty": 0.35,
                "off": 0.10,
                "check:CHECK_001": 0.12,
            },
        }
        result = avaliar_suporte_vazio_relativo_f3(state)

        self.assertFalse(result["empty_confirmed"])

    def test_estado_fisico_explicito_com_placa_nao_e_sobrescrito(self):
        state = {
            "kind": "off",
            "reference_scores": {
                "empty": 0.80,
                "off": 0.73,
                "check:CHECK_001": 0.72,
            },
        }
        result = avaliar_suporte_vazio_relativo_f3(state)

        self.assertFalse(result["empty_confirmed"])
        self.assertEqual(
            "estado_fisico_explicito_nao_sobrescrito",
            result["reason"],
        )

    def test_empty_absoluto_permanece_confirmado(self):
        result = avaliar_suporte_vazio_relativo_f3(
            {
                "kind": "empty",
                "reference_scores": {"empty": 0.88, "off": 0.40},
            }
        )

        self.assertTrue(result["empty_confirmed"])
        self.assertEqual("absolute_empty_reference", result["decision_mode"])

    def test_status_visual_mostra_placa_fora_quando_presenca_confirma_empty(self):
        state = {
            "text": "CHECK PRODUTIVO: SEM DECISÃO • FLUXO BLOQUEADO",
            "status_text": "CHECK PRODUTIVO: SEM DECISÃO • FLUXO BLOQUEADO",
            "result_kind": "power_unconfirmed",
        }
        status = {
            "board_present": False,
            "empty_confirmed": True,
            "presence": {
                "empty_confirmed": True,
                "source": F3_RELATIVE_EMPTY_PRESENCE_SOURCE,
            },
            "energy": None,
            "decision_allowed": False,
        }

        result = aplicar_status_visual_suporte_vazio_f3(state, status)

        self.assertEqual("empty_support", result["result_kind"])
        self.assertEqual("empty_support", result["selected_reference"])
        self.assertIn("PLACA FORA DO SUPORTE", result["status_text"])
        self.assertEqual(
            F3_RELATIVE_EMPTY_PRESENCE_SOURCE,
            result["effective_status_authority"],
        )
        self.assertEqual(
            "CHECK PRODUTIVO: SEM DECISÃO • FLUXO BLOQUEADO",
            result["status_text_raw"],
        )


if __name__ == "__main__":
    unittest.main()
