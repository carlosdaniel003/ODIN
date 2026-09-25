from __future__ import annotations

import inspect
import unittest

import src.platform.display_f3_fast_expected_gate as fast_gate_module
from src.platform.display_f3_fast_expected_gate import (
    F3_FAST_EXPECTED_GATE_SOURCE,
    contexto_exige_captura_rapida_f3,
    liberar_gate_fisico_para_check_rapido_f3,
)
from src.platform.desktop_production_app import DesktopProductionApp


class DisplayF3FastExpectedGateTests(unittest.TestCase):
    def test_h1_is_released_on_first_positive_check_candidate_without_waiting_debounce(self):
        context = {
            "project_name": "DISPLAY A",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "current_index": 0,
        }
        state = {
            "kind": "unknown",
            "text": "IDENTIFICANDO...",
            "allow_auto": False,
            "physical_transition_pending": True,
            "pending_physical_state_key": "check:CHECK_001",
        }

        result = liberar_gate_fisico_para_check_rapido_f3(state, context)

        self.assertTrue(result["allow_auto"])
        self.assertTrue(result["fast_expected_check_gate"])
        self.assertEqual(
            F3_FAST_EXPECTED_GATE_SOURCE,
            result["fast_expected_check_source"],
        )
        self.assertEqual("unknown", result["kind"])

    def test_board_off_is_absolute_and_never_releases_h1_fast_path(self):
        context = {
            "project_name": "DISPLAY A",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "current_index": 0,
        }
        state = {
            "kind": "off",
            "text": "PLACA NO SUPORTE • DESLIGADA • LEDS DESLIGADOS",
            "allow_auto": False,
            "physical_state_key": "off",
        }

        result = liberar_gate_fisico_para_check_rapido_f3(state, context)

        self.assertFalse(result["allow_auto"])
        self.assertNotIn("fast_expected_check_gate", result)

    def test_pending_off_debounce_is_absolute_and_never_releases_h1(self):
        context = {
            "project_name": "DISPLAY A",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "current_index": 0,
        }
        state = {
            "kind": "unknown",
            "text": "IDENTIFICANDO...",
            "allow_auto": False,
            "physical_transition_pending": True,
            "pending_physical_state_key": "off",
        }

        result = liberar_gate_fisico_para_check_rapido_f3(state, context)

        self.assertFalse(result["allow_auto"])
        self.assertNotIn("fast_expected_check_gate", result)

    def test_generic_unknown_without_positive_power_evidence_never_releases_h1(self):
        context = {
            "project_name": "DISPLAY A",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "current_index": 0,
        }
        state = {
            "kind": "unknown",
            "text": "IDENTIFICANDO...",
            "allow_auto": False,
        }

        result = liberar_gate_fisico_para_check_rapido_f3(state, context)

        self.assertFalse(result["allow_auto"])
        self.assertNotIn("fast_expected_check_gate", result)

    def test_empty_support_is_absolute_and_never_releases_blue(self):
        context = {
            "project_name": "DISPLAY A",
            "check_id": "CHECK_002",
            "check_name": "BLUE",
            "current_index": 1,
        }
        state = {
            "kind": "empty",
            "text": "PLACA FORA DO SUPORTE",
            "allow_auto": False,
        }

        result = liberar_gate_fisico_para_check_rapido_f3(state, context)

        self.assertFalse(result["allow_auto"])
        self.assertNotIn("fast_expected_check_gate", result)

    def test_blue_can_be_analyzed_on_single_powered_frame_even_if_global_state_says_usb(self):
        context = {
            "project_name": "DISPLAY A",
            "check_id": "CHECK_002",
            "check_name": "BLUE",
            "current_index": 1,
        }
        state = {
            "kind": "check",
            "check_id": "CHECK_003",
            "check_name": "USB",
            "text": "PLACA NO SUPORTE • LIGADA • DISPLAY EM USB",
            "allow_auto": False,
        }

        result = liberar_gate_fisico_para_check_rapido_f3(state, context)

        self.assertTrue(contexto_exige_captura_rapida_f3(context))
        self.assertTrue(result["allow_auto"])
        self.assertEqual("CHECK_003", result["check_id"])
        self.assertEqual("USB", result["check_name"])
        self.assertTrue(result["fast_expected_check_gate"])

    def test_usb_does_not_bypass_wrong_physical_state(self):
        context = {
            "project_name": "DISPLAY A",
            "check_id": "CHECK_003",
            "check_name": "USB",
            "current_index": 2,
        }
        state = {
            "kind": "check",
            "check_id": "CHECK_002",
            "check_name": "BLUE",
            "allow_auto": False,
        }

        result = liberar_gate_fisico_para_check_rapido_f3(state, context)

        self.assertFalse(contexto_exige_captura_rapida_f3(context))
        self.assertFalse(result["allow_auto"])
        self.assertNotIn("fast_expected_check_gate", result)

    def test_already_matching_physical_state_is_not_rewritten(self):
        context = {
            "project_name": "DISPLAY A",
            "check_id": "CHECK_002",
            "check_name": "BLUE",
            "current_index": 1,
        }
        state = {
            "kind": "check",
            "check_id": "CHECK_002",
            "check_name": "BLUE",
            "allow_auto": True,
            "score": 0.98,
        }

        result = liberar_gate_fisico_para_check_rapido_f3(state, context)

        self.assertTrue(result["allow_auto"])
        self.assertEqual(0.98, result["score"])
        self.assertNotIn("fast_expected_check_gate", result)

    def test_fast_gate_installs_after_exact_template(self):
        source = inspect.getsource(DesktopProductionApp.__init__)
        exact_position = source.index("instalar_gabarito_exato_checks_display_f3()")
        fast_position = source.index("instalar_gate_rapido_check_esperado_display_f3()")
        super_position = source.index("super().__init__(root)")

        self.assertLess(exact_position, fast_position)
        self.assertLess(fast_position, super_position)

    def test_module_has_no_f2_runtime_dependency(self):
        source = inspect.getsource(fast_gate_module)
        for forbidden in (
            "src.platform.f2_",
            "F2Automatic",
            "operacao_engine",
            "linux_f2_fixed_resolution",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
