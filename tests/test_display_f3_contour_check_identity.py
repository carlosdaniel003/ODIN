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


    def test_refinamento_direto_aplica_referencia_do_h1_identificado(self):
        raw = np.zeros((40, 60, 3), dtype=np.uint8)
        matrix = np.asarray(
            [[1.0, 0.0, 0.4], [0.0, 1.0, -0.3]],
            dtype=np.float32,
        )
        candidate = {
            "reference": "check:CHECK_001",
            "matrix": matrix,
            "matches": 18,
            "inliers": 15,
            "ratio": 0.8333,
            "rotation_deg": 0.0,
            "scale": 1.0,
            "source_type": "check",
            "current_masked_for_segments": True,
        }
        runtime = SimpleNamespace(
            width=60,
            height=40,
            canonical_masks=[],
            last_result=None,
            candidate_for_reference=lambda *_args, **_kwargs: candidate,
            _matrix_continuity=lambda _matrix: (True, 0.98),
        )
        base = SimpleNamespace(
            current_to_canonical=np.asarray(
                [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                dtype=np.float32,
            ),
            reference="board_off",
        )
        app = SimpleNamespace(
            _display_f3_tracking_result=base,
            _display_f3_tracking_live_geometry={
                "locked": True,
                "resolution": (60, 40),
                "board_points": [[5, 5], [55, 5], [55, 35], [5, 35]],
                "masks": [],
                "reference": "board_off",
                "geometry_space": "check:CHECK_001",
            },
            _display_auto_current_context=lambda: {
                "check_id": "CHECK_001",
                "check_name": "H1",
            },
        )

        def publish(_app, _raw, refined):
            _app._display_f3_tracking_live_geometry = {
                "locked": True,
                "resolution": (60, 40),
                "board_points": [[5, 5], [55, 5], [55, 35], [5, 35]],
                "masks": [{"id": "MASK_001"}],
                "reference": refined.reference,
                "geometry_space": "check:CHECK_001",
            }

        with patch.object(identity, "get_tracking_runtime", return_value=runtime), patch.object(
            identity,
            "build_tracking_mask",
            return_value=np.ones((40, 60), dtype=np.uint8) * 255,
        ), patch.object(
            identity,
            "_update_tracking_live_geometry",
            side_effect=publish,
        ):
            result = identity.refinar_geometria_check_identificado_f3(
                app,
                raw,
                {
                    "confirmed": True,
                    "best_check_id": "CHECK_001",
                    "best_check_name": "H1",
                },
            )

        self.assertTrue(result["applied"])
        self.assertEqual("board_off", result["base_reference"])
        self.assertEqual("check:CHECK_001", result["direct_reference"])
        self.assertEqual(15, result["inliers"])
        self.assertTrue(result["current_masked_for_segments"])

    def test_refinamento_nao_usa_aux_quando_logico_ainda_e_h1(self):
        raw = np.zeros((40, 60, 3), dtype=np.uint8)
        app = SimpleNamespace(
            _display_auto_current_context=lambda: {
                "check_id": "CHECK_001",
                "check_name": "H1",
            },
        )
        result = identity.refinar_geometria_check_identificado_f3(
            app,
            raw,
            {
                "confirmed": True,
                "best_check_id": "CHECK_003",
                "best_check_name": "AUX",
            },
        )

        self.assertFalse(result["applied"])
        self.assertEqual(
            "check_identificado_diferente_do_check_logico",
            result["reason"],
        )

if __name__ == "__main__":
    unittest.main()
