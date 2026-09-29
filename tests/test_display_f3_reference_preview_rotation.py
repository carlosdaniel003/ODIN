from __future__ import annotations

import inspect
import unittest
from copy import deepcopy
from unittest.mock import patch

import cv2
import numpy as np

import src.platform.display_f3_reference_preview_rotation as rotation


class _Repository:
    def __init__(self):
        self.project = {
            "name": "DISPLAY TESTE",
            "master_resolution": {"width": 120, "height": 80},
            "masks": [
                {
                    "id": "MASK_001",
                    "type": "circle",
                    "cx": 25,
                    "cy": 30,
                    "radius": 8,
                },
                {
                    "id": "MASK_002",
                    "type": "segment",
                    "cx": 80,
                    "cy": 45,
                    "width": 24,
                    "height": 8,
                    "angle": 0.0,
                },
            ],
        }

    def carregar_projeto(self, _name):
        return deepcopy(self.project)


class DisplayF3ReferencePreviewRotationTests(unittest.TestCase):
    def test_preview_90_matches_main_visual_convention(self):
        image = np.arange(2 * 3 * 3, dtype=np.uint8).reshape((2, 3, 3))
        expected = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        actual = rotation.preparar_preview_referencia_visual_f3(image, 90)
        self.assertTrue(np.array_equal(expected, actual))

    def test_roi_round_trip_for_all_supported_rotations(self):
        roi = {"x": 0.12, "y": 0.21, "width": 0.33, "height": 0.27}
        for angle in (0, 90, 180, 270):
            with self.subTest(angle=angle):
                visual = rotation.transformar_roi_referencia_visual_f3(roi, angle)
                restored = rotation.restaurar_roi_referencia_original_f3(visual, angle)
                self.assertIsNotNone(restored)
                for key in ("x", "y", "width", "height"):
                    self.assertAlmostEqual(roi[key], restored[key], places=5)

    def test_preview_180_desenha_mascaras_depois_de_reduzir_imagem(self):
        repository = _Repository()
        image = np.zeros((80, 120, 3), dtype=np.uint8)
        preview, mask_count = rotation.preparar_preview_referencia_com_mascaras_f3(
            image_raw=image,
            metadata={"width": 120, "height": 80},
            repository=repository,
            project_name="DISPLAY TESTE",
            rotacao=180,
            target_width=60,
            target_height=40,
        )

        self.assertEqual(2, mask_count)
        self.assertEqual((40, 60, 3), preview.shape)
        self.assertGreater(int(np.count_nonzero(preview)), 0)

    def test_preview_do_check_usa_a_mesma_geometria_efetiva_do_editor(self):
        project = {
            "name": "DISPLAY TESTE",
            "master_resolution": {"width": 120, "height": 80},
            "masks": [
                {
                    "id": "MASK_001",
                    "type": "circle",
                    "cx": 25,
                    "cy": 30,
                    "radius": 8,
                }
            ],
        }
        check = {
            "id": "CHECK_001",
            "name": "H1",
            "board_points_reference": [
                [50, 10],
                [115, 10],
                [115, 75],
                [50, 75],
            ],
            "mask_overrides_reference": {
                "MASK_001": {
                    "id": "MASK_001",
                    "type": "circle",
                    "cx": 82,
                    "cy": 48,
                    "radius": 9,
                }
            },
        }

        class Repository:
            def carregar_projeto(self, _name):
                return deepcopy(project)

            def carregar_check(self, _project_name, _check_id):
                return deepcopy(check)

        repository = Repository()
        geometry = rotation.resolver_geometria_referencia_check_f3(
            repository,
            "DISPLAY TESTE",
            "CHECK_001",
        )
        self.assertTrue(geometry["available"])
        self.assertEqual(82, int(geometry["masks"][0]["cx"]))
        self.assertEqual(48, int(geometry["masks"][0]["cy"]))

        image = np.zeros((80, 120, 3), dtype=np.uint8)
        captured = {}

        def draw(image_value, board_points, masks, **_kwargs):
            captured["board"] = deepcopy(board_points)
            captured["masks"] = deepcopy(masks)
            return image_value

        stale_metadata = {
            "width": 120,
            "height": 80,
            "_display_mask_regions": deepcopy(project["masks"]),
        }
        with patch(
            "src.platform.display_f3_object_tracking.draw_reference_geometry",
            side_effect=draw,
        ):
            rendered, mask_count = rotation.preparar_preview_referencia_com_mascaras_f3(
                image_raw=image,
                metadata=stale_metadata,
                repository=repository,
                project_name="DISPLAY TESTE",
                rotacao=0,
                target_width=120,
                target_height=80,
                mask_regions=geometry["masks"],
                board_points=geometry["board_points"],
                master_resolution=geometry["resolution"],
            )

        self.assertEqual((80, 120, 3), rendered.shape)
        self.assertEqual(1, mask_count)
        self.assertEqual(82, int(captured["masks"][0]["cx"]))
        self.assertEqual(48, int(captured["masks"][0]["cy"]))
        self.assertEqual(50, int(captured["board"][0][0]))

    def test_preview_nao_depende_das_mascaras_injetadas_no_metadata(self):
        repository = _Repository()
        image = np.zeros((80, 120, 3), dtype=np.uint8)
        preview, mask_count = rotation.preparar_preview_referencia_com_mascaras_f3(
            image_raw=image,
            metadata={
                "width": 120,
                "height": 80,
                "_display_mask_regions": [],
            },
            repository=repository,
            project_name="DISPLAY TESTE",
            rotacao=0,
            target_width=60,
            target_height=40,
        )

        self.assertEqual(2, mask_count)
        self.assertGreater(int(np.count_nonzero(preview)), 0)

    def test_rotacao_visual_nao_reintroduz_seletor_retangular(self):
        source = inspect.getsource(rotation)
        self.assertIn("preparar_check_visual_display", source)
        self.assertIn("_display_mask_regions", source)
        self.assertIn("ROI: {mask_count}", source)
        self.assertNotIn("DisplayReferenceRoiDialog(", source)
        self.assertNotIn("store.set_roi(", source)

    def test_rotation_is_visual_only_and_does_not_patch_capture_store(self):
        source = inspect.getsource(rotation)
        self.assertIn("preparar_frame_visual_display", source)
        self.assertNotIn("DisplayProjectPresenceReferenceStore.capture =", source)
        self.assertNotIn("DisplayCheckPresenceReferenceStore.capture =", source)

    def test_reference_rotation_module_has_no_f2_runtime_dependency(self):
        source = inspect.getsource(rotation)
        self.assertNotIn("src.platform.f2_", source)
        self.assertNotIn("F2Automatic", source)


if __name__ == "__main__":
    unittest.main()
