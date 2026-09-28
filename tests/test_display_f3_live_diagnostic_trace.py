from __future__ import annotations

from collections import deque
import inspect
import unittest
from unittest.mock import patch

import numpy as np

import src.platform.display_f3_fast_expected_gate as fast_gate_module
import src.platform.display_f3_live_diagnostic_trace as trace_module


class _Store:
    def __init__(self, values):
        self.values = values

    def get_all(self, _project_name):
        return dict(self.values)


class _Matcher:
    def __init__(self):
        self.project_store = _Store(
            {
                "board_off": {"kind": "off", "threshold": 0.72},
                "empty_support": {"kind": "empty", "threshold": 0.72},
            }
        )

    @staticmethod
    def _threshold(metadata):
        return float((metadata or {}).get("threshold", 0.72))


class _ProbeApp:
    def __init__(self, transient=False):
        self.transient = transient
        self._display_f3_live_probe_signature = None
        self._display_f3_live_probe_ok_frames = 0

    def _display_auto_is_transient_check(self, _context):
        return self.transient


class _AdvanceApp(_ProbeApp):
    DISPLAY_AUTO_TRANSITION_FRAMES = 1

    def __init__(self):
        super().__init__(transient=False)
        self.current = {
            "project_name": "TESTE",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "current_index": 0,
        }
        self.events = []
        self._display_auto_signature = ("TESTE", "CHECK_001")
        self._display_auto_transition_frames = 0

    def _display_auto_current_context(self):
        return dict(self.current)

    def registrar_resultado_check_display_f3(self, approved):
        self.events.append(bool(approved))
        self.current = {
            "project_name": "TESTE",
            "check_id": "CHECK_002",
            "check_name": "BLUE",
            "current_index": 1,
        }
        return {
            "event": "check_advanced",
            "snapshot": {
                "current_check": {
                    "id": "CHECK_002",
                    "name": "BLUE",
                }
            },
        }

    def _display_auto_arm_manual_entry_gate(self, _context, _event):
        return None

    def _display_auto_clear_manual_entry_gate(self):
        return None

    def _reset_display_auto_stability(self):
        return None


class _DebugRepository:
    config_file = "data/config/odin_display_projects.json"

    @staticmethod
    def obter_projeto_ativo():
        return "TESTE"

    @staticmethod
    def listar_checks(_project_name):
        return [
            {"id": "CHECK_001", "name": "H1"},
            {"id": "CHECK_002", "name": "BLUE"},
        ]

    @staticmethod
    def carregar_projeto(_project_name):
        return {
            "masks": [
                {"id": "MASK_008", "type": "circle", "cx": 100, "cy": 200, "radius": 12},
            ]
        }

    @staticmethod
    def carregar_check(_project_name, _check_id):
        return {"mask_states": {"MASK_008": "on"}}


class _DebugApp:
    def __init__(self):
        self.display_project_repository = _DebugRepository()
        self._display_f3_live_trace = deque(
            [
                {
                    "ts": "2026-09-03T13:10:00.000-04:00",
                    "frame_id": 123,
                    "context": {"check_id": "CHECK_001", "check_name": "H1"},
                    "physical": {"kind": "unknown", "source": "test", "allow_auto": False},
                    "reference_scores": {
                        "off": 0.61,
                        "check:CHECK_001": 0.84,
                        "check:CHECK_002": 0.33,
                    },
                    "analysis_source": "hidden_exact_probe",
                    "probe": {
                        "matched": 1,
                        "active": 1,
                        "approved": True,
                        "stable_frames": 1,
                        "required_frames": 2,
                        "similarity_min": 0.91,
                        "similarity_avg": 0.91,
                    },
                    "advance": None,
                    "masks": [
                        {
                            "mask_id": "MASK_008",
                            "expected": "on",
                            "classified": "on",
                            "matched": True,
                            "template_similarity": 0.91,
                            "pixel_similarity": 0.90,
                            "energy_similarity": 0.95,
                            "reference_v_mean": 220.0,
                            "current_v_mean": 218.0,
                            "confidence": 0.86,
                        }
                    ],
                }
            ],
            maxlen=trace_module.F3_LIVE_TRACE_MAX_FRAMES,
        )
        self._display_f3_live_probe_last_analysis = {
            "ready": True,
            "approved": True,
            "reason": "check_conforme_gabarito_exato",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "matched_mask_count": 1,
            "active_mask_count": 1,
            "mask_results": [
                {
                    "mask_id": "MASK_008",
                    "expected": "on",
                    "classified": "on",
                    "matched": True,
                    "template_similarity": 0.91,
                    "template_threshold": 0.82,
                    "pixel_similarity": 0.90,
                    "energy_similarity": 0.95,
                    "reference_v_mean": 220.0,
                    "current_v_mean": 218.0,
                    "confidence": 0.86,
                }
            ],
        }

    def _display_auto_current_context(self):
        return {
            "project_name": "TESTE",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "current_index": 0,
        }


