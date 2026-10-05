from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from src.platform.display_check_presence_reference import (
    DisplayCheckPresenceReferenceStore,
)
from src.platform.display_f3_neural_dataset import (
    F3NeuralDatasetBuilder,
    extrair_tensor_segmento_f3,
)
from src.platform.display_project_repository import DisplayProjectRepository


def _frame(left: int, right: int) -> np.ndarray:
    image = np.full((96, 160, 3), 20, dtype=np.uint8)
    cv2.rectangle(image, (12, 12), (148, 84), (45, 45, 45), 2)
    cv2.rectangle(
        image,
        (26, 34),
        (58, 62),
        (left, left, left),
        -1,
    )
    cv2.rectangle(
        image,
        (102, 34),
        (134, 62),
        (right, right, right),
        -1,
    )
    return image


class DisplayF3NeuralDatasetTests(unittest.TestCase):
    def _repository(self, root: Path):
        repository = DisplayProjectRepository(
            root / "odin_display_projects.json"
        )
        self.assertTrue(
            repository.adicionar_projeto("DISPLAY A", (160, 96))
        )
        masks = [
            {
                "id": "MASK_001",
                "type": "segment",
                "cx": 42,
                "cy": 48,
                "width": 28,
                "height": 16,
                "angle": 0.0,
            },
            {
                "id": "MASK_002",
                "type": "segment",
                "cx": 118,
                "cy": 48,
                "width": 28,
                "height": 16,
                "angle": 0.0,
            },
        ]
        self.assertTrue(
            repository.salvar_mascaras("DISPLAY A", masks)
        )
        checks = repository.listar_checks("DISPLAY A")
        h1, blue = checks[0], checks[1]

        self.assertTrue(
            repository.salvar_estados_check(
                "DISPLAY A",
                h1["id"],
                {
                    "MASK_001": "on",
                    "MASK_002": "off",
                },
            )
        )
        self.assertTrue(
            repository.salvar_estados_check(
                "DISPLAY A",
                blue["id"],
                {
                    "MASK_001": "off",
                    "MASK_002": "on",
                },
            )
        )

        board = [
            [12, 12],
            [148, 12],
            [148, 84],
            [12, 84],
        ]
        self.assertTrue(
            repository.salvar_geometria_check(
                "DISPLAY A",
                h1["id"],
                board,
                {},
            )
        )
        self.assertTrue(
            repository.salvar_geometria_check(
                "DISPLAY A",
                blue["id"],
                board,
                {
                    "MASK_001": {
                        "id": "MASK_001",
                        "type": "segment",
                        "cx": 44,
                        "cy": 48,
                        "width": 28,
                        "height": 16,
                        "angle": 0.0,
                    }
                },
            )
        )

        store = DisplayCheckPresenceReferenceStore(repository)
        self.assertIsNotNone(
            store.capture(
                "DISPLAY A",
                h1["id"],
                _frame(230, 28),
                (160, 96),
            )
        )
        self.assertIsNotNone(
            store.capture(
                "DISPLAY A",
                blue["id"],
                _frame(28, 230),
                (160, 96),
            )
        )
        return repository, h1, blue

    def test_builder_uses_existing_check_photos_masks_states_and_contours(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, h1, blue = self._repository(Path(temp))
            result = F3NeuralDatasetBuilder(repository).collect(
                "DISPLAY A"
            )

            self.assertTrue(result["ready"])
            self.assertEqual(
                "configured_f3_check_references",
                result["source"],
            )
            self.assertEqual(4, result["sample_count"])
            self.assertEqual(
                {"off": 2, "on": 2},
                result["class_counts"],
            )
            self.assertEqual(
                (h1["id"], blue["id"]),
                result["checks_used"],
            )
            self.assertIn(
                "CHECK_003",
                result["missing_reference_check_ids"],
            )
            self.assertIn(
                "CHECK_004",
                result["missing_reference_check_ids"],
            )

            by_key = {
                (sample["check_id"], sample["mask_id"]): sample
                for sample in result["samples"]
            }
            self.assertEqual(
                "on",
                by_key[(h1["id"], "MASK_001")]["state"],
            )
            self.assertEqual(
                "off",
                by_key[(h1["id"], "MASK_002")]["state"],
            )
            self.assertEqual(
                "off",
                by_key[(blue["id"], "MASK_001")]["state"],
            )
            self.assertEqual(
                "on",
                by_key[(blue["id"], "MASK_002")]["state"],
            )

            blue_mask = by_key[
                (blue["id"], "MASK_001")
            ]["mask_geometry"]
            self.assertEqual(44, blue_mask["cx"])
            self.assertEqual(
                [
                    [12.0, 12.0],
                    [148.0, 12.0],
                    [148.0, 84.0],
                    [12.0, 84.0],
                ],
                by_key[
                    (blue["id"], "MASK_001")
                ]["board_points_reference"],
            )

    def test_builder_adds_board_off_as_real_off_for_same_masks(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, h1, blue = self._repository(Path(temp))
            from src.platform.display_visual_reference_status import (
                DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                DisplayProjectPresenceReferenceStore,
            )

            project = repository.carregar_projeto("DISPLAY A")
            self.assertIsNotNone(project)
            masks = list(project.get("masks", []) or [])
            store = DisplayProjectPresenceReferenceStore(repository)
            self.assertIsNotNone(
                store.capture(
                    "DISPLAY A",
                    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                    _frame(22, 24),
                    (160, 96),
                )
            )
            self.assertTrue(
                store.save_geometry(
                    "DISPLAY A",
                    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                    [
                        [12, 12],
                        [148, 12],
                        [148, 84],
                        [12, 84],
                    ],
                    masks,
                )
            )

            result = F3NeuralDatasetBuilder(repository).collect(
                "DISPLAY A"
            )

            self.assertTrue(result["ready"])
            self.assertTrue(result["board_off_reference_configured"])
            self.assertTrue(result["board_off_geometry_configured"])
            self.assertEqual(2, result["board_off_sample_count"])
            self.assertEqual(("BOARD_OFF",), result["auxiliary_sources_used"])
            self.assertEqual(6, result["sample_count"])
            self.assertEqual({"off": 4, "on": 2}, result["class_counts"])
            self.assertEqual((h1["id"], blue["id"]), result["checks_used"])

            board_off = [
                sample
                for sample in result["samples"]
                if sample.get("check_id") == "BOARD_OFF"
            ]
            self.assertEqual(2, len(board_off))
            self.assertEqual(
                {"MASK_001", "MASK_002"},
                {sample["mask_id"] for sample in board_off},
            )
            self.assertTrue(
                all(sample["state"] == "off" for sample in board_off)
            )
            self.assertTrue(
                all(sample["label"] == 0 for sample in board_off)
            )
            self.assertTrue(
                all(
                    sample["source_kind"] == "board_off_reference"
                    for sample in board_off
                )
            )

    def test_builder_rejects_board_off_masks_outside_current_project(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, _h1, _blue = self._repository(Path(temp))
            from src.platform.display_visual_reference_status import (
                DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                DisplayProjectPresenceReferenceStore,
            )

            project = repository.carregar_projeto("DISPLAY A")
            self.assertIsNotNone(project)
            masks = list(project.get("masks", []) or [])
            stale_mask = {
                "id": "MASK_999",
                "type": "segment",
                "cx": 80,
                "cy": 48,
                "width": 20,
                "height": 14,
                "angle": 0.0,
            }
            store = DisplayProjectPresenceReferenceStore(repository)
            self.assertIsNotNone(
                store.capture(
                    "DISPLAY A",
                    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                    _frame(22, 24),
                    (160, 96),
                )
            )
            self.assertTrue(
                store.save_geometry(
                    "DISPLAY A",
                    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                    [
                        [12, 12],
                        [148, 12],
                        [148, 84],
                        [12, 84],
                    ],
                    masks + [stale_mask],
                )
            )

            result = F3NeuralDatasetBuilder(repository).collect(
                "DISPLAY A"
            )

            board_off = [
                sample
                for sample in result["samples"]
                if sample.get("check_id") == "BOARD_OFF"
            ]
            self.assertEqual(2, result["board_off_sample_count"])
            self.assertEqual(2, len(board_off))
            self.assertEqual(
                {"MASK_001", "MASK_002"},
                {sample["mask_id"] for sample in board_off},
            )
            self.assertEqual(
                ("MASK_999",),
                result["board_off_invalid_mask_ids"],
            )
            self.assertIn(
                "BOARD_OFF:MASK_999",
                result["invalid_sample_ids"],
            )

    def test_builder_does_not_guess_board_off_geometry(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, _h1, _blue = self._repository(Path(temp))
            from src.platform.display_visual_reference_status import (
                DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                DisplayProjectPresenceReferenceStore,
            )

            store = DisplayProjectPresenceReferenceStore(repository)
            self.assertIsNotNone(
                store.capture(
                    "DISPLAY A",
                    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                    _frame(22, 24),
                    (160, 96),
                )
            )

            result = F3NeuralDatasetBuilder(repository).collect(
                "DISPLAY A"
            )

            self.assertTrue(result["board_off_reference_configured"])
            self.assertFalse(result["board_off_geometry_configured"])
            self.assertEqual(0, result["board_off_sample_count"])
            self.assertEqual(4, result["sample_count"])
            self.assertEqual((), result["auxiliary_sources_used"])

    def test_segment_tensor_is_small_four_channel_input_with_explicit_mask(self):
        frame = _frame(230, 28)
        mask = {
            "id": "MASK_001",
            "type": "segment",
            "cx": 42,
            "cy": 48,
            "width": 28,
            "height": 16,
            "angle": 0.0,
        }
        tensor = extrair_tensor_segmento_f3(frame, mask)

        self.assertIsNotNone(tensor)
        self.assertEqual((4, 48, 48), tensor.shape)
        self.assertEqual(np.float32, tensor.dtype)
        self.assertGreaterEqual(float(tensor.min()), 0.0)
        self.assertLessEqual(float(tensor.max()), 1.0)
        values = set(np.unique(tensor[3]).tolist())
        self.assertTrue(values.issubset({0.0, 1.0}))
        self.assertIn(1.0, values)

    def test_manifest_is_json_serializable_and_does_not_embed_numpy_tensors(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, _h1, _blue = self._repository(Path(temp))
            manifest = F3NeuralDatasetBuilder(
                repository
            ).manifest("DISPLAY A")

            encoded = json.dumps(manifest)
            self.assertIn(
                "configured_f3_check_references",
                encoded,
            )
            self.assertEqual(4, len(manifest["samples"]))
            self.assertTrue(
                all(
                    "tensor" not in sample
                    for sample in manifest["samples"]
                )
            )
            self.assertTrue(
                all(
                    sample["tensor_shape"] == [4, 48, 48]
                    for sample in manifest["samples"]
                )
            )

    def test_dataset_refuses_training_if_only_one_class_is_configured(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repository = DisplayProjectRepository(
                root / "display.json"
            )
            repository.adicionar_projeto(
                "DISPLAY A",
                (80, 60),
            )
            repository.salvar_mascaras(
                "DISPLAY A",
                [
                    {
                        "id": "MASK_001",
                        "type": "circle",
                        "cx": 40,
                        "cy": 30,
                        "radius": 10,
                    }
                ],
            )
            h1 = repository.listar_checks("DISPLAY A")[0]
            repository.salvar_estados_check(
                "DISPLAY A",
                h1["id"],
                {"MASK_001": "on"},
            )
            store = DisplayCheckPresenceReferenceStore(
                repository
            )
            store.capture(
                "DISPLAY A",
                h1["id"],
                np.full(
                    (60, 80, 3),
                    220,
                    dtype=np.uint8,
                ),
                (80, 60),
            )

            result = F3NeuralDatasetBuilder(
                repository
            ).collect("DISPLAY A")
            self.assertFalse(result["ready"])
            self.assertEqual(
                "dataset_sem_duas_classes",
                result["reason"],
            )
            self.assertEqual(
                {"off": 0, "on": 1},
                result["class_counts"],
            )


if __name__ == "__main__":
    unittest.main()
