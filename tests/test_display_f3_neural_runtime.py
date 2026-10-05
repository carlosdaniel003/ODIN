from __future__ import annotations

import hashlib
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

import src.platform.display_auto_check_runtime as runtime_module
from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin
import src.platform.display_f3_live_diagnostic_trace as trace_module
import src.platform.display_f3_neural_runtime as neural_module
from src.platform.desktop_production_app import DesktopProductionApp
from src.platform.display_auto_check_policy import (
    decidir_analise_display_f3,
)
from src.platform.display_f3_neural_dataset import (
    f3_neural_model_path_for_repository,
)
from src.platform.display_f3_neural_runtime import (
    F3NeuralCheckAnalyzer,
    F3NeuralSegmentDetector,
)
from src.platform.display_f3_runtime_authorities import (
    F3CheckAnalyzerAuthority,
)
from src.platform.display_f3_same_mask_reference_fix import (
    F3SameMaskReferenceAnalyzer,
)
from src.platform.display_project_repository import (
    DisplayProjectRepository,
)


def _frame() -> np.ndarray:
    image = np.full((96, 160, 3), 18, dtype=np.uint8)
    image[34:62, 28:56] = 230
    image[34:62, 104:132] = 26
    return image


def _repository(root: Path):
    repository = DisplayProjectRepository(
        root / "odin_display_projects.json"
    )
    assert repository.adicionar_projeto(
        "DISPLAY A",
        (160, 96),
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
    assert repository.salvar_mascaras(
        "DISPLAY A",
        masks,
    )
    checks = repository.listar_checks(
        "DISPLAY A"
    )
    h1, blue = checks[0], checks[1]
    assert repository.salvar_estados_check(
        "DISPLAY A",
        h1["id"],
        {
            "MASK_001": "on",
            "MASK_002": "off",
        },
    )
    assert repository.salvar_estados_check(
        "DISPLAY A",
        blue["id"],
        {
            "MASK_001": "off",
            "MASK_002": "on",
        },
    )
    return repository, h1, blue


def _ready_model_status():
    return {
        "ready": True,
        "reason": "neural_model_ready",
        "project_name": "DISPLAY A",
        "model_path": "/tmp/display_a_segments.onnx",
        "metadata_path": "/tmp/display_a_segments.json",
        "model_type": "f3_segment_on_off_cnn",
        "input_size": 48,
        "on_min_on_probability": 0.80,
        "off_max_on_probability": 0.20,
        "load_count": 1,
    }


def _inference(states):
    observations = []
    for index, state in enumerate(states):
        if state == "on":
            probabilities = {"off": 0.02, "on": 0.98}
        elif state == "off":
            probabilities = {"off": 0.97, "on": 0.03}
        else:
            probabilities = {"off": 0.46, "on": 0.54}
        observations.append(
            {
                "index": index,
                "state": state,
                "certain": state != "uncertain",
                "confidence": max(probabilities.values()),
                "probabilities": probabilities,
                "logits": [0.0, 0.0],
            }
        )
    return {
        **_ready_model_status(),
        "ready": True,
        "reason": "neural_inference_ready",
        "batch_size": len(observations),
        "inference_count": 1,
        "observations": observations,
    }


class _FakeNet:
    def __init__(self):
        self.inputs = []
        self.forward_count = 0

    def setInput(self, value):
        self.inputs.append(np.asarray(value).copy())

    def forward(self):
        self.forward_count += 1
        batch = int(self.inputs[-1].shape[0])
        base = np.asarray(
            [
                [-3.0, 3.0],
                [3.0, -3.0],
            ],
            dtype=np.float32,
        )
        if batch <= 2:
            return base[:batch]
        return np.vstack(
            [base[index % 2] for index in range(batch)]
        )


class DisplayF3NeuralRuntimeTests(unittest.TestCase):
    def test_detector_loads_onnx_once_and_infers_all_segments_as_one_batch(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, _h1, _blue = _repository(
                Path(temp)
            )
            model_path = f3_neural_model_path_for_repository(
                repository,
                "DISPLAY A",
            )
            model_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            model_path.write_bytes(b"fake-onnx")
            model_hash = hashlib.sha256(
                model_path.read_bytes()
            ).hexdigest()
            model_path.with_suffix(".json").write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "model_type": "f3_segment_on_off_cnn",
                        "project_name": "DISPLAY A",
                        "input_size": 48,
                        "onnx_sha256": model_hash,
                        "split": {
                            "strategy": "hold_out_first_check_for_n1",
                            "validation_check_id": "CHECK_001",
                        },
                        "validation": {
                            "accepted_for_physical_h1_retest": True,
                        },
                        "labels": {
                            "off": 0,
                            "on": 1,
                        },
                        "suggested_thresholds": {
                            "off_max_on_probability": 0.48,
                            "on_min_on_probability": 0.62,
                        },
                        "threshold_calibration": {
                            "source": (
                                "held_out_h1_augmented_probability_gap"
                            ),
                            "separable": True,
                            "reference_sample_count": 2,
                            "augmentations_per_reference": 4,
                            "sample_count": 10,
                            "class_counts": {
                                "off": 5,
                                "on": 5,
                            },
                            "max_off_on_probability": 0.48,
                            "min_on_on_probability": 0.62,
                            "uncertainty_gap": 0.14,
                            "off_max_on_probability": 0.48,
                            "on_min_on_probability": 0.62,
                        },
                    }
                ),
                encoding="utf-8",
            )
            network = _FakeNet()
            with patch.object(
                neural_module.cv2.dnn,
                "readNetFromONNX",
                return_value=network,
            ) as loader:
                detector = F3NeuralSegmentDetector(
                    repository
                )
                tensors = [
                    np.zeros(
                        (4, 48, 48),
                        dtype=np.float32,
                    ),
                    np.zeros(
                        (4, 48, 48),
                        dtype=np.float32,
                    ),
                ]

                first = detector.predict(
                    "DISPLAY A",
                    tensors,
                )
                second = detector.predict(
                    "DISPLAY A",
                    tensors,
                )

            self.assertTrue(first["ready"])
            self.assertTrue(second["ready"])
            self.assertEqual(
                ["on", "off"],
                [
                    item["state"]
                    for item in first["observations"]
                ],
            )
            self.assertEqual(
                (2, 4, 48, 48),
                network.inputs[0].shape,
            )
            self.assertEqual(1, loader.call_count)
            self.assertEqual(1, detector.load_count)
            self.assertEqual(2, detector.inference_count)
            self.assertEqual(0.48, first["off_max_on_probability"])
            self.assertEqual(0.62, first["on_min_on_probability"])
            self.assertEqual(
                "held_out_h1_augmented_probability_gap",
                first["threshold_calibration_source"],
            )

    def test_detector_accepts_physical_multiframe_threshold_calibration(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, h1, _blue = _repository(Path(temp))
            model_path = f3_neural_model_path_for_repository(
                repository,
                "DISPLAY A",
            )
            model_path.parent.mkdir(parents=True, exist_ok=True)
            model_path.write_bytes(b"fake-onnx")
            model_hash = hashlib.sha256(
                model_path.read_bytes()
            ).hexdigest()

            base = {
                "source": "held_out_h1_augmented_probability_gap",
                "separable": True,
                "reference_sample_count": 2,
                "augmentations_per_reference": 4,
                "sample_count": 10,
                "class_counts": {"off": 5, "on": 5},
                "max_off_on_probability": 0.45,
                "min_on_on_probability": 0.62,
                "uncertainty_gap": 0.17,
                "off_max_on_probability": 0.45,
                "on_min_on_probability": 0.62,
            }
            physical = {
                "source": "f3_debug_technical_frozen_frames",
                "separable": True,
                "project_name": "DISPLAY A",
                "validation_check_id": h1["id"],
                "model_sha256": model_hash,
                "minimum_frame_count": 5,
                "frame_count": 5,
                "frame_hashes": [
                    f"frame-{index}"
                    for index in range(5)
                ],
                "sample_count": 10,
                "class_counts": {"off": 5, "on": 5},
                "max_off_on_probability": 0.48,
                "min_on_on_probability": 0.60,
                "uncertainty_gap": 0.12,
                "frames": [
                    {"frame_hash": f"frame-{index}"}
                    for index in range(5)
                ],
            }
            combined = {
                "source": (
                    "held_out_h1_augmented_plus_physical_multiframe_probability_gap"
                ),
                "separable": True,
                "reference_sample_count": 2,
                "augmentations_per_reference": 4,
                "sample_count": 20,
                "class_counts": {"off": 10, "on": 10},
                "max_off_on_probability": 0.48,
                "min_on_on_probability": 0.60,
                "uncertainty_gap": 0.12,
                "off_max_on_probability": 0.48,
                "on_min_on_probability": 0.60,
                "base_augmented_calibration": base,
                "physical_h1": physical,
            }
            model_path.with_suffix(".json").write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "model_type": "f3_segment_on_off_cnn",
                        "project_name": "DISPLAY A",
                        "input_size": 48,
                        "onnx_sha256": model_hash,
                        "split": {
                            "strategy": "hold_out_first_check_for_n1",
                            "validation_check_id": h1["id"],
                        },
                        "validation": {
                            "accepted_for_physical_h1_retest": True,
                        },
                        "labels": {
                            "off": 0,
                            "on": 1,
                        },
                        "suggested_thresholds": {
                            "off_max_on_probability": 0.48,
                            "on_min_on_probability": 0.60,
                        },
                        "threshold_calibration": combined,
                    }
                ),
                encoding="utf-8",
            )

            network = _FakeNet()
            with patch.object(
                neural_module.cv2.dnn,
                "readNetFromONNX",
                return_value=network,
            ):
                status = F3NeuralSegmentDetector(repository).prepare(
                    "DISPLAY A"
                )

            self.assertTrue(status["ready"])
            self.assertEqual(
                "held_out_h1_augmented_plus_physical_multiframe_probability_gap",
                status["threshold_calibration_source"],
            )
            self.assertEqual(
                5,
                status["physical_h1_calibration_frame_count"],
            )
            self.assertEqual(
                model_hash,
                status["onnx_sha256"],
            )

    def test_detector_rejects_artifact_without_held_out_h1_acceptance(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, _h1, _blue = _repository(
                Path(temp)
            )
            model_path = f3_neural_model_path_for_repository(
                repository,
                "DISPLAY A",
            )
            model_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            model_path.write_bytes(b"fake-onnx")
            model_hash = hashlib.sha256(
                model_path.read_bytes()
            ).hexdigest()
            model_path.with_suffix(".json").write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "model_type": "f3_segment_on_off_cnn",
                        "project_name": "DISPLAY A",
                        "input_size": 48,
                        "onnx_sha256": model_hash,
                        "split": {
                            "strategy": "hold_out_first_check_for_n1",
                            "validation_check_id": "CHECK_002",
                        },
                        "validation": {
                            "accepted_for_physical_h1_retest": False,
                        },
                        "labels": {
                            "off": 0,
                            "on": 1,
                        },
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(
                neural_module.cv2.dnn,
                "readNetFromONNX",
            ) as loader:
                status = F3NeuralSegmentDetector(
                    repository
                ).prepare("DISPLAY A")

            self.assertFalse(status["ready"])
            self.assertEqual(
                "neural_model_not_validated_for_h1",
                status["reason"],
            )
            loader.assert_not_called()

    def test_detector_rejects_hash_mismatch_before_opencv_load(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, _h1, _blue = _repository(
                Path(temp)
            )
            model_path = f3_neural_model_path_for_repository(
                repository,
                "DISPLAY A",
            )
            model_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            model_path.write_bytes(b"fake-onnx")
            model_path.with_suffix(".json").write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "model_type": "f3_segment_on_off_cnn",
                        "project_name": "DISPLAY A",
                        "input_size": 48,
                        "onnx_sha256": "0" * 64,
                        "labels": {
                            "off": 0,
                            "on": 1,
                        },
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(
                neural_module.cv2.dnn,
                "readNetFromONNX",
            ) as loader:
                status = F3NeuralSegmentDetector(
                    repository
                ).prepare("DISPLAY A")

            self.assertFalse(status["ready"])
            self.assertEqual(
                "neural_model_hash_mismatch",
                status["reason"],
            )
            loader.assert_not_called()

    def test_detector_fails_closed_when_metadata_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, _h1, _blue = _repository(
                Path(temp)
            )
            model_path = f3_neural_model_path_for_repository(
                repository,
                "DISPLAY A",
            )
            model_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            model_path.write_bytes(b"fake-onnx")

            with patch.object(
                neural_module.cv2.dnn,
                "readNetFromONNX",
            ) as loader:
                status = F3NeuralSegmentDetector(
                    repository
                ).prepare("DISPLAY A")

            self.assertFalse(status["ready"])
            self.assertEqual(
                "neural_metadata_missing",
                status["reason"],
            )
            loader.assert_not_called()

    def test_first_check_uses_neural_batch_as_only_visual_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, h1, _blue = _repository(
                Path(temp)
            )
            analyzer = F3NeuralCheckAnalyzer(
                repository
            )
            analyzer.neural_detector.prepare = Mock(
                return_value=_ready_model_status()
            )
            analyzer.neural_detector.predict = Mock(
                return_value=_inference(
                    ["on", "off"]
                )
            )

            result = analyzer.analyze(
                _frame(),
                "DISPLAY A",
                h1["id"],
            )

            self.assertTrue(result["ready"])
            self.assertTrue(result["approved"])
            self.assertEqual(2, result["active_mask_count"])
            self.assertEqual(2, result["matched_mask_count"])
            self.assertEqual(0, result["uncertain_mask_count"])
            self.assertTrue(result["neural_visual_authority"])
            self.assertFalse(
                result["conventional_visual_authority_used"]
            )
            self.assertEqual(
                neural_module.F3_H1_NEURAL_AUTHORITY,
                result["reference_authority"],
            )
            analyzer.neural_detector.predict.assert_called_once()
            batch = analyzer.neural_detector.predict.call_args.args[1]
            self.assertEqual(2, len(batch))
            self.assertTrue(
                all(
                    item.shape == (4, 48, 48)
                    for item in batch
                )
            )

    def test_detector_rejects_schema3_without_calibrated_threshold_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, h1, _blue = _repository(Path(temp))
            model_path = f3_neural_model_path_for_repository(
                repository,
                "DISPLAY A",
            )
            model_path.parent.mkdir(parents=True, exist_ok=True)
            model_path.write_bytes(b"fake-onnx")
            model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
            model_path.with_suffix(".json").write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "model_type": "f3_segment_on_off_cnn",
                        "project_name": "DISPLAY A",
                        "input_size": 48,
                        "onnx_sha256": model_hash,
                        "split": {
                            "strategy": "hold_out_first_check_for_n1",
                            "validation_check_id": h1["id"],
                        },
                        "validation": {
                            "accepted_for_physical_h1_retest": True,
                        },
                        "labels": {
                            "off": 0,
                            "on": 1,
                        },
                        "suggested_thresholds": {
                            "off_max_on_probability": 0.20,
                            "on_min_on_probability": 0.80,
                        },
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(
                neural_module.cv2.dnn,
                "readNetFromONNX",
            ) as loader:
                status = F3NeuralSegmentDetector(repository).prepare(
                    "DISPLAY A"
                )

            self.assertFalse(status["ready"])
            self.assertEqual(
                "neural_threshold_calibration_missing",
                status["reason"],
            )
            loader.assert_not_called()

    def test_neural_effective_ui_does_not_count_uncertain_as_conforming(self):
        analysis = {
            "ready": True,
            "neural_visual_authority": True,
            "mask_results": [
                {
                    "mask_id": "MASK_001",
                    "classified": "on",
                    "matched": True,
                    "neural_certain": True,
                },
                {
                    "mask_id": "MASK_002",
                    "classified": "uncertain",
                    "matched": None,
                    "neural_certain": False,
                },
                {
                    "mask_id": "MASK_003",
                    "classified": "uncertain",
                    "matched": None,
                    "neural_certain": False,
                },
            ],
        }

        published = (
            DisplayAutomaticCheckF3Mixin
            ._display_auto_publish_effective_ui_authority(analysis)
        )

        self.assertEqual(1, published["effective_matched_mask_count"])
        self.assertEqual(2, published["effective_uncertain_mask_count"])
        self.assertEqual(
            ("MASK_002", "MASK_003"),
            published["effective_uncertain_mask_ids"],
        )
        self.assertEqual((), published["effective_failed_mask_ids"])
        self.assertEqual(
            "uncertain",
            published["effective_classifications"]["MASK_002"],
        )

    def test_missing_h1_model_never_falls_back_to_conventional_analyzer(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, h1, _blue = _repository(
                Path(temp)
            )
            analyzer = F3NeuralCheckAnalyzer(
                repository
            )
            analyzer.neural_detector.prepare = Mock(
                return_value={
                    "ready": False,
                    "reason": "neural_model_missing",
                }
            )

            with patch.object(
                F3SameMaskReferenceAnalyzer,
                "analyze",
                side_effect=AssertionError(
                    "H1 neural must not call conventional analyzer"
                ),
            ) as conventional:
                result = analyzer.analyze(
                    _frame(),
                    "DISPLAY A",
                    h1["id"],
                )

            self.assertFalse(result["ready"])
            self.assertIsNone(result["approved"])
            self.assertEqual(
                "neural_model_missing",
                result["reason"],
            )
            self.assertTrue(result["neural_visual_authority"])
            conventional.assert_not_called()

    def test_blue_uses_neural_batch_as_only_visual_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, _h1, blue = _repository(
                Path(temp)
            )
            analyzer = F3NeuralCheckAnalyzer(
                repository
            )
            analyzer.neural_detector.prepare = Mock(
                return_value=_ready_model_status()
            )
            analyzer.neural_detector.predict = Mock(
                return_value=_inference(
                    ["off", "on"]
                )
            )

            with patch.object(
                F3SameMaskReferenceAnalyzer,
                "analyze",
                side_effect=AssertionError(
                    "BLUE neural must not call conventional analyzer"
                ),
            ) as conventional:
                result = analyzer.analyze(
                    _frame(),
                    "DISPLAY A",
                    blue["id"],
                )

            self.assertTrue(result["ready"])
            self.assertTrue(result["approved"])
            self.assertTrue(result["neural_visual_authority"])
            self.assertEqual(1, result["neural_check_index"])
            self.assertEqual("N2", result["neural_stage"])
            self.assertEqual(
                neural_module.F3_NEURAL_CHECK_SCOPE,
                result["neural_check_scope"],
            )
            self.assertFalse(
                result["conventional_visual_authority_used"]
            )
            conventional.assert_not_called()

    def test_usb_still_delegates_to_conventional_analyzer(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, _h1, _blue = _repository(
                Path(temp)
            )
            usb = repository.listar_checks("DISPLAY A")[2]
            analyzer = F3NeuralCheckAnalyzer(
                repository
            )
            expected = {
                "ready": True,
                "approved": True,
                "source": "conventional-usb",
            }
            with patch.object(
                F3SameMaskReferenceAnalyzer,
                "analyze",
                return_value=expected,
            ) as conventional:
                result = analyzer.analyze(
                    _frame(),
                    "DISPLAY A",
                    usb["id"],
                )

            self.assertIs(expected, result)
            conventional.assert_called_once()

    def test_neural_h1_divergence_can_emit_ng_but_uncertain_cannot(self):
        divergent = {
            "ready": True,
            "approved": False,
            "neural_visual_authority": True,
            "neural_check_scope": neural_module.F3_NEURAL_CHECK_SCOPE,
            "mask_results": [
                {
                    "mask_id": "MASK_001",
                    "expected": "on",
                    "classified": "on",
                    "matched": True,
                    "confidence": 0.98,
                    "neural_certain": True,
                },
                {
                    "mask_id": "MASK_002",
                    "expected": "off",
                    "classified": "on",
                    "matched": False,
                    "confidence": 0.97,
                    "neural_certain": True,
                },
            ],
        }
        decision = decidir_analise_display_f3(
            divergent,
            reference_gate=True,
        )
        self.assertEqual("ng", decision["decision"])
        self.assertEqual(
            "h1_neural_divergencia_confirmada",
            decision["reason"],
        )
        self.assertEqual(
            "MASK_002",
            decision["failed_mask_id"],
        )

        uncertain = {
            **divergent,
            "mask_results": [
                divergent["mask_results"][0],
                {
                    "mask_id": "MASK_002",
                    "expected": "off",
                    "classified": "uncertain",
                    "matched": None,
                    "confidence": 0.56,
                    "neural_certain": False,
                },
            ],
        }
        decision = decidir_analise_display_f3(
            uncertain,
            reference_gate=True,
        )
        self.assertEqual(
            "searching",
            decision["decision"],
        )
        self.assertEqual(
            "classificacao_neural_incerta",
            decision["reason"],
        )

    def test_neural_blue_divergence_emits_ng_but_uncertain_cannot(self):
        divergent = {
            "ready": True,
            "approved": False,
            "neural_visual_authority": True,
            "neural_check_scope": neural_module.F3_NEURAL_CHECK_SCOPE,
            "mask_results": [
                {
                    "mask_id": "MASK_023",
                    "expected": "on",
                    "classified": "on",
                    "matched": True,
                    "confidence": 0.98,
                    "neural_certain": True,
                },
                {
                    "mask_id": "MASK_024",
                    "expected": "on",
                    "classified": "off",
                    "matched": False,
                    "confidence": 0.97,
                    "neural_certain": True,
                },
            ],
        }
        decision = decidir_analise_display_f3(
            divergent,
            reference_gate=False,
        )
        self.assertEqual("ng", decision["decision"])
        self.assertEqual(
            "check_neural_divergencia_confirmada",
            decision["reason"],
        )
        self.assertEqual(
            "MASK_024",
            decision["failed_mask_id"],
        )

        uncertain = {
            **divergent,
            "mask_results": [
                divergent["mask_results"][0],
                {
                    "mask_id": "MASK_024",
                    "expected": "on",
                    "classified": "uncertain",
                    "matched": None,
                    "confidence": 0.56,
                    "neural_certain": False,
                },
            ],
        }
        decision = decidir_analise_display_f3(
            uncertain,
            reference_gate=False,
        )
        self.assertEqual("searching", decision["decision"])
        self.assertEqual(
            "classificacao_neural_incerta",
            decision["reason"],
        )

    def test_canonical_check_authority_embeds_neural_semantic_analyzer(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, _h1, _blue = _repository(
                Path(temp)
            )
            app = SimpleNamespace(
                display_project_repository=repository,
            )
            owner = F3CheckAnalyzerAuthority(app)

            self.assertIsInstance(
                owner.analyzer.semantic,
                F3NeuralCheckAnalyzer,
            )

    def test_exact_probe_is_observer_only_for_migrated_blue(self):
        old = getattr(
            runtime_module,
            "_display_f3_neural_authority",
            None,
        )
        runtime_module._display_f3_neural_authority = True
        try:
            result = trace_module._advance_positive_probe_if_needed(
                SimpleNamespace(),
                {
                    "project_name": "DISPLAY A",
                    "check_id": "CHECK_002",
                    "check_name": "BLUE",
                    "current_index": 1,
                },
                {"ready": True, "approved": True},
                {"confirm": True},
            )
        finally:
            if old is None:
                try:
                    delattr(
                        runtime_module,
                        "_display_f3_neural_authority",
                    )
                except AttributeError:
                    pass
            else:
                runtime_module._display_f3_neural_authority = old

        self.assertFalse(result["advanced"])
        self.assertTrue(result["observer_only"])
        self.assertEqual(
            "neural_check_owns_check_decision",
            result["reason"],
        )

    def test_neural_h1_bypasses_only_legacy_first_on_judgement_gate(self):
        source = inspect.getsource(
            DisplayAutomaticCheckF3Mixin._process_display_auto_check
        )
        self.assertIn("neural_reference_authority", source)
        self.assertIn(
            'analysis.get("neural_visual_authority") is True',
            source,
        )
        self.assertIn(
            '"reference_judgement_owner"',
            source,
        )
        self.assertIn(
            '"neural_visual_authority"',
            source,
        )
        self.assertIn(
            "else reference_power_evidence",
            source,
        )
        # A policy neural continua responsável por INCERTO/OK/NG; o bypass
        # remove apenas a trava óptica convencional do primeiro segmento ON.
        self.assertIn("decidir_analise_display_f3(", source)

    def test_bootstrap_installs_neural_authority_after_conventional_layers(self):
        source = inspect.getsource(
            DesktopProductionApp.__init__
        )
        neural_position = source.index(
            "instalar_autoridade_neural_h1_blue_display_f3()"
        )
        photo_position = source.index(
            "instalar_aprendizado_foto_check_display_f3()"
        )
        power_position = source.index(
            "instalar_autoridade_energia_final_display_f3()"
        )
        super_position = source.index(
            "super().__init__(root)"
        )

        self.assertGreater(
            neural_position,
            photo_position,
        )
        self.assertGreater(
            neural_position,
            power_position,
        )
        self.assertLess(
            neural_position,
            super_position,
        )


if __name__ == "__main__":
    unittest.main()
