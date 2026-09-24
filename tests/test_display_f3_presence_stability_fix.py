from __future__ import annotations

import unittest

import src.platform.display_f3_presence_stability_fix as presence_module


class _App:
    pass


class DisplayF3PresenceStabilityTests(unittest.TestCase):
    def test_frame_real_com_placa_desligada_confirma_presenca(self):
        state = {
            "kind": "unknown",
            "reference_scores": {
                "check:CHECK_001": 0.8089,
                "check:CHECK_002": 0.8002,
                "check:CHECK_004": 0.7921,
                "check:CHECK_003": 0.7885,
                "off": 0.7879,
                "empty": 0.4089,
            },
        }
        result = presence_module.avaliar_presenca_melhor_ocupado_f3(state)
        self.assertTrue(result["board_present"])
        self.assertTrue(result["presence_confirmed"])
        self.assertEqual("check:CHECK_001", result["best_occupied_reference"])
        self.assertAlmostEqual(0.4000, result["occupied_over_empty_margin"], places=4)

    def test_ambiguidade_entre_checks_nao_significa_ausencia_da_placa(self):
        state = {
            "kind": "unknown",
            "ambiguous": True,
            "best_score": 0.8089,
            "second_score": 0.8002,
            "reference_scores": {
                "check:CHECK_001": 0.8089,
                "check:CHECK_002": 0.8002,
                "off": 0.7879,
                "empty": 0.4089,
            },
        }
        result = presence_module.avaliar_presenca_melhor_ocupado_f3(state)
        self.assertTrue(result["board_present"])
        self.assertEqual("melhor_cena_com_placa_supera_empty", result["reason"])

    def test_empty_explicito_vence_imediatamente(self):
        state = {
            "kind": "empty",
            "reference_scores": {
                "empty": 0.5867,
                "check:CHECK_001": 0.4130,
                "off": 0.3973,
            },
        }
        result = presence_module.avaliar_presenca_melhor_ocupado_f3(state)
        self.assertFalse(result["board_present"])
        self.assertTrue(result["empty_confirmed"])

    def test_hold_curto_evita_piscar_quando_um_frame_perde_scores(self):
        app = _App()
        confirmed = {
            "available": True,
            "board_present": True,
            "presence_confirmed": True,
            "empty_confirmed": False,
            "source": presence_module.F3_STABLE_PRESENCE_SOURCE,
        }
        first = presence_module._hold_presence(app, confirmed)
        self.assertTrue(first["board_present"])

        ambiguous = {
            "available": False,
            "board_present": False,
            "presence_confirmed": False,
            "empty_confirmed": False,
            "source": presence_module.F3_STABLE_PRESENCE_SOURCE,
        }
        held = presence_module._hold_presence(app, ambiguous)
        self.assertTrue(held["board_present"])
        self.assertTrue(held["held_from_previous_frame"])
        self.assertEqual(1, held["held_ambiguous_frames"])

    def test_intermitente_mantem_display_ligado_durante_fase_off(self):
        app = _App()
        state = {
            "kind": "unknown",
            "reference_scores": {
                "check:CHECK_002": 0.80,
                "off": 0.70,
                "empty": 0.30,
            },
            "power_evidence": {
                "energy_state": "powered",
                "powered_confirmed": True,
                "off_confirmed": False,
            },
        }
        context = {
            "check_id": "CHECK_002",
            "check_name": "BLUE",
            "intermittent": True,
        }
        first = presence_module._apply_final_presence(
            app, state, None, "DISPLAY", context
        )
        self.assertEqual("powered", first["kind"])

        off_phase = dict(state)
        off_phase["power_evidence"] = {
            "energy_state": "off",
            "powered_confirmed": False,
            "off_confirmed": True,
        }
        held = presence_module._apply_final_presence(
            app, off_phase, None, "DISPLAY", context
        )
        self.assertEqual("powered", held["kind"])
        self.assertTrue(held["power_evidence"]["intermittent_phase_hold"])
        self.assertIn("FASE OFF INTERMITENTE", held["text"])

    def test_hold_expira_sem_evidencia(self):
        app = _App()
        presence_module._hold_presence(
            app,
            {
                "available": True,
                "board_present": True,
                "presence_confirmed": True,
                "empty_confirmed": False,
            },
        )
        ambiguous = {
            "available": False,
            "board_present": False,
            "presence_confirmed": False,
            "empty_confirmed": False,
        }
        result = None
        for _ in range(presence_module.F3_PRESENCE_AMBIGUOUS_HOLD_FRAMES + 1):
            result = presence_module._hold_presence(app, ambiguous)
        self.assertFalse(result["board_present"])


if __name__ == "__main__":
    unittest.main()
