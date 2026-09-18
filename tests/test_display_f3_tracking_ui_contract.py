from __future__ import annotations

import inspect
import unittest

import src.platform.display_f3_tracking_orientation_ui as ui
import src.platform.display_f3_object_tracking as tracking


class F3TrackingUiContractTests(unittest.TestCase):
    def test_three_cardinal_orientation_slots_are_f3_owned(self):
        self.assertEqual(
            (
                tracking.F3_ORIENTATION_90,
                tracking.F3_ORIENTATION_180,
                tracking.F3_ORIENTATION_270,
            ),
            tracking.F3_ORIENTATION_SLOTS,
        )
        self.assertEqual(
            {90.0, 180.0, 270.0},
            set(tracking.F3_ORIENTATION_ANGLE.values()),
        )

    def test_configuration_exposes_requested_controls(self):
        source = inspect.getsource(ui._build_tracking_config_class)
        for text in (
            "Ativar rastreamento automático de objetos",
            "Capturar câmera",
            "Carregar imagem",
            "Desenhar placa",
            "Remover",
        ):
            self.assertIn(text, source)

    def test_editor_exposes_precision_workflow(self):
        source = inspect.getsource(ui.F3OrientationGeometryEditor)
        self.assertIn("<Control-z>", source)
        self.assertIn("<Control-Z>", source)
        self.assertIn("<MouseWheel>", source)
        self.assertIn("REDESENHAR PLACA", source)
        self.assertIn("F3_EDITOR_HISTORY_LIMIT", source)
        self.assertIn("mask_vertex", source)
        self.assertIn("radius", source)

    def test_guided_capture_uses_existing_f3_frame_provider(self):
        source = inspect.getsource(ui.F3GuidedOrientationCaptureWindow)
        self.assertIn("self.owner.frame_provider()", source)
        self.assertNotIn("VideoCapture(", source)

    def test_runtime_guard_requires_tracking_lock_before_auto_analysis(self):
        source = inspect.getsource(
            tracking.instalar_runtime_rastreamento_objetos_display_f3
        )
        self.assertIn("_process_display_auto_check", source)
        self.assertIn('status.get("locked")', source)
        self.assertIn(
            "DisplayAutomaticCheckF3Mixin._atualizar_preview_display_f3",
            source,
        )


if __name__ == "__main__":
    unittest.main()
