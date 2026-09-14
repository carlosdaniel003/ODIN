from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

import src.platform.display_auto_check_runtime as runtime_module
import src.platform.display_f3_h1_single_frame_probe as module
import src.platform.display_f3_live_runtime_fix as live_runtime_module
from src.platform.display_auto_check_analyzer import DisplayAutomaticCheckAnalyzer
from src.platform.display_f3_exact_check_template import F3_EXACT_TEMPLATE_SOURCE


class _App:
    def __init__(self):
        self._display_f3_live_probe_signature = None
        self._display_f3_live_probe_ok_frames = 0

    @staticmethod
    def _display_auto_is_reference_gate(context):
        return int((context or {}).get("current_index", -1)) == 0

    @staticmethod
    def _display_auto_is_transient_check(context):
        return str((context or {}).get("check_name") or "").upper() == "BLUE"


def _exact_analysis(*, failed_on: bool = False, off_mismatches: int = 0) -> dict:
    results = []
    for index in range(7):
        matched = not (failed_on and index == 3)
        results.append(
            {
                "mask_id": f"ON_{index}",
                "expected": "on",
                "classified": "on" if matched else "off",
                "matched": matched,
            }
        )
    for index in range(21):
        matched = index >= off_mismatches
        results.append(
            {
                "mask_id": f"OFF_{index}",
                "expected": "off",
                "classified": "off" if matched else "on",
                "matched": matched,
            }
        )
    return {
        "ready": True,
        "approved": all(bool(item["matched"]) for item in results),
        "reference_authority": F3_EXACT_TEMPLATE_SOURCE,
        "mask_results": results,
        "active_mask_count": len(results),
        "matched_mask_count": sum(1 for item in results if item["matched"]),
        "reason": "base",
    }


class DisplayF3H1SingleFrameProbeTests(unittest.TestCase):
    def test_h1_first_check_needs_two_positive_frames(self):
        result = module.frames_necessarios_sonda_positiva_f3(
            _App(),
            {"current_index": 0, "check_name": "H1"},
        )
        self.assertEqual(2, result)

    def test_blue_keeps_one_frame_because_it_is_transient(self):
        result = module.frames_necessarios_sonda_positiva_f3(
            _App(),
            {"current_index": 1, "check_name": "BLUE"},
        )
        self.assertEqual(1, result)

    def test_aux_superset_does_not_approve_h1_only_because_all_h1_on_masks_match(self):
        # Reproduz o padrão do debug real: os 7 segmentos ACESOS do H1 estão
        # acesos, porém 9 segmentos que H1 espera APAGADOS também estão acesos.
        analysis = _exact_analysis(failed_on=False, off_mismatches=9)
        evidence = module.avaliar_sonda_positiva_f3(
            _App(),
            {
                "project_name": "CM-550-L",
                "check_id": "CHECK_001",
                "check_name": "H1",
                "current_index": 0,
            },
            analysis,
        )

        self.assertEqual(7, evidence["on_total"])
        self.assertEqual(7, evidence["on_matched"])
        self.assertEqual(9, evidence["off_template_mismatches"])
        self.assertFalse(evidence["approved"])
        self.assertFalse(evidence["full_mask_conformity"])
        self.assertEqual(module.F3_POSITIVE_PROBE_MODE_FULL_MASKS, evidence["mode"])

    def test_h1_probe_never_overwrites_failed_full_analysis(self):
        app = _App()
        analysis = _exact_analysis(failed_on=False, off_mismatches=9)
        original_reason = analysis["reason"]

        stability = module.atualizar_estabilidade_sonda_positiva_f3(
            app,
            {
                "project_name": "CM-550-L",
                "check_id": "CHECK_001",
                "check_name": "H1",
                "current_index": 0,
            },
            analysis,
        )

        self.assertFalse(stability["confirm"])
        self.assertEqual(2, stability["required"])
        self.assertFalse(analysis["approved"])
        self.assertEqual(original_reason, analysis["reason"])
        self.assertTrue(analysis["positive_probe_requires_full_mask_conformity"])
        self.assertFalse(analysis["positive_probe_approved"])

    def test_h1_requires_two_consecutive_full_approvals(self):
        app = _App()
        context = {
            "project_name": "CM-550-L",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "current_index": 0,
        }
        first = module.atualizar_estabilidade_sonda_positiva_f3(
            app, context, _exact_analysis()
        )
        second = module.atualizar_estabilidade_sonda_positiva_f3(
            app, context, _exact_analysis()
        )
        self.assertFalse(first["confirm"])
        self.assertTrue(second["confirm"])
        self.assertEqual(2, second["required"])

    def test_blue_can_confirm_one_full_approval_frame(self):
        app = _App()
        result = module.atualizar_estabilidade_sonda_positiva_f3(
            app,
            {
                "project_name": "CM-550-L",
                "check_id": "CHECK_002",
                "check_name": "BLUE",
                "current_index": 1,
            },
            _exact_analysis(),
        )
        self.assertTrue(result["confirm"])
        self.assertEqual(1, result["required"])

    def test_semantic_analysis_stays_full_analysis(self):
        analysis = _exact_analysis(off_mismatches=1)
        analysis.pop("reference_authority", None)
        evidence = module.avaliar_sonda_positiva_f3(
            _App(),
            {"current_index": 0, "check_name": "H1"},
            analysis,
        )
        self.assertFalse(evidence["approved"])
        self.assertEqual("full_analysis", evidence["mode"])

    def test_runtime_ng_authority_is_restored_to_learned_semantic_analyzer(self):
        sentinel = object()
        with patch.object(runtime_module, "DisplayAutomaticCheckAnalyzer", sentinel), patch.object(
            live_runtime_module,
            "DisplayAutomaticCheckAnalyzer",
            sentinel,
        ):
            module.restaurar_analisador_semantico_runtime_f3()
            self.assertIs(
                DisplayAutomaticCheckAnalyzer,
                runtime_module.DisplayAutomaticCheckAnalyzer,
            )
            self.assertIs(
                DisplayAutomaticCheckAnalyzer,
                live_runtime_module.DisplayAutomaticCheckAnalyzer,
            )

    def test_module_has_no_f2_dependency(self):
        source = inspect.getsource(module)
        self.assertNotIn("src.platform.f2_", source)
        self.assertNotIn("F2Automatic", source)


if __name__ == "__main__":
    unittest.main()
