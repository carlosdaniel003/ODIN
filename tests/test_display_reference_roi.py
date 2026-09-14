from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import cv2
import numpy as np

import src.platform.display_check_presence_reference as check_module
import src.platform.display_f3_exact_check_template as exact_module
import src.platform.display_reference_roi as roi_module
import src.platform.display_visual_reference_status as visual_module
from src.platform.display_reference_roi import (
    DISPLAY_REFERENCE_MASK_COMPARE_MODE,
    calcular_similaridade_referencia_por_mascaras,
    construir_mascara_uniao_referencias_display,
    descricao_roi_referencia,
    instalar_roi_referencias_display_f3,
)


class _Repository:
    def __init__(self, config_file: Path) -> None:
        self.config_file = config_file
        self.project = {
            "name": "PROJETO A",
            "master_resolution": {"width": 100, "height": 100},
            "masks": [
                {
                    "id": "MASK_001",
                    "type": "circle",
                    "cx": 50,
                    "cy": 50,
                    "radius": 12,
                },
                {
                    "id": "MASK_002",
                    "type": "circle",
                    "cx": 25,
                    "cy": 50,
                    "radius": 8,
                },
            ],
            "checks": [
                {
                    "id": "CHECK_001",
                    "name": "H1",
                    "mask_states": {
                        "MASK_001": "on",
                        "MASK_002": "off",
                    },
                }
            ],
        }

    def carregar_projeto(self, project_name=None):
        del project_name
        return deepcopy(self.project)

    def listar_checks(self, project_name):
        del project_name
        return deepcopy(self.project["checks"])


class DisplayReferenceMaskRegionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        instalar_roi_referencias_display_f3()

    def test_uniao_usa_exatamente_as_mascaras_do_projeto(self):
        masks = [
            {"id": "A", "type": "circle", "cx": 20, "cy": 20, "radius": 5},
            {"id": "B", "type": "circle", "cx": 80, "cy": 80, "radius": 7},
        ]
        union = construir_mascara_uniao_referencias_display(masks, 100, 100)
        self.assertEqual((100, 100), union.shape)
        self.assertGreater(int(union[20, 20]), 0)
        self.assertGreater(int(union[80, 80]), 0)
        self.assertEqual(0, int(union[50, 50]))

    def test_alteracao_fora_das_mascaras_nao_altera_score(self):
        reference = np.zeros((100, 100, 3), dtype=np.uint8)
        metadata = {
            "_display_master_resolution": (100, 100),
            "_display_mask_regions": [
                {
                    "id": "MASK_001",
                    "type": "circle",
                    "cx": 50,
                    "cy": 50,
                    "radius": 12,
                }
            ],
        }
        current = np.full((100, 100, 3), 255, dtype=np.uint8)
        cv2.circle(current, (50, 50), 12, (0, 0, 0), -1)

        result = calcular_similaridade_referencia_por_mascaras(
            reference,
            current,
            metadata,
        )
        self.assertIsNotNone(result["score"])
        self.assertGreater(result["score"], 0.98)
        self.assertEqual(1, result["valid_mask_region_count"])
        self.assertEqual(DISPLAY_REFERENCE_MASK_COMPARE_MODE, result["comparison_mode"])

    def test_alteracao_dentro_da_mascara_reduz_score(self):
        reference = np.zeros((100, 100, 3), dtype=np.uint8)
        current = reference.copy()
        cv2.circle(current, (50, 50), 12, (255, 255, 255), -1)
        metadata = {
            "_display_master_resolution": (100, 100),
            "_display_mask_regions": [
                {
                    "id": "MASK_001",
                    "type": "circle",
                    "cx": 50,
                    "cy": 50,
                    "radius": 12,
                }
            ],
        }

        result = calcular_similaridade_referencia_por_mascaras(
            reference,
            current,
            metadata,
        )
        self.assertIsNotNone(result["score"])
        self.assertLess(result["score"], 0.50)
        self.assertIn("MASK_001", result["mask_scores"])

    def test_store_do_check_anexa_mascaras_e_descarta_roi_retangular_legada(self):
        with tempfile.TemporaryDirectory() as tmp:
            repository = _Repository(Path(tmp) / "odin_display_projects.json")
            store = check_module.DisplayCheckPresenceReferenceStore(repository)
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            self.assertIsNotNone(
                store.capture("PROJETO A", "CHECK_001", frame, (100, 100))
            )
            metadata = store.get("PROJETO A", "CHECK_001")
            self.assertEqual(2, metadata["mask_region_count"])
            self.assertEqual(2, len(metadata["_display_mask_regions"]))
            self.assertNotIn("roi", metadata)
            self.assertEqual(
                DISPLAY_REFERENCE_MASK_COMPARE_MODE,
                metadata["comparison_mode"],
            )

    def test_store_do_projeto_usa_as_mesmas_mascaras_para_off_e_vazio(self):
        with tempfile.TemporaryDirectory() as tmp:
            repository = _Repository(Path(tmp) / "odin_display_projects.json")
            store = visual_module.DisplayProjectPresenceReferenceStore(repository)
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            for kind in visual_module.DISPLAY_PROJECT_REFERENCE_TYPES:
                self.assertIsNotNone(
                    store.capture("PROJETO A", kind, frame, (100, 100))
                )
            references = store.get_all("PROJETO A")
            self.assertEqual(
                set(visual_module.DISPLAY_PROJECT_REFERENCE_TYPES),
                set(references),
            )
            for metadata in references.values():
                self.assertEqual(2, metadata["mask_region_count"])
                self.assertEqual(2, len(metadata["_display_mask_regions"]))
                self.assertNotIn("roi", metadata)

    def test_avaliador_de_presenca_ignora_fora_e_reprova_dentro_da_mascara(self):
        with tempfile.TemporaryDirectory() as tmp:
            repository = _Repository(Path(tmp) / "odin_display_projects.json")
            store = check_module.DisplayCheckPresenceReferenceStore(repository)
            reference = np.zeros((100, 100, 3), dtype=np.uint8)
            self.assertIsNotNone(
                store.capture("PROJETO A", "CHECK_001", reference, (100, 100))
            )
            metadata = store.get("PROJETO A", "CHECK_001")

            outside = np.full((100, 100, 3), 255, dtype=np.uint8)
            for mask in repository.project["masks"]:
                cv2.circle(
                    outside,
                    (int(mask["cx"]), int(mask["cy"])),
                    int(mask["radius"]),
                    (0, 0, 0),
                    -1,
                )
            outside_result = check_module.avaliar_referencia_presenca_display(
                outside,
                metadata,
            )
            self.assertTrue(outside_result["matched"])

            inside = reference.copy()
            cv2.circle(inside, (50, 50), 12, (255, 255, 255), -1)
            inside_result = check_module.avaliar_referencia_presenca_display(
                inside,
                metadata,
            )
            self.assertFalse(inside_result["matched"])
            self.assertEqual(
                DISPLAY_REFERENCE_MASK_COMPARE_MODE,
                inside_result["comparison_mode"],
            )

    def test_gabarito_fisico_exato_tambem_usa_as_mascaras(self):
        with tempfile.TemporaryDirectory() as tmp:
            repository = _Repository(Path(tmp) / "odin_display_projects.json")
            store = check_module.DisplayCheckPresenceReferenceStore(repository)
            reference = np.zeros((100, 100, 3), dtype=np.uint8)
            self.assertIsNotNone(
                store.capture("PROJETO A", "CHECK_001", reference, (100, 100))
            )
            metadata = store.get("PROJETO A", "CHECK_001")

            outside = np.full((100, 100, 3), 255, dtype=np.uint8)
            for mask in repository.project["masks"]:
                cv2.circle(
                    outside,
                    (int(mask["cx"]), int(mask["cy"])),
                    int(mask["radius"]),
                    (0, 0, 0),
                    -1,
                )
            inside = reference.copy()
            cv2.circle(inside, (50, 50), 12, (255, 255, 255), -1)

            self.assertGreater(
                exact_module._score_reference_full_roi(outside, metadata),
                0.98,
            )
            self.assertLess(
                exact_module._score_reference_full_roi(inside, metadata),
                0.72,
            )

    def test_preview_desenha_as_rois_das_mascaras(self):
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        masks = [
            {"id": "MASK_001", "type": "circle", "cx": 50, "cy": 50, "radius": 12}
        ]
        decorated = roi_module._decorate_reference_image(image, masks, (100, 100))
        self.assertEqual(image.shape, decorated.shape)
        self.assertGreater(int(np.count_nonzero(decorated)), 0)

    def test_nao_existe_mais_seletor_retangular_na_interface_produtiva(self):
        source = Path("src/platform/display_reference_roi.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("SELECIONAR ÁREA", source)
        self.assertNotIn("class DisplayReferenceRoiDialog", source)
        self.assertEqual(
            "MÁSCARAS DO PROJETO",
            descricao_roi_referencia({"roi": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8}}),
        )

    def test_modulo_de_regioes_nao_importa_f2(self):
        source = Path("src/platform/display_reference_roi.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("src.platform.f2_", source)


if __name__ == "__main__":
    unittest.main()
