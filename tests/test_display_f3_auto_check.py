from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from src.core.feature_extractor import extrair_features_selecao
from src.models.led_features import LedFeatures
from src.platform.display_auto_check_analyzer import (
    DISPLAY_AUTO_CLASS_LOW_LIGHT,
    DisplayAutomaticCheckAnalyzer,
    DisplayLearnedStateClassifier,
    avaliar_match_check_display,
    display_mask_to_analysis_selection,
)
from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin
from src.platform.display_production_f3 import DisplayProductionF3Mixin
from src.platform.display_project_repository import DisplayProjectRepository
from src.platform.display_reference_store import (
    DisplayReferenceLearningStore,
    display_learning_path_for_repository,
)
from src.platform.desktop_production_app import DesktopProductionApp


def _features(value: float) -> LedFeatures:
    return LedFeatures(
        v_mean=float(value),
        v_max=float(value),
        v_p95=float(value),
        v_p99=float(value),
        glow_score=float(value),
    )


class DisplayF3AutoCheckTests(unittest.TestCase):
    def test_ng_preserva_frame_exato_antes_de_registrar_resultado(self):
        source = inspect.getsource(DisplayAutomaticCheckF3Mixin._process_display_auto_check)
        self.assertIn("_display_f3_pending_ng_frame = frame.copy()", source)
        self.assertIn("_display_f3_pending_ng_analysis = deepcopy(analysis)", source)
        self.assertLess(
            source.index("_display_f3_pending_ng_frame = frame.copy()"),
            source.index("registrar_resultado_check_display_f3(approved)"),
        )

    def test_intermitente_tolera_off_de_segmento_esperado_on_mas_nao_low_light(self):
        self.assertEqual(
            (True, False, True),
            avaliar_match_check_display("on", "off", intermittent=True),
        )
        self.assertEqual(
            (True, True, False),
            avaliar_match_check_display("on", "on", intermittent=True),
        )
        self.assertEqual(
            (False, False, False),
            avaliar_match_check_display("on", "low_light", intermittent=True),
        )
        self.assertEqual(
            (False, False, False),
            avaliar_match_check_display("off", "on", intermittent=True),
        )

    def test_runtime_intermitente_exige_fase_on_completa_no_mesmo_frame(self):
        app = DisplayAutomaticCheckF3Mixin.__new__(DisplayAutomaticCheckF3Mixin)
        app._display_auto_intermittent_signature = None
        app._display_auto_intermittent_seen_on = set()
        context = {
            "project_name": "DISPLAY A",
            "check_id": "CHECK_002",
            "check_name": "BLUE",
            "intermittent": True,
        }

        first = {
            "mask_results": [
                {
                    "mask_id": "MASK_001",
                    "expected": "on",
                    "classified": "on",
                    "raw_matched": True,
                    "confidence": 0.99,
                },
                {
                    "mask_id": "MASK_027",
                    "expected": "on",
                    "classified": "off",
                    "raw_matched": False,
                    "confidence": 0.99,
                },
            ]
        }
        ready, seen, total = app._display_auto_update_intermittent_evidence(
            context,
            first,
        )
        self.assertFalse(ready)
        self.assertEqual((1, 2), (seen, total))

        # A antiga regra somaria MASK_001 do frame anterior com MASK_027 deste
        # frame e aprovaria. A nova regra continua bloqueando.
        second = {
            "mask_results": [
                {
                    "mask_id": "MASK_001",
                    "expected": "on",
                    "classified": "off",
                    "raw_matched": False,
                    "confidence": 0.99,
                },
                {
                    "mask_id": "MASK_027",
                    "expected": "on",
                    "classified": "on",
                    "raw_matched": True,
                    "confidence": 0.99,
                },
            ]
        }
        ready, seen, total = app._display_auto_update_intermittent_evidence(
            context,
            second,
        )
        self.assertFalse(ready)
        self.assertEqual((1, 2), (seen, total))

        full_on = {
            "mask_results": [
                {
                    "mask_id": "MASK_001",
                    "expected": "on",
                    "classified": "on",
                    "raw_matched": True,
                    "confidence": 0.99,
                },
                {
                    "mask_id": "MASK_027",
                    "expected": "on",
                    "classified": "on",
                    "raw_matched": True,
                    "confidence": 0.99,
                },
            ]
        }
        ready, seen, total = app._display_auto_update_intermittent_evidence(
            context,
            full_on,
        )
        self.assertTrue(ready)
        self.assertEqual((2, 2), (seen, total))

    def test_classifier_uses_three_learned_states(self):
        classifier = DisplayLearnedStateClassifier(
            learned_on=_features(220),
            learned_off=_features(20),
            learned_low_light=_features(90),
        )
        self.assertEqual("on", classifier.classify(_features(218)).state)
        self.assertEqual("off", classifier.classify(_features(18)).state)
        self.assertEqual(
            DISPLAY_AUTO_CLASS_LOW_LIGHT,
            classifier.classify(_features(92)).state,
        )

    def test_rectangle_is_supported_without_using_production_engine(self):
        selection = display_mask_to_analysis_selection(
            {
                "id": "MASK_RECT",
                "type": "rectangle",
                "x": 10,
                "y": 12,
                "width": 30,
                "height": 8,
            }
        )
        self.assertEqual("MASK_RECT", selection.id)
        self.assertEqual(25, selection.centro_x)
        self.assertEqual(16, selection.centro_y)

    def test_analyzer_connects_check_masks_learning_and_decision(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repository = DisplayProjectRepository(root / "display_projects.json")
            self.assertTrue(repository.adicionar_projeto("DISPLAY A", (120, 80)))
            mask = {
                "id": "MASK_001",
                "type": "circle",
                "cx": 60,
                "cy": 40,
                "radius": 12,
            }
            self.assertTrue(repository.salvar_mascaras("DISPLAY A", [mask]))
            self.assertTrue(
                repository.salvar_estados_check(
                    "DISPLAY A",
                    "CHECK_001",
                    {"MASK_001": "on"},
                )
            )

            selection = display_mask_to_analysis_selection(mask)
            frames = {}
            for state, value in (
                ("on", 230),
                ("off", 15),
                ("low_light", 95),
            ):
                frame = np.full((80, 120, 3), value, dtype=np.uint8)
                frames[state] = frame
                features = extrair_features_selecao(frame, selection)
                store = DisplayReferenceLearningStore(
                    display_learning_path_for_repository(repository)
                )
                store.save_sample(
                    "DISPLAY A",
                    state,
                    {
                        "id": state,
                        "features": features.to_dict(),
                        "mask": mask,
                    },
                    scope="project",
                )

            analyzer = DisplayAutomaticCheckAnalyzer(repository)
            approved = analyzer.analyze(
                frames["on"],
                "DISPLAY A",
                "CHECK_001",
                visual_rotation=0,
            )
            self.assertTrue(approved["ready"])
            self.assertTrue(approved["approved"])
            self.assertEqual("on", approved["mask_results"][0]["classified"])

            low_light = analyzer.analyze(
                frames["low_light"],
                "DISPLAY A",
                "CHECK_001",
                visual_rotation=0,
            )
            self.assertTrue(low_light["ready"])
            self.assertFalse(low_light["approved"])
            self.assertEqual(
                "low_light",
                low_light["mask_results"][0]["classified"],
            )

    def test_check_with_only_ignore_does_not_auto_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = DisplayProjectRepository(Path(temp) / "projects.json")
            repository.adicionar_projeto("DISPLAY A", (100, 60))
            repository.salvar_mascaras(
                "DISPLAY A",
                [
                    {
                        "id": "MASK_001",
                        "type": "circle",
                        "cx": 50,
                        "cy": 30,
                        "radius": 8,
                    }
                ],
            )
            analyzer = DisplayAutomaticCheckAnalyzer(repository)
            result = analyzer.analyze(
                np.zeros((60, 100, 3), dtype=np.uint8),
                "DISPLAY A",
                "CHECK_001",
            )
            self.assertFalse(result["ready"])
            self.assertEqual("check_sem_mascaras_ativas", result["reason"])

    def test_incomplete_learning_holds_check_instead_of_rejecting_plate(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = DisplayProjectRepository(Path(temp) / "projects.json")
            repository.adicionar_projeto("DISPLAY A", (100, 60))
            repository.salvar_mascaras(
                "DISPLAY A",
                [
                    {
                        "id": "MASK_001",
                        "type": "circle",
                        "cx": 50,
                        "cy": 30,
                        "radius": 8,
                    }
                ],
            )
            repository.salvar_estados_check(
                "DISPLAY A",
                "CHECK_001",
                {"MASK_001": "on"},
            )
            store = DisplayReferenceLearningStore(
                display_learning_path_for_repository(repository)
            )
            store.save_sample(
                "DISPLAY A",
                "on",
                {"id": "on", "features": _features(200).to_dict()},
            )
            analyzer = DisplayAutomaticCheckAnalyzer(repository)
            result = analyzer.analyze(
                np.zeros((60, 100, 3), dtype=np.uint8),
                "DISPLAY A",
                "CHECK_001",
            )
            self.assertFalse(result["ready"])
            self.assertIsNone(result["approved"])
            self.assertEqual("aprendizado_incompleto", result["reason"])

    def test_ui_h1_nao_julga_mascaras_antes_do_primeiro_expected_on(self):
        analysis = {
            "ready": True,
            "approved": False,
            "mask_results": [
                {
                    "mask_id": "MASK_ON",
                    "expected": "on",
                    "classified": "off",
                    "matched": False,
                    "confidence": 0.99,
                },
                {
                    # Simula reflexo/falso ON numa máscara que deveria estar OFF.
                    # Isso não pode liberar o julgamento do H1.
                    "mask_id": "MASK_OFF",
                    "expected": "off",
                    "classified": "on",
                    "matched": False,
                    "confidence": 0.99,
                },
            ],
        }

        self.assertFalse(
            DisplayAutomaticCheckF3Mixin._display_auto_has_reference_power_evidence(
                analysis
            )
        )
        result = (
            DisplayAutomaticCheckF3Mixin._display_auto_publish_effective_ui_authority(
                analysis,
                judgement_ready=False,
            )
        )

        self.assertFalse(result["ui_judgement_ready"])
        self.assertEqual(
            {
                "MASK_ON": "unknown",
                "MASK_OFF": "unknown",
            },
            result["effective_classifications"],
        )
        self.assertEqual((), result["effective_failed_mask_ids"])
        self.assertEqual(0, result["effective_matched_mask_count"])
        self.assertEqual(
            "blocked_until_first_expected_on_v1",
            result["ui_mask_authority"],
        )

    def test_ui_h1_libera_ok_ng_apos_primeiro_expected_on_confirmado(self):
        analysis = {
            "ready": True,
            "approved": False,
            "mask_results": [
                {
                    "mask_id": "MASK_ON_1",
                    "expected": "on",
                    "classified": "on",
                    "matched": True,
                    "confidence": 0.99,
                },
                {
                    "mask_id": "MASK_ON_2",
                    "expected": "on",
                    "classified": "off",
                    "matched": False,
                    "confidence": 0.99,
                },
            ],
        }

        ready = (
            DisplayAutomaticCheckF3Mixin._display_auto_has_reference_power_evidence(
                analysis
            )
        )
        self.assertTrue(ready)
        result = (
            DisplayAutomaticCheckF3Mixin._display_auto_publish_effective_ui_authority(
                analysis,
                judgement_ready=ready,
            )
        )

        self.assertTrue(result["ui_judgement_ready"])
        self.assertEqual("on", result["effective_classifications"]["MASK_ON_1"])
        self.assertEqual("off", result["effective_classifications"]["MASK_ON_2"])
        self.assertEqual(("MASK_ON_2",), result["effective_failed_mask_ids"])
        self.assertEqual("effective_mask_results_v1", result["ui_mask_authority"])

    def test_h1_desempata_falsos_off_ambiguos_com_prova_fisica_same_mask(self):
        analysis = {
            "ready": True,
            "approved": False,
            "reason": "check_diverge_mascara_configurada",
            "matched_mask_count": 26,
            "active_mask_count": 28,
            "failed_mask_ids": ["MASK_012", "MASK_020"],
            "missing_on_mask_ids": ["MASK_012", "MASK_020"],
            "mask_results": [],
        }
        expected_on_ids = {
            "MASK_008",
            "MASK_009",
            "MASK_011",
            "MASK_012",
            "MASK_013",
            "MASK_017",
            "MASK_020",
        }
        for index in range(1, 29):
            mask_id = f"MASK_{index:03d}"
            expected = "on" if mask_id in expected_on_ids else "off"
            false_off = mask_id in {"MASK_012", "MASK_020"}
            analysis["mask_results"].append(
                {
                    "mask_id": mask_id,
                    "expected": expected,
                    "classified": "off" if false_off else expected,
                    "matched": not false_off,
                    "raw_matched": not false_off,
                    "confidence": (
                        0.5274
                        if mask_id == "MASK_012"
                        else (0.5106 if mask_id == "MASK_020" else 0.95)
                    ),
                }
            )

        evidence = {
            "available": True,
            "source": "f3_same_mask_relative_power_authority",
            "same_mask_comparison": True,
            "details": [
                {
                    "mask_id": mask_id,
                    "winner": "powered",
                    "reference_discriminative": True,
                    "power_position": 0.98,
                }
                for mask_id in sorted(expected_on_ids)
            ],
        }

        result = (
            DisplayAutomaticCheckF3Mixin
            ._display_auto_apply_reference_gate_physical_tie_breaker(
                analysis,
                evidence,
            )
        )
        by_id = {item["mask_id"]: item for item in result["mask_results"]}

        self.assertTrue(result["approved"])
        self.assertEqual(28, result["matched_mask_count"])
        self.assertEqual([], result["failed_mask_ids"])
        self.assertEqual([], result["missing_on_mask_ids"])
        self.assertEqual(
            ("MASK_012", "MASK_020"),
            result["reference_gate_physical_tie_breaker_ids"],
        )
        for mask_id in ("MASK_012", "MASK_020"):
            self.assertEqual("on", by_id[mask_id]["classified"])
            self.assertTrue(by_id[mask_id]["matched"])
            self.assertTrue(
                by_id[mask_id]["reference_gate_physical_confirmation"]
            )
            self.assertEqual(
                "reference_gate_same_mask_power_over_false_off_semantic",
                by_id[mask_id]["classification_source"],
            )

    def test_h1_segmento_realmente_apagado_nao_e_resgatado(self):
        analysis = {
            "ready": True,
            "approved": False,
            "reason": "check_diverge_mascara_configurada",
            "mask_results": [
                {
                    "mask_id": "MASK_020",
                    "expected": "on",
                    "classified": "off",
                    "matched": False,
                    "raw_matched": False,
                    "confidence": 0.95,
                }
            ],
        }
        evidence = {
            "available": True,
            "source": "f3_same_mask_relative_power_authority",
            "same_mask_comparison": True,
            "details": [
                {
                    "mask_id": "MASK_020",
                    "winner": "off",
                    "reference_discriminative": True,
                    "power_position": 0.05,
                }
            ],
        }

        result = (
            DisplayAutomaticCheckF3Mixin
            ._display_auto_apply_reference_gate_physical_tie_breaker(
                analysis,
                evidence,
            )
        )

        self.assertFalse(result["approved"])
        self.assertEqual(["MASK_020"], result["failed_mask_ids"])
        self.assertEqual((), result["reference_gate_physical_tie_breaker_ids"])
        self.assertEqual("off", result["mask_results"][0]["classified"])
        self.assertFalse(result["mask_results"][0]["matched"])

    def test_h1_false_off_05944_e_reconciliado_por_prova_fisica(self):
        analysis = {
            "ready": True,
            "approved": False,
            "reason": "check_diverge_mascara_configurada",
            "mask_results": [
                {
                    "mask_id": "MASK_013",
                    "expected": "on",
                    "classified": "off",
                    "matched": False,
                    "raw_matched": False,
                    "confidence": 0.5944,
                }
            ],
        }
        evidence = {
            "available": True,
            "source": "f3_same_mask_relative_power_authority",
            "same_mask_comparison": True,
            "details": [
                {
                    "mask_id": "MASK_013",
                    "winner": "powered",
                    "reference_discriminative": True,
                    "power_position": 0.99,
                }
            ],
        }

        self.assertTrue(
            DisplayAutomaticCheckF3Mixin
            ._display_auto_reference_gate_needs_physical_tie_breaker(analysis)
        )
        result = (
            DisplayAutomaticCheckF3Mixin
            ._display_auto_apply_reference_gate_physical_tie_breaker(
                analysis,
                evidence,
            )
        )
        item = result["mask_results"][0]

        self.assertTrue(result["approved"])
        self.assertEqual([], result["failed_mask_ids"])
        self.assertEqual(
            ("MASK_013",),
            result["reference_gate_physical_tie_breaker_ids"],
        )
        self.assertEqual("on", item["classified"])
        self.assertTrue(item["matched"])
        self.assertEqual(
            0.5944,
            item["semantic_confidence_before_reference_power_reconciliation"],
        )
        self.assertEqual(
            "reference_gate_same_mask_power_over_false_off_semantic",
            item["classification_source"],
        )

    def test_h1_mascara_expected_off_nunca_e_corrigida_como_on(self):
        analysis = {
            "ready": True,
            "approved": False,
            "reason": "check_diverge_mascara_configurada",
            "mask_results": [
                {
                    "mask_id": "MASK_014",
                    "expected": "off",
                    "classified": "on",
                    "matched": False,
                    "raw_matched": False,
                    "confidence": 0.51,
                }
            ],
        }
        evidence = {
            "available": True,
            "source": "f3_same_mask_relative_power_authority",
            "same_mask_comparison": True,
            "details": [
                {
                    "mask_id": "MASK_014",
                    "winner": "powered",
                    "reference_discriminative": True,
                }
            ],
        }

        result = (
            DisplayAutomaticCheckF3Mixin
            ._display_auto_apply_reference_gate_physical_tie_breaker(
                analysis,
                evidence,
            )
        )
        self.assertFalse(result["approved"])
        self.assertEqual(["MASK_014"], result["failed_mask_ids"])
        self.assertEqual((), result["reference_gate_physical_tie_breaker_ids"])

    def test_runtime_approves_on_first_fully_conforming_frame(self):
        app = DisplayAutomaticCheckF3Mixin.__new__(DisplayAutomaticCheckF3Mixin)
        app.display_f3_ativo = True
        app.display_f3_result_after_id = None
        app._display_project_config_window = None
        app.camera_frame_atual = np.zeros((10, 10, 3), dtype=np.uint8)
        app.camera_ultimo_frame_id = 1
        app.display_f3_window = SimpleNamespace(
            set_preview_status=lambda *_args, **_kwargs: None
        )
        app.display_project_repository = SimpleNamespace(
            obter_projeto_ativo=lambda: "DISPLAY A"
        )
        app.display_check_runtime = SimpleNamespace(
            snapshot=lambda: {
                "current_index": 0,
                "current_check": {"id": "CHECK_001", "name": "H1"},
            }
        )
        app._display_auto_analyzer = SimpleNamespace(
            repository=app.display_project_repository,
            analyze=lambda **_kwargs: {
                "ready": True,
                "approved": True,
                "matched_mask_count": 1,
                "active_mask_count": 1,
                "mask_results": [
                    {
                        "mask_id": "MASK_001",
                        "expected": "on",
                        "classified": "on",
                        "matched": True,
                        "confidence": 0.99,
                    }
                ],
            },
        )
        app._display_auto_signature = ("DISPLAY A", "CHECK_001")
        app._display_auto_last_decision = None
        app._display_auto_stable_frames = 0
        app._display_auto_transition_frames = 0
        app._display_auto_last_frame_token = None
        app._display_auto_last_analysis = None
        app._display_auto_manual_entry_signature = None
        app._display_auto_manual_entry_label = ""
        app._obter_rotacao_visual_display_f3 = lambda: 0
        events = []
        app.registrar_resultado_check_display_f3 = (
            lambda approved: events.append(bool(approved))
            or {"event": "check_advanced"}
        )

        app._process_display_auto_check()
        self.assertEqual([True], events)
        self.assertEqual(0, app._display_auto_stable_frames)

    def test_runtime_h1_ambiguo_usa_autoridade_fisica_e_avanca(self):
        app = DisplayAutomaticCheckF3Mixin.__new__(DisplayAutomaticCheckF3Mixin)
        app.display_f3_ativo = True
        app.display_f3_result_after_id = None
        app._display_project_config_window = None
        app.camera_frame_atual = np.zeros((10, 10, 3), dtype=np.uint8)
        app.camera_ultimo_frame_id = 2
        app.display_f3_window = SimpleNamespace(
            set_preview_status=lambda *_args, **_kwargs: None
        )
        app.display_project_repository = SimpleNamespace(
            obter_projeto_ativo=lambda: "DISPLAY A"
        )
        app.display_check_runtime = SimpleNamespace(
            snapshot=lambda: {
                "current_index": 0,
                "current_check": {"id": "CHECK_001", "name": "H1"},
            }
        )
        app._display_auto_analyzer = SimpleNamespace(
            repository=app.display_project_repository,
            analyze=lambda **_kwargs: {
                "ready": True,
                "approved": False,
                "reason": "check_diverge_mascara_configurada",
                "matched_mask_count": 1,
                "active_mask_count": 2,
                "mask_results": [
                    {
                        "mask_id": "MASK_008",
                        "expected": "on",
                        "classified": "on",
                        "matched": True,
                        "raw_matched": True,
                        "confidence": 0.99,
                    },
                    {
                        "mask_id": "MASK_013",
                        "expected": "on",
                        "classified": "off",
                        "matched": False,
                        "raw_matched": False,
                        "confidence": 0.5944,
                    },
                ],
            },
        )
        app._display_f3_runtime_authorities = SimpleNamespace(
            power=SimpleNamespace(
                evaluate_current_check_relative=lambda *_args, **_kwargs: {
                    "available": True,
                    "source": "f3_same_mask_relative_power_authority",
                    "same_mask_comparison": True,
                    "details": [
                        {
                            "mask_id": "MASK_013",
                            "winner": "powered",
                            "reference_discriminative": True,
                            "power_position": 0.99,
                        }
                    ],
                }
            )
        )
        app._display_auto_signature = ("DISPLAY A", "CHECK_001")
        app._display_auto_last_decision = None
        app._display_auto_stable_frames = 0
        app._display_auto_transition_frames = 0
        app._display_auto_last_frame_token = None
        app._display_auto_last_analysis = None
        app._display_auto_manual_entry_signature = None
        app._display_auto_manual_entry_label = ""
        app._obter_rotacao_visual_display_f3 = lambda: 0
        events = []
        app.registrar_resultado_check_display_f3 = (
            lambda approved: events.append(bool(approved))
            or {"event": "check_advanced"}
        )

        app._process_display_auto_check()

        self.assertEqual([True], events)
        self.assertTrue(app._display_auto_last_analysis["approved"])
        self.assertEqual(
            ("MASK_013",),
            app._display_auto_last_analysis[
                "reference_gate_physical_tie_breaker_ids"
            ],
        )

    def test_blue_suporte_intermitente_usa_autoridade_fisica_estavel(self):
        analysis = {
            "ready": True,
            "approved": False,
            "mask_results": [
                {
                    "mask_id": "MASK_024",
                    "expected": "on",
                    "classified": "off",
                    "matched": False,
                    "raw_matched": False,
                    "confidence": 0.6414,
                    "intermittent_power_confirmation": False,
                    "intermittent_power_support": {
                        "source": "f3_current_check_vs_board_off_same_mask_support",
                        "winner": "off",
                    },
                }
            ],
        }
        evidence = {
            "available": True,
            "source": "f3_same_mask_relative_power_authority",
            "same_mask_comparison": True,
            "details": [
                {
                    "mask_id": "MASK_024",
                    "winner": "powered",
                    "reference_discriminative": True,
                    "power_position": 0.99,
                }
            ],
        }

        result = (
            DisplayAutomaticCheckF3Mixin
            ._display_auto_apply_intermittent_physical_authority(
                analysis,
                evidence,
            )
        )
        item = result["mask_results"][0]

        self.assertTrue(item["intermittent_power_confirmation"])
        self.assertEqual(
            "f3_same_mask_relative_power_authority",
            item["intermittent_power_support"]["source"],
        )
        self.assertEqual(
            "powered",
            item["intermittent_power_support"]["winner"],
        )
        self.assertFalse(
            item["intermittent_learning_support_confirmation"]
        )
        self.assertEqual(
            ("MASK_024",),
            result["intermittent_power_support_confirmed_mask_ids"],
        )
        self.assertTrue(result["intermittent_power_support_authoritative"])

    def test_blue_autoridade_global_nao_pode_confirmar_suporte_intermitente(self):
        analysis = {
            "ready": True,
            "approved": False,
            "mask_results": [
                {
                    "mask_id": "MASK_024",
                    "expected": "on",
                    "classified": "off",
                    "matched": False,
                    "raw_matched": False,
                    "confidence": 0.6414,
                }
            ],
        }
        evidence = {
            "available": True,
            "source": "f3_unified_live_mask_power_authority",
            "same_mask_comparison": True,
            "details": [
                {
                    "mask_id": "MASK_024",
                    "winner": "powered",
                    "reference_discriminative": True,
                }
            ],
        }

        result = (
            DisplayAutomaticCheckF3Mixin
            ._display_auto_apply_intermittent_physical_authority(
                analysis,
                evidence,
            )
        )

        self.assertFalse(
            result["mask_results"][0]["intermittent_power_confirmation"]
        )
        self.assertEqual(
            (),
            result["intermittent_power_support_confirmed_mask_ids"],
        )
        self.assertFalse(result["intermittent_power_support_authoritative"])

    def test_runtime_blue_falsos_off_022_024_026_usam_prova_fisica_e_avancam(self):
        app = DisplayAutomaticCheckF3Mixin.__new__(DisplayAutomaticCheckF3Mixin)
        app.display_f3_ativo = True
        app.display_f3_result_after_id = None
        app._display_project_config_window = None
        app.camera_frame_atual = np.zeros((10, 10, 3), dtype=np.uint8)
        app.camera_ultimo_frame_id = 7
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
                    "name": "BLUE",
                    "intermittent": True,
                },
            }
        )

        false_off_ids = {"MASK_022", "MASK_024", "MASK_026"}
        rows = []
        for index in range(1, 19):
            mask_id = f"MASK_{index:03d}"
            if index == 16:
                mask_id = "MASK_022"
            elif index == 17:
                mask_id = "MASK_024"
            elif index == 18:
                mask_id = "MASK_026"
            false_off = mask_id in false_off_ids
            rows.append(
                {
                    "mask_id": mask_id,
                    "expected": "on",
                    "classified": "off" if false_off else "on",
                    "matched": not false_off,
                    "raw_matched": not false_off,
                    "confidence": 0.6414 if false_off else 0.99,
                    # Simula a evidência antiga divergente que existia no analyzer.
                    "intermittent_power_confirmation": False,
                    "intermittent_power_support": {
                        "source": "f3_current_check_vs_board_off_same_mask_support",
                        "winner": "off",
                    },
                }
            )

        app._display_auto_analyzer = SimpleNamespace(
            repository=app.display_project_repository,
            analyze=lambda **_kwargs: {
                "ready": True,
                "approved": False,
                "reason": "check_diverge_mascara_configurada",
                "matched_mask_count": 15,
                "active_mask_count": 18,
                "mask_results": rows,
            },
        )
        app._display_f3_runtime_authorities = SimpleNamespace(
            power=SimpleNamespace(
                evaluate_current_check_relative=lambda *_args, **_kwargs: {
                    "available": True,
                    "source": "f3_same_mask_relative_power_authority",
                    "same_mask_comparison": True,
                    "details": [
                        {
                            "mask_id": mask_id,
                            "winner": "powered",
                            "reference_discriminative": True,
                            "power_position": 0.99,
                        }
                        for mask_id in sorted(false_off_ids)
                    ],
                }
            )
        )
        app._display_auto_signature = ("DISPLAY A", "CHECK_002")
        app._display_auto_last_decision = None
        app._display_auto_stable_frames = 0
        app._display_auto_transition_frames = 0
        app._display_auto_last_frame_token = None
        app._display_auto_last_analysis = None
        app._display_auto_manual_entry_signature = None
        app._display_auto_manual_entry_label = ""
        app._display_auto_intermittent_signature = ("DISPLAY A", "CHECK_002")
        app._display_auto_intermittent_seen_on = set()
        app._display_auto_intermittent_phase = "unknown"
        app._display_auto_intermittent_on_samples = 0
        app._display_auto_intermittent_failure_counts = {}
        app._display_auto_intermittent_persistent_failed_ids = set()
        app._display_auto_intermittent_exact_veto_ids = set()
        app._display_auto_intermittent_physical_support_veto_ids = set()
        app._display_auto_intermittent_candidate_failed_ids = set()
        app._display_auto_intermittent_last_phase_analysis = None
        app._obter_rotacao_visual_display_f3 = lambda: 0
        events = []
        app.registrar_resultado_check_display_f3 = (
            lambda approved: events.append(bool(approved))
            or {"event": "check_advanced"}
        )

        app._process_display_auto_check()

        self.assertEqual([True], events)
        self.assertTrue(app._display_auto_last_analysis["approved"])
        self.assertEqual(
            tuple(sorted(false_off_ids)),
            app._display_auto_last_analysis[
                "intermittent_physical_support_veto_ids"
            ],
        )
        self.assertEqual(
            tuple(sorted(false_off_ids)),
            app._display_auto_last_analysis[
                "intermittent_power_support_confirmed_mask_ids"
            ],
        )
        self.assertEqual(
            (),
            tuple(
                app._display_auto_last_analysis[
                    "effective_confirmed_failed_mask_ids"
                ]
            ),
        )

    def test_auto_mixin_is_before_f3_runtime_and_does_not_replace_trigger_methods(self):
        mro = DesktopProductionApp.__mro__
        self.assertLess(
            mro.index(DisplayAutomaticCheckF3Mixin),
            mro.index(DisplayProductionF3Mixin),
        )
        for forbidden in (
            "disparar_inspecao_operacao",
            "preparar_tela_operacao",
            "_evento_enter_pressionado",
            "_evento_enter_liberado",
            "iniciar_tela_ao_vivo",
            "parar_tela_ao_vivo",
        ):
            self.assertNotIn(forbidden, DisplayAutomaticCheckF3Mixin.__dict__)

    def test_auto_modules_do_not_depend_on_existing_production_runtime(self):
        modules = (
            __import__(
                "src.platform.display_auto_check_analyzer",
                fromlist=["DisplayAutomaticCheckAnalyzer"],
            ),
            __import__(
                "src.platform.display_auto_check_runtime",
                fromlist=["DisplayAutomaticCheckF3Mixin"],
            ),
        )
        source = "\n".join(inspect.getsource(module) for module in modules)
        for forbidden in (
            "OperationEngine",
            "ConfigRepository",
            "operacao_engine",
            "operacao_total",
            "operacao_ok",
            "operacao_ng",
            "linux_f2_fixed_resolution",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
