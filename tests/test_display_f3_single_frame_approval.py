from __future__ import annotations

import inspect
import unittest

import src.platform.display_f3_h1_single_frame_probe as probe_module
import src.platform.display_f3_live_diagnostic_trace as trace_module
import src.platform.display_f3_single_frame_approval as module
from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin


class _App:
    @staticmethod
    def _display_auto_is_transient_check(context):
        return str((context or {}).get("check_name") or "").upper() == "BLUE"


class DisplayF3SingleFrameApprovalTests(unittest.TestCase):
    def setUp(self):
        self.original_ok_frames = DisplayAutomaticCheckF3Mixin.DISPLAY_AUTO_OK_STABLE_FRAMES
        self.original_probe_function = probe_module.frames_necessarios_sonda_positiva_f3
        self.original_trace_function = trace_module._probe_required_frames
        self.original_installed = module._INSTALLED
        module._INSTALLED = False

    def tearDown(self):
        DisplayAutomaticCheckF3Mixin.DISPLAY_AUTO_OK_STABLE_FRAMES = self.original_ok_frames
        probe_module.frames_necessarios_sonda_positiva_f3 = self.original_probe_function
        trace_module._probe_required_frames = self.original_trace_function
        module._INSTALLED = self.original_installed

    def test_h1_e_checks_estaveis_exigem_dois_frames(self):
        contexts = [
            {"current_index": 0, "check_name": "H1"},
            {"current_index": 2, "check_name": "USB"},
            {"current_index": 3, "check_name": "AUX"},
            {"current_index": 4, "check_name": "CHECK_FUTURO_5"},
        ]
        for context in contexts:
            with self.subTest(context=context):
                self.assertEqual(
                    2,
                    module.frames_necessarios_aprovacao_f3(_App(), context),
                )

    def test_blue_transitorio_continua_em_um_frame(self):
        self.assertEqual(
            1,
            module.frames_necessarios_aprovacao_f3(
                _App(),
                {"current_index": 1, "check_name": "BLUE"},
            ),
        )

    def test_instalador_unifica_runtime_e_sonda_sem_reduzir_h1_para_um_frame(self):
        DisplayAutomaticCheckF3Mixin.DISPLAY_AUTO_OK_STABLE_FRAMES = 1
        module.instalar_aprovacao_um_frame_display_f3()

        self.assertEqual(2, DisplayAutomaticCheckF3Mixin.DISPLAY_AUTO_OK_STABLE_FRAMES)
        self.assertIs(
            module.frames_necessarios_aprovacao_f3,
            probe_module.frames_necessarios_sonda_positiva_f3,
        )
        self.assertIs(
            module.frames_necessarios_aprovacao_f3,
            trace_module._probe_required_frames,
        )
        self.assertTrue(
            getattr(
                DisplayAutomaticCheckF3Mixin,
                "_display_f3_single_frame_approval_installed",
                False,
            )
        )

    def test_ng_nao_e_reduzido_por_esta_regra(self):
        original_ng = DisplayAutomaticCheckF3Mixin.DISPLAY_AUTO_NG_STABLE_FRAMES
        module.instalar_aprovacao_um_frame_display_f3()
        self.assertEqual(original_ng, DisplayAutomaticCheckF3Mixin.DISPLAY_AUTO_NG_STABLE_FRAMES)

    def test_modulo_nao_depende_do_f2(self):
        source = inspect.getsource(module)
        self.assertNotIn("src.platform.f2_", source)
        self.assertNotIn("F2Automatic", source)


if __name__ == "__main__":
    unittest.main()
