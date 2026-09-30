from __future__ import annotations

import inspect
import unittest

import src.platform.display_f3_segregate_action as segregate_module
from src.platform.display_production_f3_window import DisplayProductionF3Window
from src.platform.desktop_production_app import DesktopProductionApp


class DisplayF3SegregateActionTests(unittest.TestCase):
    def test_interface_produtiva_usa_segregar_placa(self):
        self.assertEqual("SEGREGAR PLACA  [1]", segregate_module.SEGREGATE_BUTTON_TEXT)
        self.assertIn("SEGREGAR PLACA", segregate_module.SEGREGATE_FOOTER_TEXT)
        self.assertEqual("PLACA SEGREGADA", segregate_module.SEGREGATE_RESULT_TEXT)
        self.assertNotIn("DESCARTAR", segregate_module.SEGREGATE_BUTTON_TEXT)
        self.assertNotIn("DESCARTAR", segregate_module.SEGREGATE_FOOTER_TEXT)
        self.assertNotIn("DESCARTADA", segregate_module.SEGREGATE_RESULT_TEXT)

    def test_instalador_altera_somente_a_apresentacao_da_janela_f3(self):
        segregate_module.instalar_acao_segregar_placa_display_f3()
        self.assertTrue(DisplayProductionF3Window._odin_display_f3_segregate_action)

        init_source = inspect.getsource(DisplayProductionF3Window.__init__)
        result_source = inspect.getsource(DisplayProductionF3Window.show_plate_result)
        self.assertIn("SEGREGATE_BUTTON_TEXT", init_source)
        self.assertIn("SEGREGATE_FOOTER_TEXT", init_source)
        self.assertIn("SEGREGATE_RESULT_TEXT", result_source)
        self.assertIn("discarded", result_source)

    def test_atalho_1_global_funciona_com_foco_em_widget_filho(self):
        class _Container:
            def __init__(self, mapped: bool) -> None:
                self.mapped = mapped

            def winfo_ismapped(self):
                return self.mapped

        calls = []
        window = DisplayProductionF3Window.__new__(
            DisplayProductionF3Window
        )
        window.container = _Container(True)
        window.on_discard = lambda: calls.append("segregar")

        result = window._handle_global_discard()

        self.assertEqual("break", result)
        self.assertEqual(["segregar"], calls)

        window.container.mapped = False
        self.assertIsNone(window._handle_global_discard())
        self.assertEqual(["segregar"], calls)

    def test_atalho_1_e_numpad_1_sao_capturados_no_toplevel_sem_sobrescrever_bindings(self):
        source = inspect.getsource(DisplayProductionF3Window.__init__)
        self.assertIn(
            'self.root.bind(\n            "<KeyPress-1>",',
            source,
        )
        self.assertIn(
            'self.root.bind(\n            "<KP_1>",',
            source,
        )
        self.assertGreaterEqual(source.count('add="+"'), 2)
        self.assertIn("_handle_global_discard", source)

    def test_botao_e_teclas_usam_a_mesma_acao_de_segregacao(self):
        init_source = inspect.getsource(DisplayProductionF3Window.__init__)
        discard_source = inspect.getsource(DisplayProductionF3Window._discard_plate)
        self.assertIn("command=self._discard_plate", init_source)
        self.assertIn(
            'self.container.bind("<KeyPress-1>", self._handle_discard)',
            init_source,
        )
        self.assertIn("_handle_global_discard", init_source)
        self.assertIn("self.on_discard()", discard_source)

    def test_snapshot_nao_reverte_resultado_terminal_para_h1_antes_do_rearme(self):
        state_changes = []
        rendered = []
        window = DisplayProductionF3Window.__new__(
            DisplayProductionF3Window
        )
        window._display_ng_evidence_frozen = False
        window._display_terminal_waiting_removal = True
        window._display_waiting_new_board_ui = False
        window._check_snapshot = {}
        window._set_counters = lambda *_args: None
        window._render_check_cards = lambda snapshot, **_kwargs: rendered.append(snapshot)
        window._set_state = lambda **kwargs: state_changes.append(kwargs)

        snapshot = {
            "checks": [{"id": "CHECK_001", "name": "H1", "state": "current"}],
            "current_check": {"id": "CHECK_001", "name": "H1"},
            "current_index": 0,
            "total": 1,
            "ok": 0,
            "ng": 1,
        }
        window.set_check_sequence(snapshot)

        self.assertEqual([], state_changes)
        self.assertEqual([snapshot], rendered)

    def test_nova_placa_confirmada_reativa_segregar_e_fluxo(self):
        class _Button:
            def __init__(self):
                self.state = "disabled"

            def configure(self, **kwargs):
                if "state" in kwargs:
                    self.state = kwargs["state"]

        snapshots = []
        window = DisplayProductionF3Window.__new__(
            DisplayProductionF3Window
        )
        window.discard_button = _Button()
        window._display_terminal_waiting_removal = True
        window._display_waiting_new_board_ui = True
        window.set_check_sequence = lambda snapshot: snapshots.append(snapshot)

        snapshot = {"current_check": {"id": "CHECK_001", "name": "H1"}}
        window.release_terminal_rearm(snapshot)

        self.assertFalse(window._display_terminal_waiting_removal)
        self.assertFalse(window._display_waiting_new_board_ui)
        self.assertEqual("normal", window.discard_button.state)
        self.assertEqual([snapshot], snapshots)

    def test_segregacao_terminal_mantem_cards_e_chrome_vermelhos(self):
        result_source = inspect.getsource(DisplayProductionF3Window.show_plate_result)
        cards_source = inspect.getsource(DisplayProductionF3Window._render_check_cards)
        sequence_source = inspect.getsource(DisplayProductionF3Window.set_check_sequence)
        chrome_source = inspect.getsource(
            DisplayProductionF3Window._set_terminal_segregation_chrome
        )

        self.assertIn('"segregated" if discarded else "ng"', result_source)
        self.assertIn("force_terminal_segregated=bool(discarded)", result_source)
        self.assertIn("PLACA SEGREGADA", result_source)
        self.assertIn('status = "SEGREGADO"', cards_source)
        self.assertIn("self.COLOR_NG", cards_source)
        self.assertIn("force_terminal_segregated=", sequence_source)
        self.assertIn("self.DISPLAY_READOUT_NG", chrome_source)

    def test_mascaras_nao_sao_forcadas_para_vermelho_pela_segregacao(self):
        result_source = inspect.getsource(DisplayProductionF3Window.show_plate_result)
        self.assertNotIn("live_visual_classifications", result_source)
        self.assertNotIn("failed_mask_ids", result_source)

    def test_desktop_instala_segregar_antes_de_construir_janela_f3(self):
        source = inspect.getsource(DesktopProductionApp.__init__)
        self.assertIn("instalar_acao_segregar_placa_display_f3()", source)
        self.assertLess(
            source.index("instalar_acao_segregar_placa_display_f3()"),
            source.index("super().__init__(root)"),
        )

    def test_extensao_de_segregacao_nao_importa_f2(self):
        source = inspect.getsource(segregate_module)
        self.assertNotIn("src.platform.f2_", source)
        self.assertNotIn("operacao_total", source)
        self.assertNotIn("operacao_ok", source)
        self.assertNotIn("operacao_ng", source)


if __name__ == "__main__":
    unittest.main()
