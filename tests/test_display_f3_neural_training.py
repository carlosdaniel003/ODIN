from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts.treinar_f3_segmentos_neural import (
    _augment_sample,
    _build_calibration_batch,
    _build_calibration_batch_with_details,
    _build_mask_state_coverage,
    _calibrate_thresholds_from_logits,
    _export_onnx_candidate,
    _validate_candidate,
    _write_calibration_diagnostics,
    _write_mask_state_coverage,
    preparar_preflight,
)
from src.platform.display_f3_neural_physical_calibration import (
    collect_physical_h1_debug_calibration,
    combine_augmented_and_physical_calibration,
)


class _Repository:
    def listar_checks(self, _project_name):
        return [
            {"id": "CHECK_001", "name": "H1"},
            {"id": "CHECK_002", "name": "BLUE"},
            {"id": "CHECK_003", "name": "USB"},
        ]


class _PhysicalCalibrationRepository:
    def listar_checks(self, _project_name):
        return [
            {
                "id": "CHECK_001",
                "name": "H1",
                "mask_states": {
                    "MASK_001": "off",
                    "MASK_002": "on",
                },
            }
        ]


def _sample(check_id: str, check_name: str, label: int, mask_id: str):
    return {
        "project_name": "DISPLAY A",
        "check_id": check_id,
        "check_name": check_name,
        "mask_id": mask_id,
        "state": "on" if label == 1 else "off",
        "label": int(label),
        "tensor": np.zeros((4, 48, 48), dtype=np.float32),
    }


class _Builder:
    def __init__(self, samples, *, missing=()):
        self.samples = list(samples)
        self.missing = tuple(missing)

    def collect(self, _project_name):
        counts = {
            "off": sum(1 for item in self.samples if int(item["label"]) == 0),
            "on": sum(1 for item in self.samples if int(item["label"]) == 1),
        }
        checks = []
        for item in self.samples:
            check_id = str(item["check_id"])
            if check_id not in checks:
                checks.append(check_id)
        board_off_count = sum(
            1
            for item in self.samples
            if str(item.get("check_id") or "") == "BOARD_OFF"
        )
        return {
            "ready": bool(self.samples and counts["off"] and counts["on"]),
            "reason": "dataset_pronto",
            "project_name": "DISPLAY A",
            "sample_count": len(self.samples),
            "class_counts": counts,
            "checks_used": tuple(
                check_id
                for check_id in checks
                if check_id != "BOARD_OFF"
            ),
            "auxiliary_sources_used": (
                ("BOARD_OFF",)
                if board_off_count
                else ()
            ),
            "board_off_reference_configured": bool(board_off_count),
            "board_off_geometry_configured": bool(board_off_count),
            "board_off_sample_count": board_off_count,
            "board_off_invalid_mask_ids": (),
            "missing_reference_check_ids": self.missing,
            "invalid_sample_ids": (),
            "samples": list(self.samples),
        }


