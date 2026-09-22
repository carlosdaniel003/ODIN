from __future__ import annotations

import inspect
import unittest

import src.platform.display_f3_current_check_status_sync as module


class _Window:
    def __init__(self):
        self.calls = []

    def set_operational_reference_status(self, text, color):
        self.calls.append((str(text), str(color)))


class _App:
    def __init__(self, check_id="CHECK_004", check_name="USB"):
        self.display_f3_ativo = True
        self._display_f3_waiting_empty_rearm = False
        self._display_f3_waiting_new_board_after_empty = False
        self.display_f3_result_after_id = None
        self.display_f3_window = _Window()
        self._context = {
            "project_name": "TESTE",
            "check_id": check_id,
            "check_name": check_name,
        }
        self._display_auto_last_analysis = {
            "ready": True,
            "approved": True,
            "project_name": "TESTE",
            "check_id": check_id,
            "check_name": check_name,
            "active_mask_count": 28,
            "matched_mask_count": 28,
        }
        self._display_f3_operational_state = {
            "kind": "check",
            "allow_auto": True,
            "physical_state_key": f"check:{check_id}",
            "check_id": check_id,
            "check_name": check_name,
            "text": f"PLACA NO SUPORTE • LIGADA • DISPLAY EM {check_name}",
            # Reproduz exatamente o problema do debug: estado atual USB,
            # porém metadados/memória ainda apontando para BLUE.
            "physical_status_memory_override": True,
            "physical_status_memory_underlying_kind": "off",
            "physical_status_memory_check_id": "CHECK_002",
            "physical_status_memory_check_name": "BLUE",
            "physical_status_memory_source": "f3_last_confirmed_check_physical_status",
            "physical_status_memory_evidence": {"check_id": "CHECK_002"},
        }

    def _display_auto_current_context(self):
        return dict(self._context)

    def _display_auto_update_intermittent_evidence(self, context, analysis):
        expected = {
            str(item.get("mask_id") or "")
            for item in (analysis.get("mask_results") or [])
            if isinstance(item, dict) and str(item.get("expected") or "") == "on"
        }
        seen = {
            str(item.get("mask_id") or "")
            for item in (analysis.get("mask_results") or [])
            if isinstance(item, dict)
            and str(item.get("expected") or "") == "on"
            and str(item.get("classified") or "") == "on"
            and item.get("raw_matched") is not False
        }
        return bool(not expected or expected.issubset(seen)), len(seen), len(expected)


class DisplayF3CurrentCheckStatusSyncTests(unittest.TestCase):
    def test_usb_28_de_28_substitui_memoria_visual_blue_imediatamente(self):
        app = _App()
        self.assertTrue(module.sincronizar_status_check_atual_f3(app))

        state = app._display_f3_operational_state
        self.assertIn("DISPLAY EM USB", state["text"])
        self.assertTrue(state["current_check_status_sync"])
        self.assertEqual("CHECK_004", state["current_check_status_sync_check_id"])
        self.assertEqual("USB", state["current_check_status_sync_check_name"])
        self.assertNotIn("physical_status_memory_check_name", state)
        self.assertEqual("CHECK_004", app._display_f3_physical_status_memory_check_id)
        self.assertEqual("USB", app._display_f3_physical_status_memory_check_name)
        self.assertIn("DISPLAY EM USB", app.display_f3_window.calls[-1][0])

    def test_status_intermitente_nao_confirma_durante_fase_apagada_incompleta(self):
        app = _App(check_id="CHECK_002", check_name="BLUE")
        app._context["intermittent"] = True
        app._display_auto_last_analysis.update(
            {
                "intermittent": True,
                "active_mask_count": 2,
                "matched_mask_count": 2,
                "mask_results": [
                    {
                        "mask_id": "MASK_001",
                        "expected": "on",
                        "classified": "on",
                        "matched": True,
                        "raw_matched": True,
                    },
                    {
                        "mask_id": "MASK_002",
                        "expected": "on",
                        "classified": "off",
                        "matched": True,
                        "raw_matched": False,
                        "intermittent_tolerated": True,
                    },
                ],
            }
        )
        self.assertFalse(module.sincronizar_status_check_atual_f3(app))
        self.assertEqual([], app.display_f3_window.calls)

    def test_regra_e_generica_para_quinto_check_futuro(self):
        app = _App(check_id="CHECK_005", check_name="SPDIF")
        self.assertTrue(module.sincronizar_status_check_atual_f3(app))
        self.assertEqual("SPDIF", app._display_f3_physical_status_memory_check_name)
        self.assertIn("DISPLAY EM SPDIF", app._display_f3_operational_state["text"])

    def test_analise_parcial_nao_substitui_memoria_anterior(self):
        app = _App()
        app._display_auto_last_analysis["matched_mask_count"] = 27
        self.assertFalse(module.sincronizar_status_check_atual_f3(app))
        self.assertEqual("BLUE", app._display_f3_operational_state["physical_status_memory_check_name"])
        self.assertEqual([], app.display_f3_window.calls)

    def test_contexto_ja_avancou_nao_republica_check_anterior(self):
        app = _App()
        app._context = {
            "project_name": "TESTE",
            "check_id": "CHECK_003",
            "check_name": "AUX",
        }
        self.assertFalse(module.sincronizar_status_check_atual_f3(app))
        self.assertEqual([], app.display_f3_window.calls)

    def test_empty_continua_absoluto(self):
        app = _App()
        app._display_f3_operational_state = {
            "kind": "empty",
            "allow_auto": False,
            "text": "PLACA FORA DO SUPORTE",
        }
        self.assertFalse(module.sincronizar_status_check_atual_f3(app))
        self.assertEqual("empty", app._display_f3_operational_state["kind"])

    def test_sincronia_nao_altera_campos_de_autoridade(self):
        app = _App()
        app._display_f3_operational_state.update(
            {
                "kind": "off",
                "allow_auto": False,
                "physical_state_key": "off",
                "_display_f3_physical_decision_allowed": False,
            }
        )
        self.assertTrue(module.sincronizar_status_check_atual_f3(app))
        state = app._display_f3_operational_state
        self.assertEqual("off", state["kind"])
        self.assertFalse(state["allow_auto"])
        self.assertEqual("off", state["physical_state_key"])
        self.assertFalse(state["_display_f3_physical_decision_allowed"])
        self.assertIn("DISPLAY EM USB", state["text"])

    def test_modulo_e_exclusivo_do_f3(self):
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
