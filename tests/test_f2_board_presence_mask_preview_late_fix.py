from __future__ import annotations

import inspect
import unittest

import src.platform.f2_board_presence_mask_preview_late_fix as module


class F2BoardPresenceMaskPreviewLateFixTests(unittest.TestCase):
    def test_final_hook_targets_application_class_above_mro(self):
        source = inspect.getsource(module)
        self.assertIn("RaspberryPi3ProductionApp.abrir_configuracoes", source)
        self.assertIn("_odin_f2_mask_preview_final_hook", source)
        self.assertIn("_f2_board_presence_refs", source)

    def test_final_renderer_bakes_masks_into_preview_and_reapplies_after_tk(self):
        source = inspect.getsource(module)
        self.assertIn("criar_imagem_preview_presenca_com_mascaras_f2", source)
        self.assertIn("window.after", source)
        self.assertIn("0, 80, 220", source)
        self.assertIn("_odin_f2_board_presence_mask_preview_diagnostic", source)

    def test_diagnostic_distinguishes_missing_and_out_of_bounds_rois(self):
        source = inspect.getsource(module)
        self.assertIn("0 ROIs carregadas", source)
        self.assertIn("ROIs fora da referência", source)
        self.assertIn("visible_roi_count", source)
        self.assertIn("[F2 MASK PREVIEW]", source)

    def test_fix_is_f2_only(self):
        source = inspect.getsource(module).lower()
        self.assertNotIn("display_f3", source)
        self.assertNotIn("check_f3", source)


if __name__ == "__main__":
    unittest.main()
