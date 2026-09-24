from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

import src.platform.display_f3_contour_check_identity as identity


class DisplayF3ContourCheckIdentityTests(unittest.TestCase):
    def test_identidade_escolhe_check_com_melhor_contorno_e_margem(self):
        result = identity.selecionar_identidade_check_f3(
            [
                {"available": True, "check_id": "CHECK_001", "check_name": "H1", "score": 0.82},
                {"available": True, "check_id": "CHECK_002", "check_name": "BLUE", "score": 0.61},
                {"available": True, "check_id": "CHECK_004", "check_name": "USB", "score": 0.58},
            ]
        )
        self.assertTrue(result["confirmed"])
        self.assertEqual("CHECK_001", result["best_check_id"])
        self.assertGreater(result["margin"], identity.F3_CONTOUR_IDENTITY_MIN_MARGIN)

    def test_identidade_nao_chuta_quando_checks_estao_empatados(self):
        result = identity.selecionar_identidade_check_f3(
            [
                {"available": True, "check_id": "CHECK_001", "check_name": "H1", "score": 0.72},
                {"available": True, "check_id": "CHECK_003", "check_name": "AUX", "score": 0.71},
            ]
        )
        self.assertFalse(result["confirmed"])
        self.assertEqual("identidade_check_ambigua_no_contorno", result["reason"])

    def test_similaridade_do_display_resiste_a_mudanca_global_de_exposicao(self):
        board = np.zeros((80, 140), dtype=np.uint8)
        board[10:70, 10:130] = 255
        display = np.zeros_like(board)
        display[25:55, 45:95] = 255

        reference = np.full((80, 140, 3), 70, dtype=np.uint8)
        reference[25:55, 45:95] = 220
        current = np.full((80, 140, 3), 35, dtype=np.uint8)
        current[25:55, 45:95] = 150

        result = identity.calcular_similaridade_contorno_check_f3(
            current,
            reference,
            board,
            display,
        )
        self.assertTrue(result["available"])
        self.assertGreater(result["score"], 0.70)

    def test_analisador_rastreado_usa_frame_raw_e_mascaras_moveis(self):
        raw = np.zeros((40, 60, 3), dtype=np.uint8)
        aligned = np.ones((40, 60, 3), dtype=np.uint8)
        geometry = {
            "locked": True,
            "resolution": (60, 40),
            "geometry_space": "check:CHECK_001",
            "reference": "check:CHECK_001",
            "masks": [{"id": "MASK_001", "type": "circle", "cx": 20, "cy": 20, "radius": 5}],
        }
        app = SimpleNamespace(
            _display_f3_tracking_live_geometry=geometry,
            _display_f3_tracking_raw_authority_frame=raw,
        )
        repository = object()
        analyzer = object.__new__(identity.F3TrackedRawCheckAnalyzer)
        analyzer.repository = repository
        analyzer.app = app
        analyzer.semantic = SimpleNamespace(analyze=lambda **_kwargs: {})

        expected = {
            "ready": True,
            "approved": True,
            "mask_results": [],
        }
        with patch.object(analyzer.semantic, "analyze", return_value=expected) as call:
            result = analyzer.analyze(
                aligned,
                "DISPLAY A",
                "CHECK_001",
                180,
            )

        kwargs = call.call_args.kwargs
        self.assertIs(raw, kwargs["frame"])
        self.assertEqual(geometry["masks"], kwargs["mask_geometry_override"])
        self.assertEqual((60, 40), kwargs["mask_geometry_resolution"])
        self.assertEqual("tracking_raw_with_live_geometry", result["analysis_frame_source"])


if __name__ == "__main__":
    unittest.main()
