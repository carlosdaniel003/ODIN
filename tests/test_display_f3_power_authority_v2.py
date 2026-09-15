from __future__ import annotations

import unittest
from unittest.mock import patch

import src.platform.display_f3_power_authority as legacy_power
import src.platform.display_f3_power_authority_v2 as power_v2
import src.platform.display_f3_runtime_contract_fix as contract_module


class _FakeApp:
    _display_f3_waiting_empty_rearm = False
    _display_f3_waiting_new_board_after_empty = False


def _row(mask_id: str, *, classified: str, matched: bool, confidence: float = 0.99):
    return {
        "mask_id": mask_id,
        "expected": "on",
        "classified": classified,
        "matched": matched,
        "confidence": confidence,
        "template_similarity": 0.99 if matched else 0.60,
    }


class DisplayF3UnifiedPowerAuthorityTests(unittest.TestCase):
    def test_h1_7_on_confirmados_provam_energia_mesmo_com_secundario_em_empate(self):
        analysis = {
            "ready": True,
            "approved": True,
            "active_mask_count": 28,
            "matched_mask_count": 28,
            "mask_results": [
                _row(mask_id, classified="on", matched=True)
                for mask_id in (
                    "MASK_008",
                    "MASK_009",
                    "MASK_011",
                    "MASK_013",
                    "MASK_014",
                    "MASK_020",
                    "MASK_021",
                )
            ],
        }
        secondary = {
            str(item["mask_id"]): {"winner": "tie"}
            for item in analysis["mask_results"]
        }

        result = power_v2.resumir_energia_por_analise_bruta_f3(analysis, secondary)

        self.assertEqual(legacy_power.F3_POWER_STATE_POWERED, result["energy_state"])
        self.assertTrue(result["powered_confirmed"])
        self.assertEqual(7, result["powered_votes"])
        self.assertEqual(0, result["off_votes"])
        self.assertEqual(power_v2.F3_POWER_PRIMARY_SOURCE, result["primary_authority"])
        self.assertFalse(result["legacy_power_evidence_used"])

    def test_todos_os_on_esperados_classificados_off_confirmam_display_desligado(self):
        analysis = {
            "ready": True,
            "approved": False,
            "active_mask_count": 28,
            "matched_mask_count": 21,
            "mask_results": [
                _row(mask_id, classified="off", matched=False)
                for mask_id in (
                    "MASK_008",
                    "MASK_009",
                    "MASK_011",
                    "MASK_013",
                    "MASK_014",
                    "MASK_020",
                    "MASK_021",
                )
            ],
        }

        result = power_v2.resumir_energia_por_analise_bruta_f3(analysis, {})

        self.assertEqual(legacy_power.F3_POWER_STATE_OFF, result["energy_state"])
        self.assertTrue(result["off_confirmed"])
        self.assertFalse(result["powered_confirmed"])
        self.assertEqual(7, result["off_votes"])

    def test_secundario_full_pixel_pode_vetar_um_on_contraditorio_sem_criar_ng(self):
        analysis = {
            "ready": True,
            "approved": True,
            "active_mask_count": 1,
            "matched_mask_count": 1,
            "mask_results": [
                _row("MASK_008", classified="on", matched=True),
            ],
        }
        secondary = {
            "MASK_008": {
                "winner": "off",
                "source": power_v2.F3_POWER_SECONDARY_SOURCE,
            }
        }

        result = power_v2.resumir_energia_por_analise_bruta_f3(analysis, secondary)

        self.assertEqual(legacy_power.F3_POWER_STATE_UNCONFIRMED, result["energy_state"])
        self.assertFalse(result["powered_confirmed"])
        self.assertFalse(result["off_confirmed"])
        self.assertEqual("tie", result["details"][0]["winner"])

    def test_estado_final_remove_evidencias_legadas_e_publica_uma_unica_fonte(self):
        app = _FakeApp()
        state = {
            "kind": "check",
            "allow_auto": True,
            "reference_scores": {
                "off": 0.7539,
                "empty": 0.3969,
                "check:CHECK_001": 0.7591,
            },
            "powered_mask_evidence": {"strong": True},
            "power_mask_evidence_v2": {"energy_state": "unconfirmed"},
        }
        evidence = {
            "available": True,
            "source": power_v2.F3_UNIFIED_POWER_SOURCE,
            "energy_state": legacy_power.F3_POWER_STATE_POWERED,
            "powered_confirmed": True,
            "off_confirmed": False,
            "expected_on_mask_count": 7,
            "powered_votes": 7,
            "off_votes": 0,
            "tie_votes": 0,
            "details": [],
        }

        with patch.object(
            power_v2,
            "avaliar_evidencia_energia_unificada_display_f3",
            return_value=evidence,
        ):
            result = power_v2.aplicar_autoridade_energia_unificada_ao_estado_f3(
                app,
                state,
                frame=object(),
                project_name="CM-550-L",
                context={"check_id": "CHECK_001", "check_name": "H1"},
            )

        self.assertNotIn("powered_mask_evidence", result)
        self.assertNotIn("power_mask_evidence_v2", result)
        self.assertEqual(evidence, result["power_evidence"])
        self.assertEqual(power_v2.F3_UNIFIED_POWER_SOURCE, result["power_authority_source"])
        self.assertTrue(result["allow_auto"])
        self.assertTrue(result[contract_module.F3_DECISION_ALLOWED_KEY])

    def test_protecao_secundaria_reutiliza_banda_ambigua_do_gabarito_exato(self):
        # Regressão estrutural: não queremos outro threshold de margem criado
        # apenas para o gate de energia.
        import inspect

        source = inspect.getsource(power_v2._secondary_full_pixel_details)
        self.assertIn("F3_EXACT_MASK_AMBIGUOUS_BAND", source)
        self.assertIn("comparar_mascara_com_gabarito_f3", source)

    def test_debug_por_check_usa_analisador_fresco_e_proveniencia(self):
        import inspect

        source = inspect.getsource(power_v2._run_check_analyses_with_provenance)
        self.assertIn("F3CheckPhotoLearningAnalyzer(repository)", source)
        self.assertIn("reference_provenance", source)
        self.assertIn("single_canonical_analysis", source)


if __name__ == "__main__":
    unittest.main()
