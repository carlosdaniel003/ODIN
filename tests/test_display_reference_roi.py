from __future__ import annotations

import inspect
import unittest
from copy import deepcopy

import cv2
import numpy as np

import src.platform.display_reference_roi as roi


class _Repository:
    def __init__(self):
        self.calls = 0
        self.project = {
            "name": "PROJETO A",
            "master_resolution": {"width": 120, "height": 80},
            "masks": [
                {
                    "id": "MASK_001",
                    "type": "circle",
                    "cx": 40,
                    "cy": 40,
                    "radius": 10,
                },
                {
                    "id": "MASK_002",
                    "type": "circle",
                    "cx": 80,
                    "cy": 40,
                    "radius": 10,
                },
            ],
        }

    def carregar_projeto(self, _name):
        self.calls += 1
        return deepcopy(self.project)


class DisplayReferenceMaskRoiTests(unittest.TestCase):
    def setUp(self):
        roi._PROJECT_MASK_CACHE.clear()
        roi._UNION_CACHE.clear()
        self.repository = _Repository()
        self.metadata = roi._decorate_metadata(
            self.repository,
            "PROJETO A",
            {
                "image_path": "reference.jpg",
                "threshold": 0.72,
                "roi": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8},
            },
        )

    def test_recorte_retangular_antigo_perde_autoridade(self):
        self.assertNotIn("roi", self.metadata)
        self.assertEqual(2, self.metadata["mask_region_count"])
        self.assertEqual("project_mask_union", self.metadata["comparison_mode"])
        self.assertEqual("MÁSCARAS DO PROJETO", roi.descricao_roi_referencia(self.metadata))

    def test_contexto_de_mascaras_do_projeto_e_cacheado(self):
        roi._decorate_metadata(
            self.repository,
            "PROJETO A",
            {"image_path": "outra.jpg", "threshold": 0.72},
        )
        self.assertEqual(1, self.repository.calls)

    def test_uniao_contem_exatamente_as_regioes_das_mascaras(self):
        union = roi._union_mask(self.metadata, 120, 80)
        self.assertEqual((80, 120), union.shape)
        self.assertGreater(int(union[40, 40]), 0)
        self.assertGreater(int(union[40, 80]), 0)
        self.assertEqual(0, int(union[10, 10]))
        self.assertEqual(0, int(union[40, 60]))

    def test_alteracao_fora_das_mascaras_nao_afeta_score(self):
        reference = np.zeros((80, 120, 3), dtype=np.uint8)
        current = np.full((80, 120, 3), 255, dtype=np.uint8)
        cv2.circle(current, (40, 40), 10, (0, 0, 0), -1)
        cv2.circle(current, (80, 40), 10, (0, 0, 0), -1)

        score = roi.calcular_similaridade_referencia_por_mascaras(
            reference,
            current,
            self.metadata,
        )
        self.assertIsNotNone(score)
        self.assertGreater(score, 0.98)

    def test_alteracao_dentro_da_mascara_reduz_score(self):
        reference = np.zeros((80, 120, 3), dtype=np.uint8)
        current = reference.copy()
        cv2.circle(current, (40, 40), 10, (255, 255, 255), -1)

        score = roi.calcular_similaridade_referencia_por_mascaras(
            reference,
            current,
            self.metadata,
        )
        self.assertIsNotNone(score)
        self.assertLess(score, 0.90)

    def test_preview_desenha_as_mascaras_na_foto_de_referencia(self):
        image = np.zeros((80, 120, 3), dtype=np.uint8)
        decorated = roi._decorate_reference_image(image, self.metadata)
        self.assertEqual(image.shape, decorated.shape)
        self.assertGreater(int(np.count_nonzero(decorated)), 0)

    def test_instalador_nao_altera_loop_preview_ou_cria_timer(self):
        source = inspect.getsource(roi)
        self.assertNotIn("_atualizar_preview_display_f3", source)
        self.assertNotIn("root.after(", source)
        self.assertNotIn("DISPLAY_F3_PREVIEW_INTERVAL_MS", source)
        self.assertNotIn("SELECIONAR ÁREA", source)

    def test_modulo_permanece_isolado_do_f2(self):
        source = inspect.getsource(roi).lower()
        self.assertNotIn("src.platform.f2_", source)


if __name__ == "__main__":
    unittest.main()
