from __future__ import annotations

import unittest

from src.platform.display_f3_presence_relative_empty_fix import (
    F3_RELATIVE_BOARD_PRESENCE_SOURCE,
    F3_RELATIVE_EMPTY_PRESENCE_SOURCE,
    aplicar_status_visual_suporte_vazio_f3,
    avaliar_presenca_relativa_f3,
    avaliar_suporte_vazio_relativo_f3,
    resolver_presenca_global_relativa_f3,
)


class DisplayF3RelativePresenceTests(unittest.TestCase):
    def _removed_board_debug_state(self):
        # Snapshot real: placa retirada durante BLUE.
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

    def _restart_with_board_debug_state(self):
        # Snapshot real: programa reiniciado, placa desligada colocada no suporte.
        # H1 e BLUE ficam separados por apenas 0.0087, mas isso é irrelevante para
        # PRESENÇA porque todas as referências CHECK/OFF contêm a placa.
        return {
            "kind": "unknown",
            "text": "IDENTIFICANDO...",
            "ambiguous": True,
            "best_score": 0.8089,
            "second_score": 0.8002,
            "reference_scores": {
                "check:CHECK_001": 0.8089,
                "check:CHECK_002": 0.8002,
                "check:CHECK_004": 0.7921,
                "check:CHECK_003": 0.7885,
                "off": 0.7879,
                "empty": 0.4089,
            },
        }

    def test_debug_real_confirma_suporte_vazio_por_separacao_forte(self):
        result = avaliar_suporte_vazio_relativo_f3(self._removed_board_debug_state())

        self.assertTrue(result["empty_confirmed"])
        self.assertTrue(result["presence_confirmed"])
        self.assertFalse(result["board_present"])
        self.assertEqual("check:CHECK_001", result["best_board_reference"])
        self.assertAlmostEqual(0.1737, result["empty_over_best_board_margin"], places=4)
        self.assertEqual(
            "relative_empty_strong_separation",
            result["decision_mode"],
        )
        self.assertEqual(F3_RELATIVE_EMPTY_PRESENCE_SOURCE, result["source"])

    def test_debug_real_reinicio_confirma_placa_mesmo_com_checks_ambiguos(self):
        result = avaliar_presenca_relativa_f3(self._restart_with_board_debug_state())

        self.assertTrue(result["presence_confirmed"])
        self.assertTrue(result["board_present"])
        self.assertFalse(result["empty_confirmed"])
        self.assertEqual("check:CHECK_001", result["best_board_reference"])
        self.assertAlmostEqual(0.4000, result["board_over_empty_margin"], places=4)
        self.assertEqual(
            "relative_board_strong_separation",
            result["decision_mode"],
        )
        self.assertEqual(F3_RELATIVE_BOARD_PRESENCE_SOURCE, result["source"])

    def test_debug_camera_rebaixada_refocada_confirma_placa_por_margem_relativa(self):
        # Snapshot 24/09/2026: todos os scores absolutos caíram após reposicionar
        # e refocar a câmera, mas a cena com placa continua claramente acima do
        # suporte vazio.
        state = {
            "kind": "unknown",
            "reference_scores": {
                "check:CHECK_001": 0.5377,
                "off": 0.5351,
                "check:CHECK_002": 0.5250,
                "check:CHECK_003": 0.5210,
                "check:CHECK_004": 0.5065,
                "empty": 0.3901,
            },
        }

        result = avaliar_presenca_relativa_f3(state)

        self.assertTrue(result["presence_confirmed"])
        self.assertTrue(result["board_present"])
        self.assertFalse(result["empty_confirmed"])
        self.assertEqual("check:CHECK_001", result["best_board_reference"])
        self.assertAlmostEqual(0.1476, result["board_over_empty_margin"], places=4)
        self.assertEqual(
            "relative_board_strong_separation",
            result["decision_mode"],
        )

    def test_presenca_global_nao_depende_apenas_da_referencia_off(self):
        state = self._restart_with_board_debug_state()
        legacy = {
            "available": True,
            "board_present": False,
            "reason": "legacy_inconclusive",
        }

        result = resolver_presenca_global_relativa_f3(state, legacy)

        self.assertTrue(result["board_present"])
        self.assertTrue(result["presence_confirmed"])
        self.assertEqual(
            "relative_board_strong_separation",
            result["decision_mode"],
        )
        self.assertEqual(0.4089, result["empty_score"])
        self.assertEqual(0.8089, result["best_board_score"])

    def test_ambiguidade_h1_blue_nao_pode_virar_ambiguidade_de_presenca(self):
        state = self._restart_with_board_debug_state()
        self.assertLess(
            abs(
                state["reference_scores"]["check:CHECK_001"]
                - state["reference_scores"]["check:CHECK_002"]
            ),
            0.01,
        )

        result = avaliar_presenca_relativa_f3(state)

        self.assertTrue(result["board_present"])
        self.assertTrue(result["presence_confirmed"])

    def test_scores_proximos_continuam_unknown(self):
        state = {
            "kind": "unknown",
            "reference_scores": {
                "empty": 0.5867,
                "off": 0.55,
                "check:CHECK_002": 0.56,
            },
        }
        result = avaliar_presenca_relativa_f3(state)

        self.assertFalse(result["empty_confirmed"])
        self.assertFalse(result["presence_confirmed"])
        self.assertFalse(result["board_present"])
        self.assertEqual(
            "relative_presence_insufficient_separation",
            result["decision_mode"],
        )

    def test_cena_com_placa_score_muito_baixo_nao_e_confirmada(self):
        state = {
            "kind": "unknown",
            "reference_scores": {
                "empty": 0.10,
                "off": 0.35,
                "check:CHECK_001": 0.36,
            },
        }
        result = avaliar_presenca_relativa_f3(state)

        self.assertFalse(result["presence_confirmed"])
        self.assertFalse(result["board_present"])

    def test_empty_com_score_muito_baixo_nao_e_confirmado(self):
        state = {
            "kind": "unknown",
            "reference_scores": {
                "empty": 0.35,
                "off": 0.10,
                "check:CHECK_001": 0.12,
            },
        }
        result = avaliar_presenca_relativa_f3(state)

        self.assertFalse(result["empty_confirmed"])
        self.assertFalse(result["presence_confirmed"])

    def test_estado_fisico_explicito_com_placa_nao_e_sobrescrito_por_empty(self):
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

    def test_estado_fisico_off_confirma_presenca(self):
        result = avaliar_presenca_relativa_f3(
            {
                "kind": "off",
                "reference_scores": {"empty": 0.30, "off": 0.90},
            }
        )

        self.assertTrue(result["presence_confirmed"])
        self.assertTrue(result["board_present"])
        self.assertFalse(result["empty_confirmed"])
        self.assertEqual("absolute_board_scene_reference", result["decision_mode"])

    def test_empty_absoluto_permanece_confirmado(self):
        result = avaliar_presenca_relativa_f3(
            {
                "kind": "empty",
                "reference_scores": {"empty": 0.88, "off": 0.40},
            }
        )

        self.assertTrue(result["empty_confirmed"])
        self.assertFalse(result["board_present"])
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
                "presence_confirmed": True,
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
