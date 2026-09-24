from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

import numpy as np

import src.platform.display_f3_same_mask_reference_fix as same_mask_module
from src.models.led_features import LedFeatures
from src.platform.display_check_presence_reference import (
    DisplayCheckPresenceReferenceStore,
)
from src.platform.display_visual_reference_status import (
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
    DisplayProjectPresenceReferenceStore,
)
from src.platform.display_f3_same_mask_reference_fix import (
    F3_CHECK_PHOTO_LEARNING_SOURCE,
    F3_CHECK_PHOTO_MIN_CONFIDENCE,
    F3_SAME_MASK_REFERENCE_SOURCE,
    F3_STATE_SAMPLE_FALLBACK_SOURCE,
    F3SameMaskReferenceAnalyzer,
    classificar_mascara_por_referencias_locais_f3,
)
from src.platform.display_project_repository import DisplayProjectRepository


def _features(value: float) -> LedFeatures:
    return LedFeatures(
        v_mean=float(value),
        v_max=float(value),
        v_std=float(value) * 0.18,
        v_p95=float(value),
        v_p99=float(value),
        s_mean=float(value) * 0.22,
        s_std=float(value) * 0.08,
        center_to_ring_v=float(value) * 0.06,
        center_to_ring_s=float(value) * 0.02,
        percent_hot_235=max(0.0, min(1.0, (float(value) - 180.0) / 80.0)),
        percent_hot_245=max(0.0, min(1.0, (float(value) - 200.0) / 60.0)),
        percent_hot_250=max(0.0, min(1.0, (float(value) - 220.0) / 40.0)),
        glow_score=float(value) * 0.20,
        area_pixels=120,
        inner_area_pixels=60,
        ring_area_pixels=60,
    )


def _frame(mask_1_value: int, mask_2_value: int) -> np.ndarray:
    image = np.full((80, 120, 3), 20, dtype=np.uint8)
    image[25:56, 15:46] = int(mask_1_value)
    image[25:56, 75:106] = int(mask_2_value)
    return image


def _project_with_two_masks(root: Path):
    repository = DisplayProjectRepository(root / "odin_display_projects.json")
    assert repository.adicionar_projeto("DISPLAY A", (120, 80))
    masks = [
        {
            "id": "MASK_001",
            "type": "circle",
            "cx": 30,
            "cy": 40,
            "radius": 10,
        },
        {
            "id": "MASK_002",
            "type": "circle",
            "cx": 90,
            "cy": 40,
            "radius": 10,
        },
    ]
    assert repository.salvar_mascaras("DISPLAY A", masks)
    checks = repository.listar_checks("DISPLAY A")
    assert len(checks) >= 2
    return repository, masks, checks


