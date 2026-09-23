from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin


class DisplayF3H1ToBluetoothGateTests(unittest.TestCase):
    def test_h1_arms_bluetooth_gate_even_before_bluetooth_appears(self):
        app = DisplayAutomaticCheckF3Mixin.__new__(DisplayAutomaticCheckF3Mixin)
        app._display_auto_manual_entry_signature = None
        app._display_auto_manual_entry_label = ""

        context = {
            "project_name": "DISPLAY A",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "current_index": 0,
        }
        event = {
            "event": "check_advanced",
            "snapshot": {
                "current_check": {
                    "id": "CHECK_002",
                    "name": "BLUETOOTH",
                }
            },
        }

        app._display_auto_arm_manual_entry_gate(context, event)

        self.assertEqual(
            ("DISPLAY A", "CHECK_002"),
            app._display_auto_manual_entry_signature,
        )
        self.assertEqual("BLUETOOTH", app._display_auto_manual_entry_label)

    def test_qualquer_avanco_logico_arma_gate_fisico_do_proximo_check(self):
        app = DisplayAutomaticCheckF3Mixin.__new__(DisplayAutomaticCheckF3Mixin)
        app._display_auto_manual_entry_signature = None
        app._display_auto_manual_entry_label = ""

        context = {
            "project_name": "DISPLAY A",
            "check_id": "CHECK_003",
            "check_name": "AUX",
            "current_index": 3,
        }
        event = {
            "event": "check_advanced",
            "snapshot": {
                "current_check": {
                    "id": "CHECK_005",
                    "name": "HDMI",
                }
            },
        }

        app._display_auto_arm_manual_entry_gate(context, event)

        self.assertEqual(
            ("DISPLAY A", "CHECK_005"),
            app._display_auto_manual_entry_signature,
        )
        self.assertEqual("HDMI", app._display_auto_manual_entry_label)

    def test_bluetooth_cannot_ng_while_display_is_still_physically_in_h1(self):
        app = DisplayAutomaticCheckF3Mixin.__new__(DisplayAutomaticCheckF3Mixin)
        app.display_f3_ativo = True
        app.display_f3_result_after_id = None
        app._display_project_config_window = None
        app.camera_frame_atual = np.zeros((10, 10, 3), dtype=np.uint8)
        app.camera_ultimo_frame_id = 100
        statuses = []
        app.display_f3_window = SimpleNamespace(
            set_preview_status=lambda text, color: statuses.append((text, color))
        )
        app.display_project_repository = SimpleNamespace(
            obter_projeto_ativo=lambda: "DISPLAY A"
        )
        app.display_check_runtime = SimpleNamespace(
            snapshot=lambda: {
                "current_index": 1,
                "current_check": {
                    "id": "CHECK_002",
                    "name": "BLUETOOTH",
                },
            }
        )

        # A imagem ainda corresponde ao H1: para o CHECK Bluetooth a leitura é
        # inconsistente e, sem o gate, poderia começar a acumular NG.
        mismatch = {
            "ready": True,
            "approved": False,
            "matched_mask_count": 0,
            "active_mask_count": 2,
            "mask_results": [
                {
                    "mask_id": "A",
                    "expected": "on",
                    "classified": "off",
                    "matched": False,
                    "confidence": 0.95,
                },
                {
                    "mask_id": "B",
                    "expected": "off",
                    "classified": "on",
                    "matched": False,
                    "confidence": 0.95,
                },
            ],
        }
        app._display_auto_analyzer = SimpleNamespace(
            repository=app.display_project_repository,
            analyze=lambda **_kwargs: mismatch,
        )
        app._display_auto_signature = None
        app._display_auto_last_decision = None
        app._display_auto_stable_frames = 0
        app._display_auto_transition_frames = 0
        app._display_auto_last_frame_token = None
        app._display_auto_last_analysis = None
        app._display_auto_manual_entry_signature = ("DISPLAY A", "CHECK_002")
        app._display_auto_manual_entry_label = "BLUETOOTH"
        app._obter_rotacao_visual_display_f3 = lambda: 0

        events = []
        app.registrar_resultado_check_display_f3 = (
            lambda approved: events.append(bool(approved))
            or {"event": "plate_ng"}
        )

        for frame_id in range(100, 108):
            app.camera_ultimo_frame_id = frame_id
            app._process_display_auto_check()

        self.assertEqual([], events)
        self.assertEqual(0, app._display_auto_stable_frames)
        self.assertEqual(
            ("DISPLAY A", "CHECK_002"),
            app._display_auto_manual_entry_signature,
        )
        self.assertTrue(
            any(
                "aguardando botão / mudança de função" in text
                for text, _color in statuses
            )
        )


if __name__ == "__main__":
    unittest.main()
