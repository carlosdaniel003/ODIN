from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

import src.platform.display_f3_mask_reference_performance as perf
import src.platform.display_f3_overlay_immediate as overlay_immediate
import src.platform.display_f3_reference_lightweight as lightweight


class DisplayF3MaskReferencePerformanceTests(unittest.TestCase):
    def setUp(self):
        perf.limpar_cache_referencias_mascaras_f3()
        lightweight.limpar_cache_projeto_f3()

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

    def test_uniao_simples_ignora_tudo_fora_das_mascaras(self):
        metadata = self._metadata()
        reference = np.zeros((80, 120, 3), dtype=np.uint8)
        current = np.full((80, 120, 3), 255, dtype=np.uint8)
        cv2.circle(current, (40, 40), 10, (0, 0, 0), -1)
        cv2.circle(current, (80, 40), 10, (0, 0, 0), -1)

        result = lightweight._union_similarity(reference, current, metadata)

        self.assertGreater(result["score"], 0.99)
        self.assertEqual("single_union_of_project_masks", result["region_strategy"])
        self.assertEqual(2, result["valid_mask_region_count"])

    def test_uniao_simples_detecta_alteracao_dentro_de_uma_mascara(self):
        metadata = self._metadata()
        reference = np.zeros((80, 120, 3), dtype=np.uint8)
        current = reference.copy()
        cv2.circle(current, (40, 40), 10, (255, 255, 255), -1)

        result = lightweight._union_similarity(reference, current, metadata)

        self.assertLess(result["score"], 0.85)
        self.assertEqual(2, result["valid_mask_region_count"])

    def test_uniao_binaria_e_cacheada_em_vez_de_reconstruida_por_referencia(self):
        metadata = self._metadata()
        reference = np.zeros((80, 120, 3), dtype=np.uint8)
        original = lightweight.roi.construir_mascara_uniao_referencias_display

        with patch.object(
            lightweight.roi,
            "construir_mascara_uniao_referencias_display",
            wraps=original,
        ) as mocked:
            lightweight._union_similarity(reference, reference, metadata)
            lightweight._union_similarity(reference, reference, metadata)

        self.assertEqual(1, mocked.call_count)

    def test_frame_full_hd_no_formato_correto_nao_e_copiado(self):
        frame = np.zeros((80, 120, 3), dtype=np.uint8)
        prepared = perf._prepare_bgr_readonly(frame, (120, 80))
        self.assertIs(frame, prepared)

    def test_bootstrap_instala_uniao_leve_depois_da_autoridade_final(self):
        source = Path("src/platform/raspberry_pi3_production_app.py").read_text(
            encoding="utf-8"
        )
        roi_call = source.index("instalar_roi_referencias_display_f3()")
        perf_call = source.index(
            "instalar_desempenho_referencias_mascaras_display_f3()"
        )
        strict_call = source.index("instalar_conformidade_estrita_mascaras_display_f3()")
        lightweight_call = source.index("instalar_referencias_leves_display_f3()")
        self.assertLess(roi_call, perf_call)
        self.assertLess(strict_call, lightweight_call)

    def test_preview_e_analysis_sao_callbacks_separados(self):
        source = inspect.getsource(overlay_immediate._install_analysis_after_paint)
        self.assertIn(
            "DisplayProductionF3Mixin._atualizar_preview_display_f3(self)",
            source,
        )
        self.assertIn("self.root.after(", source)
        self.assertGreaterEqual(overlay_immediate.F3_RESPONSIVE_PREVIEW_INTERVAL_MS, 70)
        self.assertGreater(overlay_immediate.F3_ANALYSIS_AFTER_PAINT_MS, 0)

    def test_modulos_de_desempenho_permanecem_isolados_do_f2(self):
        sources = (
            inspect.getsource(perf).lower(),
            inspect.getsource(lightweight).lower(),
            inspect.getsource(overlay_immediate).lower(),
        )
        for source in sources:
            self.assertNotIn("src.platform.f2_", source)
        self.assertNotIn("registrar_resultado_check_display_f3(", sources[0])
        self.assertGreater(perf.F3_MASK_REFERENCE_REFRESH_SECONDS, 0.0)


if __name__ == "__main__":
    unittest.main()
