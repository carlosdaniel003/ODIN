from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

import numpy as np

import src.platform.display_f3_check_photo_learning as learning_module
import src.platform.display_f3_strict_mask_conformity as strict_module
from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin
from src.platform.display_check_presence_reference import DisplayCheckPresenceReferenceStore
from src.platform.display_f3_same_mask_reference_fix import F3SameMaskReferenceAnalyzer
from src.platform.display_f3_check_photo_learning import (
    F3_CHECK_PHOTO_LEARNING_AUTHORITY,
    F3_CHECK_PHOTO_LEARNING_SOURCE,
    F3CheckPhotoLearningAnalyzer,
    instalar_aprendizado_foto_check_display_f3,
)
from src.platform.display_project_repository import DisplayProjectRepository
from src.platform.desktop_production_app import DesktopProductionApp


def _frame(left: int, right: int) -> np.ndarray:
    image = np.full((80, 120, 3), 24, dtype=np.uint8)
    image[24:57, 14:47] = int(left)
    image[24:57, 74:107] = int(right)
    return image


def _repository(root: Path):
    repository = DisplayProjectRepository(root / "odin_display_projects.json")
    assert repository.adicionar_projeto("DISPLAY A", (120, 80))
    masks = [
        {"id": "MASK_001", "type": "circle", "cx": 30, "cy": 40, "radius": 11},
        {"id": "MASK_002", "type": "circle", "cx": 90, "cy": 40, "radius": 11},
    ]
    assert repository.salvar_mascaras("DISPLAY A", masks)
    check = repository.listar_checks("DISPLAY A")[0]
    check_id = str(check["id"])
    assert repository.salvar_estados_check(
        "DISPLAY A",
        check_id,
        {"MASK_001": "on", "MASK_002": "off"},
    )
    reference = _frame(225, 35)
    store = DisplayCheckPresenceReferenceStore(repository)
    assert store.capture("DISPLAY A", check_id, reference, (120, 80)) is not None
    return repository, check_id, reference


class DisplayF3CheckPhotoLearningTests(unittest.TestCase):
    def test_current_check_photo_and_mask_states_are_the_learning_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, check_id, reference = _repository(Path(temp))
            analyzer = F3CheckPhotoLearningAnalyzer(repository)

            result = analyzer.analyze(
                frame=reference.copy(),
                project_name="DISPLAY A",
                check_id=check_id,
                visual_rotation=0,
            )

            self.assertTrue(result["ready"])
            self.assertTrue(result["approved"])
            self.assertEqual(2, result["matched_mask_count"])
            self.assertEqual(F3_CHECK_PHOTO_LEARNING_AUTHORITY, result["learning_authority"])
            self.assertEqual(F3_CHECK_PHOTO_LEARNING_SOURCE, result["learning_source"])
            self.assertTrue(result["uses_current_check_photo"])
            self.assertTrue(result["uses_mask_states"])
            self.assertFalse(result["legacy_reference_learning_used"])
            self.assertFalse(result["cross_check_learning_used"])
            self.assertFalse(result["manual_reference_store_used"])
            self.assertTrue(
                all(item["same_physical_mask_template"] for item in result["mask_results"])
            )

    def test_divergent_segment_fails_against_same_mask_in_check_photo(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, check_id, _reference = _repository(Path(temp))
            analyzer = F3CheckPhotoLearningAnalyzer(repository)

            result = analyzer.analyze(
                frame=_frame(35, 35),
                project_name="DISPLAY A",
                check_id=check_id,
                visual_rotation=0,
            )

            self.assertTrue(result["ready"])
            self.assertFalse(result["approved"])
            failed = next(
                item for item in result["mask_results"] if item["mask_id"] == "MASK_001"
            )
            self.assertEqual("on", failed["expected"])
            self.assertEqual("off", failed["classified"])
            self.assertFalse(failed["matched"])
            self.assertEqual("check.mask_states", failed["expected_state_source"])

    def test_final_installer_replaces_strict_cross_check_runtime_authority(self):
        # A camada estrita histórica ainda fornece overlay/status, mas deixa de
        # ser a classe produtiva depois da autoridade final do CHECK.
        strict_module.instalar_conformidade_estrita_mascaras_display_f3()
        instalar_aprendizado_foto_check_display_f3()

        import src.platform.display_auto_check_runtime as runtime_module
        import src.platform.display_f3_live_runtime_fix as live_runtime_module
        import src.platform.display_f3_live_diagnostic_trace as trace_module

        self.assertIs(runtime_module.DisplayAutomaticCheckAnalyzer, F3SameMaskReferenceAnalyzer)
        self.assertIs(live_runtime_module.DisplayAutomaticCheckAnalyzer, F3SameMaskReferenceAnalyzer)
        self.assertIs(trace_module.F3ExactCheckTemplateAnalyzer, F3SameMaskReferenceAnalyzer)

    def test_final_authority_is_installed_after_historical_strict_layer(self):
        source = inspect.getsource(DesktopProductionApp.__init__)
        strict_position = source.index("instalar_conformidade_estrita_mascaras_display_f3()")
        photo_position = source.index("instalar_aprendizado_foto_check_display_f3()")
        super_position = source.index("super().__init__(root)")
        self.assertLess(strict_position, photo_position)
        self.assertLess(photo_position, super_position)

    def test_new_authority_has_no_manual_reference_store_or_f2_dependency(self):
        source = inspect.getsource(learning_module)
        self.assertNotIn("DisplayReferenceLearningStore", source)
        self.assertNotIn("display_reference_store", source)
        for forbidden in (
            "src.platform.f2_",
            "F2Automatic",
            "operacao_engine",
            "linux_f2_fixed_resolution",
        ):
            self.assertNotIn(forbidden, source)

    def test_legacy_reference_panel_is_retired_by_final_installer(self):
        import src.platform.display_project_config as config_module

        instalar_aprendizado_foto_check_display_f3()
        self.assertTrue(
            getattr(
                config_module.DisplayProjectConfigWindow,
                "_display_f3_legacy_reference_ui_retired",
                False,
            )
        )


if __name__ == "__main__":
    unittest.main()
