from __future__ import annotations

import inspect
import unittest

import src.platform.display_f3_powered_cycle_latch as module
import src.platform.display_f3_runtime_contract_fix as contract_module


class _App:
    def __init__(self):
        self.display_f3_ativo = True
        self.display_f3_result_after_id = None
        self._display_f3_waiting_empty_rearm = False
        self._display_f3_waiting_new_board_after_empty = False
        self.current = {
            "project_name": "TESTE",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "current_index": 0,
        }
        self._display_f3_operational_state = {
            "kind": "off",
            "text": "PLACA NO SUPORTE • DESLIGADA",
            "allow_auto": False,
            "physical_state_key": "off",
            contract_module.F3_DECISION_ALLOWED_KEY: False,
        }

    def _display_auto_current_context(self):
        return dict(self.current)

    def _display_auto_is_reference_gate(self, context):
        return int((context or {}).get("current_index", -1)) == 0


class DisplayF3PoweredCycleLatchTests(unittest.TestCase):
    @staticmethod
    def _h1_analysis(matched=28, active=28):
        return {
            "ready": True,
            "approved": True,
            "exact_all_masks_approved": matched >= active,
            "project_name": "TESTE",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "matched_mask_count": matched,
            "active_mask_count": active,
            "mask_results": [
                {
                    "mask_id": "MASK_008",
                    "expected": "on",
                    "classified": "on",
                    "matched": True,
                },
                {
                    "mask_id": "MASK_001",
                    "expected": "off",
                    "classified": "off",
                    "matched": True,
                },
            ],
        }

    def test_h1_28_de_28_libera_registro_mesmo_com_falso_off_global(self):
        app = _App()
        context = app._display_auto_current_context()

        used = module.preparar_gate_decisao_sonda_exata_f3(
            app,
            context,
            self._h1_analysis(),
            {"confirm": True, "frames": 1, "required": 1},
        )

        self.assertTrue(used)
        state = app._display_f3_operational_state
        self.assertEqual("check", state["kind"])
        self.assertEqual("CHECK_001", state["check_id"])
        self.assertTrue(state["allow_auto"])
        self.assertTrue(state[contract_module.F3_DECISION_ALLOWED_KEY])
        self.assertTrue(state["exact_probe_decision_bridge"])
        self.assertEqual("off", state["physical_reference_kind_before_bridge"])

    def test_runtime_canonico_desativa_bridge_de_decisao_da_sonda(self):
        app = _App()
        app._display_f3_runtime_authorities_installed = True
        original_state = dict(app._display_f3_operational_state)

        used = module.preparar_gate_decisao_sonda_exata_f3(
            app,
            app._display_auto_current_context(),
            self._h1_analysis(),
            {"confirm": True, "frames": 1, "required": 1},
        )

        self.assertFalse(used)
        self.assertEqual(original_state, app._display_f3_operational_state)
        self.assertEqual(
            "autoridade_canonica_runtime_ativa",
            app._display_f3_exact_decision_bridge_last["blocked_reason"],
        )

    def test_sonda_parcial_nao_libera_registro(self):
        app = _App()
        context = app._display_auto_current_context()

        used = module.preparar_gate_decisao_sonda_exata_f3(
            app,
            context,
            self._h1_analysis(matched=27, active=28),
            {"confirm": True, "frames": 1, "required": 1},
        )

        self.assertFalse(used)
        self.assertEqual("off", app._display_f3_operational_state["kind"])
        self.assertFalse(
            app._display_f3_operational_state[contract_module.F3_DECISION_ALLOWED_KEY]
        )
        self.assertEqual(
            "check_nao_confirmado_integralmente",
            app._display_f3_exact_decision_bridge_last["blocked_reason"],
        )

    def test_empty_e_rearme_continuam_absolutos(self):
        for setup in ("empty", "rearm"):
            app = _App()
            if setup == "empty":
                app._display_f3_operational_state = {
                    "kind": "empty",
                    "allow_auto": False,
                    contract_module.F3_DECISION_ALLOWED_KEY: False,
                }
            else:
                app._display_f3_waiting_empty_rearm = True

            used = module.preparar_gate_decisao_sonda_exata_f3(
                app,
                app._display_auto_current_context(),
                self._h1_analysis(),
                {"confirm": True},
            )
            self.assertFalse(used)

    def test_apos_h1_falso_off_vira_ligada_aguardando_blue_sem_liberar_decisao(self):
        app = _App()
        module._mark_powered_cycle_latch(app, app._display_auto_current_context())
        app.current = {
            "project_name": "TESTE",
            "check_id": "CHECK_002",
            "check_name": "BLUE",
            "current_index": 1,
        }

        result = module.aplicar_latch_ciclo_ligado_ao_estado_fisico_f3(
            app,
            {
                "kind": "off",
                "allow_auto": True,
                "physical_state_key": "off",
                contract_module.F3_DECISION_ALLOWED_KEY: False,
            },
            "TESTE",
            app._display_auto_current_context(),
        )

        self.assertEqual("powered", result["kind"])
        self.assertIn("LIGADA", result["text"])
        self.assertIn("AGUARDANDO BLUE", result["text"])
        self.assertTrue(result["allow_auto"], "máscaras devem continuar vivas")
        self.assertFalse(
            result[contract_module.F3_DECISION_ALLOWED_KEY],
            "o latch não pode aprovar BLUE por memória do H1",
        )
        self.assertTrue(result["powered_cycle_latched"])

    def test_suporte_vazio_limpa_latch_do_ciclo(self):
        app = _App()
        module._mark_powered_cycle_latch(app, app._display_auto_current_context())

        result = module.aplicar_latch_ciclo_ligado_ao_estado_fisico_f3(
            app,
            {"kind": "empty", "allow_auto": False},
            "TESTE",
            app._display_auto_current_context(),
        )

        self.assertEqual("empty", result["kind"])
        self.assertFalse(app._display_f3_powered_cycle_latched)
        self.assertEqual("suporte_vazio", app._display_f3_powered_cycle_clear_reason)

    def test_modulo_nao_importa_f2(self):
        source = inspect.getsource(module)
        for forbidden in (
            "src.platform.f2_",
            "F2Automatic",
            "linux_f2_fixed_resolution",
            "operacao_engine",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
