from __future__ import annotations

import inspect
import unittest

from src.platform.display_f3_final_check_stability import estabilizar_check_final_f3


class _FakeApp:
    DISPLAY_AUTO_OK_STABLE_FRAMES = 2

    def __init__(self, *, check_id="CHECK_005", check_name="NOVO CHECK"):
        self.display_f3_ativo = True
        self.display_f3_result_after_id = None
        self._display_f3_waiting_empty_rearm = False
        self._display_f3_waiting_new_board_after_empty = False
        self.camera_frame_atual = object()
        self.camera_ultimo_frame_id = 100
        self._context = {
            "project_name": "TESTE",
            "check_id": check_id,
            "check_name": check_name,
            "current_index": 4,
        }
        self._display_f3_operational_state = {
            "kind": "check",
            "allow_auto": True,
            "physical_state_key": f"check:{check_id}",
            "check_id": check_id,
            "check_name": check_name,
            "_display_f3_physical_decision_allowed": True,
            "source": "f3_current_check_confirmed_by_live_masks",
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
        # Reproduz o estado observado no debug: a camada antiga deixou zero.
        self._display_auto_stable_frames = 0
        self._display_auto_last_decision = None
        self.registered = []

    def _display_auto_current_context(self):
        return dict(self._context) if self._context is not None else None

    def _display_auto_frame_token(self, _frame):
        return ("camera", self.camera_ultimo_frame_id)

    def _display_auto_is_transient_check(self, context):
        return bool((context or {}).get("intermittent", False))

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

    def registrar_resultado_check_display_f3(self, aprovado=True):
        self.registered.append(bool(aprovado))
        return {"event": "check_advanced", "approved": bool(aprovado)}


class DisplayF3FinalCheckStabilityTests(unittest.TestCase):
    def test_future_check_accumulates_two_frames_even_if_legacy_counter_was_zero(self):
        app = _FakeApp(check_id="CHECK_005", check_name="HDMI")
        context = app._display_auto_current_context()

        first = estabilizar_check_final_f3(app, context)
        self.assertTrue(first["counted"])
        self.assertEqual(first["frames"], 1)
        self.assertFalse(first["registered"])
        self.assertEqual(app._display_auto_stable_frames, 1)
        self.assertEqual(app.registered, [])

        # Simula exatamente o bug: outra camada histórica volta a zerar o campo
        # legado entre frames. A estabilidade final própria não pode se perder.
        app._display_auto_stable_frames = 0
        app._display_auto_last_decision = None
        app.camera_ultimo_frame_id = 101

        second = estabilizar_check_final_f3(app, context)
        self.assertEqual(second["frames"], 2)
        self.assertTrue(second["registered"])
        self.assertEqual(second["register_event"], "check_advanced")
        self.assertEqual(app.registered, [True])

    def test_intermitente_nao_registra_enquanto_fase_acesa_nao_foi_observada(self):
        app = _FakeApp(check_id="CHECK_002", check_name="BLUE")
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
        result = estabilizar_check_final_f3(
            app,
            app._display_auto_current_context(),
        )
        self.assertFalse(result["counted"])
        self.assertFalse(result["registered"])
        self.assertEqual(
            "intermitente_aguardando_fase_acesa",
            result["reason"],
        )
        self.assertEqual([], app.registered)

    def test_same_camera_frame_is_never_counted_twice(self):
        app = _FakeApp()
        context = app._display_auto_current_context()
        first = estabilizar_check_final_f3(app, context)
        second = estabilizar_check_final_f3(app, context)
        self.assertEqual(first["frames"], 1)
        self.assertEqual(second["reason"], "mesmo_frame")
        self.assertEqual(second["frames"], 1)
        self.assertEqual(app.registered, [])

    def test_empty_state_remains_absolute(self):
        app = _FakeApp()
        app._display_f3_operational_state = {
            "kind": "empty",
            "allow_auto": False,
            "physical_state_key": "empty",
            "_display_f3_physical_decision_allowed": False,
        }
        result = estabilizar_check_final_f3(app, app._display_auto_current_context())
        self.assertFalse(result["counted"])
        self.assertEqual(result["reason"], "autoridade_fisica_nao_liberada")
        self.assertEqual(app.registered, [])

    def test_wrong_check_analysis_cannot_accumulate(self):
        app = _FakeApp(check_id="CHECK_005")
        app._display_auto_last_analysis["check_id"] = "CHECK_004"
        result = estabilizar_check_final_f3(app, app._display_auto_current_context())
        self.assertFalse(result["counted"])
        self.assertEqual(result["reason"], "analise_nao_aprovada_integralmente")

    def test_partial_masks_cannot_accumulate(self):
        app = _FakeApp()
        app._display_auto_last_analysis["matched_mask_count"] = 27
        result = estabilizar_check_final_f3(app, app._display_auto_current_context())
        self.assertFalse(result["counted"])
        self.assertEqual(result["reason"], "analise_nao_aprovada_integralmente")

    def test_source_is_generic_and_has_no_f2_dependency(self):
        import src.platform.display_f3_final_check_stability as module

        source = inspect.getsource(module)
        self.assertNotIn("f2_automatic", source.lower())
        self.assertNotIn('check_id == "CHECK_004"', source)
        self.assertNotIn('check_name == "USB"', source)
        self.assertNotIn('check_name == "AUX"', source)


if __name__ == "__main__":
    unittest.main()