class _FakeOnnxExporter:
    def __init__(self):
        self.calls = []

    def export(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class _FakeTorch:
    def __init__(self):
        self.onnx = _FakeOnnxExporter()


class DisplayF3NeuralTrainingTests(unittest.TestCase):
    def test_n1_holds_entire_first_check_out_of_training(self):
        samples = [
            _sample("CHECK_001", "H1", 1, "MASK_001"),
            _sample("CHECK_001", "H1", 0, "MASK_002"),
            _sample("CHECK_002", "BLUE", 0, "MASK_001"),
            _sample("CHECK_002", "BLUE", 1, "MASK_002"),
            _sample("CHECK_003", "USB", 1, "MASK_001"),
            _sample("CHECK_003", "USB", 0, "MASK_002"),
        ]

        dataset, report, train_indices, val_indices = preparar_preflight(
            _Repository(),
            _Builder(samples),
            "DISPLAY A",
        )

        self.assertTrue(dataset["ready"])
        self.assertTrue(report["ready"])
        self.assertEqual("CHECK_001", report["validation_check_id"])
        self.assertEqual(["CHECK_001"], report["validation_check_ids"])
        self.assertEqual(
            ["CHECK_002", "CHECK_003"],
            report["train_check_ids"],
        )
        self.assertTrue(
            all(
                samples[index]["check_id"] != "CHECK_001"
                for index in train_indices
            )
        )
        self.assertTrue(
            all(
                samples[index]["check_id"] == "CHECK_001"
                for index in val_indices
            )
        )
        self.assertEqual(
            {"off": 1, "on": 1},
            report["validation_class_counts"],
        )
        self.assertEqual(
            {"off": 2, "on": 2},
            report["train_class_counts"],
        )

    def test_board_off_samples_stay_in_training_and_close_h1_off_coverage_gap(self):
        samples = [
            _sample("CHECK_001", "H1", 1, "MASK_001"),
            _sample("CHECK_001", "H1", 0, "MASK_002"),
            _sample("CHECK_002", "BLUE", 1, "MASK_001"),
            _sample("CHECK_002", "BLUE", 1, "MASK_002"),
            _sample("CHECK_003", "USB", 1, "MASK_001"),
            _sample("CHECK_003", "USB", 1, "MASK_002"),
            _sample("BOARD_OFF", "PLACA OFF", 0, "MASK_001"),
            _sample("BOARD_OFF", "PLACA OFF", 0, "MASK_002"),
        ]

        _dataset, report, train_indices, val_indices = preparar_preflight(
            _Repository(),
            _Builder(samples),
            "DISPLAY A",
        )

        self.assertTrue(report["ready"])
        self.assertEqual(
            ["CHECK_002", "CHECK_003", "BOARD_OFF"],
            report["train_check_ids"],
        )
        self.assertEqual(["BOARD_OFF"], report["auxiliary_sources_used"])
        self.assertEqual(2, report["board_off_sample_count"])
        self.assertTrue(
            all(
                samples[index]["check_id"] != "CHECK_001"
                for index in train_indices
            )
        )
        self.assertTrue(
            all(
                samples[index]["check_id"] == "CHECK_001"
                for index in val_indices
            )
        )
        self.assertEqual(
            0,
            report["state_coverage_summary"][
                "validation_state_unseen_in_training_count"
            ],
        )
        self.assertEqual(
            [],
            report["state_coverage_summary"][
                "validation_state_unseen_in_training_mask_ids"
            ],
        )

    def test_n1_does_not_silently_validate_blue_when_h1_photo_is_missing(self):
        samples = [
            _sample("CHECK_002", "BLUE", 0, "MASK_001"),
            _sample("CHECK_002", "BLUE", 1, "MASK_002"),
            _sample("CHECK_003", "USB", 1, "MASK_001"),
            _sample("CHECK_003", "USB", 0, "MASK_002"),
        ]

        _dataset, report, train_indices, val_indices = preparar_preflight(
            _Repository(),
            _Builder(samples, missing=("CHECK_001",)),
            "DISPLAY A",
        )

        self.assertFalse(report["ready"])
        self.assertEqual(
            "first_check_reference_missing",
            report["reason"],
        )
        self.assertEqual([], train_indices)
        self.assertEqual([], val_indices)

    def test_n1_requires_both_on_and_off_outside_h1(self):
        samples = [
            _sample("CHECK_001", "H1", 1, "MASK_001"),
            _sample("CHECK_001", "H1", 0, "MASK_002"),
            _sample("CHECK_002", "BLUE", 1, "MASK_001"),
            _sample("CHECK_002", "BLUE", 1, "MASK_002"),
        ]

        _dataset, report, _train_indices, _val_indices = preparar_preflight(
            _Repository(),
            _Builder(samples),
            "DISPLAY A",
        )

        self.assertFalse(report["ready"])
        self.assertEqual(
            "treino_sem_duas_classes_fora_do_h1",
            report["reason"],
        )

    def test_mask_state_coverage_finds_validation_state_unseen_in_training(self):
        samples = [
            _sample("CHECK_001", "H1", 1, "MASK_001"),
            _sample("CHECK_001", "H1", 0, "MASK_002"),
            _sample("CHECK_002", "BLUE", 0, "MASK_001"),
            _sample("CHECK_002", "BLUE", 1, "MASK_002"),
            _sample("CHECK_003", "USB", 0, "MASK_001"),
            _sample("CHECK_003", "USB", 0, "MASK_002"),
        ]
        report = _build_mask_state_coverage(
            _Repository(),
            "DISPLAY A",
            samples,
            train_indices=[2, 3, 4, 5],
            val_indices=[0, 1],
        )

        self.assertEqual(2, report["summary"]["mask_count"])
        self.assertEqual(
            ["MASK_001"],
            report["summary"][
                "validation_state_unseen_in_training_mask_ids"
            ],
        )
        rows = {
            item["mask_id"]: item
            for item in report["masks"]
        }
        self.assertEqual(
            ["off"],
            rows["MASK_001"]["training_states"],
        )
        self.assertFalse(
            rows["MASK_001"][
                "validation_state_seen_in_training"
            ]
        )
        self.assertEqual(
            "validation_state_unseen_in_training",
            rows["MASK_001"]["status"],
        )
        self.assertEqual(
            ["off", "on"],
            rows["MASK_002"]["training_states"],
        )
        self.assertTrue(
            rows["MASK_002"][
                "validation_state_seen_in_training"
            ]
        )

    def test_mask_state_coverage_is_persisted_as_json(self):
        samples = [
            _sample("CHECK_001", "H1", 1, "MASK_001"),
            _sample("CHECK_002", "BLUE", 0, "MASK_001"),
            _sample("CHECK_003", "USB", 1, "MASK_001"),
        ]
        report = _build_mask_state_coverage(
            _Repository(),
            "DISPLAY A",
            samples,
            train_indices=[1, 2],
            val_indices=[0],
        )

        with tempfile.TemporaryDirectory() as temp:
            path = _write_mask_state_coverage(
                report,
                Path(temp) / "coverage.json",
            )
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            "f3_neural_mask_state_coverage_audit",
            saved["purpose"],
        )
        self.assertEqual("MASK_001", saved["masks"][0]["mask_id"])
        self.assertEqual(
            {"off": 1, "on": 1},
            {
                "off": saved["masks"][0]["training_off_count"],
                "on": saved["masks"][0]["training_on_count"],
            },
        )

    def test_preflight_exposes_mask_state_coverage_summary(self):
        samples = [
            _sample("CHECK_001", "H1", 1, "MASK_001"),
            _sample("CHECK_001", "H1", 0, "MASK_002"),
            _sample("CHECK_002", "BLUE", 0, "MASK_001"),
            _sample("CHECK_002", "BLUE", 1, "MASK_002"),
            _sample("CHECK_003", "USB", 0, "MASK_001"),
            _sample("CHECK_003", "USB", 0, "MASK_002"),
        ]

        _dataset, report, _train, _val = preparar_preflight(
            _Repository(),
            _Builder(samples),
            "DISPLAY A",
        )

        self.assertIn("state_coverage", report)
        self.assertIn("state_coverage_summary", report)
        self.assertEqual(
            1,
            report["state_coverage_summary"][
                "validation_state_unseen_in_training_count"
            ],
        )

    def test_export_uses_legacy_torchscript_path_without_onnxscript(self):
        fake_torch = _FakeTorch()
        model = object()
        dummy = object()

        _export_onnx_candidate(
            fake_torch,
            model,
            dummy,
            destination=__import__("pathlib").Path("candidate.onnx"),
        )

        self.assertEqual(1, len(fake_torch.onnx.calls))
        args, kwargs = fake_torch.onnx.calls[0]
        self.assertIs(model, args[0])
        self.assertIs(dummy, args[1])
        self.assertEqual("candidate.onnx", args[2])
        self.assertEqual(13, kwargs["opset_version"])
        self.assertFalse(kwargs["dynamo"])
        self.assertEqual(
            {"segments": {0: "batch"}, "logits": {0: "batch"}},
            kwargs["dynamic_axes"],
        )

    def test_calibration_derives_uncertain_band_from_held_out_h1_gap(self):
        logits = np.asarray(
            [
                [1.4, 0.0],
                [0.8, 0.0],
                [0.0, 0.7],
                [0.0, 1.6],
            ],
            dtype=np.float32,
        )
        labels = np.asarray([0, 0, 1, 1], dtype=np.int64)

        calibration = _calibrate_thresholds_from_logits(
            logits,
            labels,
            reference_sample_count=4,
            augmentations_per_reference=2,
        )

        self.assertTrue(calibration["separable"])
        self.assertEqual(
            "held_out_h1_augmented_probability_gap",
            calibration["source"],
        )
        self.assertLess(
            calibration["off_max_on_probability"],
            calibration["on_min_on_probability"],
        )
        self.assertGreater(calibration["uncertainty_gap"], 0.0)
        self.assertEqual({"off": 2, "on": 2}, calibration["class_counts"])

    def test_calibration_rejects_overlapping_h1_probability_distributions(self):
        logits = np.asarray(
            [
                [0.0, 1.0],
                [1.0, 0.0],
            ],
            dtype=np.float32,
        )
        labels = np.asarray([0, 1], dtype=np.int64)

        with self.assertRaisesRegex(RuntimeError, "não separou OFF/ON"):
            _calibrate_thresholds_from_logits(
                logits,
                labels,
                reference_sample_count=2,
                augmentations_per_reference=1,
            )

    def test_calibration_batch_is_deterministic_and_keeps_h1_labels(self):
        samples = [
            _sample("CHECK_001", "H1", 0, "MASK_001"),
            _sample("CHECK_001", "H1", 1, "MASK_002"),
        ]
        samples[0]["tensor"][0] = 0.2
        samples[1]["tensor"][1] = 0.8

        first_batch, first_labels = _build_calibration_batch(
            samples,
            [0, 1],
            augmentations_per_reference=2,
            seed=42,
        )
        second_batch, second_labels = _build_calibration_batch(
            samples,
            [0, 1],
            augmentations_per_reference=2,
            seed=42,
        )

        self.assertEqual((6, 4, 48, 48), first_batch.shape)
        self.assertEqual([0, 0, 0, 1, 1, 1], first_labels.tolist())
        np.testing.assert_array_equal(first_labels, second_labels)
        np.testing.assert_allclose(first_batch, second_batch)

    def test_augmentation_trace_does_not_change_generated_tensor(self):
        tensor = np.zeros((4, 48, 48), dtype=np.float32)
        tensor[0] = 0.25
        tensor[1] = 0.50
        tensor[2] = 0.75
        tensor[3, 12:36, 20:28] = 1.0

        plain = _augment_sample(
            tensor,
            0,
            __import__("random").Random(20261005),
        )
        trace = {}
        instrumented = _augment_sample(
            tensor,
            0,
            __import__("random").Random(20261005),
            diagnostic=trace,
        )

        np.testing.assert_array_equal(plain, instrumented)
        self.assertIn("angle_deg", trace)
        self.assertIn("noise_applied", trace)
        self.assertIn("reflection_applied", trace)

    def test_photometric_augmentation_uses_one_primary_operator_per_sample(self):
        tensor = np.zeros((4, 48, 48), dtype=np.float32)
        tensor[:3] = 0.5
        tensor[3, 12:36, 20:28] = 1.0

        modes_seen = set()
        for seed in range(120):
            trace = {}
            _augment_sample(
                tensor,
                seed % 2,
                __import__("random").Random(seed),
                diagnostic=trace,
            )
            mode = trace["photometric_mode"]
            modes_seen.add(mode)

            alpha = float(trace["brightness_alpha"])
            beta = float(trace["brightness_beta"])
            gamma = float(trace["gamma"])

            if mode == "gain":
                self.assertGreaterEqual(alpha, 0.85)
                self.assertLessEqual(alpha, 1.15)
                self.assertEqual(0.0, beta)
                self.assertEqual(1.0, gamma)
            elif mode == "offset":
                self.assertEqual(1.0, alpha)
                self.assertGreaterEqual(beta, -0.06)
                self.assertLessEqual(beta, 0.06)
                self.assertEqual(1.0, gamma)
            elif mode == "gamma":
                self.assertEqual(1.0, alpha)
                self.assertEqual(0.0, beta)
                self.assertGreaterEqual(gamma, 0.85)
                self.assertLessEqual(gamma, 1.18)
            else:
                self.fail(f"Modo fotométrico inesperado: {mode}")

        self.assertEqual({"gain", "offset", "gamma"}, modes_seen)

    def test_photometric_trace_prevents_old_cumulative_extremes(self):
        tensor = np.zeros((4, 48, 48), dtype=np.float32)
        tensor[:3] = 0.5
        tensor[3, 12:36, 20:28] = 1.0

        for seed in range(250):
            trace = {}
            _augment_sample(
                tensor,
                0,
                __import__("random").Random(seed),
                diagnostic=trace,
            )
            non_neutral = sum(
                (
                    abs(float(trace["brightness_alpha"]) - 1.0) > 1e-12,
                    abs(float(trace["brightness_beta"])) > 1e-12,
                    abs(float(trace["gamma"]) - 1.0) > 1e-12,
                )
            )
            self.assertLessEqual(non_neutral, 1)

    def test_calibration_details_preserve_mask_and_transform_origin(self):
        samples = [
            _sample("CHECK_001", "H1", 0, "MASK_010"),
            _sample("CHECK_001", "H1", 1, "MASK_017"),
        ]

        batch, labels, details = _build_calibration_batch_with_details(
            samples,
            [0, 1],
            augmentations_per_reference=1,
            seed=42,
        )

        self.assertEqual((4, 4, 48, 48), batch.shape)
        self.assertEqual([0, 0, 1, 1], labels.tolist())
        self.assertEqual("MASK_010", details[0]["mask_id"])
        self.assertEqual("original", details[0]["kind"])
        self.assertIsNone(details[0]["augmentation_index"])
        self.assertEqual("MASK_010", details[1]["mask_id"])
        self.assertEqual("augmented", details[1]["kind"])
        self.assertEqual(0, details[1]["augmentation_index"])
        self.assertIn("angle_deg", details[1]["transform"])

    def test_calibration_diagnostics_save_worst_off_and_on_images(self):
        batch = np.zeros((4, 4, 48, 48), dtype=np.float32)
        batch[:, 3, 14:34, 20:28] = 1.0
        labels = np.asarray([0, 0, 1, 1], dtype=np.int64)
        details = [
            {
                "mask_id": "MASK_010",
                "state": "off",
                "kind": "augmented",
                "augmentation_index": 7,
                "transform": {"reflection_applied": True},
            },
            {
                "mask_id": "MASK_004",
                "state": "off",
                "kind": "original",
                "augmentation_index": None,
                "transform": {},
            },
            {
                "mask_id": "MASK_017",
                "state": "on",
                "kind": "augmented",
                "augmentation_index": 12,
                "transform": {"blur_applied": True},
            },
            {
                "mask_id": "MASK_013",
                "state": "on",
                "kind": "original",
                "augmentation_index": None,
                "transform": {},
            },
        ]
        logits = np.asarray(
            [
                [0.0, 0.484],
                [0.4, 0.0],
                [0.0, 0.288],
                [0.0, 1.2],
            ],
            dtype=np.float32,
        )

        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "calibration_latest"
            report = _write_calibration_diagnostics(
                batch=batch,
                labels=labels,
                details=details,
                logits=logits,
                destination=destination,
                top_k=2,
            )

            self.assertEqual(
                "MASK_010",
                report["worst_off"]["mask_id"],
            )
            self.assertEqual(
                "MASK_017",
                report["worst_on"]["mask_id"],
            )
            self.assertLess(report["raw_gap"], 0.0)
            self.assertFalse(report["separable"])
            self.assertTrue(
                (destination / "calibration_diagnostics.json").is_file()
            )
            self.assertTrue(
                (destination / report["worst_off"]["image_file"]).is_file()
            )
            self.assertTrue(
                (destination / report["worst_on"]["image_file"]).is_file()
            )
            persisted = json.loads(
                (destination / "calibration_diagnostics.json")
                .read_text(encoding="utf-8")
            )
            self.assertEqual(
                "MASK_010",
                persisted["worst_off"]["mask_id"],
            )
            self.assertEqual(
                7,
                persisted["worst_off"]["augmentation_index"],
            )

    def test_physical_h1_debug_calibration_uses_five_unique_frozen_frames(self):
        base_calibration = {
            "source": "held_out_h1_augmented_probability_gap",
            "separable": True,
            "reference_sample_count": 2,
            "augmentations_per_reference": 16,
            "sample_count": 34,
            "class_counts": {"off": 17, "on": 17},
            "max_off_on_probability": 0.58,
            "min_on_on_probability": 0.83,
            "uncertainty_gap": 0.25,
            "off_max_on_probability": 0.58,
            "on_min_on_probability": 0.83,
        }
        metadata = {
            "schema_version": 3,
            "model_type": "f3_segment_on_off_cnn",
            "project_name": "DISPLAY A",
            "input_size": 48,
            "onnx_sha256": "a" * 64,
            "suggested_thresholds": {
                "off_max_on_probability": 0.58,
                "on_min_on_probability": 0.83,
            },
            "threshold_calibration": base_calibration,
        }

        def debug_report(frame_number, off_p, on_p):
            analysis = {
                "ready": True,
                "approved": bool(on_p >= 0.83),
                "reason": (
                    "h1_neural_conforme"
                    if on_p >= 0.83
                    else "h1_neural_incerto"
                ),
                "project_name": "DISPLAY A",
                "check_id": "CHECK_001",
                "check_name": "H1",
                "mask_results": [
                    {
                        "mask_id": "MASK_001",
                        "expected": "off",
                        "neural_probabilities": {
                            "off": 1.0 - off_p,
                            "on": off_p,
                        },
                    },
                    {
                        "mask_id": "MASK_002",
                        "expected": "on",
                        "neural_probabilities": {
                            "off": 1.0 - on_p,
                            "on": on_p,
                        },
                    },
                ],
                "reference_authority": "f3_h1_neural_segment_detector",
                "neural_visual_authority": True,
                "conventional_visual_authority_used": False,
                "neural_model": {
                    "ready": True,
                    "project_name": "DISPLAY A",
                    "model_type": "f3_segment_on_off_cnn",
                    "input_size": 48,
                    "off_max_on_probability": 0.58,
                    "on_min_on_probability": 0.83,
                    "threshold_calibration_source": (
                        "held_out_h1_augmented_probability_gap"
                    ),
                    "threshold_calibration_gap": 0.25,
                    "threshold_calibration_sample_count": 34,
                    "threshold_calibration_augmentations_per_reference": 16,
                },
            }
            return (
                "[RESUMO OPERACIONAL - LEIA PRIMEIRO]\n"
                f"capturado_em=2026-10-05T12:1{frame_number}:00-04:00\n"
                f"frame_sha256_24={frame_number:024x}\n"
                '"last_auto_analysis": '
                + json.dumps(analysis)
                + "\n"
            )

        payload = "".join(
            [
                debug_report(1, 0.51, 0.84),
                debug_report(2, 0.54, 0.82),
                debug_report(3, 0.52, 0.81),
                debug_report(4, 0.50, 0.815),
                debug_report(5, 0.49, 0.812),
            ]
        )

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "h1_debug.txt"
            path.write_text(payload, encoding="utf-8")
            physical = collect_physical_h1_debug_calibration(
                [path],
                repository=_PhysicalCalibrationRepository(),
                project_name="DISPLAY A",
                validation_check_id="CHECK_001",
                metadata=metadata,
            )

        self.assertEqual(5, physical["frame_count"])
        self.assertEqual(10, physical["sample_count"])
        self.assertEqual(
            {"off": 5, "on": 5},
            physical["class_counts"],
        )
        self.assertAlmostEqual(
            0.54,
            physical["max_off_on_probability"],
        )
        self.assertAlmostEqual(
            0.81,
            physical["min_on_on_probability"],
        )
        self.assertEqual(
            "MASK_001",
            physical["worst_off"]["mask_id"],
        )
        self.assertEqual(
            "MASK_002",
            physical["worst_on"]["mask_id"],
        )

    def test_physical_h1_calibration_combines_conservative_extremes(self):
        base = {
            "source": "held_out_h1_augmented_probability_gap",
            "separable": True,
            "reference_sample_count": 28,
            "augmentations_per_reference": 16,
            "sample_count": 476,
            "class_counts": {"off": 357, "on": 119},
            "max_off_on_probability": 0.584876,
            "min_on_on_probability": 0.827438,
            "uncertainty_gap": 0.242562,
            "off_max_on_probability": 0.584876,
            "on_min_on_probability": 0.827438,
        }
        physical = {
            "separable": True,
            "frame_count": 5,
            "sample_count": 140,
            "class_counts": {"off": 105, "on": 35},
            "max_off_on_probability": 0.534034,
            "min_on_on_probability": 0.809613,
            "uncertainty_gap": 0.275579,
        }

        combined = combine_augmented_and_physical_calibration(
            base,
            physical,
        )

        self.assertEqual(
            "held_out_h1_augmented_plus_physical_multiframe_probability_gap",
            combined["source"],
        )
        self.assertAlmostEqual(
            0.584876,
            combined["max_off_on_probability"],
        )
        self.assertAlmostEqual(
            0.809613,
            combined["min_on_on_probability"],
        )
        self.assertAlmostEqual(
            0.224737,
            combined["uncertainty_gap"],
            places=6,
        )
        self.assertEqual(616, combined["sample_count"])
        self.assertEqual(
            {"off": 462, "on": 154},
            combined["class_counts"],
        )

    def test_candidate_requires_exact_h1_and_torch_onnx_equivalence(self):
        logits = np.asarray(
            [[4.0, -4.0], [-4.0, 4.0]],
            dtype=np.float32,
        )
        metrics = {
            "accuracy": 1.0,
            "class_accuracy": {
                "off": 1.0,
                "on": 1.0,
            },
            "all_validation_checks_exact": True,
        }

        _validate_candidate(
            cv_logits=logits.copy(),
            torch_logits=logits.copy(),
            metrics=metrics,
        )

        with self.assertRaises(RuntimeError):
            _validate_candidate(
                cv_logits=logits + 0.01,
                torch_logits=logits,
                metrics=metrics,
            )

        with self.assertRaises(RuntimeError):
            _validate_candidate(
                cv_logits=logits.copy(),
                torch_logits=logits.copy(),
                metrics={
                    **metrics,
                    "accuracy": 0.95,
                    "all_validation_checks_exact": False,
                },
            )


if __name__ == "__main__":
    unittest.main()
