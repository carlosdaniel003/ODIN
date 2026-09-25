from __future__ import annotations

import inspect
import unittest

import src.platform.display_f3_status_layout_fix as fix_module
from src.platform.display_f3_status_layout_fix import (
    F3_CHECK_CARD_HEIGHT,
    format_board_status_f3,
    format_display_status_f3,
)
from src.platform.display_visual_reference_status import (
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
    DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
)
from src.platform.desktop_production_app import DesktopProductionApp


class DisplayF3StatusLayoutFixTests(unittest.TestCase):
    def test_status_display_remove_percentual_e_exibe_nome_do_check(self):
        text, _color = format_display_status_f3(
            {
                "configured_count": 4,
                "camera": True,
                "matched": True,
                "best": {"name": "H1", "score": 0.88},
            }
        )
        self.assertEqual("STATUS DO DISPLAY: H1", text)
        self.assertNotIn("%", text)

        blue_text, _ = format_display_status_f3(
            {
                "configured_count": 4,
                "camera": True,
                "matched": True,
                "best": {"name": "BLUE", "score": 0.93},
            }
        )
        self.assertEqual("STATUS DO DISPLAY: BLUE", blue_text)
        self.assertNotIn("%", blue_text)

    def test_status_placa_mostra_apenas_presenca_sem_percentual(self):
        present, _ = format_board_status_f3(
            {
                "configured_count": 2,
                "required_count": 2,
                "camera": True,
                "matched": True,
                "best": {
                    "kind": DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                    "score": 0.88,
                },
            }
        )
        self.assertEqual("STATUS DA PLACA: PLACA NO SUPORTE", present)
        self.assertNotIn("%", present)
        self.assertNotIn("DESLIGADA", present)

        absent, _ = format_board_status_f3(
            {
                "configured_count": 2,
                "required_count": 2,
                "camera": True,
                "matched": True,
                "best": {
                    "kind": DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
                    "score": 0.95,
                },
            }
        )
        self.assertEqual("STATUS DA PLACA: PLACA FORA DO SUPORTE", absent)
        self.assertNotIn("%", absent)

    def test_status_visual_e_criado_no_preview_da_direita(self):
        source = inspect.getsource(fix_module._install_status_on_preview_right)
        self.assertIn("self.preview_header", source)
        self.assertIn("old_status_box.destroy()", source)
        self.assertIn("STATUS DA PLACA: IDENTIFICANDO", source)
        self.assertIn("STATUS DO DISPLAY: IDENTIFICANDO", source)
        self.assertNotIn("self.project_frame", source)

    def test_cards_mantem_altura_e_borda_constantes_entre_resultados(self):
        source = inspect.getsource(fix_module._render_check_cards_f3_fixed)
        self.assertIn("height=F3_CHECK_CARD_HEIGHT", source)
        self.assertIn("card.grid_propagate(False)", source)
        self.assertIn("highlightthickness=2", source)
        self.assertGreater(F3_CHECK_CARD_HEIGHT, 0)
        # A espessura não depende mais de current/completed/pending.
        self.assertNotIn('2 if state == "current" else 1', source)

    def test_estado_f3_nao_forca_update_idletasks_nem_troca_tamanho_de_fonte(self):
        source = inspect.getsource(fix_module._set_state_f3_without_reflow)
        self.assertNotIn("update_idletasks", source)
        self.assertIn("font=F3_STATUS_FONT", source)
        self.assertIn("height=1", source)
        self.assertIn("font=F3_DETAIL_FONT", source)
        self.assertIn("height=2", source)

    def test_perfil_final_instala_fix_apos_status_visual(self):
        source = inspect.getsource(DesktopProductionApp.__init__)
        status_pos = source.index("instalar_status_referencias_visuais_display()")
        fix_pos = source.index("instalar_layout_status_f3_estavel()")
        self.assertLess(status_pos, fix_pos)


if __name__ == "__main__":
    unittest.main()
