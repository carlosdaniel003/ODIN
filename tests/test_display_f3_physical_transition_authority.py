from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

import src.platform.display_f3_physical_transition_authority as authority


class _Runtime:
    def __init__(self, current_index=3):
        self.current_index = current_index

    def snapshot(self):
        checks = [
            {"id": "CHECK_001", "name": "H1", "state": "completed"},
            {"id": "CHECK_002", "name": "BLUE", "state": "completed"},
            {"id": "CHECK_004", "name": "USB", "state": "completed"},
            {"id": "CHECK_003", "name": "AUX", "state": "current"},
        ]
        return {
            "checks": checks,
            "current_index": self.current_index,
            "current_check": checks[self.current_index],
            "completed_ids": tuple(
                item["id"] for item in checks[: self.current_index]
            ),
            "total": 0,
        }


class _App:
    def __init__(self):
        self.display_check_runtime = _Runtime()
        self.camera_frame_atual = np.zeros((20, 20, 3), dtype=np.uint8)
        self.display_project_repository = object()
        self._display_f3_operational_state = {
            "kind": "unknown",
            "_display_f3_physical_decision_allowed": False,
            "physical_status_memory_override": True,
            "physical_status_memory_underlying_kind": "unknown",
            "physical_status_memory_check_id": "CHECK_003",
            "physical_status_memory_check_name": "AUX",
        }
        self._display_auto_last_analysis = {
            "ready": True,
            "approved": True,
            "project_name": "CM_500_L",
            "check_id": "CHECK_003",
        }
        self._registered = []

    def _display_auto_current_context(self):
        current = self.display_check_runtime.snapshot()["current_check"]
        return {
            "project_name": "CM_500_L",
            "check_id": current["id"],
            "check_name": current["name"],
            "current_index": self.display_check_runtime.current_index,
        }

    def registrar_resultado_check_display_f3(self, aprovado=True):
        self._registered.append(bool(aprovado))
        return {"event": "plate_ok"}

    def _reset_display_auto_stability(self, transition=False):
        self._reset_called = bool(not transition)

    def _display_auto_set_preview_status(self, text, color):
        self._last_status = (text, color)


class DisplayF3PhysicalTransitionAuthorityTests(unittest.TestCase):
    def test_memoria_visual_de_aux_nao_prova_que_placa_chegou_em_aux(self):
        app = _App()
        with patch.object(
            authority,
            "avaliar_transicao_fisica_checks_f3",
            return_value={
                "available": True,
                "current_preferred": False,
                "reason": "frame_ainda_nao_prefere_check_atual",
            },
        ):
            result = authority.avaliar_entrada_fisica_check_f3(app)

        self.assertFalse(result["confirmed"])
        self.assertEqual("CHECK_004", result["previous_check_id"])
        self.assertEqual("CHECK_003", result["current_check_id"])
        self.assertEqual(
            "frame_ainda_nao_prefere_check_atual",
            result["reason"],
        )

    def test_aux_so_confirma_quando_frame_prefere_aux_ao_usb(self):
        app = _App()
        with patch.object(
            authority,
            "avaliar_transicao_fisica_checks_f3",
            return_value={
                "available": True,
                "current_preferred": True,
                "reason": "frame_prefere_check_atual_ao_anterior",
            },
        ):
            result = authority.avaliar_entrada_fisica_check_f3(app)

        self.assertTrue(result["confirmed"])
        self.assertEqual("transicao_fisica_confirmada", result["reason"])

    def test_estado_fisico_exato_do_check_atual_tem_prioridade(self):
        app = _App()
        app._display_f3_operational_state = {
            "kind": "check",
            "check_id": "CHECK_003",
            "check_name": "AUX",
            "physical_matches_expected_check": True,
        }
        result = authority.avaliar_entrada_fisica_check_f3(app)
        self.assertTrue(result["confirmed"])
        self.assertEqual(
            "estado_fisico_exato_corresponde_ao_check",
            result["reason"],
        )

    def test_check_promovido_pelas_proprias_mascaras_nao_bypassa_transicao(self):
        app = _App()
        app._display_f3_operational_state = {
            "kind": "check",
            "check_id": "CHECK_003",
            "check_name": "AUX",
            "physical_matches_expected_check": True,
            "mask_confirmed_physical_state": True,
            "source": "f3_current_check_confirmed_by_live_masks",
        }
        with patch.object(
            authority,
            "avaliar_transicao_fisica_checks_f3",
            return_value={
                "available": True,
                "current_preferred": False,
                "reason": "frame_ainda_nao_prefere_check_atual",
            },
        ):
            result = authority.avaliar_entrada_fisica_check_f3(app)

        self.assertFalse(result["confirmed"])
        self.assertEqual(
            "frame_ainda_nao_prefere_check_atual",
            result["reason"],
        )

    def test_primeiro_check_nao_exige_transicao_anterior(self):
        app = _App()
        app.display_check_runtime = _Runtime(current_index=0)
        result = authority.avaliar_entrada_fisica_check_f3(app)
        self.assertTrue(result["confirmed"])
        self.assertEqual(
            "primeiro_check_sem_transicao_anterior",
            result["reason"],
        )

    def test_registro_final_e_vetado_quando_transicao_fisica_nao_confirmou(self):
        app = _App()
        with patch.object(
            authority,
            "avaliar_entrada_fisica_check_f3",
            return_value={
                "available": True,
                "confirmed": False,
                "reason": "frame_ainda_nao_prefere_check_atual",
                "previous_check_name": "USB",
                "current_check_name": "AUX",
            },
        ):
            authority._install_instance_result_guard(app)
            event = app.registrar_resultado_check_display_f3(True)

        self.assertEqual("physical_transition_blocked", event["event"])
        self.assertEqual([], app._registered)
        self.assertEqual(
            "physical_transition_not_confirmed",
            event["blocked_by"],
        )
        self.assertIn("USB", app._last_status[0])
        self.assertIn("AUX", app._last_status[0])

    def test_registro_final_passa_depois_da_transicao_confirmada(self):
        app = _App()
        with patch.object(
            authority,
            "avaliar_entrada_fisica_check_f3",
            return_value={
                "available": True,
                "confirmed": True,
                "reason": "transicao_fisica_confirmada",
                "previous_check_name": "USB",
                "current_check_name": "AUX",
            },
        ):
            authority._install_instance_result_guard(app)
            event = app.registrar_resultado_check_display_f3(True)

        self.assertEqual("plate_ok", event["event"])
        self.assertEqual([True], app._registered)


if __name__ == "__main__":
    unittest.main()
