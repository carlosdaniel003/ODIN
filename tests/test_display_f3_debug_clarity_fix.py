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


class DisplayF3DebugClarityFixTests(unittest.TestCase):
    def test_resumo_separa_h1_conforme_do_bloqueio_de_rearme(self):
        summary = construir_resumo_operacional_debug_f3(_snapshot())
        self.assertTrue(summary["fully_matched"])
        self.assertEqual(28, summary["matched_mask_count"])
        self.assertEqual(28, summary["active_mask_count"])
        self.assertTrue(summary["flow_blocked"])
        self.assertIn("H1 CONFORME 28/28", summary["productive_text"])
        self.assertIn("PLACA FORA DO SUPORTE", summary["flow_reason"])

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
