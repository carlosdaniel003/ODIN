from __future__ import annotations

import unittest
import numpy as np

from scripts.treinar_f3_segmentos_neural import (
    _export_onnx_candidate,
    _validate_candidate,
    preparar_preflight,
)


class _Repository:
    def listar_checks(self, _project_name):
        return [
            {"id": "CHECK_001", "name": "H1"},
            {"id": "CHECK_002", "name": "BLUE"},
            {"id": "CHECK_003", "name": "USB"},
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
        return {
            "ready": bool(self.samples and counts["off"] and counts["on"]),
            "reason": "dataset_pronto",
            "project_name": "DISPLAY A",
            "sample_count": len(self.samples),
            "class_counts": counts,
            "checks_used": tuple(checks),
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
