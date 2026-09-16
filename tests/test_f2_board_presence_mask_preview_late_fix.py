from __future__ import annotations

import inspect
import unittest

import src.platform.f2_board_presence_mask_preview_late_fix as module


class F2BoardPresenceMaskPreviewLateFixTests(unittest.TestCase):
    def test_late_fix_targets_real_f2_settings_opening_path(self):
        source = inspect.getsource(module)
        self.assertIn("F2AutomaticCycleGuardMixin.abrir_configuracoes", source)
        self.assertIn("_f2_board_presence_refs", source)
        self.assertIn("_aplicar_mascaras_nas_previews", source)

    def test_overlay_is_reapplied_after_tk_composition(self):
        source = inspect.getsource(module)
        self.assertIn("window.after", source)
        self.assertIn("0, 60, 180, 350", source)
        self.assertIn("_odin_f2_board_presence_mask_preview_last_error", source)

    def test_fix_is_f2_only(self):
        source = inspect.getsource(module).lower()
        self.assertNotIn("display_f3", source)
        self.assertNotIn("check_f3", source)


if __name__ == "__main__":
    unittest.main()
