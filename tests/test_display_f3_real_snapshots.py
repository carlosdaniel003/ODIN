"""Testes sobre os PNGs físicos sem mocks de classificação e sem adivinhar máscaras."""

from __future__ import annotations

import unittest
from pathlib import Path

import cv2

from scripts.avaliar_f3_fotos_reais import (
    FIXTURE_ROOT,
    blue_pair_diagnostics,
    evaluate_snapshots,
    image_diagnostics,
    load_snapshot,
    read_manifest,
)


class DisplayF3RealSnapshotsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = read_manifest()
        cls.images = {
            case["filename"]: load_snapshot(FIXTURE_ROOT / case["filename"])
            for case in cls.manifest["cases"]
        }

    def test_six_real_pngs_and_explicit_ground_truth(self):
        cases = self.manifest["cases"]
        self.assertEqual(6, len(cases))
        self.assertEqual(
            {"H1", "BLUE", "USB", "FM", "AUX"},
            {case["check"] for case in cases},
        )
        self.assertEqual(5, sum(case["ground_truth"] == "OK" for case in cases))
        negatives = [case for case in cases if case["ground_truth"] == "NG"]
        self.assertEqual(1, len(negatives))
        self.assertEqual("BLUE", negatives[0]["check"])
        self.assertEqual(["MASK_024"], negatives[0]["failed_mask_ids"])
        self.assertEqual("ON", negatives[0]["capture_phase"])
        self.assertEqual(
            {"H1_OK.png", "BLUE_OK.png", "USB_OK.png",
             "FM_OK.png", "AUX_OK.png", "BLUE_NG_024.png"},
            set(self.images),
        )

    def test_camera_resolution_and_real_luminous_evidence(self):
        images_hashes = set()
        for name, image in self.images.items():
            with self.subTest(name=name):
                self.assertEqual((1080, 1920, 3), image.shape)
                info = image_diagnostics(FIXTURE_ROOT / name, image)
                self.assertEqual([1920, 1080], [info["width"], info["height"]])
                self.assertEqual(255, info["max_value"])
                self.assertGreater(info["pixels_v_ge_200"], 50)
                self.assertIsNotNone(info["luminous_bbox"])
                images_hashes.add(info["sha256"])
        self.assertEqual(6, len(images_hashes))

    def test_blue_ok_ng_real_pixels_remain_distinguishable(self):
        ok = self.images["BLUE_OK.png"]
        ng = self.images["BLUE_NG_024.png"]
        report = blue_pair_diagnostics(ok, ng)
        self.assertEqual("DIAGNOSTIC_ONLY", report["status"])
        self.assertGreater(report["mean_absolute_brightness_difference"], 0)
        self.assertGreater(report["missing_brightness_sum"], 0)
        # Não atribuir identidade MASK_024 sem geometria real rastreada.

    def test_already_rotated_images_and_missing_assets_fail_closed(self):
        self.assertEqual(
            180,
            self.manifest["orientation"]["already_applied_rotation_degrees"],
        )
        self.assertEqual(
            0,
            self.manifest["orientation"]["additional_rotation_degrees_for_replay"],
        )
        report = evaluate_snapshots()
        self.assertEqual(6, report["snapshot_count"])
        self.assertEqual(0, report["additional_rotation_degrees"])
        # A CI não contém os dados privados da instalação industrial.
        # Não simular inferência ONNX para declarar OK/NG.
        for case in report["cases"]:
            if case["semantic_replay"]["status"] == "BLOCKED":
                self.assertIn(
                    case["semantic_replay"]["reason"],
                    {"display_project_config_missing", "trained_cnn_and_metadata_missing",
                     "CM_500_L_missing_from_display_project_config"},
                )
            else:
                self.assertIn(case["semantic_replay"]["status"], {"PASS", "FAIL"})


if __name__ == "__main__":
    unittest.main()
