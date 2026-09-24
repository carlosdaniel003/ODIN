from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace

import src.platform.display_f3_mask_status as mask_status_module
from src.platform.display_f3_mask_status import (
    F3_MASK_STATUS_COLORS,
    formatar_status_mascaras_f3,
)


class DisplayF3MaskStatusTests(unittest.TestCase):
    def test_h1_detectado_mostra_conformidade_e_leitura_das_mascaras(self):
        context = {
            "project_name": "DISPLAY_TESTE",
            "check_id": "h1",
            "check_name": "H1",
        }
        analysis = {
            "ready": True,
            "approved": True,
            "project_name": "DISPLAY_TESTE",
            "check_id": "h1",
            "check_name": "H1",
            "active_mask_count": 3,
            "matched_mask_count": 3,
            "mask_results": [
                {"classified": "on", "matched": True},
                {"classified": "on", "matched": True},
                {"classified": "on", "matched": True},
            ],
        }

        text, color = formatar_status_mascaras_f3(analysis, context)

        self.assertIn("MÁSCARAS • H1 DETECTADO", text)
        self.assertIn("3/3 CONFORMES", text)
        self.assertIn("3 ACESOS", text)
        self.assertEqual(F3_MASK_STATUS_COLORS["detected"], color)

    def test_leitura_parcial_mostra_aceso_apagado_e_pouca_luz(self):
        context = {
            "project_name": "DISPLAY_TESTE",
            "check_id": "usb",
            "check_name": "USB",
        }
        analysis = {
            "ready": True,
            "approved": False,
            "project_name": "DISPLAY_TESTE",
            "check_id": "usb",
            "check_name": "USB",
            "active_mask_count": 3,
            "matched_mask_count": 1,
            "mask_results": [
                {"classified": "on", "matched": True},
                {"classified": "off", "matched": False},
                {"classified": "low_light", "matched": False},
            ],
        }

        text, color = formatar_status_mascaras_f3(analysis, context)

        self.assertIn("MÁSCARAS • USB NÃO CONFIRMADO", text)
        self.assertIn("1/3 CONFORMES", text)
        self.assertIn("1 ACESO", text)
        self.assertIn("1 APAGADO", text)
        self.assertIn("1 POUCA LUZ", text)
        self.assertEqual(F3_MASK_STATUS_COLORS["partial"], color)

    def test_status_usa_contagem_e_classificacao_efetivas(self):
        context = {
            "project_name": "DISPLAY_TESTE",
            "check_id": "blue",
            "check_name": "BLUE",
        }
        analysis = {
            "ready": True,
            "approved": False,
            "project_name": "DISPLAY_TESTE",
            "check_id": "blue",
            "active_mask_count": 2,
            "matched_mask_count": 0,
            "effective_matched_mask_count": 1,
            "effective_classifications": {
                "MASK_010": "on",
                "MASK_027": "off",
            },
            "effective_failed_mask_ids": ("MASK_027",),
            "mask_results": [
                {"mask_id": "MASK_010", "classified": "off", "matched": False},
                {"mask_id": "MASK_027", "classified": "off", "matched": False},
            ],
        }
        text, _color = formatar_status_mascaras_f3(analysis, context)
        self.assertIn("1/2 CONFORMES", text)
        self.assertIn("1 ACESO", text)
        self.assertIn("1 APAGADO", text)

    def test_status_expoe_blue_bluf_quando_assinatura_diverge(self):
        context = {
            "project_name": "DISPLAY_TESTE",
            "check_id": "blue",
            "check_name": "BLUE",
        }
        analysis = {
            "ready": True,
            "approved": False,
            "project_name": "DISPLAY_TESTE",
            "check_id": "blue",
            "active_mask_count": 28,
            "effective_matched_mask_count": 27,
            "effective_classifications": {
                "MASK_024": "off",
            },
            "mask_results": [
                {"mask_id": "MASK_024", "classified": "off", "matched": False},
            ],
            "segment_signature": {
                "expected": "BLUE",
                "observed": "BLUF",
                "failed_mask_ids": ("MASK_024",),
            },
        }
        text, _color = formatar_status_mascaras_f3(analysis, context)
        self.assertIn("27/28 CONFORMES", text)
        self.assertIn("PADRÃO BLUF≠BLUE", text)

    def test_status_nao_publica_28_apagados_enquanto_tracking_sem_lock(self):
        class _Window:
            def __init__(self):
                self.last = None

            def set_mask_analysis_status(self, text, color):
                self.last = (text, color)

        window = _Window()
        app = SimpleNamespace(
            display_f3_ativo=True,
            display_f3_window=window,
            _display_auto_current_context=lambda: {
                "project_name": "DISPLAY_TESTE",
                "check_id": "blue",
                "check_name": "BLUE",
            },
            _display_f3_object_tracking_last_status={
                "enabled": True,
                "locked": False,
                "reason": "object_not_locked",
            },
            _display_auto_last_analysis={
                "ready": True,
                "project_name": "DISPLAY_TESTE",
                "check_id": "blue",
                "active_mask_count": 28,
                "matched_mask_count": 10,
                "mask_results": [
                    {"classified": "off", "matched": False}
                    for _ in range(28)
                ],
            },
        )

        mask_status_module._publish_mask_status(app)

        self.assertIsNotNone(window.last)
        self.assertEqual(
            "MÁSCARAS • BLUE: AGUARDANDO RASTREAMENTO",
            window.last[0],
        )
        self.assertNotIn("28 APAGADOS", window.last[0])

    def test_analise_de_outro_check_nao_vaza_para_status_atual(self):
        context = {
            "project_name": "DISPLAY_TESTE",
            "check_id": "blue",
            "check_name": "BLUE",
        }
        analysis = {
            "ready": True,
            "approved": True,
            "project_name": "DISPLAY_TESTE",
            "check_id": "h1",
            "active_mask_count": 2,
            "matched_mask_count": 2,
            "mask_results": [],
        }

        text, color = formatar_status_mascaras_f3(analysis, context)

        self.assertEqual("MÁSCARAS • BLUE: AGUARDANDO LEITURA", text)
        self.assertEqual(F3_MASK_STATUS_COLORS["waiting"], color)

    def test_analise_indisponivel_explica_motivo(self):
        context = {
            "project_name": "DISPLAY_TESTE",
            "check_id": "aux",
            "check_name": "AUX",
        }
        analysis = {
            "ready": False,
            "approved": None,
            "reason": "aprendizado_incompleto",
            "project_name": "DISPLAY_TESTE",
            "check_id": "aux",
            "mask_results": [],
        }

        text, color = formatar_status_mascaras_f3(analysis, context)

        self.assertIn("MÁSCARAS • AUX: INDISPONÍVEL", text)
        self.assertIn("APRENDIZADO INCOMPLETO", text)
        self.assertEqual(F3_MASK_STATUS_COLORS["unavailable"], color)

    def test_segundo_status_fica_abaixo_do_status_fisico(self):
        source = inspect.getsource(mask_status_module._install_mask_status_window)
        self.assertIn("_display_operational_status_box", source)
        self.assertIn("mask_analysis_state_label", source)
        self.assertIn("row=1", source)
        self.assertIn("status_box.configure(height=76)", source)

    def test_status_de_mascaras_e_apenas_diagnostico(self):
        source = inspect.getsource(mask_status_module._install_mask_status_runtime)
        self.assertIn("_publish_mask_status", source)
        self.assertNotIn("registrar_resultado_check_display_f3", source)
        self.assertNotIn("decidir_analise_display_f3", source)

    def test_modulo_nao_importa_f2(self):
        source = inspect.getsource(mask_status_module)
        self.assertNotIn("src.platform.f2_", source)

    def test_perfil_final_instala_status_de_mascaras_apos_runtime_ao_vivo(self):
        from src.platform.raspberry_pi3_production_app import RaspberryPi3ProductionApp

        source = inspect.getsource(RaspberryPi3ProductionApp.__init__)
        live_index = source.index("instalar_runtime_ao_vivo_display_f3()")
        mask_index = source.index("instalar_status_mascaras_display_f3()")
        super_index = source.index("super().__init__(root)")
        self.assertLess(live_index, mask_index)
        self.assertLess(mask_index, super_index)


if __name__ == "__main__":
    unittest.main()
