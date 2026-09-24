from __future__ import annotations

import unittest

from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin


BLUE_ON_IDS = {
    "MASK_001", "MASK_002", "MASK_005", "MASK_006", "MASK_007",
    "MASK_008", "MASK_009", "MASK_010", "MASK_015", "MASK_017",
    "MASK_019", "MASK_020", "MASK_021", "MASK_022", "MASK_023",
    "MASK_025", "MASK_026", "MASK_027",
}


def _analysis(
    missing: set[str] | None = None,
    exact_similarity: dict[str, float] | None = None,
):
    missing = set(missing or set())
    exact_similarity = dict(exact_similarity or {})
    rows = []
    for index in range(1, 29):
        mask_id = f"MASK_{index:03d}"
        expected = "on" if mask_id in BLUE_ON_IDS else "off"
        is_missing = mask_id in missing and expected == "on"
        classified = "off" if is_missing else expected
        rows.append(
            {
                "mask_id": mask_id,
                "expected": expected,
                "classified": classified,
                "matched": classified == expected,
                "confidence": 0.95,
                "template_similarity": exact_similarity.get(mask_id),
                "template_threshold": 0.82 if mask_id in exact_similarity else None,
            }
        )
    return {"ready": True, "mask_results": rows}


class DisplayF3IntermittentRuntimeTests(unittest.TestCase):
    def _runtime(self):
        runtime = DisplayAutomaticCheckF3Mixin.__new__(
            DisplayAutomaticCheckF3Mixin
        )
        runtime._display_auto_intermittent_on_samples = 0
        runtime._display_auto_intermittent_failure_counts = {}
        runtime._display_auto_intermittent_persistent_failed_ids = set()
        runtime._display_auto_intermittent_exact_veto_ids = set()
        runtime._display_auto_intermittent_candidate_failed_ids = set()
        runtime._display_auto_intermittent_last_phase_analysis = None
        return runtime

    def test_fase_totalmente_apagada_nao_e_amostra_de_defeito(self):
        runtime = self._runtime()
        analysis = _analysis(set(BLUE_ON_IDS))
        state = runtime._display_auto_observe_intermittent_phase(
            {"intermittent": True},
            analysis,
        )
        self.assertEqual("off", state["phase"])
        self.assertEqual(0, state["on_phase_samples"])
        self.assertEqual((), state["persistent_failed_ids"])

    def test_mesma_mascara_ausente_em_tres_fases_on_vira_defeito_persistente(self):
        runtime = self._runtime()
        state = None
        for _ in range(3):
            state = runtime._display_auto_observe_intermittent_phase(
                {"intermittent": True},
                _analysis({"MASK_023"}),
            )
        self.assertEqual("on", state["phase"])
        self.assertIn("MASK_023", state["persistent_failed_ids"])
        self.assertEqual(3, state["failure_counts"]["MASK_023"])

    def test_mascara_que_volta_a_acender_na_fase_on_reseta_suspeita(self):
        runtime = self._runtime()
        runtime._display_auto_observe_intermittent_phase(
            {"intermittent": True},
            _analysis({"MASK_023"}),
        )
        state = runtime._display_auto_observe_intermittent_phase(
            {"intermittent": True},
            _analysis(),
        )
        self.assertEqual(0, state["failure_counts"]["MASK_023"])
        self.assertNotIn("MASK_023", state["persistent_failed_ids"])


    def test_mask_010_falso_off_e_vetado_por_template_exato_forte(self):
        runtime = self._runtime()
        analysis = _analysis(
            {"MASK_010", "MASK_027"},
            exact_similarity={
                "MASK_010": 0.9875,
                "MASK_027": 0.7105,
            },
        )
        state = runtime._display_auto_observe_intermittent_phase(
            {"intermittent": True},
            analysis,
        )

        self.assertIn("MASK_010", state["exact_template_veto_ids"])
        self.assertNotIn("MASK_010", state["candidate_failed_ids"])
        self.assertEqual(0, state["failure_counts"]["MASK_010"])
        self.assertIn("MASK_027", state["candidate_failed_ids"])
        self.assertEqual(1, state["failure_counts"]["MASK_027"])

        effective = runtime._display_auto_apply_intermittent_exact_veto(
            analysis,
            state,
        )
        by_id = {item["mask_id"]: item for item in effective["mask_results"]}
        self.assertEqual("on", by_id["MASK_010"]["classified"])
        self.assertTrue(by_id["MASK_010"]["matched"])
        self.assertEqual(
            "off",
            by_id["MASK_010"]["learned_classified_before_exact_veto"],
        )
        self.assertEqual("off", by_id["MASK_027"]["classified"])
        self.assertFalse(by_id["MASK_027"]["matched"])

    def test_mask_027_continua_defeito_apos_tres_fases_on(self):
        runtime = self._runtime()
        state = None
        for _ in range(3):
            state = runtime._display_auto_observe_intermittent_phase(
                {"intermittent": True},
                _analysis(
                    {"MASK_010", "MASK_027"},
                    exact_similarity={
                        "MASK_010": 0.9875,
                        "MASK_027": 0.7105,
                    },
                ),
            )
        self.assertEqual(("MASK_027",), state["persistent_failed_ids"])
        self.assertEqual(0, state["failure_counts"]["MASK_010"])
        self.assertEqual(3, state["failure_counts"]["MASK_027"])


if __name__ == "__main__":
    unittest.main()
