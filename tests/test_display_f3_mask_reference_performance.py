from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

import src.platform.display_f3_mask_reference_performance as perf


class DisplayF3MaskReferencePerformanceTests(unittest.TestCase):
    def setUp(self):
        perf.limpar_cache_referencias_mascaras_f3()

    @staticmethod
    def _metadata(path: str = "reference.jpg") -> dict:
        return {
            "image_path": path,
            "_display_master_resolution": (120, 80),
            "_display_mask_regions": [
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

    def test_foto_jpeg_e_decodificada_uma_vez_enquanto_arquivo_nao_muda(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reference.jpg"
            cv2.imwrite(str(path), np.zeros((80, 120, 3), dtype=np.uint8))
            metadata = self._metadata(str(path))
            original_imread = cv2.imread

            with patch.object(perf.cv2, "imread", wraps=original_imread) as mocked:
                first, _ = perf._cached_reference_image(metadata)
                second, _ = perf._cached_reference_image(metadata)

            self.assertIs(first, second)
            self.assertEqual(1, mocked.call_count)

    def test_geometria_das_mascaras_e_compilada_uma_vez(self):
        metadata = self._metadata()
        original = perf.criar_mascaras_roi
        with patch.object(perf, "criar_mascaras_roi", wraps=original) as mocked:
            first, signature_a, count_a = perf._compiled_mask_regions(
                metadata,
                120,
                80,
            )
            second, signature_b, count_b = perf._compiled_mask_regions(
                metadata,
                120,
                80,
            )

        self.assertIs(first, second)
        self.assertEqual(signature_a, signature_b)
        self.assertEqual(2, count_a)
        self.assertEqual(2, count_b)
        self.assertEqual(2, mocked.call_count)

    def test_score_visual_recente_e_reutilizado_sem_refazer_todas_as_mascaras(self):
        metadata = self._metadata()
        reference = np.zeros((80, 120, 3), dtype=np.uint8)
        current = reference.copy()
        original = perf._score_regions_uncached

        with patch.object(
            perf,
            "_score_regions_uncached",
            wraps=original,
        ) as mocked:
            first = perf._fast_similarity_by_masks(reference, current, metadata)
            second = perf._fast_similarity_by_masks(reference, current, metadata)

        self.assertEqual(1, mocked.call_count)
        self.assertFalse(first["score_cache_hit"])
        self.assertTrue(second["score_cache_hit"])
        self.assertEqual(first["score"], second["score"])
        self.assertGreater(first["score"], 0.99)

    def test_frame_full_hd_no_formato_correto_nao_e_copiado(self):
        frame = np.zeros((80, 120, 3), dtype=np.uint8)
        prepared = perf._prepare_bgr_readonly(frame, (120, 80))
        self.assertIs(frame, prepared)

    def test_bootstrap_instala_otimizacao_depois_das_rois_por_mascara(self):
        source = Path("src/platform/raspberry_pi3_production_app.py").read_text(
            encoding="utf-8"
        )
        roi_call = source.index("instalar_roi_referencias_display_f3()")
        perf_call = source.index(
            "instalar_desempenho_referencias_mascaras_display_f3()"
        )
        self.assertLess(roi_call, perf_call)

    def test_modulo_de_desempenho_permanece_isolado_do_f2(self):
        source = inspect.getsource(perf).lower()
        self.assertNotIn("src.platform.f2_", source)
        self.assertNotIn("registrar_resultado_check_display_f3(", source)
        self.assertGreater(perf.F3_MASK_REFERENCE_REFRESH_SECONDS, 0.0)
        self.assertLessEqual(perf.F3_MASK_REFERENCE_REFRESH_SECONDS, 0.25)


if __name__ == "__main__":
    unittest.main()
