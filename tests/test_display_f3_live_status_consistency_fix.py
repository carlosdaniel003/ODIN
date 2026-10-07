from __future__ import annotations

import unittest

from src.platform.display_f3_live_status_consistency_fix import (
    F3_INITIAL_FRAME_PLACEHOLDER,
    F3_LEGACY_REFERENCE_PLACEHOLDER,
    corrigir_placeholder_inicial_f3,
    resolver_status_visual_runtime_f3,
)


class _Label:
    def __init__(self, text):
        self.text = text

    def cget(self, key):
        if key == "text":
            return self.text
        raise KeyError(key)

    def configure(self, **kwargs):
        if "text" in kwargs:
            self.text = kwargs["text"]


class _Window:
    def __init__(self, text=F3_LEGACY_REFERENCE_PLACEHOLDER):
        self.visual_analysis_state_label = _Label(text)


class _App:
    def __init__(self):
        self._display_f3_waiting_empty_rearm = False
        self._display_f3_waiting_new_board_after_empty = False
        self._display_auto_last_analysis = None

    @staticmethod
    def _display_auto_current_context():
        return {
            "project_name": "CM-550-L",
            "check_id": "CHECK_002",
            "check_name": "BLUE",
        }


class DisplayF3LiveStatusConsistencyFixTests(unittest.TestCase):
    def test_placeholder_inicial_agora_e_divergencia(self):
        window = _Window()
        changed = corrigir_placeholder_inicial_f3(window)

        self.assertTrue(changed)
        self.assertEqual(
            F3_INITIAL_FRAME_PLACEHOLDER,
            window.visual_analysis_state_label.text,
        )
        self.assertTrue(
            window.visual_analysis_state_label.text.startswith("DIVERGÊNCIA")
        )
        self.assertNotIn(
            "ANÁLISE VISUAL",
            window.visual_analysis_state_label.text,
        )

    def test_divergencia_confirmada_e_publicada_em_qualquer_check(self):
        app = _App()
        app._display_auto_last_analysis = {
            "ready": True,
            "approved": False,
            "check_id": "CHECK_002",
            "mask_results": [
                {
                    "mask_id": "MASK_024",
                    "expected": "on",
                    "classified": "off",
                    "matched": False,
                }
            ],
            "effective_classifications": {"MASK_024": "off"},
            "effective_confirmed_failed_mask_ids": ("MASK_024",),
        }

        result = resolver_status_visual_runtime_f3(app)

        self.assertEqual(
            "DIVERGÊNCIA • MASK_024 • ESPERADO: ACESO • DETECTADO: APAGADO",
            result[0],
        )

    def test_sem_divergencia_mostra_check_conforme(self):
        app = _App()
        app._display_auto_last_analysis = {
            "ready": True,
            "approved": True,
            "check_id": "CHECK_002",
            "mask_results": [
                {
                    "mask_id": "MASK_024",
                    "expected": "on",
                    "classified": "on",
                    "matched": True,
                }
            ],
        }

        result = resolver_status_visual_runtime_f3(app)

        self.assertEqual(
            "DIVERGÊNCIA • NENHUMA • CHECK BLUE CONFORME",
            result[0],
        )

    def test_rearme_exibe_estado_da_divergencia_sem_matching_visual(self):
        app = _App()
        app._display_f3_waiting_empty_rearm = True

        waiting_remove = resolver_status_visual_runtime_f3(app)
        self.assertEqual(
            "DIVERGÊNCIA • NENHUMA • AGUARDANDO RETIRADA DA PLACA",
            waiting_remove[0],
        )

        app._display_f3_waiting_empty_rearm = False
        app._display_f3_waiting_new_board_after_empty = True
        waiting_new = resolver_status_visual_runtime_f3(app)
        self.assertEqual(
            "DIVERGÊNCIA • NENHUMA • AGUARDANDO NOVA PLACA",
            waiting_new[0],
        )

    def test_analise_stale_do_check_anterior_nao_vaza_para_blue(self):
        app = _App()
        app._display_auto_last_analysis = {
            "ready": True,
            "approved": False,
            "check_id": "CHECK_001",
            "mask_results": [
                {
                    "mask_id": "MASK_004",
                    "expected": "on",
                    "classified": "off",
                    "matched": False,
                }
            ],
            "effective_confirmed_failed_mask_ids": ("MASK_004",),
        }

        result = resolver_status_visual_runtime_f3(app)

        self.assertEqual(
            "DIVERGÊNCIA • NENHUMA • AGUARDANDO BLUE",
            result[0],
        )


if __name__ == "__main__":
    unittest.main()
