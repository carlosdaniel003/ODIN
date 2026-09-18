from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import cv2
import numpy as np

import src.platform.display_f3_object_tracking as tracking
import src.platform.display_f3_tracking_orientation_ui as tracking_ui


class F3ObjectTrackingIsolationTests(unittest.TestCase):
    def _store(self, directory: str):
        repository = SimpleNamespace(
            config_file=Path(directory) / "odin_display_projects.json"
        )
        return tracking.F3TrackingConfigStore(repository)

    def test_setting_uses_dedicated_f3_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            self.assertFalse(store.enabled())
            store.set_enabled(True)

            self.assertTrue(store.enabled())
            self.assertEqual(
                "odin_display_tracking.json",
                store.config_file.name,
            )
            self.assertTrue(store.config_file.is_file())
            self.assertNotEqual(
                tracking.F3_TRACKING_SETTING_KEY,
                "f2_object_tracking_enabled",
            )

    def test_tracking_sidecar_reuses_normalized_cache_until_file_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            store.set_enabled(True)
            first = store._load_shared()
            second = store._load_shared()
            self.assertIs(first, second)
            self.assertTrue(second[tracking.F3_TRACKING_SETTING_KEY])

            store.set_enabled(False)
            third = store._load_shared()
            self.assertIsNot(second, third)
            self.assertFalse(third[tracking.F3_TRACKING_SETTING_KEY])

    def test_f3_tracking_modules_do_not_import_f2_runtime(self):
        for module in (tracking, tracking_ui):
            tree = ast.parse(inspect.getsource(module))
            imported = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imported.append(str(node.module or ""))
            self.assertFalse(
                any(name.startswith("src.platform.f2") for name in imported),
                imported,
            )

    def test_nominal_cardinal_orientations_keep_display_inside_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            project = {
                "name": "DISPLAY TESTE",
                "master_resolution": {"width": 640, "height": 480},
                "masks": [
                    {
                        "id": "MASK_001",
                        "type": "circle",
                        "cx": 230,
                        "cy": 210,
                        "radius": 18,
                    },
                    {
                        "id": "MASK_002",
                        "type": "circle",
                        "cx": 410,
                        "cy": 270,
                        "radius": 18,
                    },
                ],
                "checks": [],
            }
            board = tracking.canonical_board_points(project, store)
            self.assertGreaterEqual(len(board), 3)

            for slot in tracking.F3_ORIENTATION_SLOTS:
                matrix = tracking.nominal_orientation_matrix(project, store, slot)
                self.assertIsNotNone(matrix)
                rotated = np.asarray(
                    tracking.transform_points(board, matrix),
                    dtype=np.float32,
                )
                self.assertTrue(np.all(rotated[:, 0] >= 0.0))
                self.assertTrue(np.all(rotated[:, 0] < 640.0))
                self.assertTrue(np.all(rotated[:, 1] >= 0.0))
                self.assertTrue(np.all(rotated[:, 1] < 480.0))

    def test_orientation_mask_override_returns_to_canonical_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            project = {
                "name": "DISPLAY TESTE",
                "master_resolution": {"width": 640, "height": 480},
                "masks": [
                    {
                        "id": "MASK_001",
                        "type": "circle",
                        "cx": 100,
                        "cy": 100,
                        "radius": 10,
                    }
                ],
                "checks": [],
            }
            self.assertTrue(
                store.save_orientation(
                    "DISPLAY TESTE",
                    tracking.F3_ORIENTATION_90,
                    {
                        "image_path": str(Path(directory) / "orientation_90.png"),
                        "width": 640,
                        "height": 480,
                        "canonical_to_reference": [
                            [1.0, 0.0, 50.0],
                            [0.0, 1.0, 20.0],
                        ],
                        "calibrated": True,
                        "mask_overrides_reference": {
                            "MASK_001": {
                                "id": "MASK_001",
                                "type": "circle",
                                "cx": 155.0,
                                "cy": 125.0,
                                "radius": 12.0,
                            }
                        },
                    },
                )
            )
            runtime = SimpleNamespace(store=store)
            corrected = tracking._canonical_masks_for_orientation(
                runtime,
                project,
                tracking.F3_ORIENTATION_90,
            )

            self.assertIsNotNone(corrected)
            self.assertEqual(1, len(corrected))
            self.assertEqual("MASK_001", corrected[0]["id"])
            self.assertAlmostEqual(105.0, float(corrected[0]["cx"]), places=3)
            self.assertAlmostEqual(105.0, float(corrected[0]["cy"]), places=3)
            self.assertAlmostEqual(12.0, float(corrected[0]["radius"]), places=3)

    def test_tracking_mask_excludes_display_segments(self):
        board = [[80, 80], [560, 80], [560, 400], [80, 400]]
        masks = [
            {
                "id": "MASK_001",
                "type": "circle",
                "cx": 320,
                "cy": 240,
                "radius": 24,
            }
        ]
        result = tracking.build_tracking_mask(640, 480, board, masks)
        self.assertIsNotNone(result)
        self.assertEqual(0, int(result[240, 320]))
        self.assertGreater(int(result[140, 140]), 0)
        self.assertEqual(0, int(result[20, 20]))

    def test_tracking_keeps_operator_preview_on_raw_camera(self):
        source = inspect.getsource(
            tracking.instalar_runtime_rastreamento_objetos_display_f3
        )
        self.assertIn("_display_f3_tracking_raw_preview_frame", source)
        self.assertIn("base_preview_with_raw_camera", source)
        self.assertIn(
            "DisplayProductionF3Mixin._atualizar_preview_display_f3",
            source,
        )

    def test_disabled_runtime_has_literal_legacy_bypass(self):
        source = inspect.getsource(
            tracking.instalar_runtime_rastreamento_objetos_display_f3
        )
        self.assertIn("if not tracking_enabled(self)", source)
        self.assertIn("return preview_previous(self)", source)
        self.assertIn(
            "DisplayAutomaticCheckF3Mixin._atualizar_preview_display_f3",
            source,
        )


if __name__ == "__main__":
    unittest.main()