class DisplayF3SameMaskReferenceFixTests(unittest.TestCase):
    def test_reflexo_legitimo_off_uses_same_physical_mask(self):
        result = classificar_mascara_por_referencias_locais_f3(
            current=_features(121),
            on_references=[_features(220)],
            off_references=[_features(120)],
        )

        self.assertIsNotNone(result)
        self.assertEqual("off", result["state"])
        self.assertEqual(F3_SAME_MASK_REFERENCE_SOURCE, result["reference_source"])
        self.assertGreaterEqual(result["confidence"], F3_CHECK_PHOTO_MIN_CONFIDENCE)
        self.assertLess(result["distances"]["off"], result["distances"]["on"])

    def test_classifier_does_not_receive_expected_state(self):
        result = classificar_mascara_por_referencias_locais_f3(
            current=_features(219),
            on_references=[_features(220)],
            off_references=[_features(120)],
        )

        self.assertIsNotNone(result)
        self.assertEqual("on", result["state"])

    def test_near_tie_without_low_light_evidence_keeps_searching(self):
        result = classificar_mascara_por_referencias_locais_f3(
            current=_features(150),
            on_references=[_features(160)],
            off_references=[_features(140)],
            detect_low_light=False,
        )

        self.assertIsNotNone(result)
        self.assertLess(result["confidence"], F3_CHECK_PHOTO_MIN_CONFIDENCE)

    def test_low_light_is_derived_from_real_on_off_pair(self):
        result = classificar_mascara_por_referencias_locais_f3(
            current=_features(140),
            on_references=[_features(220)],
            off_references=[_features(40)],
        )

        self.assertIsNotNone(result)
        self.assertEqual("low_light", result["state"])
        self.assertGreaterEqual(result["confidence"], F3_CHECK_PHOTO_MIN_CONFIDENCE)
        self.assertIsNotNone(result["low_light_interpolation"])

    def test_check_photos_build_complete_learning_without_manual_references(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repository, masks, checks = _project_with_two_masks(root)
            h1_id = str(checks[0]["id"])
            blue_id = str(checks[1]["id"])

            self.assertTrue(
                repository.salvar_estados_check(
                    "DISPLAY A",
                    h1_id,
                    {"MASK_001": "on", "MASK_002": "off"},
                )
            )
            self.assertTrue(
                repository.salvar_estados_check(
                    "DISPLAY A",
                    blue_id,
                    {"MASK_001": "off", "MASK_002": "on"},
                )
            )

            presence_store = DisplayCheckPresenceReferenceStore(repository)
            self.assertIsNotNone(
                presence_store.capture(
                    "DISPLAY A",
                    h1_id,
                    _frame(220, 35),
                    (120, 80),
                )
            )
            self.assertIsNotNone(
                presence_store.capture(
                    "DISPLAY A",
                    blue_id,
                    _frame(35, 220),
                    (120, 80),
                )
            )

            analyzer = F3SameMaskReferenceAnalyzer(repository)
            project = repository.carregar_projeto("DISPLAY A")
            learning = analyzer._build_check_photo_learning(
                "DISPLAY A",
                project,
                masks,
                0,
            )

            self.assertEqual(2, learning["photo_count"])
            self.assertEqual(4, learning["sample_count"])
            self.assertEqual(1, len(learning["by_mask"]["MASK_001"]["on"]))
            self.assertEqual(1, len(learning["by_mask"]["MASK_001"]["off"]))
            self.assertEqual(2, len(learning["by_state"]["on"]))
            self.assertEqual(2, len(learning["by_state"]["off"]))

    def test_live_analysis_works_with_only_check_photos_and_annotations(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repository, _masks, checks = _project_with_two_masks(root)
            h1_id = str(checks[0]["id"])
            blue_id = str(checks[1]["id"])

            self.assertTrue(
                repository.salvar_estados_check(
                    "DISPLAY A",
                    h1_id,
                    {"MASK_001": "on", "MASK_002": "off"},
                )
            )
            self.assertTrue(
                repository.salvar_estados_check(
                    "DISPLAY A",
                    blue_id,
                    {"MASK_001": "off", "MASK_002": "on"},
                )
            )

            presence_store = DisplayCheckPresenceReferenceStore(repository)
            h1_frame = _frame(220, 35)
            blue_frame = _frame(35, 220)
            self.assertIsNotNone(
                presence_store.capture(
                    "DISPLAY A",
                    h1_id,
                    h1_frame,
                    (120, 80),
                )
            )
            self.assertIsNotNone(
                presence_store.capture(
                    "DISPLAY A",
                    blue_id,
                    blue_frame,
                    (120, 80),
                )
            )

            analyzer = F3SameMaskReferenceAnalyzer(repository)
            h1 = analyzer.analyze(h1_frame, "DISPLAY A", h1_id, 0)
            blue = analyzer.analyze(blue_frame, "DISPLAY A", blue_id, 0)

            self.assertTrue(h1["ready"])
            self.assertTrue(h1["approved"])
            self.assertEqual(2, h1["matched_mask_count"])
            self.assertTrue(blue["ready"])
            self.assertTrue(blue["approved"])
            self.assertEqual(2, blue["matched_mask_count"])
            self.assertEqual(F3_CHECK_PHOTO_LEARNING_SOURCE, blue["reference_authority"])
            self.assertEqual(2, blue["same_mask_reference_used_count"])

    def test_board_off_completa_par_local_para_mascara_sempre_acesa(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repository, masks, checks = _project_with_two_masks(root)
            first_id = str(checks[0]["id"])
            second_id = str(checks[1]["id"])

            # MASK_001 fica ON em todos os CHECKS: antes desta correção ela não
            # possuía OFF local e caía no class_pool de outra máscara.
            self.assertTrue(
                repository.salvar_estados_check(
                    "DISPLAY A",
                    first_id,
                    {"MASK_001": "on", "MASK_002": "off"},
                )
            )
            self.assertTrue(
                repository.salvar_estados_check(
                    "DISPLAY A",
                    second_id,
                    {"MASK_001": "on", "MASK_002": "on"},
                )
            )

            check_store = DisplayCheckPresenceReferenceStore(repository)
            first_frame = _frame(220, 35)
            second_frame = _frame(220, 220)
            check_store.capture(
                "DISPLAY A",
                first_id,
                first_frame,
                (120, 80),
            )
            check_store.capture(
                "DISPLAY A",
                second_id,
                second_frame,
                (120, 80),
            )

            project_store = DisplayProjectPresenceReferenceStore(repository)
            board_off = _frame(35, 35)
            self.assertIsNotNone(
                project_store.capture(
                    "DISPLAY A",
                    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                    board_off,
                    (120, 80),
                )
            )
            self.assertTrue(
                project_store.save_geometry(
                    "DISPLAY A",
                    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                    [],
                    masks,
                )
            )

            analyzer = F3SameMaskReferenceAnalyzer(repository)
            project = repository.carregar_projeto("DISPLAY A")
            learning = analyzer._build_check_photo_learning(
                "DISPLAY A",
                project,
                masks,
                0,
            )

            profile = learning["by_mask"]["MASK_001"]
            self.assertEqual(2, len(profile["on"]))
            self.assertEqual(1, len(profile["off"]))
            self.assertEqual(
                DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                profile["sources"]["off"][0]["reference_kind"],
            )
            self.assertEqual(2, learning["board_off_sample_count"])

            on_refs, off_refs, source, context = analyzer._references_for_mask(
                "MASK_001",
                learning,
            )
            self.assertEqual(F3_SAME_MASK_REFERENCE_SOURCE, source)
            self.assertTrue(context["complete_local_pair"])
            self.assertEqual(2, len(on_refs))
            self.assertEqual(1, len(off_refs))

            result = analyzer.analyze(
                first_frame,
                "DISPLAY A",
                first_id,
                0,
            )
            mask_1 = next(
                item
                for item in result["mask_results"]
                if item["mask_id"] == "MASK_001"
            )
            self.assertEqual("on", mask_1["classified"])
            self.assertTrue(mask_1["matched"])
            self.assertEqual(
                F3_SAME_MASK_REFERENCE_SOURCE,
                mask_1["reference_source"],
            )
            self.assertEqual(
                DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                mask_1["reference_checks"]["off"]["reference_kind"],
            )
            self.assertTrue(result["board_off_reference_configured"])
            self.assertEqual(2, result["board_off_same_mask_sample_count"])

    def test_missing_same_mask_state_uses_other_labeled_check_masks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repository, masks, checks = _project_with_two_masks(root)
            first_id = str(checks[0]["id"])
            second_id = str(checks[1]["id"])

            self.assertTrue(
                repository.salvar_estados_check(
                    "DISPLAY A",
                    first_id,
                    {"MASK_001": "on", "MASK_002": "off"},
                )
            )
            self.assertTrue(
                repository.salvar_estados_check(
                    "DISPLAY A",
                    second_id,
                    {"MASK_001": "on", "MASK_002": "on"},
                )
            )
            store = DisplayCheckPresenceReferenceStore(repository)
            store.capture("DISPLAY A", first_id, _frame(220, 35), (120, 80))
            store.capture("DISPLAY A", second_id, _frame(220, 220), (120, 80))

            analyzer = F3SameMaskReferenceAnalyzer(repository)
            project = repository.carregar_projeto("DISPLAY A")
            learning = analyzer._build_check_photo_learning(
                "DISPLAY A",
                project,
                masks,
                0,
            )
            on_refs, off_refs, source, context = analyzer._references_for_mask(
                "MASK_001",
                learning,
            )

            self.assertEqual(F3_STATE_SAMPLE_FALLBACK_SOURCE, source)
            self.assertTrue(context["local_on"])
            self.assertFalse(context["local_off"])
            self.assertGreaterEqual(len(on_refs), 1)
            self.assertGreaterEqual(len(off_refs), 1)

    def test_no_check_dataset_is_not_replaced_by_manual_learning(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repository, _masks, checks = _project_with_two_masks(root)
            check_id = str(checks[0]["id"])
            self.assertTrue(
                repository.salvar_estados_check(
                    "DISPLAY A",
                    check_id,
                    {"MASK_001": "on", "MASK_002": "off"},
                )
            )

            analyzer = F3SameMaskReferenceAnalyzer(repository)
            result = analyzer.analyze(
                _frame(220, 35),
                "DISPLAY A",
                check_id,
                0,
            )

            self.assertFalse(result["ready"])
            self.assertEqual("checks_sem_amostras_aceso_apagado", result["reason"])
            self.assertEqual(F3_CHECK_PHOTO_LEARNING_SOURCE, result["reference_authority"])

    def test_module_has_no_manual_reference_learning_dependency(self):
        source = inspect.getsource(same_mask_module)
        for forbidden in (
            "DisplayReferenceLearningStore",
            "display_learning_path_for_repository",
            "active_references",
            "learned_features",
            "_state_reference_sets",
            "F3ReferenceAuthorityAnalyzer",
        ):
            self.assertNotIn(forbidden, source)

    def test_module_isolated_from_other_production_mode(self):
        source = inspect.getsource(same_mask_module)
        for forbidden in (
            "src.platform.f2_",
            "F2Automatic",
            "operacao_engine",
            "linux_f2_fixed_resolution",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
