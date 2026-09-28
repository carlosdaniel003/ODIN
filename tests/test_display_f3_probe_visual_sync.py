from __future__ import annotations

import inspect
import unittest

import src.platform.display_f3_probe_visual_sync as module


class _App:
    def __init__(self):
        self.display_f3_ativo = True
        self.display_f3_result_after_id = None
        self._display_f3_waiting_empty_rearm = False
        self._display_f3_waiting_new_board_after_empty = False
        self.camera_frame_atual = object()
        self.current = {
            "project_name": "TESTE",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "current_index": 0,
        }
        self._display_auto_last_analysis = None
        self._display_f3_overlay_analysis_cache_key = None
        self._display_f3_overlay_analysis_cache = None

    def _display_auto_current_context(self):
        return dict(self.current)

    def _display_auto_configuration_open(self):
        return False

    def _display_auto_frame_token(self, _frame):
        return ("camera", 1221)


class DisplayF3ProbeVisualSyncTests(unittest.TestCase):
    @staticmethod
    def _analysis():
        return {
            "ready": True,
            "approved": True,
            "reason": "check_conforme_gabarito_exato",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "matched_mask_count": 28,
            "active_mask_count": 28,
            "mask_results": [
                {
                    "mask_id": "MASK_008",
                    "expected": "on",
                    "classified": "on",
                    "matched": True,
                    "confidence": 0.99,
                },
                {
                    "mask_id": "MASK_001",
                    "expected": "off",
                    "classified": "off",
                    "matched": True,
                    "confidence": 0.97,
                },
            ],
        }

    def test_exact_h1_probe_is_published_to_live_mask_overlay(self):
        app = _App()
        context = app._display_auto_current_context()

        published = module.publicar_analise_visual_sonda_f3(
            app,
            context,
            self._analysis(),
        )

        self.assertTrue(published)
        self.assertIsInstance(app._display_auto_last_analysis, dict)
        self.assertEqual("TESTE", app._display_auto_last_analysis["project_name"])
        self.assertEqual("CHECK_001", app._display_auto_last_analysis["check_id"])
        self.assertEqual("on", app._display_auto_last_analysis["mask_results"][0]["classified"])
        self.assertEqual(
            ("TESTE", "CHECK_001", ("camera", 1221)),
            app._display_f3_overlay_analysis_cache_key,
        )
        self.assertIs(app._display_f3_overlay_analysis_cache, app._display_auto_last_analysis)

    def test_blocked_register_keeps_visual_analysis_and_is_not_reported_as_advanced(self):
        app = _App()
        context = app._display_auto_current_context()

        def previous_advance(owner, _context, _analysis, _stability):
            # Reproduz o legado: registro recusado limpa a análise do core.
            owner._display_auto_last_analysis = None
            return {
                "advanced": True,
                "event": {
                    "event": "physical_gate_blocked",
                    "snapshot": {"current_check": {"id": "CHECK_001", "name": "H1"}},
                },
            }

        result = module.executar_avanco_sonda_com_sincronia_visual_f3(
            previous_advance,
            app,
            context,
            self._analysis(),
            {"confirm": True, "frames": 1, "required": 1},
        )

        self.assertFalse(result["advanced"])
        self.assertEqual("physical_gate_blocked_after_exact_probe", result["reason"])
        self.assertTrue(result["visual_analysis_published"])
        self.assertEqual("CHECK_001", app._display_auto_last_analysis["check_id"])
        self.assertEqual(28, app._display_auto_last_analysis["matched_mask_count"])

    def test_real_check_advance_does_not_republish_stale_h1_analysis(self):
        app = _App()
        context = app._display_auto_current_context()

        def previous_advance(owner, _context, _analysis, _stability):
            owner.current = {
                "project_name": "TESTE",
                "check_id": "CHECK_002",
                "check_name": "BLUE",
                "current_index": 1,
            }
            owner._display_auto_last_analysis = None
            return {
                "advanced": True,
                "event": {
                    "event": "check_advanced",
                    "snapshot": {"current_check": {"id": "CHECK_002", "name": "BLUE"}},
                },
            }

        result = module.executar_avanco_sonda_com_sincronia_visual_f3(
            previous_advance,
            app,
            context,
            self._analysis(),
            {"confirm": True, "frames": 1, "required": 1},
        )

        self.assertTrue(result["advanced"])
        self.assertIsNone(app._display_auto_last_analysis)
        self.assertEqual("CHECK_002", app.current["check_id"])

    def test_canonical_runtime_preserves_tracked_analysis_instead_of_probe(self):
        app = _App()
        app._display_f3_runtime_authorities_installed = True
        canonical = {
            "ready": True,
            "approved": True,
            "project_name": "TESTE",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "matched_mask_count": 28,
            "active_mask_count": 28,
            "live_geometry_override": True,
            "analysis_frame_source": "tracking_raw_with_live_geometry",
            "mask_results": [
                {
                    "mask_id": "MASK_008",
                    "expected": "on",
                    "classified": "on",
                    "matched": True,
                }
            ],
        }
        app._display_auto_last_analysis = canonical
        stale_probe = self._analysis()
        stale_probe["approved"] = False
        stale_probe["matched_mask_count"] = 22

        published = module.publicar_analise_visual_sonda_f3(
            app,
            app._display_auto_current_context(),
            stale_probe,
        )

        self.assertFalse(published)
        self.assertIs(canonical, app._display_auto_last_analysis)
        self.assertEqual(28, app._display_auto_last_analysis["matched_mask_count"])
        self.assertTrue(app._display_auto_last_analysis["live_geometry_override"])
        self.assertIsNone(app._display_f3_overlay_analysis_cache)

    def test_rearm_never_publishes_probe_colors(self):
        app = _App()
        app._display_f3_waiting_empty_rearm = True

        published = module.publicar_analise_visual_sonda_f3(
            app,
            app._display_auto_current_context(),
            self._analysis(),
        )

        self.assertFalse(published)
        self.assertIsNone(app._display_auto_last_analysis)

    def test_module_is_isolated_from_f2(self):
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
