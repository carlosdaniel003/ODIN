from __future__ import annotations

import inspect
import unittest

import src.platform.display_f3_analysis_service as service
import src.platform.display_f3_manual_snapshot_debug as manual


class DisplayF3ManualAnalysisStage2Tests(unittest.TestCase):
    def test_current_check_service_is_ui_free_and_single_check(self):
        source = inspect.getsource(service)
        self.assertIn("DisplayF3CurrentCheckAnalysisService", source)
        self.assertIn("F3SameMaskReferenceAnalyzer", source)
        self.assertIn('check_id=check_id', source)
        self.assertNotIn("_run_check_analyses", source)
        self.assertNotIn("import tkinter", source)
        for forbidden in (
            "registrar_resultado_check_display_f3",
            "concluir_check_display_f3",
            "descartar_placa_display_f3",
        ):
            self.assertNotIn(forbidden, source)

    def test_analyze_click_has_no_full_debug_work(self):
        source = inspect.getsource(manual._capture_from_window)
        self.assertIn("DisplayF3CurrentCheckAnalysisService", source)
        self.assertNotIn("capturar_snapshot_debug_display_f3", source)
        self.assertNotIn("montar_relatorio_snapshot_display_f3", source)

    def test_debug_click_owns_full_audit(self):
        source = inspect.getsource(manual._generate_debug_from_window)
        self.assertIn("capturar_snapshot_debug_display_f3", source)
        self.assertIn("montar_relatorio_snapshot_display_f3", source)
        self.assertIn("_display_f3_manual_analysis_seed", source)

    def test_minimal_analyze_seed_avoids_full_runtime_snapshot(self):
        source = inspect.getsource(manual._prepare_async_snapshot_seed)
        self.assertIn('"frame": frame', source)
        self.assertIn('"logical_context"', source)
        self.assertIn('"rotation"', source)
        self.assertNotIn("_runtime_state_at_frame", source)
        self.assertNotIn("_camera_settings_at_frame", source)

    def test_full_debug_still_compares_all_checks_only_on_demand(self):
        source = inspect.getsource(manual.capturar_snapshot_debug_display_f3)
        self.assertIn("_run_check_analyses", source)
        report = inspect.getsource(manual.montar_relatorio_snapshot_display_f3)
        self.assertIn("auditoria completa sob demanda", report)


if __name__ == "__main__":
    unittest.main()