class DisplayF3LiveDiagnosticTraceTests(unittest.TestCase):
    def test_presence_scores_use_full_resolution_roi_first_pipeline(self):
        matcher = _Matcher()
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

        def score(_frame, metadata):
            return 0.91 if metadata.get("kind") == "off" else 0.22

        with patch.object(trace_module.exact_module, "_score_reference_full_roi", side_effect=score):
            result = trace_module._presence_scores_full_roi(matcher, frame, "TESTE")

        self.assertEqual(0.91, result["off_score"])
        self.assertEqual(0.22, result["empty_score"])
        self.assertEqual("full_resolution_roi_first", result["comparison_mode"])
        self.assertTrue(result["board_references_complete"])

    def test_h1_probe_confirms_on_first_positive_frame(self):
        app = _ProbeApp(transient=False)
        context = {"project_name": "TESTE", "check_id": "CHECK_001", "check_name": "H1"}
        analysis = {"approved": True}

        first = trace_module._update_positive_probe_stability(app, context, analysis)

        self.assertTrue(first["confirm"])
        self.assertEqual(1, first["frames"])
        self.assertEqual(1, first["required"])

    def test_blue_probe_can_confirm_in_first_exact_frame(self):
        app = _ProbeApp(transient=True)
        context = {"project_name": "TESTE", "check_id": "CHECK_002", "check_name": "BLUE"}
        result = trace_module._update_positive_probe_stability(app, context, {"approved": True})

        self.assertTrue(result["confirm"])
        self.assertEqual(1, result["required"])

    def test_negative_probe_never_advances_or_generates_ng(self):
        app = _ProbeApp(transient=True)
        context = {"project_name": "TESTE", "check_id": "CHECK_002", "check_name": "BLUE"}
        result = trace_module._update_positive_probe_stability(app, context, {"approved": False})

        self.assertFalse(result["confirm"])
        self.assertEqual(0, result["frames"])

    def test_exact_positive_probe_can_advance_even_if_global_physical_gate_was_wrong(self):
        app = _AdvanceApp()
        context = dict(app.current)
        stability = {"confirm": True, "frames": 1, "required": 1}
        event = trace_module._advance_positive_probe_if_needed(
            app,
            context,
            {"approved": True},
            stability,
        )

        self.assertTrue(event["advanced"])
        self.assertEqual([True], app.events)
        self.assertEqual("CHECK_002", app.current["check_id"])
        self.assertEqual(trace_module.F3_EXACT_PROBE_SOURCE, app._display_f3_operational_state["source"])

    def test_canonical_runtime_reuses_core_analysis_when_latest_frame_advanced(self):
        app = _AdvanceApp()
        app._display_f3_runtime_authorities_installed = True
        app._display_auto_last_frame_token = ("camera", 2026)
        app._display_auto_last_analysis = {
            "ready": True,
            "approved": True,
            "project_name": "TESTE",
            "check_id": "CHECK_001",
            "matched_mask_count": 28,
            "active_mask_count": 28,
            "live_geometry_override": True,
            "mask_results": [],
        }
        context = dict(app.current)

        with patch.object(
            trace_module,
            "_probe_expected_check",
            side_effect=AssertionError("sonda estática não pode rodar no runtime canônico"),
        ):
            analysis, source = trace_module._select_live_trace_analysis(
                app,
                object(),
                ("camera", 2035),
                context,
            )

        self.assertEqual("canonical_runtime_analysis", source)
        self.assertTrue(analysis["live_geometry_override"])
        self.assertEqual(28, analysis["matched_mask_count"])

    def test_canonical_runtime_makes_exact_probe_observer_only(self):
        app = _AdvanceApp()
        app._display_f3_runtime_authorities_installed = True
        context = dict(app.current)

        event = trace_module._advance_positive_probe_if_needed(
            app,
            context,
            {"approved": True},
            {"confirm": True, "frames": 1, "required": 1},
        )

        self.assertFalse(event["advanced"])
        self.assertTrue(event["observer_only"])
        self.assertEqual("runtime_canonical_owns_check_decision", event["reason"])
        self.assertEqual([], app.events)
        self.assertEqual("CHECK_001", app.current["check_id"])

    def test_debug_contains_live_mask_data_and_historical_frames(self):
        text = trace_module._append_live_trace_debug(_DebugApp(), "DEBUG BASE")

        self.assertIn("[DEBUG AO VIVO]", text)
        self.assertIn("[MÁSCARAS AO VIVO - ÚLTIMO FRAME ANALISADO]", text)
        self.assertIn("[HISTÓRICO AO VIVO - RESUMO POR FRAME]", text)
        self.assertIn("[HISTÓRICO DETALHADO DE MÁSCARAS", text)
        self.assertIn("MASK_008", text)
        self.assertIn("frame=123", text)
        self.assertIn("H1=0.8400", text)
        self.assertIn("v_live=218.00", text)

    def test_live_trace_is_installed_after_base_unknown_debug(self):
        source = inspect.getsource(fast_gate_module.instalar_gate_rapido_check_esperado_display_f3)
        base_position = source.index("instalar_correcao_unknown_e_debug_display_f3()")
        live_position = source.index("instalar_rastreio_ao_vivo_debug_display_f3()")
        self.assertLess(base_position, live_position)

    def test_module_does_not_depend_on_f2_runtime(self):
        source = inspect.getsource(trace_module)
        for forbidden in (
            "src.platform.f2_",
            "F2Automatic",
            "linux_f2_fixed_resolution",
            "operacao_engine",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
