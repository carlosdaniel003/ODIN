from __future__ import annotations

import unittest
from unittest.mock import patch

import src.platform.display_f3_debug_clarity_fix as debug_clarity_module
import src.platform.display_f3_power_authority as power_module
import src.platform.display_f3_runtime_contract_fix as contract_module


class _FakeApp:
    _display_f3_waiting_empty_rearm = False
    _display_f3_waiting_new_board_after_empty = False


class DisplayF3PowerAuthorityTests(unittest.TestCase):
    def _signature(self, mean, p95, p99, hot235, hot245):
        return {
            "v_mean": mean,
            "v_p95": p95,
            "v_p99": p99,
            "hot_235": hot235,
            "hot_245": hot245,
            "pixel_count": 100,
        }

    def test_live_proximo_da_placa_desligada_vota_off(self):
        off = self._signature(155, 171, 179, 0.01, 0.0)
        on = self._signature(251, 255, 255, 0.96, 0.89)
        live = self._signature(157, 173, 181, 0.01, 0.0)

        result = power_module.classificar_posicao_relativa_energia_f3(
            live,
            off,
            on,
        )

        self.assertEqual("off", result["winner"])
        self.assertLessEqual(
            result["power_position"],
            power_module.F3_POWER_RELATIVE_OFF_MAX,
        )
        self.assertTrue(result["reference_discriminative"])

    def test_live_proximo_da_foto_on_confirma_energia(self):
        off = self._signature(155, 171, 179, 0.01, 0.0)
        on = self._signature(251, 255, 255, 0.96, 0.89)
        live = self._signature(248, 254, 255, 0.91, 0.84)

        result = power_module.classificar_posicao_relativa_energia_f3(
            live,
            off,
            on,
        )

        self.assertEqual("powered", result["winner"])
        self.assertGreaterEqual(
            result["power_position"],
            power_module.F3_POWER_RELATIVE_ON_MIN,
        )

    def test_todos_os_on_esperados_apagados_viram_placa_off_e_nao_ng(self):
        details = [
            {"mask_id": mask_id, "winner": "off"}
            for mask_id in (
                "MASK_008",
                "MASK_009",
                "MASK_011",
                "MASK_013",
                "MASK_014",
                "MASK_020",
                "MASK_021",
            )
        ]

        result = power_module.resumir_votos_energia_f3(details, 7)

        self.assertEqual(power_module.F3_POWER_STATE_OFF, result["energy_state"])
        self.assertTrue(result["off_confirmed"])
        self.assertFalse(result["powered_confirmed"])
        self.assertEqual(7, result["off_votes"])
        self.assertEqual(0, result["powered_votes"])

    def test_um_segmento_on_ja_prova_que_display_tem_energia(self):
        details = [
            {"mask_id": "MASK_008", "winner": "powered"},
            {"mask_id": "MASK_009", "winner": "off"},
            {"mask_id": "MASK_011", "winner": "off"},
        ]

        result = power_module.resumir_votos_energia_f3(details, 3)

        self.assertEqual(
            power_module.F3_POWER_STATE_POWERED,
            result["energy_state"],
        )
        self.assertTrue(result["powered_confirmed"])
        self.assertFalse(result["off_confirmed"])

    def test_referencia_global_h1_nao_fura_gate_quando_mascaras_dizem_off(self):
        state = {
            "kind": "check",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "allow_auto": True,
            "reference_scores": {
                "check:CHECK_001": 0.7501,
                "check:CHECK_002": 0.7466,
                "off": 0.7450,
                "empty": 0.4001,
            },
        }
        evidence = {
            "available": True,
            "energy_state": power_module.F3_POWER_STATE_OFF,
            "powered_confirmed": False,
            "off_confirmed": True,
            "expected_on_mask_count": 7,
            "powered_votes": 0,
            "off_votes": 7,
            "tie_votes": 0,
            "details": [],
        }
        app = _FakeApp()

        with patch.object(
            power_module,
            "avaliar_evidencia_energia_relativa_display_f3",
            return_value=evidence,
        ):
            result = power_module.aplicar_autoridade_energia_ao_estado_f3(
                app,
                state,
                frame=object(),
                project_name="CM-550-L",
                context={"check_id": "CHECK_001", "check_name": "H1"},
            )

        self.assertEqual("off", result["kind"])
        self.assertFalse(result["allow_auto"])
        self.assertFalse(result[contract_module.F3_DECISION_ALLOWED_KEY])
        self.assertTrue(result["power_gate_blocked"])
        self.assertEqual(
            "todos_segmentos_esperados_acesos_estao_apagados",
            result["power_gate_reason"],
        )

    def test_um_on_confirmado_libera_somente_gate_de_energia(self):
        state = {
            "kind": "unknown",
            "allow_auto": False,
            "reference_scores": {"off": 0.74, "empty": 0.40},
        }
        evidence = {
            "available": True,
            "energy_state": power_module.F3_POWER_STATE_POWERED,
            "powered_confirmed": True,
            "off_confirmed": False,
            "expected_on_mask_count": 7,
            "powered_votes": 1,
            "off_votes": 5,
            "tie_votes": 1,
            "details": [],
        }
        app = _FakeApp()

        with patch.object(
            power_module,
            "avaliar_evidencia_energia_relativa_display_f3",
            return_value=evidence,
        ):
            result = power_module.aplicar_autoridade_energia_ao_estado_f3(
                app,
                state,
                frame=object(),
                project_name="CM-550-L",
                context={"check_id": "CHECK_001", "check_name": "H1"},
            )

        self.assertEqual("powered", result["kind"])
        self.assertTrue(result["allow_auto"])
        self.assertTrue(result[contract_module.F3_DECISION_ALLOWED_KEY])
        # Energia não significa CHECK aprovado: a identidade/conformidade ainda
        # pertence ao analisador produtivo.
        self.assertFalse(result["physical_matches_expected_check"])

    def test_debug_separa_gate_de_energia_da_analise_bruta(self):
        legacy = getattr(
            debug_clarity_module,
            "_legacy_power_summary_builder",
            None,
        )
        debug_clarity_module._legacy_power_summary_builder = lambda _snapshot: {
            "check_name": "H1",
            "check_id": "CHECK_001",
            "productive_text": "H1 NÃO CONFORME 21/28 máscaras",
            "waiting_empty_rearm": False,
            "waiting_new_board_after_empty": False,
            "cycle_rearm_waiting": False,
            "cycle_rearmed_waiting_new_board": False,
        }
        snapshot = {
            "logical_context": {
                "project_name": "CM-550-L",
                "check_id": "CHECK_001",
                "check_name": "H1",
            },
            "runtime_at_click": {
                "power_authority": {
                    "board_present": True,
                    "decision_allowed": False,
                    "energy": {
                        "energy_state": power_module.F3_POWER_STATE_OFF,
                        "expected_on_mask_count": 7,
                        "powered_votes": 0,
                        "off_votes": 7,
                    },
                },
                "last_auto_analysis": {
                    "ready": True,
                    "approved": False,
                    "project_name": "CM-550-L",
                    "check_id": "CHECK_001",
                    "active_mask_count": 28,
                    "matched_mask_count": 21,
                    "mask_results": [],
                },
            },
        }

        try:
            summary = power_module.construir_resumo_energia_debug_f3(snapshot)
            report = power_module._report_summary_power(snapshot)
        finally:
            if legacy is None:
                delattr(debug_clarity_module, "_legacy_power_summary_builder")
            else:
                debug_clarity_module._legacy_power_summary_builder = legacy

        self.assertTrue(summary["flow_blocked"])
        self.assertEqual(7, summary["expected_on_mask_count"])
        self.assertEqual(0, summary["powered_on_count"])
        self.assertEqual(7, summary["off_on_expected_count"])
        self.assertIn("GATE PRODUTIVO: BLOQUEADO", report)
        self.assertIn("ENERGIA DO DISPLAY: DESLIGADA", report)
        self.assertIn("ANÁLISE BRUTA H1: 21/28 máscaras", report)
        self.assertIn("SEM AUTORIDADE", report)


if __name__ == "__main__":
    unittest.main()
