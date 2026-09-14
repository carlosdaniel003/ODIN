from __future__ import annotations

import inspect
import unittest

from src.platform.display_f3_final_rearm_guard import (
    F3_REARM_PHASE_WAIT_EMPTY,
    F3_REARM_PHASE_WAIT_NEW_BOARD,
    estado_visivel_rearme_terminal_f3,
    fase_rearme_terminal_f3,
    instalar_guard_rearme_terminal_final_display_f3,
)


class _App:
    def __init__(self, waiting_empty=False, waiting_new=False):
        self._display_f3_waiting_empty_rearm = waiting_empty
        self._display_f3_waiting_new_board_after_empty = waiting_new


class DisplayF3FinalRearmGuardTests(unittest.TestCase):
    def test_fase_rearme_prioriza_espera_por_suporte_vazio(self):
        app = _App(waiting_empty=True, waiting_new=True)
        self.assertEqual(F3_REARM_PHASE_WAIT_EMPTY, fase_rearme_terminal_f3(app))

    def test_fase_rearme_identifica_espera_por_nova_placa(self):
        app = _App(waiting_new=True)
        self.assertEqual(F3_REARM_PHASE_WAIT_NEW_BOARD, fase_rearme_terminal_f3(app))

    def test_estado_bloqueado_nao_pode_continuar_exibindo_h1_como_livre(self):
        state = {
            "kind": "check",
            "text": "PLACA NO SUPORTE • LIGADA • DISPLAY EM H1",
            "allow_auto": True,
            "_display_f3_physical_decision_allowed": True,
        }
        result = estado_visivel_rearme_terminal_f3(
            state,
            F3_REARM_PHASE_WAIT_EMPTY,
        )

        self.assertEqual("unknown", result["kind"])
        self.assertFalse(result["allow_auto"])
        self.assertFalse(result["_display_f3_physical_decision_allowed"])
        self.assertTrue(result["cycle_rearm_waiting"])
        self.assertIn("RETIRE A PLACA", result["text"])
        self.assertEqual(
            "PLACA NO SUPORTE • LIGADA • DISPLAY EM H1",
            result["rearm_underlying_text"],
        )

    def test_estado_apos_empty_exige_nova_placa(self):
        result = estado_visivel_rearme_terminal_f3(
            {"kind": "empty", "allow_auto": False},
            F3_REARM_PHASE_WAIT_NEW_BOARD,
        )
        self.assertTrue(result["cycle_rearmed_waiting_new_board"])
        self.assertFalse(result["cycle_rearm_waiting"])
        self.assertIn("AGUARDANDO NOVA PLACA", result["text"])

    def test_instalador_reaplica_builder_dedicado_antes_do_guard_final(self):
        source = inspect.getsource(instalar_guard_rearme_terminal_final_display_f3)
        self.assertIn("instalar_rearme_fisico_final_display_f3()", source)
        self.assertIn("_process_display_auto_check", source)


if __name__ == "__main__":
    unittest.main()
