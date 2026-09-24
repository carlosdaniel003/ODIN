from __future__ import annotations

import unittest

from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin


def _analysis(missing: set[str] | None = None):
    missing = set(missing or set())
    rows = []
    for index in range(1, 19):
        mask_id = f"MASK_{index:03d}"
        is_missing = mask_id in missing
        rows.append(
            {
                "mask_id": mask_id,
                "expected": "on",
                "classified": "off" if is_missing else "on",
                "matched": not is_missing,
                "confidence": 0.95,
            }
        )
    for index in range(19, 29):
        mask_id = f"MASK_{index:03d}"
        rows.append(
            {
                "mask_id": mask_id,
                "expected": "off",
                "classified": "off",
                "matched": True,
                "confidence": 0.95,
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
        runtime._display_auto_intermittent_last_phase_analysis = None
        return runtime

    def test_fase_totalmente_apagada_nao_e_amostra_de_defeito(self):
        runtime = self._runtime()
        analysis = _analysis(
            {f"MASK_{index:03d}" for index in range(1, 19)}
        )
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


if __name__ == "__main__":
    unittest.main()
