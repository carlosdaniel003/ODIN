from __future__ import annotations

import inspect
import unittest

import src.platform.display_f3_tracking_orientation_ui as ui
import src.platform.display_f3_object_tracking as tracking


class F3TrackingUiContractTests(unittest.TestCase):
    def test_configuration_has_no_rotation_slot_controls(self):
        source = inspect.getsource(ui._build_tracking_config_class)
        self.assertIn("Ativar rastreamento automático de objetos", source)
        self.assertIn("CONTORNO + SEGMENTOS LUMINOSOS", source)
        for removed in (
            "Capturar câmera",
            "Carregar imagem",
            "Desenhar placa e máscaras",
            "Rotação real 90°",
            "Rotação real 180°",
            "Rotação real 270°",
            "CARREGANDO PREVIEW",
        ):
            self.assertNotIn(removed, source)

    def test_tracking_store_contract_has_no_orientation_bank(self):
        source = inspect.getsource(tracking.F3TrackingConfigStore)
        self.assertNotIn("orientations", source)
        self.assertNotIn("managed_image_path", source)
        self.assertNotIn("save_orientation", source)
        self.assertIn("save_board_points", source)

    def test_tracker_configuration_does_not_load_angular_images(self):
        source = inspect.getsource(tracking.F3DisplayObjectTracker.configure)
        self.assertNotIn("F3_ORIENTATION", source)
        self.assertNotIn('source_type="orientation"', source)
        self.assertIn("_calibrated_reference_specs", source)

    def test_configuration_marks_tracking_as_paused_while_open(self):
        source = inspect.getsource(ui._build_tracking_config_class)
        self.assertIn("_display_f3_tracking_config_open = True", source)
        self.assertIn("_display_f3_tracking_config_open = False", source)

    def test_runtime_guard_requires_tracking_lock_before_auto_analysis(self):
        source = inspect.getsource(tracking.instalar_runtime_rastreamento_objetos_display_f3)
        self.assertIn("_process_display_auto_check", source)
        self.assertIn('status.get("locked")', source)
        self.assertIn("_display_f3_waiting_empty_rearm", source)
        self.assertIn("_display_f3_waiting_new_board_after_empty", source)

    def test_runtime_keeps_luminous_segment_refinement(self):
        source = inspect.getsource(tracking.align_frame_for_f3)
        self.assertIn("_rescue_luminous_segment_tracking_lock", source)
        fit_source = inspect.getsource(tracking._find_luminous_segment_pose)
        self.assertIn("_detect_luminous_segment_centers", fit_source)
        self.assertIn("_fit_luminous_pose", fit_source)


if __name__ == "__main__":
    unittest.main()
