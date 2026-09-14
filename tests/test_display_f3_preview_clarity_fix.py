from __future__ import annotations

import inspect
import unittest

import src.platform.display_f3_preview_clarity_fix as clarity
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
)


class DisplayF3PreviewClarityFixTests(unittest.TestCase):
    def test_aceso_correto_fica_verde(self):
        self.assertEqual(
            DISPLAY_CHECK_STATE_ON,
            clarity.estado_visual_mascara_f3(
                DISPLAY_CHECK_STATE_ON,
                DISPLAY_CHECK_STATE_ON,
                has_any_on=True,
            ),
        )

    def test_apagado_correto_fica_vermelho_quando_placa_ja_acendeu(self):
        self.assertEqual(
            DISPLAY_CHECK_STATE_OFF,
            clarity.estado_visual_mascara_f3(
                DISPLAY_CHECK_STATE_OFF,
                DISPLAY_CHECK_STATE_OFF,
                has_any_on=True,
            ),
        )

    def test_pouca_luz_fica_amarela(self):
        self.assertEqual(
            "alert",
            clarity.estado_visual_mascara_f3(
                "low_light",
                DISPLAY_CHECK_STATE_ON,
                has_any_on=False,
            ),
        )

    def test_aceso_quando_deveria_apagado_fica_amarelo(self):
        self.assertEqual(
            "alert",
            clarity.estado_visual_mascara_f3(
                DISPLAY_CHECK_STATE_ON,
                DISPLAY_CHECK_STATE_OFF,
                has_any_on=True,
            ),
        )

    def test_apagado_quando_deveria_aceso_fica_amarelo_so_apos_placa_acender(self):
        self.assertEqual(
            "alert",
            clarity.estado_visual_mascara_f3(
                DISPLAY_CHECK_STATE_OFF,
                DISPLAY_CHECK_STATE_ON,
                has_any_on=True,
            ),
        )
        self.assertIsNone(
            clarity.estado_visual_mascara_f3(
                DISPLAY_CHECK_STATE_OFF,
                DISPLAY_CHECK_STATE_ON,
                has_any_on=False,
            )
        )

    def test_startup_todo_apagado_nao_pinta_h1_inteiro_de_vermelho(self):
        self.assertIsNone(
            clarity.estado_visual_mascara_f3(
                DISPLAY_CHECK_STATE_OFF,
                DISPLAY_CHECK_STATE_OFF,
                has_any_on=False,
            )
        )

    def test_preview_final_tem_apenas_verde_vermelho_amarelo(self):
        colors = clarity.F3_PREVIEW_CLEAR_COLORS
        self.assertEqual({"on", "off", "alert"}, set(colors))
        self.assertEqual(colors["alert"], (21, 204, 250))
        self.assertLessEqual(clarity.F3_PREVIEW_CLEAR_ALPHA, 0.10)
        self.assertNotIn("AZUL", clarity.F3_PREVIEW_CLEAR_LEGEND)
        self.assertNotIn("CINZA", clarity.F3_PREVIEW_CLEAR_LEGEND)
        self.assertIn("VERDE: ACESO", clarity.F3_PREVIEW_CLEAR_LEGEND)
        self.assertIn("VERMELHO: APAGADO", clarity.F3_PREVIEW_CLEAR_LEGEND)
        self.assertIn("AMARELO: POUCA LUZ / DIVERGÊNCIA", clarity.F3_PREVIEW_CLEAR_LEGEND)

    def test_render_nao_escreve_ng_sobre_segmento(self):
        source = inspect.getsource(clarity.renderizar_preview_claro_display_f3)
        self.assertNotIn("putText", source)
        self.assertNotIn("NG ", source)

    def test_modulo_permanece_isolado_de_f2(self):
        source = inspect.getsource(clarity)
        self.assertNotIn("src.platform.f2_", source)
        self.assertNotIn("F2Automatic", source)


if __name__ == "__main__":
    unittest.main()
