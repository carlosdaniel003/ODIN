"""Testes sobre os PNGs físicos sem mocks de classificação e sem adivinhar máscaras."""

from __future__ import annotations

import unittest
import json
import tempfile
from zipfile import ZipFile
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


    def test_offline_geometry_estimates_translation_and_respects_photo_orientation(self):
        import numpy as np
        from scripts.avaliar_f3_fotos_reais import estimate_snapshot_geometry
        from src.platform.display_f3_neural_dataset import _rasterizar_mascara
        from src.platform.display_mask_geometry import pontos_mascara_display

        image = np.zeros((240, 480, 3), dtype=np.uint8)
        masks = []
        states = {}
        for idx, (x, y) in enumerate(
            [(170, 35), (230, 35), (290, 35), (170, 90),
             (230, 90), (290, 90), (170, 145), (230, 145),
             (290, 145)], start=1
        ):
            mask = {"id": f"MASK_{idx:03d}", "type": "circle",
                    "cx": x, "cy": y, "radius": 8}
            masks.append(mask)
            states[mask["id"]] = "off" if idx in {3, 6} else "on"
            if states[mask["id"]] == "on":
                cv2.circle(image, (x - 20, y + 24), 8, (255, 255, 255), -1)
        estimate, report = estimate_snapshot_geometry(
            image, {"masks": masks}, {"mask_states": states},
            orientations=(0,),
            reduction=2,
        )
        self.assertEqual("DIAGNOSTIC_ONLY", report["status"])
        self.assertEqual(0, report["orientation_masks_degrees"])
        self.assertEqual(0, report["additional_photo_rotation_degrees"])
        self.assertLessEqual(abs(report["translation_px"][0] + 20), 2)
        self.assertLessEqual(abs(report["translation_px"][1] - 24), 2)
        self.assertEqual(len(masks), len(estimate))



    def test_offline_geometry_rotates_masks_not_pre_rotated_photo(self):
        import numpy as np
        from scripts.avaliar_f3_fotos_reais import estimate_snapshot_geometry
        height, width = 240, 480
        image = np.zeros((height, width, 3), dtype=np.uint8)
        positions = [
            (70, 40), (120, 70), (220, 50), (320, 80), (100, 120),
            (275, 140), (360, 120), (60, 160), (240, 170),
        ]
        masks = [
            {"id": f"MASK_{i:03d}", "type": "circle",
             "cx": cx, "cy": cy, "radius": 8}
            for i, (cx, cy) in enumerate(positions, start=1)
        ]
        off_ids = {"MASK_002", "MASK_006", "MASK_009"}
        states = {m["id"]: ("off" if m["id"] in off_ids else "on")
                  for m in masks}
        for mask in masks:
            if states[mask["id"]] == "on":
                cv2.circle(
                    image,
                    (width - 1 - mask["cx"] + 6,
                     height - 1 - mask["cy"] - 8),
                    8, (255, 255, 255), -1,
                )
        result, report = estimate_snapshot_geometry(
            image, {"masks": masks}, {"mask_states": states},
            orientations=(0, 180), reduction=2,
        )
        self.assertIsNotNone(result)
        self.assertEqual("DIAGNOSTIC_ONLY", report["status"])
        self.assertEqual(180, report["orientation_masks_degrees"])
        self.assertEqual(0, report["additional_photo_rotation_degrees"])
        self.assertLessEqual(abs(report["translation_px"][0] - 6), 2)
        self.assertLessEqual(abs(report["translation_px"][1] + 8), 2)

    def test_staged_private_zip_rewrites_local_windows_reference_path(self):
        from scripts.avaliar_f3_fotos_reais import staged_private_assets
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "example.zip"
            records = {
                "schema_version": 1,
                "references": {
                    "CM_500_L::CHECK_001": {
                        "image_path": "data\\\\config\\\\display_check_presence\\\\cm_500_l_check_001.jpg"
                    }
                },
            }
            with ZipFile(archive, "w") as package:
                package.writestr("enviar/odin_display_projects.json",
                                 '{"projects":{"CM_500_L":{}}}')
                package.writestr("enviar/odin_display_check_presence.json",
                                 json.dumps(records))
                package.writestr("enviar/cm_500_l_segments.onnx", b"model-bytes")
                package.writestr("enviar/cm_500_l_segments.json", b"{}")
                package.writestr("enviar/display_check_presence/cm_500_l_check_001.jpg",
                                 b"reference-bytes")
            with staged_private_assets(archive) as project_path:
                reference_path = project_path.parent / "odin_display_check_presence.json"
                saved = json.loads(reference_path.read_text(encoding="utf-8"))
                photo_path = Path(
                    saved["references"]["CM_500_L::CHECK_001"]["image_path"]
                )
                self.assertTrue(project_path.is_file())
                self.assertTrue(photo_path.is_file())
                self.assertEqual(b"reference-bytes", photo_path.read_bytes())
                self.assertTrue(
                    (project_path.parent / "models" / "f3_neural" /
                     "cm_500_l_segments.onnx").is_file()
                )
            self.assertFalse(photo_path.exists())

    def test_offline_geometry_blocks_dark_frame(self):
        import numpy as np
        from scripts.avaliar_f3_fotos_reais import estimate_snapshot_geometry
        masks = [
            {"id": f"MASK_{i:03d}", "type": "circle",
             "cx": 50 + i * 30, "cy": 70, "radius": 8}
            for i in range(1, 8)
        ]
        geometry, report = estimate_snapshot_geometry(
            np.zeros((180, 320, 3), dtype=np.uint8),
            {"masks": masks},
            {"mask_states": {m["id"]: "on" for m in masks}},
        )
        self.assertIsNone(geometry)
        self.assertEqual("BLOCKED", report["status"])

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
