from __future__ import annotations

import inspect
import unittest

from src.platform.display_f3_final_rearm_guard import (
    F3_REARM_PHASE_WAIT_EMPTY,
    F3_REARM_PHASE_WAIT_NEW_BOARD,
    F3_SEGREGATION_TERMINAL_COLOR,
    _atualizar_rearme_terminal_f3,
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

    def test_segregacao_terminal_permanece_vermelha_ate_empty(self):
        result = estado_visivel_rearme_terminal_f3(
            {
                "kind": "check",
                "text": "PLACA NO SUPORTE • LIGADA • H1",
                "allow_auto": True,
            },
            F3_REARM_PHASE_WAIT_EMPTY,
            segregated=True,
        )
        self.assertFalse(result["allow_auto"])
        self.assertTrue(result["cycle_rearm_waiting"])
        self.assertEqual(F3_SEGREGATION_TERMINAL_COLOR, result["color"])
        self.assertIn("PLACA SEGREGADA", result["text"])
        self.assertEqual(
            "segregacao_aguardando_suporte_vazio",
            result["final_rearm_reason"],
        )

    def test_estado_apos_empty_exige_nova_placa(self):
        result = estado_visivel_rearme_terminal_f3(
            {"kind": "empty", "allow_auto": False},
            F3_REARM_PHASE_WAIT_NEW_BOARD,
        )
        self.assertTrue(result["cycle_rearmed_waiting_new_board"])
        self.assertFalse(result["cycle_rearm_waiting"])
        self.assertIn("AGUARDANDO NOVA PLACA", result["text"])

    def test_handoff_visual_usa_mesmo_latch_do_rearme_fisico(self):
        source = inspect.getsource(
            __import__(
                "src.platform.display_f3_final_rearm_guard",
                fromlist=["_atualizar_rearme_terminal_f3"],
            )._atualizar_rearme_terminal_f3
        )
        self.assertIn("show_waiting_new_plate", source)
        self.assertIn("release_terminal_rearm", source)
        self.assertIn("phase_before", source)

    def test_empty_confirmado_libera_freeze_ng_pelo_caminho_canonico(self):
        import src.platform.display_f3_final_rearm_guard as guard_module

        class _Frame:
            size = 1

        class _Repository:
            @staticmethod
            def obter_projeto_ativo():
                return "DISPLAY_TESTE"

        class _Runtime:
            @staticmethod
            def snapshot():
                return {
                    "checks": [],
                    "current_check": None,
                    "current_index": None,
                    "completed_ids": (),
                    "total": 1,
                    "ok": 0,
                    "ng": 1,
                    "last_result": "NG",
                }

        class _Window:
            def __init__(self):
                self._display_terminal_result_kind = "ng"
                self.waiting_calls = 0
                self.operational_states = []

            def show_waiting_new_plate(self, _snapshot):
                self.waiting_calls += 1

            def set_operational_reference_status(self, text, color):
                self.operational_states.append((text, color))

        class _RearmApp:
            def __init__(self):
                self._display_f3_waiting_empty_rearm = True
                self._display_f3_waiting_new_board_after_empty = False
                self._display_f3_ng_evidence_frozen = True
                self.camera_frame_atual = _Frame()
                self.display_project_repository = _Repository()
                self.display_check_runtime = _Runtime()
                self.display_f3_window = _Window()
                self.release_calls = 0

            @staticmethod
            def _display_auto_current_context():
                return {}

            def _liberar_evidencia_ng_display_f3(self):
                self.release_calls += 1
                self._display_f3_ng_evidence_frozen = False
                self.display_f3_window.show_waiting_new_plate(
                    self.display_check_runtime.snapshot()
                )

        app = _RearmApp()
        original_builder = guard_module.operational_module._build_operational_state

        def builder(owner, _frame, _project_name, _context):
            owner._display_f3_waiting_empty_rearm = False
            owner._display_f3_waiting_new_board_after_empty = True
            return {
                "kind": "empty",
                "text": "PLACA FORA DO SUPORTE",
                "allow_auto": False,
                "rearm_empty_confirmed": True,
            }

        try:
            guard_module.operational_module._build_operational_state = builder
            phase = _atualizar_rearme_terminal_f3(app)
        finally:
            guard_module.operational_module._build_operational_state = original_builder

        self.assertEqual(F3_REARM_PHASE_WAIT_NEW_BOARD, phase)
        self.assertEqual(1, app.release_calls)
        self.assertFalse(app._display_f3_ng_evidence_frozen)
        self.assertEqual(1, app.display_f3_window.waiting_calls)

    def test_instalador_reaplica_builder_dedicado_antes_do_guard_final(self):
        source = inspect.getsource(instalar_guard_rearme_terminal_final_display_f3)
        self.assertIn("instalar_rearme_fisico_final_display_f3()", source)
        self.assertIn("_process_display_auto_check", source)


if __name__ == "__main__":
    unittest.main()
