from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin


class DisplayF3TransientBluetoothTests(unittest.TestCase):
    def test_bluetooth_aliases_are_transient_but_usb_and_aux_are_not(self):
        for name in ("BLUETOOTH", "Bluetooth", "BLUE", "BT", "CHECK BLUETOOTH"):
            self.assertTrue(
                DisplayAutomaticCheckF3Mixin._display_auto_is_transient_check(
                    {"check_name": name}
                )
            )

        for name in ("H1", "USB", "AUX"):
            self.assertFalse(
                DisplayAutomaticCheckF3Mixin._display_auto_is_transient_check(
                    {"check_name": name}
                )
            )

    def test_flag_intermitente_explicitamente_desativada_supera_nome_blue(self):
        self.assertFalse(
            DisplayAutomaticCheckF3Mixin._display_auto_is_transient_check(
                {"check_name": "BLUE", "intermittent": False}
            )
        )
        self.assertTrue(
            DisplayAutomaticCheckF3Mixin._display_auto_is_transient_check(
                {"check_name": "AUX", "intermittent": True}
            )
        )

    def test_blue_and_usb_require_manual_transition_after_success(self):
        for name in ("BLUETOOTH", "BLUE", "BT", "CHECK BLUE", "USB", "CHECK USB"):
            self.assertTrue(
                DisplayAutomaticCheckF3Mixin._display_auto_requires_manual_transition_after(
                    name
                )
            )
        for name in ("H1", "AUX"):
            self.assertFalse(
                DisplayAutomaticCheckF3Mixin._display_auto_requires_manual_transition_after(
                    name
                )
            )

    def test_bluetooth_advances_on_first_conforming_fresh_frame_and_arms_usb_gate(self):
        app = DisplayAutomaticCheckF3Mixin.__new__(DisplayAutomaticCheckF3Mixin)
        app.display_f3_ativo = True
        app.display_f3_result_after_id = None
        app._display_project_config_window = None
        app.camera_frame_atual = np.zeros((10, 10, 3), dtype=np.uint8)
        app.camera_ultimo_frame_id = 10
        app.display_f3_window = SimpleNamespace(
            set_preview_status=lambda *_args, **_kwargs: None
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
        app._display_auto_analyzer = SimpleNamespace(
            repository=app.display_project_repository,
            analyze=lambda **_kwargs: {
                "ready": True,
                "approved": True,
                "matched_mask_count": 2,
                "active_mask_count": 2,
            },
        )
        app._display_auto_signature = None
        app._display_auto_last_decision = None
        app._display_auto_stable_frames = 0
        app._display_auto_transition_frames = 1
        app._display_auto_last_frame_token = None
        app._display_auto_last_analysis = None
        app._display_auto_manual_entry_signature = None
        app._display_auto_manual_entry_label = ""
        app._obter_rotacao_visual_display_f3 = lambda: 0

        events = []

        def registrar(approved):
            events.append(bool(approved))
            return {
                "event": "check_advanced",
                "snapshot": {
                    "current_check": {
                        "id": "CHECK_003",
                        "name": "USB",
                    }
                },
            }

        app.registrar_resultado_check_display_f3 = registrar

        app._process_display_auto_check()

        self.assertEqual([True], events)
        self.assertEqual(0, app._display_auto_stable_frames)
        self.assertEqual(
            ("DISPLAY A", "CHECK_003"),
            app._display_auto_manual_entry_signature,
        )
        self.assertEqual("USB", app._display_auto_manual_entry_label)

    def test_usb_cannot_generate_ng_before_visual_evidence_of_button_change(self):
        app = DisplayAutomaticCheckF3Mixin.__new__(DisplayAutomaticCheckF3Mixin)
        app.display_f3_ativo = True
        app.display_f3_result_after_id = None
        app._display_project_config_window = None
        app.camera_frame_atual = np.zeros((10, 10, 3), dtype=np.uint8)
        app.camera_ultimo_frame_id = 20
        statuses = []
        app.display_f3_window = SimpleNamespace(
            set_preview_status=lambda text, color: statuses.append((text, color))
        )
        app.display_project_repository = SimpleNamespace(
            obter_projeto_ativo=lambda: "DISPLAY A"
        )
        app.display_check_runtime = SimpleNamespace(
            snapshot=lambda: {
                "current_index": 2,
                "current_check": {
                    "id": "CHECK_003",
                    "name": "USB",
                },
            }
        )

        analyses = iter(
            [
                {
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
                },
                {
                    "ready": True,
                    "approved": True,
                    "matched_mask_count": 2,
                    "active_mask_count": 2,
                    "mask_results": [
                        {
                            "mask_id": "A",
                            "expected": "on",
                            "classified": "on",
                            "matched": True,
                            "confidence": 0.95,
                        },
                        {
                            "mask_id": "B",
                            "expected": "off",
                            "classified": "off",
                            "matched": True,
                            "confidence": 0.95,
                        },
                    ],
                },
                {
                    "ready": True,
                    "approved": True,
                    "matched_mask_count": 2,
                    "active_mask_count": 2,
                    "mask_results": [
                        {
                            "mask_id": "A",
                            "expected": "on",
                            "classified": "on",
                            "matched": True,
                            "confidence": 0.95,
                        },
                        {
                            "mask_id": "B",
                            "expected": "off",
                            "classified": "off",
                            "matched": True,
                            "confidence": 0.95,
                        },
                    ],
                },
            ]
        )
        app._display_auto_analyzer = SimpleNamespace(
            repository=app.display_project_repository,
            analyze=lambda **_kwargs: next(analyses),
        )
        app._display_auto_signature = None
        app._display_auto_last_decision = None
        app._display_auto_stable_frames = 0
        app._display_auto_transition_frames = 1
        app._display_auto_last_frame_token = None
        app._display_auto_last_analysis = None
        app._display_auto_manual_entry_signature = ("DISPLAY A", "CHECK_003")
        app._display_auto_manual_entry_label = "USB"
        app._obter_rotacao_visual_display_f3 = lambda: 0

        events = []

        def registrar(approved):
            events.append(bool(approved))
            return {
                "event": "check_advanced",
                "snapshot": {
                    "current_check": {
                        "id": "CHECK_004",
                        "name": "AUX",
                    }
                },
            }

        app.registrar_resultado_check_display_f3 = registrar

        # Ainda está visualmente no Bluetooth: mesmo sendo uma inconsistência
        # que normalmente poderia virar NG, o gate deve apenas aguardar o botão.
        app._process_display_auto_check()
        self.assertEqual([], events)
        self.assertEqual(0, app._display_auto_stable_frames)
        self.assertEqual(
            ("DISPLAY A", "CHECK_003"),
            app._display_auto_manual_entry_signature,
        )
        self.assertTrue(
            any("aguardando botão / mudança de função" in text for text, _ in statuses)
        )

        # O botão foi pressionado e o padrão USB apareceu: libera o gate e usa
        # a estabilidade normal de dois frames para concluir o USB.
        app.camera_ultimo_frame_id = 21
        app._process_display_auto_check()
        self.assertEqual([], events)
        self.assertIsNone(app._display_auto_manual_entry_signature)
        self.assertEqual(1, app._display_auto_stable_frames)

        app.camera_ultimo_frame_id = 22
        app._process_display_auto_check()
        self.assertEqual([True], events)

        # Como USB também depende de novo clique físico, a entrada no AUX fica
        # protegida até aparecer evidência visual da função AUX.
        self.assertEqual(
            ("DISPLAY A", "CHECK_004"),
            app._display_auto_manual_entry_signature,
        )
        self.assertEqual("AUX", app._display_auto_manual_entry_label)


if __name__ == "__main__":
    unittest.main()
