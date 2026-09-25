from __future__ import annotations

import inspect
import unittest

from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin
from src.platform.display_f3_optical_power_reconciliation import (
    reconciliar_estado_operacional_com_evidencia_optica_f3,
)
from src.platform.desktop_production_app import DesktopProductionApp


class _DummyApp:
    def __init__(self, analysis: dict | None = None) -> None:
        self._display_auto_last_analysis = analysis
        self._display_f3_waiting_empty_rearm = False
        self._display_f3_waiting_new_board_after_empty = False

    def _display_auto_has_manual_entry_evidence(self, analysis: dict) -> bool:
        return DisplayAutomaticCheckF3Mixin._display_auto_has_manual_entry_evidence(
            analysis
        )


class DisplayF3OpticalPowerReconciliationTests(unittest.TestCase):
    @staticmethod
    def _context() -> dict:
        return {
            "project_name": "TESTE",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "current_index": 0,
        }

    @staticmethod
    def _off_state() -> dict:
        return {
            "kind": "off",
            "text": "PLACA NO SUPORTE • DESLIGADA",
            "color": "#FBBF24",
            "allow_auto": False,
            "board_references_complete": True,
            "current_check_reference_configured": True,
        }

    @staticmethod
    def _powered_analysis() -> dict:
        return {
            "ready": True,
            "approved": False,
            "project_name": "TESTE",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "mask_results": [
                {
                    "expected": "on",
                    "classified": "on",
                    "confidence": 0.99,
                    "matched": True,
                },
                {
                    "expected": "off",
                    "classified": "off",
                    "confidence": 0.98,
                    "matched": True,
                },
                {
                    "expected": "off",
                    "classified": "on",
                    "confidence": 0.97,
                    "matched": False,
                },
            ],
        }

    def test_mascara_acesa_libera_motor_quando_quadro_inteiro_parece_off(self):
        app = _DummyApp(self._powered_analysis())
        state = reconciliar_estado_operacional_com_evidencia_optica_f3(
            app,
            self._off_state(),
            self._context(),
        )

        self.assertEqual("check", state["kind"])
        self.assertTrue(state["allow_auto"])
        self.assertEqual("CHECK_001", state["check_id"])
        self.assertEqual("H1", state["check_name"])
        self.assertEqual("DISPLAY LIGADO • ANALISANDO H1", state["text"])
        self.assertTrue(state["optical_power_evidence"])
        self.assertEqual("off", state["physical_reference_kind"])

    def test_evidencia_optica_nao_aprova_check_sozinha(self):
        app = _DummyApp(self._powered_analysis())
        state = reconciliar_estado_operacional_com_evidencia_optica_f3(
            app,
            self._off_state(),
            self._context(),
        )

        # A análise usada no teste está reprovada por uma terceira máscara. A
        # reconciliação apenas libera o analisador; não converte isso em OK.
        self.assertFalse(app._display_auto_last_analysis["approved"])
        self.assertNotIn("approved", state)
        self.assertTrue(state["allow_auto"])

    def test_analise_de_outro_check_nao_pode_liberar_h1(self):
        analysis = self._powered_analysis()
        analysis["check_id"] = "CHECK_002"
        app = _DummyApp(analysis)

        state = reconciliar_estado_operacional_com_evidencia_optica_f3(
            app,
            self._off_state(),
            self._context(),
        )

        self.assertEqual("off", state["kind"])
        self.assertFalse(state["allow_auto"])

    def test_sem_segmento_aceso_estado_off_continua_bloqueado(self):
        analysis = self._powered_analysis()
        for item in analysis["mask_results"]:
            if item["expected"] == "on":
                item["classified"] = "off"
                item["matched"] = False
        app = _DummyApp(analysis)

        state = reconciliar_estado_operacional_com_evidencia_optica_f3(
            app,
            self._off_state(),
            self._context(),
        )

        self.assertEqual("off", state["kind"])
        self.assertFalse(state["allow_auto"])

    def test_empty_nunca_e_promovido_por_mascara(self):
        app = _DummyApp(self._powered_analysis())
        empty_state = {
            "kind": "empty",
            "text": "PLACA FORA DO SUPORTE",
            "allow_auto": False,
        }

        state = reconciliar_estado_operacional_com_evidencia_optica_f3(
            app,
            empty_state,
            self._context(),
        )

        self.assertEqual("empty", state["kind"])
        self.assertFalse(state["allow_auto"])

    def test_rearme_terminal_nao_pode_ser_furado_por_evidencia_optica(self):
        for attr in (
            "_display_f3_waiting_empty_rearm",
            "_display_f3_waiting_new_board_after_empty",
        ):
            app = _DummyApp(self._powered_analysis())
            setattr(app, attr, True)

            state = reconciliar_estado_operacional_com_evidencia_optica_f3(
                app,
                self._off_state(),
                self._context(),
            )

            self.assertEqual("off", state["kind"])
            self.assertFalse(state["allow_auto"])

    def test_perfil_final_instala_reconciliacao_depois_do_estado_fisico(self):
        source = inspect.getsource(DesktopProductionApp.__init__)
        physical_position = source.index("instalar_correcao_estado_fisico_display_f3()")
        optical_position = source.index(
            "instalar_reconciliacao_optica_estado_fisico_display_f3()"
        )
        live_position = source.index("instalar_runtime_ao_vivo_display_f3()")

        self.assertLess(physical_position, optical_position)
        self.assertLess(optical_position, live_position)


if __name__ == "__main__":
    unittest.main()
