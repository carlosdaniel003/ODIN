from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.models.led_features import LedFeatures
import src.platform.display_f3_physical_learning_policy as policy_module
from src.platform.display_check_presence_reference import (
    DisplayCheckPresenceReferenceStore,
)
from src.platform.display_f3_physical_learning_policy import (
    F3_STATUS_BOARD_OFF,
    F3_STATUS_BOARD_ON_PREFIX,
    aplicar_contexto_ao_estado_fisico_f3,
    avaliar_evidencia_energia_check_pelas_mascaras_f3,
    classificar_mascara_binaria_pelas_fotos_dos_checks_f3,
    decidir_placa_desligada_por_votos_mascaras_f3,
)
from src.platform.display_project_repository import DisplayProjectRepository
from src.platform.display_visual_reference_status import (
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
    DisplayProjectPresenceReferenceStore,
    DisplayVisualReferenceMatcher,
)
from src.platform.desktop_production_app import DesktopProductionApp


def _features(value: float) -> LedFeatures:
    return LedFeatures(
        v_mean=float(value),
        v_max=float(value),
        v_std=float(value) * 0.18,
        v_p95=float(value),
        v_p99=float(value),
        s_mean=float(value) * 0.22,
        s_std=float(value) * 0.08,
        center_to_ring_v=float(value) * 0.06,
        center_to_ring_s=float(value) * 0.02,
        percent_hot_235=max(0.0, min(1.0, (float(value) - 180.0) / 80.0)),
        percent_hot_245=max(0.0, min(1.0, (float(value) - 200.0) / 60.0)),
        percent_hot_250=max(0.0, min(1.0, (float(value) - 220.0) / 40.0)),
        glow_score=float(value) * 0.20,
        area_pixels=120,
        inner_area_pixels=60,
        ring_area_pixels=60,
    )


def _frame(mask_1_value: int, mask_2_value: int) -> np.ndarray:
    image = np.full((80, 120, 3), 20, dtype=np.uint8)
    image[25:56, 15:46] = int(mask_1_value)
    image[25:56, 75:106] = int(mask_2_value)
    return image


def _project_with_h1(root: Path):
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
    h1 = repository.listar_checks("DISPLAY A")[0]
    h1_id = str(h1["id"])
    assert repository.salvar_estados_check(
        "DISPLAY A",
        h1_id,
        {"MASK_001": "on", "MASK_002": "on"},
    )
    return repository, h1_id


class DisplayF3PhysicalLearningPolicyTests(unittest.TestCase):
    def test_board_off_has_priority_over_logical_h1(self):
        state = aplicar_contexto_ao_estado_fisico_f3(
            {
                "kind": "off",
                "text": "CHECK ATUAL • H1",
                "allow_auto": True,
            },
            current_check_id="CHECK_H1",
        )

        self.assertEqual("off", state["kind"])
        self.assertEqual(F3_STATUS_BOARD_OFF, state["text"])
        self.assertFalse(state["allow_auto"])

    def test_only_same_physical_check_releases_automatic_analysis(self):
        h1 = aplicar_contexto_ao_estado_fisico_f3(
            {
                "kind": "check",
                "check_id": "CHECK_H1",
                "check_name": "H1",
            },
            current_check_id="CHECK_H1",
        )
        blue = aplicar_contexto_ao_estado_fisico_f3(
            {
                "kind": "check",
                "check_id": "CHECK_BLUE",
                "check_name": "BLUE",
            },
            current_check_id="CHECK_H1",
        )

        self.assertTrue(h1["allow_auto"])
        self.assertTrue(h1["physical_matches_expected_check"])
        self.assertIn(F3_STATUS_BOARD_ON_PREFIX, h1["text"])
        self.assertIn("DISPLAY EM H1", h1["text"])

        self.assertFalse(blue["allow_auto"])
        self.assertFalse(blue["physical_matches_expected_check"])

    def test_runtime_does_not_infer_low_light_without_explicit_label(self):
        result = classificar_mascara_binaria_pelas_fotos_dos_checks_f3(
            current=_features(140),
            on_references=[_features(220)],
            off_references=[_features(40)],
            detect_low_light=True,
        )

        self.assertIsNotNone(result)
        self.assertIn(result["state"], {"on", "off"})
        self.assertNotEqual("low_light", result["state"])
        self.assertEqual(0, result["reference_counts"]["low_light"])

    def test_off_votes_require_strong_majority(self):
        self.assertTrue(
            decidir_placa_desligada_por_votos_mascaras_f3(
                off_votes=7,
                powered_votes=1,
                valid_votes=8,
            )
        )
        self.assertFalse(
            decidir_placa_desligada_por_votos_mascaras_f3(
                off_votes=4,
                powered_votes=4,
                valid_votes=8,
            )
        )

    def test_real_off_frame_beats_h1_only_inside_expected_on_masks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repository, h1_id = _project_with_h1(root)

            off_frame = _frame(35, 35)
            h1_frame = _frame(220, 220)

            board_store = DisplayProjectPresenceReferenceStore(repository)
            self.assertIsNotNone(
                board_store.capture(
                    "DISPLAY A",
                    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                    off_frame,
                    (120, 80),
                )
            )
            check_store = DisplayCheckPresenceReferenceStore(repository)
            self.assertIsNotNone(
                check_store.capture(
                    "DISPLAY A",
                    h1_id,
                    h1_frame,
                    (120, 80),
                )
            )

            matcher = DisplayVisualReferenceMatcher(repository)
            off_evidence = avaliar_evidencia_energia_check_pelas_mascaras_f3(
                repository=repository,
                matcher=matcher,
                frame=off_frame,
                project_name="DISPLAY A",
                check_id=h1_id,
            )
            h1_evidence = avaliar_evidencia_energia_check_pelas_mascaras_f3(
                repository=repository,
                matcher=matcher,
                frame=h1_frame,
                project_name="DISPLAY A",
                check_id=h1_id,
            )

            self.assertTrue(off_evidence["available"])
            self.assertTrue(off_evidence["off_confirmed"])
            self.assertEqual(2, off_evidence["off_votes"])
            self.assertEqual(0, off_evidence["powered_votes"])

            self.assertTrue(h1_evidence["available"])
            self.assertFalse(h1_evidence["off_confirmed"])
            self.assertEqual(0, h1_evidence["off_votes"])
            self.assertEqual(2, h1_evidence["powered_votes"])

    def test_final_policy_is_installed_after_check_photo_learning(self):
        source = inspect.getsource(DesktopProductionApp.__init__)
        learning_position = source.index(
            "instalar_referencias_por_mesma_mascara_display_f3()"
        )
        policy_position = source.index(
            "instalar_politica_fisica_e_aprendizado_display_f3()"
        )
        super_position = source.index("super().__init__(root)")
        self.assertLess(learning_position, policy_position)
        self.assertLess(policy_position, super_position)

    def test_new_policy_has_no_f2_runtime_dependency(self):
        source = inspect.getsource(policy_module)
        for forbidden in (
            "src.platform.f2_",
            "F2Automatic",
            "operacao_engine",
            "linux_f2_fixed_resolution",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
