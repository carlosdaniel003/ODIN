from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

import src.platform.display_f3_final_performance as performance
import src.platform.display_f3_fast_expected_gate as fast_gate
import src.platform.display_f3_workspace_ui as workspace


class _FakeFileStore:
    def __init__(self, path: Path) -> None:
        self.config_file = path
        self.loads = 0

    def _load(self):
        self.loads += 1
        return {"value": self.config_file.read_text(encoding="utf-8")}

    def _write(self, data):
        self.config_file.write_text(str(data["value"]), encoding="utf-8")


class DisplayF3FinalPerformanceTests(unittest.TestCase):
    def test_file_cache_reuses_payload_and_invalidates_on_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "data.json"
            path.write_text("A", encoding="utf-8")

            class Store(_FakeFileStore):
                pass

            performance._install_file_backed_cache(
                Store,
                load_name="_load",
                write_name="_write",
                path_attr="config_file",
                marker="_test_cache",
            )
            store = Store(path)
            first = store._load()
            second = store._load()
            self.assertEqual("A", first["value"])
            self.assertIs(first, second)
            self.assertEqual(1, store.loads)

            path.write_text("BBBB", encoding="utf-8")
            self.assertEqual("BBBB", store._load()["value"])
            self.assertEqual(2, store.loads)

            store._write({"value": "CC"})
            self.assertEqual("CC", store._load()["value"])
            self.assertEqual(3, store.loads)

    def test_configuration_visibility_includes_opening_phase(self):
        class Config:
            visible = True

        class App:
            _display_f3_configuration_opening = False
            _display_project_config_window = Config()

        self.assertTrue(performance.configuracao_f3_visivel(App()))
        App._display_project_config_window = None
        self.assertFalse(performance.configuracao_f3_visivel(App()))
        App._display_f3_configuration_opening = True
        self.assertTrue(performance.configuracao_f3_visivel(App()))

    def test_configuration_open_and_lazy_content_are_not_runtime_patches(self):
        installer = inspect.getsource(
            performance.instalar_performance_final_display_f3
        )
        self.assertNotIn("_install_fast_configuration_open", installer)
        self.assertNotIn("_install_lazy_configuration_content", installer)
        self.assertIn("_install_configuration_runtime_pause", installer)


    def test_fresh_frame_gate_is_before_expensive_runtime(self):
        source = inspect.getsource(performance._install_fresh_frame_outer_gate)
        self.assertIn("_display_f3_outer_last_frame_token", source)
        self.assertIn("_display_auto_frame_token", source)
        self.assertIn("return None", source)
        installer = inspect.getsource(
            performance.instalar_performance_final_display_f3
        )
        self.assertIn("_install_fresh_frame_outer_gate()", installer)
        self.assertNotIn("_install_adaptive_preview_cadence()", installer)

    def test_preview_cadence_is_not_installed_by_performance_layer(self):
        installer = inspect.getsource(
            performance.instalar_performance_final_display_f3
        )
        self.assertNotIn("_install_adaptive_preview_cadence()", installer)
        self.assertIn("_install_fresh_frame_outer_gate()", installer)

    def test_exact_reference_hot_path_avoids_full_hd_read_per_candidate(self):
        source = inspect.getsource(performance._install_exact_reference_hot_path)
        self.assertIn("_reference_image_cached", source)
        self.assertIn("_small_reference_after_roi", source)
        self.assertIn("_prepare_current_roi_small", source)
        self.assertIn("_score_reference_full_roi", source)
        self.assertNotIn("frame.copy()", source)

    def test_exact_mask_reference_side_is_precomputed(self):
        source = inspect.getsource(performance._install_exact_mask_reference_cache)
        self.assertIn("_mask_reference_prepared", source)
        self.assertIn("ref_bgr", source)
        self.assertIn("ref_v", source)
        self.assertIn("current_blur", source)

    def test_mask_hot_path_limits_full_redraw_to_30_hz(self):
        self.assertGreaterEqual(performance.F3_MASK_POINTER_INTERVAL_S, 1.0 / 20.0)
        self.assertGreaterEqual(performance.F3_MASK_DRAG_REDRAW_INTERVAL_S, 1.0 / 30.0)
        source = inspect.getsource(performance._install_mask_editor_hot_path)
        self.assertIn("F3_MAGNIFIER_TAG", source)
        self.assertIn("DisplayMaskEditorInteractionMixin._drag", source)
        self.assertNotIn("deepcopy(by_id", source)

    def test_workspace_does_not_flush_tk_while_window_is_being_built(self):
        source = inspect.getsource(workspace.maximizar_janela_workspace_f3)
        self.assertNotIn("window.update_idletasks(", source)
        installer = inspect.getsource(workspace.instalar_workspace_telas_display_f3)
        self.assertIn("agendar_maximizacao_workspace_f3", installer)

    def test_old_responsive_layer_is_not_installed_anymore(self):
        source = inspect.getsource(fast_gate.instalar_gate_rapido_check_esperado_display_f3)
        self.assertNotIn("instalar_configuracao_responsiva_display_f3", source)
        self.assertIn("instalar_performance_final_display_f3", source)

    def test_final_performance_layer_has_no_f2_runtime_dependency(self):
        source = inspect.getsource(performance)
        self.assertNotIn("src.platform.f2_", source)
        self.assertNotIn("F2Automatic", source)


if __name__ == "__main__":
    unittest.main()
