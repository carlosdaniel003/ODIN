from __future__ import annotations

import unittest

from src.platform.display_f3_debug_clarity_fix import (
    SUMMARY_MARKER,
    _report_summary_block,
    aplicar_clareza_snapshot_debug_f3,
    construir_resumo_operacional_debug_f3,
)


class _App:
    def __init__(self):
        self._display_f3_waiting_empty_rearm = True
        self._display_f3_waiting_new_board_after_empty = False
        self._display_f3_rearm_empty_frames = 0
        self._display_f3_new_board_frames = 0


def _snapshot():
    return {
        "logical_context": {
            "project_name": "CM-550-L",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "current_index": 0,
        },
        "runtime_at_click": {
            "logical_context": {
                "project_name": "CM-550-L",
                "check_id": "CHECK_001",
                "check_name": "H1",
            },
            "operational_state": {
                "kind": "check",
                "text": "PLACA NO SUPORTE • LIGADA • DISPLAY EM H1",
                "allow_auto": True,
                "cycle_rearm_waiting": True,
            },
            "last_auto_analysis": {
                "ready": True,
                "approved": True,
                "project_name": "CM-550-L",
                "check_id": "CHECK_001",
                "check_name": "H1",
                "active_mask_count": 28,
                "matched_mask_count": 28,
            },
        },
        "visual_analysis": {
            "result_kind": "ambiguous",
            "status_text": "ANÁLISE VISUAL: referências muito próximas • identificando...",
            "informational_only": True,
            "affects_result": False,
        },
    }


def _neural_snapshot():
    return {
        "logical_context": {
            "project_name": "CM_500_L",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "current_index": 0,
        },
        "runtime_at_click": {
            "logical_context": {
                "project_name": "CM_500_L",
                "check_id": "CHECK_001",
                "check_name": "H1",
            },
            "operational_state": {
                "kind": "check",
                "text": "PLACA NO SUPORTE • LIGADA • ANALISANDO H1",
                "allow_auto": True,
            },
            "last_auto_analysis": {
                "ready": True,
                "approved": False,
                "reason": "h1_neural_incerto",
                "project_name": "CM_500_L",
                "check_id": "CHECK_001",
                "check_name": "H1",
                "active_mask_count": 4,
                "matched_mask_count": 0,
                "uncertain_mask_count": 4,
                "reference_authority": "f3_h1_neural_segment_detector",
                "neural_visual_authority": True,
                "conventional_visual_authority_used": False,
                "mask_results": [
                    {
                        "mask_id": "MASK_ON_1",
                        "expected": "on",
                        "classified": "uncertain",
                        "neural_certain": False,
                        "neural_probabilities": {"off": 0.40, "on": 0.60},
                    },
                    {
                        "mask_id": "MASK_ON_2",
                        "expected": "on",
                        "classified": "uncertain",
                        "neural_certain": False,
                        "neural_probabilities": {"off": 0.25, "on": 0.75},
                    },
                    {
                        "mask_id": "MASK_OFF_1",
                        "expected": "off",
                        "classified": "uncertain",
                        "neural_certain": False,
                        "neural_probabilities": {"off": 0.70, "on": 0.30},
                    },
                    {
                        "mask_id": "MASK_OFF_2",
                        "expected": "off",
                        "classified": "uncertain",
                        "neural_certain": False,
                        "neural_probabilities": {"off": 0.48, "on": 0.52},
                    },
                ],
                "neural_model": {
                    "ready": True,
                    "reason": "neural_inference_ready",
                    "model_path": "data/models/f3_neural/cm_500_l_segments.onnx",
                    "input_size": 48,
                    "on_min_on_probability": 0.80,
                    "off_max_on_probability": 0.20,
                    "load_count": 1,
                    "batch_size": 4,
                    "inference_count": 355,
                },
            },
        },
        "visual_analysis": {
            "result_kind": "ambiguous",
            "status_text": "ANÁLISE VISUAL: estado visual não identificado",
            "informational_only": True,
            "affects_result": False,
        },
    }


