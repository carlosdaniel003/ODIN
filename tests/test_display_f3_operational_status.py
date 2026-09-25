from __future__ import annotations

import inspect
import unittest

import src.platform.display_f3_operational_status as operational_module
from src.platform.display_f3_operational_status import resolver_estado_operacional_f3
from src.platform.desktop_production_app import DesktopProductionApp


class DisplayF3OperationalStatusTests(unittest.TestCase):
    @staticmethod
    def _candidate(score: float, threshold: float = 0.72):
        return {
            "score": score,
            "threshold": threshold,
            "matched": score >= threshold,
        }

    def test_suporte_vazio_bloqueia_qualquer_check(self):
        state = resolver_estado_operacional_f3(
            empty_candidate=self._candidate(0.98),
            off_candidate=self._candidate(0.60),
            current_check_candidate=self._candidate(0.77),
            current_check_name="H1",
            current_check_id="CHECK_001",
            board_references_complete=True,
        )
        self.assertEqual("empty", state["kind"])
        self.assertEqual("PLACA FORA DO SUPORTE", state["text"])
        self.assertFalse(state["allow_auto"])

    def test_placa_desligada_bloqueia_h1_mesmo_com_similaridade_visual(self):
        state = resolver_estado_operacional_f3(
            empty_candidate=self._candidate(0.42),
            off_candidate=self._candidate(0.99),
            current_check_candidate=self._candidate(0.84),
            current_check_name="H1",
            current_check_id="CHECK_001",
            board_references_complete=True,
        )
        self.assertEqual("off", state["kind"])
        self.assertEqual("PLACA NO SUPORTE • DESLIGADA", state["text"])
        self.assertFalse(state["allow_auto"])

    def test_h1_vence_referencia_estrutural_da_placa_desligada(self):
        state = resolver_estado_operacional_f3(
            empty_candidate=self._candidate(0.31),
            off_candidate=self._candidate(0.88),
            current_check_candidate=self._candidate(0.96),
            current_check_name="H1",
            current_check_id="CHECK_001",
            board_references_complete=True,
        )
        self.assertEqual("check", state["kind"])
        self.assertEqual("DISPLAY EM H1", state["text"])
        self.assertTrue(state["allow_auto"])

    def test_blue_substitui_h1_quando_nova_referencia_fica_melhor(self):
        state = resolver_estado_operacional_f3(
            empty_candidate=self._candidate(0.35),
            off_candidate=self._candidate(0.81),
            current_check_candidate=self._candidate(0.97),
            current_check_name="BLUE",
            current_check_id="CHECK_002",
            last_check_candidate=self._candidate(0.86),
            last_check_name="H1",
            last_check_id="CHECK_001",
            board_references_complete=True,
        )
        self.assertEqual("check", state["kind"])
        self.assertEqual("DISPLAY EM BLUE", state["text"])
        self.assertEqual("CHECK_002", state["check_id"])

    def test_h1_permanece_durante_transicao_ate_blue_realmente_aparecer(self):
        state = resolver_estado_operacional_f3(
            empty_candidate=self._candidate(0.30),
            off_candidate=self._candidate(0.82),
            current_check_candidate=self._candidate(0.64),
            current_check_name="BLUE",
            current_check_id="CHECK_002",
            last_check_candidate=self._candidate(0.95),
            last_check_name="H1",
            last_check_id="CHECK_001",
            board_references_complete=True,
        )
        self.assertEqual("check", state["kind"])
        self.assertEqual("DISPLAY EM H1", state["text"])

    def test_sem_match_fisico_com_referencias_completas_fica_bloqueado(self):
        state = resolver_estado_operacional_f3(
            empty_candidate=self._candidate(0.55),
            off_candidate=self._candidate(0.61),
            current_check_candidate=self._candidate(0.66),
            current_check_name="USB",
            current_check_id="CHECK_003",
            board_references_complete=True,
        )
        self.assertEqual("unknown", state["kind"])
        self.assertEqual("IDENTIFICANDO...", state["text"])
        self.assertFalse(state["allow_auto"])

    def test_interface_possui_somente_um_status_operacional(self):
        source = inspect.getsource(operational_module._install_single_status_window)
        self.assertIn("operational_reference_state_label", source)
        self.assertIn("self.board_reference_state_label = None", source)
        self.assertIn("self.visual_reference_state_label = None", source)
        self.assertNotIn("score * 100", source)

    def test_status_fisico_nao_bloqueia_decisao_das_mascaras(self):
        source = inspect.getsource(operational_module._install_operational_auto_gate)
        self.assertIn("return original_process(self)", source)
        self.assertNotIn('kind in {"empty", "off"}', source)
        self.assertNotIn("allow_auto =", source)
        self.assertNotIn('kind == "check" and not allow_auto', source)
        self.assertIn("_display_f3_waiting_empty_rearm", source)
        self.assertIn("decisão", source)

    def test_perfil_final_instala_status_operacional_depois_do_layout(self):
        source = inspect.getsource(DesktopProductionApp.__init__)
        layout_position = source.index("instalar_layout_status_f3_estavel()")
        operational_position = source.index("instalar_status_operacional_display_f3()")
        self.assertLess(layout_position, operational_position)


if __name__ == "__main__":
    unittest.main()
