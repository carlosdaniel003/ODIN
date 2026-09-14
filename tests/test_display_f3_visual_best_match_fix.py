from __future__ import annotations

import inspect
import unittest

import src.platform.display_f3_visual_analysis_relative_fallback as visual_module
from src.platform.display_f3_visual_best_match_fix import (
    resolver_melhor_check_visual_f3,
)


class DisplayF3VisualBestMatchFixTests(unittest.TestCase):
    @staticmethod
    def _candidate(
        score: float,
        *,
        kind: str,
        name: str = "",
        check_id: str = "",
        threshold: float = 0.72,
    ) -> dict:
        return {
            "score": score,
            "threshold": threshold,
            "matched": score >= threshold,
            "kind": kind,
            "name": name,
            "check_name": name,
            "check_id": check_id,
        }

    def test_frame_real_h1_mantem_h1_como_melhor_correspondencia_visual(self):
        candidates = {
            "check:CHECK_001": self._candidate(
                0.9881,
                kind="check",
                name="H1",
                check_id="CHECK_001",
            ),
            "board_off": self._candidate(0.9810, kind="board_off"),
            "check:CHECK_003": self._candidate(
                0.9787,
                kind="check",
                name="AUX",
                check_id="CHECK_003",
            ),
            "check:CHECK_004": self._candidate(
                0.9771,
                kind="check",
                name="USB",
                check_id="CHECK_004",
            ),
            "check:CHECK_002": self._candidate(
                0.9708,
                kind="check",
                name="BLUE",
                check_id="CHECK_002",
            ),
            "empty_support": self._candidate(0.3773, kind="empty_support"),
        }
        base = visual_module.resolver_analise_visual_candidatos_f3(candidates)
        self.assertEqual("ambiguous", base["result_kind"])
        self.assertEqual("check:CHECK_001", base["best_reference"])

        fixed = resolver_melhor_check_visual_f3(candidates, base)
        self.assertEqual("check", fixed["result_kind"])
        self.assertEqual("check:CHECK_001", fixed["selected_reference"])
        self.assertEqual("CHECK_001", fixed["check_id"])
        self.assertEqual("H1", fixed["check_name"])
        self.assertEqual("best_matched_check_close_references", fixed["decision_mode"])
        self.assertTrue(fixed["close_references"])
        self.assertFalse(fixed["affects_result"])

    def test_ambiguidade_fisica_continua_ambigua(self):
        candidates = {
            "empty_support": self._candidate(0.74, kind="empty_support"),
            "board_off": self._candidate(0.73, kind="board_off"),
        }
        base = visual_module.resolver_analise_visual_candidatos_f3(candidates)
        fixed = resolver_melhor_check_visual_f3(candidates, base)

        self.assertEqual("ambiguous", fixed["result_kind"])
        self.assertIsNone(fixed["selected_reference"])

    def test_empate_numerico_de_check_continua_ambiguo(self):
        candidates = {
            "check:CHECK_001": self._candidate(
                0.98,
                kind="check",
                name="H1",
                check_id="CHECK_001",
            ),
            "board_off": self._candidate(0.98, kind="board_off"),
        }
        base = visual_module.resolver_analise_visual_candidatos_f3(candidates)
        fixed = resolver_melhor_check_visual_f3(candidates, base)

        self.assertEqual("ambiguous", fixed["result_kind"])
        self.assertIsNone(fixed["selected_reference"])

    def test_correcao_nao_importa_f2_nem_altera_fluxo_produtivo(self):
        source = inspect.getsource(
            __import__(
                "src.platform.display_f3_visual_best_match_fix",
                fromlist=["resolver_melhor_check_visual_f3"],
            )
        ).lower()
        self.assertNotIn("src.platform.f2_", source)
        self.assertNotIn("registrar_resultado_check_display_f3(", source)
        self.assertNotIn("concluir_check_display_f3(", source)
        self.assertIn('"affects_result": false', source)


if __name__ == "__main__":
    unittest.main()