class DisplayF3DebugClarityFixTests(unittest.TestCase):
    def test_resumo_separa_h1_conforme_do_bloqueio_de_rearme(self):
        summary = construir_resumo_operacional_debug_f3(_snapshot())
        self.assertTrue(summary["fully_matched"])
        self.assertEqual(28, summary["matched_mask_count"])
        self.assertEqual(28, summary["active_mask_count"])
        self.assertTrue(summary["flow_blocked"])
        self.assertIn("H1 CONFORME 28/28", summary["productive_text"])
        self.assertIn("PLACA FORA DO SUPORTE", summary["flow_reason"])

    def test_resumo_neural_distingue_incerto_de_nao_conforme(self):
        summary = construir_resumo_operacional_debug_f3(
            _neural_snapshot()
        )
        self.assertFalse(summary["approved"])
        self.assertIn("INDETERMINADO", summary["productive_text"])

        neural = summary["neural"]
        self.assertTrue(neural["active"])
        self.assertEqual(4, neural["uncertain_count"])
        self.assertEqual(3, neural["raw_argmax_match_count"])
        self.assertEqual(
            ("MASK_OFF_2",),
            neural["raw_argmax_mismatch_ids"],
        )
        self.assertAlmostEqual(
            0.08,
            neural["diagnostic_separation_gap"],
            places=6,
        )
        self.assertAlmostEqual(
            0.56,
            neural["diagnostic_midpoint"],
            places=6,
        )

    def test_relatorio_neural_expoe_modelo_probabilidades_e_separacao(self):
        snapshot = _neural_snapshot()
        snapshot["operational_summary"] = (
            construir_resumo_operacional_debug_f3(snapshot)
        )
        block = _report_summary_block(snapshot)

        self.assertIn(
            "AUTORIDADE VISUAL PRODUTIVA: HÍBRIDA H1",
            block,
        )
        self.assertIn("inference_count=355", block)
        self.assertIn("OFF se P(ON)≤0.2000", block)
        self.assertIn("ON se P(ON)≥0.8000", block)
        self.assertIn("argmax=3/4 compatíveis", block)
        self.assertIn("divergentes=MASK_OFF_2", block)
        self.assertIn("gap=+0.0800", block)
        self.assertIn("midpoint=0.5600", block)
        self.assertIn(
            "AUTORIDADE CONVENCIONAL DE ON/OFF USADA: NÃO",
            block,
        )

    def test_relatorio_neural_identifica_blue_sem_rotulo_h1(self):
        snapshot = _neural_snapshot()
        snapshot["logical_context"].update(
            check_id="CHECK_002",
            check_name="BLUE",
            current_index=1,
        )
        snapshot["runtime_at_click"]["logical_context"].update(
            check_id="CHECK_002",
            check_name="BLUE",
        )
        analysis = snapshot["runtime_at_click"]["last_auto_analysis"]
        analysis.update(
            check_id="CHECK_002",
            check_name="BLUE",
            reason="blue_neural_incerto",
            neural_stage="HYBRID_ALL_CHECKS_V1",
            neural_check_scope="all_configured_checks_hybrid_v1",
        )
        snapshot["operational_summary"] = (
            construir_resumo_operacional_debug_f3(snapshot)
        )

        block = _report_summary_block(snapshot)

        self.assertIn(
            "AUTORIDADE VISUAL PRODUTIVA: HÍBRIDA BLUE",
            block,
        )
        self.assertNotIn(
            "AUTORIDADE VISUAL PRODUTIVA: HÍBRIDA H1",
            block,
        )

    def test_snapshot_corrige_atributo_real_do_rearme_e_clareia_preview(self):
        snapshot = aplicar_clareza_snapshot_debug_f3(_snapshot(), _App())
        runtime = snapshot["runtime_at_click"]
        self.assertTrue(runtime["waiting_empty_rearm"])
        self.assertFalse(runtime["waiting_new_board_after_empty"])
        text = snapshot["visual_analysis"]["status_text"]
        self.assertIn("CHECK PRODUTIVO: H1 CONFORME 28/28", text)
        self.assertIn("FLUXO BLOQUEADO", text)
        self.assertIn("PLACA FORA DO SUPORTE", text)

    def test_relatorio_explica_que_referencias_proximas_sao_informativas(self):
        snapshot = aplicar_clareza_snapshot_debug_f3(_snapshot(), _App())
        block = _report_summary_block(snapshot)
        self.assertIn(SUMMARY_MARKER, block)
        self.assertIn("DECISÃO PRODUTIVA: H1 CONFORME 28/28 máscaras", block)
        self.assertIn("FLUXO: BLOQUEADO", block)
        self.assertIn("ANÁLISE VISUAL: SOMENTE INFORMATIVA", block)
        self.assertIn("referências muito próximas", block)


if __name__ == "__main__":
    unittest.main()
