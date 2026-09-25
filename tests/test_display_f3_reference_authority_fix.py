from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.models.led_features import LedFeatures
import src.platform.display_f3_reference_authority_fix as fix_module
from src.platform.display_f3_reference_authority_fix import (
    F3_REFERENCE_MIN_CONFIDENCE,
    _sequence_authoritative_operational_state,
    classificar_mascara_com_referencias_f3,
)
from src.platform.desktop_production_app import DesktopProductionApp


def _features(value: float) -> LedFeatures:
    return LedFeatures(
        v_mean=float(value),
        v_max=float(value),
        v_std=float(value) * 0.20,
        v_p95=float(value),
        v_p99=float(value),
        s_mean=float(value) * 0.30,
        s_std=float(value) * 0.10,
        center_to_ring_v=float(value) * 0.08,
        center_to_ring_s=float(value) * 0.03,
        percent_hot_235=max(0.0, min(1.0, (float(value) - 180.0) / 80.0)),
        percent_hot_245=max(0.0, min(1.0, (float(value) - 200.0) / 60.0)),
        percent_hot_250=max(0.0, min(1.0, (float(value) - 220.0) / 40.0)),
        glow_score=float(value) * 0.25,
        area_pixels=120,
        inner_area_pixels=60,
        ring_area_pixels=60,
    )


class DisplayF3ReferenceAuthorityFixTests(unittest.TestCase):
    def test_same_mask_check_reference_absorbs_legitimate_neighbor_reflection(self):
        # A referência genérica APAGADO é escura, mas esta máscara específica
        # recebe bastante reflexo de um segmento vizinho. A foto do CHECK já
        # contém esse reflexo e deve ser a referência primária da máscara.
        result = classificar_mascara_com_referencias_f3(
            current=_features(121),
            expected="off",
            on_references=[_features(220)],
            off_references=[_features(20)],
            low_light_references=[_features(80)],
            check_expected_reference=_features(120),
        )
        self.assertIsNotNone(result)
        self.assertEqual("off", result["state"])
        self.assertEqual("f3_check_mask", result["reference_source"])
        self.assertGreaterEqual(result["confidence"], F3_REFERENCE_MIN_CONFIDENCE)
        self.assertLess(
            result["expected_reference_distance"],
            result["opposite_reference_distance"],
        )

    def test_multiple_f3_samples_are_used_individually_instead_of_centroid(self):
        result = classificar_mascara_com_referencias_f3(
            current=_features(218),
            expected="on",
            on_references=[_features(120), _features(220)],
            off_references=[_features(20), _features(45)],
            low_light_references=[],
        )
        self.assertIsNotNone(result)
        self.assertEqual(1, result["nearest_reference_indexes"]["on"])
        self.assertEqual(2, result["reference_counts"]["on"])
        self.assertEqual("f3_state_samples", result["reference_source"])

    def test_near_tie_is_not_confident_enough_to_accumulate_ok_or_ng(self):
        result = classificar_mascara_com_referencias_f3(
            current=_features(100),
            expected="on",
            on_references=[_features(110)],
            off_references=[_features(90)],
            low_light_references=[],
        )
        self.assertIsNotNone(result)
        self.assertLess(result["confidence"], F3_REFERENCE_MIN_CONFIDENCE)

    def test_operational_status_uses_logical_current_check_not_previous_visual_match(self):
        with tempfile.TemporaryDirectory() as temp:
            app = SimpleNamespace(
                _display_f3_waiting_empty_rearm=False,
                display_project_repository=SimpleNamespace(
                    config_file=Path(temp) / "odin_display_projects.json"
                ),
            )
            state = _sequence_authoritative_operational_state(
                app,
                frame=None,
                project_name="DISPLAY A",
                context={
                    "check_id": "CHECK_003",
                    "check_name": "USB",
                },
            )
        self.assertEqual("check", state["kind"])
        self.assertEqual("CHECK ATUAL • USB", state["text"])
        self.assertEqual("CHECK_003", state["check_id"])
        self.assertEqual("f3_sequence", state["source"])

    def test_reference_authority_module_has_no_f2_runtime_dependency(self):
        source = inspect.getsource(fix_module)
        for forbidden in (
            "src.platform.f2_",
            "F2Automatic",
            "operacao_engine",
            "linux_f2_fixed_resolution",
        ):
            self.assertNotIn(forbidden, source)

    def test_final_profile_installs_reference_authority_after_existing_f3_layers(self):
        source = inspect.getsource(DesktopProductionApp.__init__)
        status_position = source.index("instalar_status_mascaras_display_f3()")
        authority_position = source.index("instalar_autoridade_referencias_display_f3()")
        super_position = source.index("super().__init__(root)")
        self.assertLess(status_position, authority_position)
        self.assertLess(authority_position, super_position)


if __name__ == "__main__":
    unittest.main()
