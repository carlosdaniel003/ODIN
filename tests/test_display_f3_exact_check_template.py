from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

import src.platform.display_f3_exact_check_template as exact_module
from src.platform.display_check_presence_reference import (
    DisplayCheckPresenceReferenceStore,
)
from src.platform.display_f3_exact_check_template import (
    F3_EXACT_MASK_MIN_SIMILARITY,
    F3ExactCheckTemplateAnalyzer,
    _score_reference_full_roi,
    comparar_mascara_com_gabarito_f3,
)
from src.platform.display_project_repository import DisplayProjectRepository
from src.platform.raspberry_pi3_production_app import RaspberryPi3ProductionApp


def _frame(mask_1_value: int, mask_2_value: int) -> np.ndarray:
    image = np.full((80, 120, 3), 25, dtype=np.uint8)
    image[25:56, 15:46] = int(mask_1_value)
    image[25:56, 75:106] = int(mask_2_value)
    return image


def _repository(root: Path):
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
    check = repository.listar_checks("DISPLAY A")[0]
    check_id = str(check["id"])
    assert repository.salvar_estados_check(
        "DISPLAY A",
        check_id,
        {"MASK_001": "on", "MASK_002": "off"},
    )
    return repository, masks, check_id


class DisplayF3ExactCheckTemplateTests(unittest.TestCase):
    def test_analisador_exato_intermitente_mantem_classificador_on_off_separado_da_foto(self):
        source = inspect.getsource(F3ExactCheckTemplateAnalyzer)
        self.assertIn("learned_state_analyzer", source)
        self.assertIn("classification_source", source)
        self.assertIn("intermittent_tolerated", source)
        self.assertIn("avaliar_match_check_display", source)

    def test_current_check_photo_alone_is_enough_to_approve_same_scene(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repository, _masks, check_id = _repository(root)
            reference = _frame(225, 35)
            store = DisplayCheckPresenceReferenceStore(repository)
            self.assertIsNotNone(
                store.capture(
                    "DISPLAY A",
                    check_id,
                    reference,
                    (120, 80),
                )
            )

            analyzer = F3ExactCheckTemplateAnalyzer(repository)
            result = analyzer.analyze(
                frame=reference.copy(),
                project_name="DISPLAY A",
                check_id=check_id,
                visual_rotation=0,
            )

            self.assertTrue(result["ready"])
            self.assertTrue(result["approved"])
            self.assertEqual(2, result["active_mask_count"])
            self.assertEqual(2, result["matched_mask_count"])
            self.assertEqual(
                "f3_current_check_exact_photo",
                result["reference_authority"],
            )
            self.assertTrue(
                all(
                    item["template_similarity"] >= F3_EXACT_MASK_MIN_SIMILARITY
                    for item in result["mask_results"]
                )
            )

    def test_expected_on_mask_fails_when_same_physical_segment_is_off(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repository, _masks, check_id = _repository(root)
            reference = _frame(225, 35)
            store = DisplayCheckPresenceReferenceStore(repository)
            store.capture("DISPLAY A", check_id, reference, (120, 80))

            current = _frame(35, 35)
            analyzer = F3ExactCheckTemplateAnalyzer(repository)
            result = analyzer.analyze(
                frame=current,
                project_name="DISPLAY A",
                check_id=check_id,
                visual_rotation=0,
            )

            self.assertTrue(result["ready"])
            self.assertFalse(result["approved"])
            self.assertEqual(1, result["matched_mask_count"])
            first = next(
                item
                for item in result["mask_results"]
                if item["mask_id"] == "MASK_001"
            )
            self.assertEqual("on", first["expected"])
            self.assertEqual("off", first["classified"])
            self.assertFalse(first["matched"])

    def test_identical_mask_pixels_score_as_same_template(self):
        from src.platform.display_auto_check_analyzer import (
            display_mask_to_analysis_selection,
        )

        mask = {
            "id": "MASK_001",
            "type": "circle",
            "cx": 30,
            "cy": 40,
            "radius": 10,
        }
        selection = display_mask_to_analysis_selection(mask)
        reference = _frame(225, 35)
        comparison = comparar_mascara_com_gabarito_f3(
            reference.copy(),
            reference,
            selection,
        )
        self.assertIsNotNone(comparison)
        self.assertGreaterEqual(comparison["similarity"], 0.99)

    def test_reference_roi_is_cropped_before_similarity_reduction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            off_path = root / "off.png"
            h1_path = root / "h1.png"

            off = np.full((500, 1000, 3), 100, dtype=np.uint8)
            h1 = off.copy()
            # O display ocupa uma área pequena do frame grande. Esta diferença
            # seria quase apagada se 1000 px fossem reduzidos antes do recorte.
            off[220:280, 400:600] = 30
            h1[220:280, 400:600] = 225
            cv2.imwrite(str(off_path), off)
            cv2.imwrite(str(h1_path), h1)

            roi = {
                "x": 0.40,
                "y": 0.44,
                "width": 0.20,
                "height": 0.12,
            }
            off_meta = {
                "image_path": str(off_path),
                "threshold": 0.72,
                "roi": roi,
            }
            h1_meta = {
                "image_path": str(h1_path),
                "threshold": 0.72,
                "roi": roi,
            }

            score_off = _score_reference_full_roi(off.copy(), off_meta)
            score_h1 = _score_reference_full_roi(off.copy(), h1_meta)
            self.assertIsNotNone(score_off)
            self.assertIsNotNone(score_h1)
            self.assertGreater(score_off, 0.99)
            self.assertGreater(score_off - score_h1, 0.20)

    def test_exact_template_installs_after_previous_f3_learning_layers(self):
        source = inspect.getsource(RaspberryPi3ProductionApp.__init__)
        policy_position = source.index(
            "instalar_politica_fisica_e_aprendizado_display_f3()"
        )
        exact_position = source.index(
            "instalar_gabarito_exato_checks_display_f3()"
        )
        super_position = source.index("super().__init__(root)")
        self.assertLess(policy_position, exact_position)
        self.assertLess(exact_position, super_position)

    def test_exact_template_module_has_no_f2_dependency(self):
        source = inspect.getsource(exact_module)
        for forbidden in (
            "src.platform.f2_",
            "F2Automatic",
            "operacao_engine",
            "linux_f2_fixed_resolution",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
