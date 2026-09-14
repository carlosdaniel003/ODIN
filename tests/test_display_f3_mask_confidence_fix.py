from __future__ import annotations

import inspect
import unittest

import src.platform.display_f3_mask_confidence_fix as fix
import src.platform.display_f3_strict_mask_conformity as strict_module
import src.platform.display_live_roi_overlay as overlay_module


class _FakeApp:
    def __init__(self, matched: int, active: int, approved: bool = True) -> None:
        self._display_auto_last_analysis = {
            "ready": True,
            "approved": approved,
            "project_name": "CM-550-L",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "active_mask_count": active,
            "matched_mask_count": matched,
            "reference_authority": "f3_strict_cross_check_mask_states",
            "mask_results": [
                {"mask_id": f"MASK_{index:03d}", "matched": index <= matched}
                for index in range(1, active + 1)
            ],
        }

    @staticmethod
    def _display_auto_current_context():
        return {
            "project_name": "CM-550-L",
            "check_id": "CHECK_001",
            "check_name": "H1",
        }


class DisplayF3MaskConfidenceFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fix.instalar_correcao_confianca_mascaras_display_f3()

    def test_28_de_28_confirma_check_atual_para_status_visual(self):
        confirmed = fix._analysis_confirms_current_check(
            _FakeApp(matched=28, active=28),
            "CM-550-L",
        )
        self.assertIsNotNone(confirmed)
        self.assertEqual(confirmed["check_id"], "CHECK_001")
        self.assertEqual(confirmed["check_name"], "H1")
        self.assertEqual(confirmed["matched"], 28)

    def test_26_de_28_nao_pode_desambiguar_status_visual(self):
        confirmed = fix._analysis_confirms_current_check(
            _FakeApp(matched=26, active=28),
            "CM-550-L",
        )
        self.assertIsNone(confirmed)

    def test_paleta_preview_f3_segue_convencao_operacional(self):
        self.assertEqual(
            overlay_module.DISPLAY_ROI_OVERLAY_COLORS["on"],
            fix.F3_PREVIEW_ON_BGR,
        )
        self.assertEqual(
            overlay_module.DISPLAY_ROI_OVERLAY_COLORS["off"],
            fix.F3_PREVIEW_OFF_BGR,
        )
        self.assertEqual(
            overlay_module.DISPLAY_ROI_OVERLAY_COLORS["low_light"],
            fix.F3_PREVIEW_LOW_LIGHT_BGR,
        )
        self.assertEqual(
            strict_module.F3_STRICT_FAILED_MASK_BGR,
            fix.F3_PREVIEW_FAILURE_BGR,
        )
        self.assertIn("VERDE: ACESO", fix.F3_PREVIEW_LEGEND)
        self.assertIn("AMARELO: POUCA LUZ", fix.F3_PREVIEW_LEGEND)
        self.assertIn("VERMELHO: FALHA", fix.F3_PREVIEW_LEGEND)
        self.assertIn("AZUL: APAGADO", fix.F3_PREVIEW_LEGEND)

    def test_board_off_vira_referencia_off_da_mesma_mascara(self):
        source = inspect.getsource(fix._append_board_off_same_mask_samples)
        self.assertIn("DISPLAY_PROJECT_REFERENCE_BOARD_OFF", source)
        self.assertIn("profile[DISPLAY_CHECK_STATE_OFF].append(features)", source)
        self.assertIn("mask_id", source)

    def test_correcao_permanece_isolada_de_f2(self):
        source = inspect.getsource(fix)
        self.assertNotIn("src.platform.f2_", source)
        self.assertNotIn("F2Automatic", source)


if __name__ == "__main__":
    unittest.main()
