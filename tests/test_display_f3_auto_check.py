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
from src.platform.raspberry_pi3_production_app import RaspberryPi3ProductionApp


def _features(value: float) -> LedFeatures:
    return LedFeatures(
        v_mean=float(value),
        v_max=float(value),
        v_p95=float(value),
        v_p99=float(value),
        glow_score=float(value),
    )


class DisplayF3AutoCheckTests(unittest.TestCase):
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

    def test_runtime_intermitente_exige_ver_cada_segmento_on_ao_menos_uma_vez(self):
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
                    "mask_id": "MASK_002",
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
                    "mask_id": "MASK_002",
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

    def test_runtime_counts_only_fresh_frames_and_auto_confirms_after_stability(self):
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
        app._process_display_auto_check()
        self.assertEqual([], events)
        self.assertEqual(1, app._display_auto_stable_frames)

        app.camera_ultimo_frame_id = 2
        app._process_display_auto_check()
        self.assertEqual([True], events)

    def test_auto_mixin_is_before_f3_runtime_and_does_not_replace_trigger_methods(self):
        mro = RaspberryPi3ProductionApp.__mro__
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
