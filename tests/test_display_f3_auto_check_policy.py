from __future__ import annotations

import unittest

from src.platform.display_auto_check_policy import (
    DISPLAY_AUTO_DECISION_NG,
    DISPLAY_AUTO_DECISION_OK,
    DISPLAY_AUTO_DECISION_SEARCHING,
    decidir_analise_display_f3,
)


def _result(mask_id, expected, classified, matched, confidence=0.95):
    return {
        "mask_id": mask_id,
        "expected": expected,
        "classified": classified,
        "matched": bool(matched),
        "confidence": float(confidence),
    }


def _analysis(*results):
    items = list(results)
    return {
        "ready": True,
        "approved": all(item["matched"] for item in items),
        "mask_results": items,
        "active_mask_count": len(items),
        "matched_mask_count": sum(1 for item in items if item["matched"]),
    }


class DisplayF3AutoCheckPolicyTests(unittest.TestCase):
    def test_h1_mismatch_never_generates_automatic_ng(self):
        decision = decidir_analise_display_f3(
            _analysis(_result("A", "on", "off", False)),
            reference_gate=True,
        )
        self.assertEqual(DISPLAY_AUTO_DECISION_SEARCHING, decision["decision"])
        self.assertEqual(
            "aguardando_evidencia_placa_ligada",
            decision["reason"],
        )

    def test_h1_advances_when_reference_is_confirmed(self):
        decision = decidir_analise_display_f3(
            _analysis(
                _result("A", "on", "on", True),
                _result("B", "off", "off", True),
            ),
            reference_gate=True,
        )
        self.assertEqual(DISPLAY_AUTO_DECISION_OK, decision["decision"])

    def test_expected_on_that_looks_off_keeps_searching_without_power_evidence(self):
        decision = decidir_analise_display_f3(
            _analysis(
                _result("A", "on", "off", False),
                _result("B", "off", "off", True),
            )
        )
        self.assertEqual(DISPLAY_AUTO_DECISION_SEARCHING, decision["decision"])
        self.assertFalse(decision["board_powered"])
        self.assertEqual("aguardando_evidencia_placa_ligada", decision["reason"])

    def test_expected_on_that_looks_off_is_ng_when_another_segment_is_on(self):
        decision = decidir_analise_display_f3(
            _analysis(
                _result("A", "on", "off", False),
                _result("B", "on", "on", True),
            )
        )
        self.assertEqual(DISPLAY_AUTO_DECISION_NG, decision["decision"])
        self.assertTrue(decision["board_powered"])
        self.assertEqual("apagado_com_placa_ligada", decision["reason"])

    def test_low_light_on_expected_on_is_confirmed_ng_after_h1(self):
        decision = decidir_analise_display_f3(
            _analysis(_result("A", "on", "low_light", False))
        )
        self.assertEqual(DISPLAY_AUTO_DECISION_NG, decision["decision"])
        self.assertEqual("pouca_luz_confirmada", decision["reason"])

    def test_low_light_on_expected_off_is_confirmed_ng_after_h1(self):
        decision = decidir_analise_display_f3(
            _analysis(_result("A", "off", "low_light", False))
        )
        self.assertEqual(DISPLAY_AUTO_DECISION_NG, decision["decision"])
        self.assertEqual("pouca_luz_confirmada", decision["reason"])

    def test_on_when_expected_off_is_direct_ng(self):
        decision = decidir_analise_display_f3(
            _analysis(_result("A", "off", "on", False))
        )
        self.assertEqual(DISPLAY_AUTO_DECISION_NG, decision["decision"])
        self.assertEqual("aceso_quando_deveria_apagado", decision["reason"])

    def test_below_classifier_minimum_confidence_keeps_searching(self):
        decision = decidir_analise_display_f3(
            _analysis(
                _result("A", "on", "off", False, confidence=0.49),
                _result("B", "on", "on", True, confidence=0.95),
            )
        )
        self.assertEqual(DISPLAY_AUTO_DECISION_SEARCHING, decision["decision"])
        self.assertEqual("classificacao_incerta", decision["reason"])


if __name__ == "__main__":
    unittest.main()
