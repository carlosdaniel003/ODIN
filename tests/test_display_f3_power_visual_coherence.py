from __future__ import annotations

import unittest

import src.platform.display_f3_power_authority as power_module
import src.platform.display_f3_power_visual_coherence as coherence_module


class DisplayF3PowerVisualCoherenceTests(unittest.TestCase):
    def _status(self, *, energy_state: str, decision_allowed: bool, board_present: bool = True):
        return {
            "source": "f3_unified_current_check_mask_power_authority",
            "board_present": board_present,
            "decision_allowed": decision_allowed,
            "reason": (
                "todos_segmentos_esperados_acesos_estao_apagados"
                if energy_state == power_module.F3_POWER_STATE_OFF
                else "segmento_aceso_confirmado_pela_analise_bruta"
                if energy_state == power_module.F3_POWER_STATE_POWERED
                else "nenhum_segmento_aceso_confirmou_energia"
            ),
            "energy": {
                "energy_state": energy_state,
                "powered_confirmed": energy_state == power_module.F3_POWER_STATE_POWERED,
                "off_confirmed": energy_state == power_module.F3_POWER_STATE_OFF,
            },
        }

    def test_placa_desligada_remove_amarelos_e_deixa_guias_neutras(self):
        # Reproduz o debug do BLUE: quase todos os ON esperados viraram OFF, mas
        # duas máscaras esperadas OFF foram classificadas ON e poderiam enganar
        # has_any_on, fazendo o desenho inteiro do BLUE ficar amarelo.
        context = {
            "resolution": (1920, 1080),
            "masks": ({"id": "MASK_001"}, {"id": "MASK_026"}),
            "expected_states": {"MASK_001": "on", "MASK_026": "off"},
            "classifications": {"MASK_001": "off", "MASK_026": "on"},
            "failed_mask_ids": ("MASK_001", "MASK_026"),
            "failed_masks": {"MASK_001": {}, "MASK_026": {}},
            "has_any_on": True,
        }
        status = self._status(
            energy_state=power_module.F3_POWER_STATE_OFF,
            decision_allowed=False,
        )

        result = coherence_module.aplicar_coerencia_overlay_com_energia_f3(
            context,
            status,
        )

        self.assertEqual({}, result["classifications"])
        self.assertEqual((), result["failed_mask_ids"])
        self.assertEqual({}, result["failed_masks"])
        self.assertFalse(result["has_any_on"])
        self.assertFalse(result["semantic_overlay_allowed"])
        self.assertTrue(result["semantic_overlay_suppressed"])
        self.assertEqual(
            coherence_module.F3_OVERLAY_MODE_NEUTRAL,
            result["semantic_overlay_mode"],
        )
        # Geometria permanece para a camada de guias neutras.
        self.assertEqual((1920, 1080), result["resolution"])
        self.assertEqual(2, len(result["masks"]))

    def test_energia_confirmada_preserva_overlay_semantico_e_defeito_real(self):
        context = {
            "resolution": (1920, 1080),
            "masks": ({"id": "MASK_001"}, {"id": "MASK_002"}),
            "expected_states": {"MASK_001": "on", "MASK_002": "on"},
            "classifications": {"MASK_001": "on", "MASK_002": "off"},
            "failed_mask_ids": ("MASK_002",),
            "has_any_on": True,
        }
        status = self._status(
            energy_state=power_module.F3_POWER_STATE_POWERED,
            decision_allowed=True,
        )

        result = coherence_module.aplicar_coerencia_overlay_com_energia_f3(
            context,
            status,
        )

        self.assertEqual(context["classifications"], result["classifications"])
        self.assertEqual(("MASK_002",), result["failed_mask_ids"])
        self.assertTrue(result["has_any_on"])
        self.assertTrue(result["semantic_overlay_allowed"])
        self.assertEqual(
            coherence_module.F3_OVERLAY_MODE_SEMANTIC,
            result["semantic_overlay_mode"],
        )

    def test_status_visual_check_global_e_substituido_por_placa_desligada(self):
        state = {
            "text": "ANÁLISE VISUAL: CHECK BLUE • 76%",
            "color": "#7DD3FC",
            "result_kind": "check",
            "selected_reference": "check:CHECK_002",
            "best_reference": "check:CHECK_002",
            "decision_mode": "best_matched_check_close_references",
            "best_score": 0.76,
            "candidates": {"board_off": {"score": 0.746}},
        }
        status = self._status(
            energy_state=power_module.F3_POWER_STATE_OFF,
            decision_allowed=False,
        )

        result = coherence_module.aplicar_coerencia_estado_visual_com_energia_f3(
            state,
            status,
        )

        self.assertEqual("board_off", result["result_kind"])
        self.assertEqual("board_off", result["selected_reference"])
        self.assertIn("PLACA DESLIGADA NO SUPORTE", result["text"])
        self.assertEqual(
            "ANÁLISE VISUAL: CHECK BLUE • 76%",
            result["status_text_raw"],
        )
        self.assertEqual(
            "check:CHECK_002",
            result["global_visual_selected_reference_raw"],
        )
        self.assertEqual(
            "power_authority_override_off",
            result["decision_mode"],
        )

    def test_energia_nao_confirmada_nao_anuncia_check(self):
        state = {
            "text": "ANÁLISE VISUAL: CHECK H1 • 75%",
            "result_kind": "check",
            "selected_reference": "check:CHECK_001",
        }
        status = self._status(
            energy_state=power_module.F3_POWER_STATE_UNCONFIRMED,
            decision_allowed=False,
        )

        result = coherence_module.aplicar_coerencia_estado_visual_com_energia_f3(
            state,
            status,
        )

        self.assertEqual("power_unconfirmed", result["result_kind"])
        self.assertIsNone(result["selected_reference"])
        self.assertIn("ENERGIA NÃO CONFIRMADA", result["text"])
        self.assertEqual(
            "ANÁLISE VISUAL: CHECK H1 • 75%",
            result["status_text_raw"],
        )

    def test_sem_status_de_energia_nao_altera_contexto(self):
        context = {
            "classifications": {"MASK_001": "on"},
            "failed_mask_ids": (),
            "has_any_on": True,
        }
        result = coherence_module.aplicar_coerencia_overlay_com_energia_f3(
            context,
            None,
        )
        self.assertEqual(context, result)


if __name__ == "__main__":
    unittest.main()
