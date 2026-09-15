from __future__ import annotations

import unittest

import src.platform.display_f3_power_authority as power_module
from src.platform.display_f3_live_status_consistency_fix import (
    F3_INITIAL_FRAME_PLACEHOLDER,
    F3_LEGACY_REFERENCE_PLACEHOLDER,
    corrigir_placeholder_inicial_f3,
    resolver_status_visual_runtime_f3,
)


class _Label:
    def __init__(self, text):
        self.text = text

    def cget(self, key):
        if key == "text":
            return self.text
        raise KeyError(key)

    def configure(self, **kwargs):
        if "text" in kwargs:
            self.text = kwargs["text"]


class _Window:
    def __init__(self, text=F3_LEGACY_REFERENCE_PLACEHOLDER):
        self.visual_analysis_state_label = _Label(text)


class _App:
    def __init__(self):
        self._display_f3_waiting_empty_rearm = False
        self._display_f3_waiting_new_board_after_empty = False
        self._display_f3_power_authority_status = None
        self._display_f3_operational_state = None

    @staticmethod
    def _display_auto_current_context():
        return {
            "project_name": "CM-550-L",
            "check_id": "CHECK_001",
            "check_name": "H1",
        }


class DisplayF3LiveStatusConsistencyFixTests(unittest.TestCase):
    def test_placeholder_inicial_nao_diz_que_faltam_referencias(self):
        window = _Window()
        changed = corrigir_placeholder_inicial_f3(window)

        self.assertTrue(changed)
        self.assertEqual(F3_INITIAL_FRAME_PLACEHOLDER, window.visual_analysis_state_label.text)
        self.assertNotIn("referências do projeto", window.visual_analysis_state_label.text)

    def test_gate_off_publica_placa_desligada_em_vez_do_placeholder(self):
        app = _App()
        app._display_f3_power_authority_status = {
            "board_present": True,
            "presence": {
                "board_present": True,
                "empty_confirmed": False,
            },
            "energy": {
                "energy_state": power_module.F3_POWER_STATE_OFF,
                "off_confirmed": True,
                "expected_on_mask_count": 7,
                "off_votes": 7,
                "powered_votes": 0,
            },
            "decision_allowed": False,
            "reason": "todos_segmentos_esperados_acesos_estao_apagados",
        }

        result = resolver_status_visual_runtime_f3(
            app,
            F3_LEGACY_REFERENCE_PLACEHOLDER,
        )

        self.assertIsNotNone(result)
        self.assertIn("PLACA DESLIGADA NO SUPORTE", result[0])
        self.assertNotIn("aguardando referências", result[0])

    def test_empty_confirmado_publica_placa_fora_do_suporte(self):
        app = _App()
        app._display_f3_power_authority_status = {
            "board_present": False,
            "empty_confirmed": True,
            "presence": {
                "board_present": False,
                "empty_confirmed": True,
            },
            "energy": None,
            "decision_allowed": False,
        }

        result = resolver_status_visual_runtime_f3(app, F3_INITIAL_FRAME_PLACEHOLDER)

        self.assertIsNotNone(result)
        self.assertEqual("ANÁLISE VISUAL: PLACA FORA DO SUPORTE", result[0])

    def test_powered_so_substitui_placeholder_e_preserva_status_global_valido(self):
        app = _App()
        app._display_f3_power_authority_status = {
            "board_present": True,
            "presence": {"board_present": True},
            "energy": {
                "energy_state": power_module.F3_POWER_STATE_POWERED,
                "powered_confirmed": True,
            },
            "decision_allowed": True,
        }

        from_placeholder = resolver_status_visual_runtime_f3(
            app,
            F3_LEGACY_REFERENCE_PLACEHOLDER,
        )
        existing_global = resolver_status_visual_runtime_f3(
            app,
            "ANÁLISE VISUAL: CHECK H1 • 98%",
        )

        self.assertIsNotNone(from_placeholder)
        self.assertIn("analisando H1", from_placeholder[0])
        self.assertIsNone(existing_global)

    def test_rearme_tem_prioridade_e_nao_e_sobrescrito(self):
        app = _App()
        app._display_f3_waiting_empty_rearm = True
        app._display_f3_power_authority_status = {
            "board_present": True,
            "energy": {"energy_state": power_module.F3_POWER_STATE_OFF},
        }

        result = resolver_status_visual_runtime_f3(
            app,
            F3_LEGACY_REFERENCE_PLACEHOLDER,
        )

        self.assertIsNone(result)

    def test_fallback_operacional_so_age_se_referencias_estao_configuradas(self):
        app = _App()
        app._display_f3_operational_state = {
            "kind": "off",
            "board_references_complete": True,
        }
        configured = resolver_status_visual_runtime_f3(
            app,
            F3_LEGACY_REFERENCE_PLACEHOLDER,
        )

        app._display_f3_operational_state = {
            "kind": "off",
            "board_references_complete": False,
        }
        missing = resolver_status_visual_runtime_f3(
            app,
            F3_LEGACY_REFERENCE_PLACEHOLDER,
        )

        self.assertIsNotNone(configured)
        self.assertIn("PLACA DESLIGADA", configured[0])
        self.assertIsNone(missing)


if __name__ == "__main__":
    unittest.main()
