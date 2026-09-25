from __future__ import annotations

import inspect
import unittest

import src.platform.display_f3_runtime_contract_fix as contract


class DisplayF3RuntimeContractFixTests(unittest.TestCase):
    @staticmethod
    def _approved_positive_analysis(
        check_id: str = "CHECK_005",
        check_name: str = "HDMI",
    ) -> dict:
        return {
            "ready": True,
            "approved": True,
            "project_name": "TESTE",
            "check_id": check_id,
            "check_name": check_name,
            "positive_on_matched_count": 1,
            "mask_results": [
                {
                    "mask_id": "MASK_001",
                    "expected": "on",
                    "classified": "on",
                    "matched": True,
                },
                {
                    "mask_id": "MASK_002",
                    "expected": "off",
                    "classified": "off",
                    "matched": True,
                },
            ],
        }

    def test_blocked_physical_state_still_releases_mask_analysis(self):
        for kind in ("unknown", "powered", "off", "empty", "unavailable", "check"):
            with self.subTest(kind=kind):
                state = contract.preparar_estado_para_mascaras_ativas_f3(
                    {"kind": kind, "allow_auto": False}
                )
                self.assertTrue(state["allow_auto"])
                self.assertTrue(state[contract.F3_MASK_LIVE_KEY])
                self.assertFalse(state[contract.F3_DECISION_ALLOWED_KEY])

                restored = contract.restaurar_autoridade_fisica_f3(state)
                self.assertFalse(restored["allow_auto"])
                self.assertTrue(restored[contract.F3_MASK_LIVE_KEY])

    def test_source_never_publishes_masks_as_inactive(self):
        source = inspect.getsource(contract)
        self.assertNotIn("MÁSCARAS • INATIVAS", source)
        self.assertIn("máscaras em leitura", source)

    def test_live_mask_confirmation_can_resolve_unknown_current_check(self):
        state = contract._state_from_mask_confirmation(
            {"kind": "unknown", "allow_auto": False},
            {
                "project_name": "DISPLAY A",
                "check_id": "h1",
                "check_name": "H1",
            },
        )
        self.assertEqual("check", state["kind"])
        self.assertEqual("h1", state["check_id"])
        self.assertTrue(state["allow_auto"])
        self.assertTrue(state[contract.F3_DECISION_ALLOWED_KEY])
        self.assertIn("DISPLAY EM H1", state["text"])

    def test_powered_cycle_can_be_resolved_by_current_check_masks(self):
        self.assertTrue(
            contract._state_accepts_mask_confirmation(
                {
                    "kind": "powered",
                    "allow_auto": True,
                    contract.F3_DECISION_ALLOWED_KEY: False,
                }
            )
        )
        state = contract._state_from_mask_confirmation(
            {
                "kind": "powered",
                "allow_auto": True,
                contract.F3_DECISION_ALLOWED_KEY: False,
            },
            {
                "project_name": "TESTE",
                "check_id": "CHECK_004",
                "check_name": "USB",
            },
        )
        self.assertEqual("check", state["kind"])
        self.assertEqual("CHECK_004", state["check_id"])
        self.assertTrue(state[contract.F3_DECISION_ALLOWED_KEY])
        self.assertIn("DISPLAY EM USB", state["text"])

    def test_false_off_requires_positive_on_evidence(self):
        state = {"kind": "off", "allow_auto": False}
        self.assertFalse(contract._state_accepts_mask_confirmation(state))

        approved_all_off = {
            "ready": True,
            "approved": True,
            "positive_on_matched_count": 0,
            "mask_results": [
                {
                    "mask_id": "MASK_001",
                    "expected": "off",
                    "classified": "off",
                    "matched": True,
                }
            ],
        }
        self.assertFalse(
            contract._state_accepts_mask_confirmation(state, approved_all_off)
        )
        self.assertTrue(
            contract._state_accepts_mask_confirmation(
                state,
                self._approved_positive_analysis(),
            )
        )

    def test_future_check_can_reconcile_false_off_without_name_specific_rule(self):
        analysis = self._approved_positive_analysis()
        self.assertTrue(
            contract._state_accepts_mask_confirmation(
                {"kind": "off", "allow_auto": False},
                analysis,
            )
        )
        state = contract._state_from_mask_confirmation(
            {"kind": "off", "allow_auto": False},
            {
                "project_name": "TESTE",
                "check_id": "CHECK_005",
                "check_name": "HDMI",
            },
        )
        self.assertEqual("check", state["kind"])
        self.assertEqual("CHECK_005", state["check_id"])
        self.assertEqual("check:CHECK_005", state["physical_state_key"])
        self.assertTrue(state["powered_board_confirmed"])
        self.assertIn("DISPLAY EM HDMI", state["text"])

    def test_empty_unavailable_and_other_check_remain_absolute(self):
        analysis = self._approved_positive_analysis()
        for kind in ("empty", "unavailable", "check"):
            with self.subTest(kind=kind):
                self.assertFalse(
                    contract._state_accepts_mask_confirmation(
                        {"kind": kind},
                        analysis,
                    )
                )

    def test_positive_on_evidence_can_be_derived_from_mask_results(self):
        analysis = self._approved_positive_analysis()
        analysis.pop("positive_on_matched_count")
        self.assertTrue(contract._analysis_has_positive_on_evidence(analysis))

    def test_powered_preview_explains_that_board_is_on_while_waiting_check(self):
        text = contract._blocked_preview_text(
            {"kind": "powered"},
            {"check_name": "USB"},
        )
        self.assertIn("placa ligada", text)
        self.assertIn("aguardando USB", text)

    def test_runtime_reuses_same_generic_rule_before_reset_and_on_register(self):
        source = inspect.getsource(contract._install_masks_always_live_gate)
        self.assertGreaterEqual(
            source.count("_state_accepts_mask_confirmation(state, analysis)"),
            3,
        )
        self.assertIn("_display_f3_mask_confirmed_signature", source)
        self.assertIn("physical_kind_before_mask_confirmation", source)
        self.assertNotIn('check_name == "USB"', source)
        self.assertNotIn('check_name == "AUX"', source)

    def test_configuration_contract_keeps_on_change_and_explicit_arguments(self):
        contract._install_configuration_constructor_contract()

        from src.platform.display_project_config import DisplayProjectConfigWindow
        from src.platform.display_visual_reference_status import (
            DisplayProjectConfigPresenceWindow,
        )

        base_parameters = inspect.signature(DisplayProjectConfigWindow.__init__).parameters
        presence_parameters = inspect.signature(
            DisplayProjectConfigPresenceWindow.__init__
        ).parameters

        for parameter in (
            "root",
            "repository",
            "frame_provider",
            "heavy_executor",
            "on_change",
            "on_close",
        ):
            self.assertIn(parameter, base_parameters)
            self.assertIn(parameter, presence_parameters)

    def test_contract_is_installed_after_final_performance(self):
        from src.platform import display_f3_fast_expected_gate as fast_gate

        source = inspect.getsource(fast_gate.instalar_gate_rapido_check_esperado_display_f3)
        self.assertLess(
            source.index("instalar_performance_final_display_f3()"),
            source.index("instalar_contrato_runtime_display_f3()"),
        )

    def test_contract_has_no_f2_runtime_dependency(self):
        source = inspect.getsource(contract)
        self.assertNotIn("src.platform.f2_", source)
        self.assertNotIn("F2Automatic", source)
        self.assertNotIn("operacao_engine", source)


if __name__ == "__main__":
    unittest.main()
