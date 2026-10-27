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
    F3HybridCheckAnalyzer,
    F3NeuralCheckAnalyzer,
    F3NeuralSegmentDetector,
)
from src.platform.display_f3_runtime_authorities import (
    F3CheckAnalyzerAuthority,
)
from src.platform.display_f3_same_mask_reference_fix import (
    F3_SAME_MASK_REFERENCE_SOURCE,
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


def _physical_analysis(states, *, confidence: float = 0.98):
    rows = []
    for index, state in enumerate(states, start=1):
        rows.append(
            {
                "mask_id": f"MASK_{index:03d}",
                "classified": state,
                "confidence": confidence,
                "reference_source": F3_SAME_MASK_REFERENCE_SOURCE,
                "reference_separation": 0.95,
                "distances": {
                    "on": 5.0 if state == "on" else 900.0,
                    "off": 900.0 if state == "on" else 5.0,
                },
            }
        )
    return {
        "ready": True,
        "approved": True,
        "reason": "physical_test_ready",
        "mask_results": rows,
        "matched_mask_count": len(rows),
        "active_mask_count": len(rows),
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
    def test_fm_circles_cannot_be_certain_off_when_model_prefers_on(self):
        """Reproduz o modelo real: OFF <= 0.660738 inclui p(ON)>50%."""
        class CalibratedNet:
            def setInput(self, batch):
                self.batch_size = len(batch)

            def forward(self):
                assert self.batch_size == 3
                probabilities = ((0.341842, 0.658158),
                                 (0.487847, 0.512153),
                                 (0.82, 0.18))
                return np.log(np.asarray(probabilities, dtype=np.float32))

        with tempfile.TemporaryDirectory() as temp:
            repository, _, _ = _repository(Path(temp))
            detector = F3NeuralSegmentDetector(repository)
            detector._net = CalibratedNet()
            detector.prepare = Mock(return_value={
                **_ready_model_status(),
                "off_max_on_probability": 0.660738,
                "on_min_on_probability": 0.809613,
            })
            batch = [np.zeros((4, 48, 48), dtype=np.float32) for _ in range(3)]
            observations = detector.predict("DISPLAY A", batch)["observations"]

        self.assertEqual(
            ["uncertain", "uncertain", "off"],
            [item["state"] for item in observations],
        )
        self.assertEqual(
            [False, False, True],
            [item["certain"] for item in observations],
        )
        self.assertGreater(observations[0]["probabilities"]["on"], 0.5)
        self.assertGreater(observations[1]["probabilities"]["on"], 0.5)

    def test_circulos_fm_geram_par_local_de_fotos_de_checks_e_avancam(self):
        """Se ON no FM e OFF no H1, o aprendizado real gera pares por ID."""
        from src.platform.display_check_presence_reference import (
            DisplayCheckPresenceReferenceStore,
        )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repository = DisplayProjectRepository(root / "display_projects.json")
            repository.adicionar_projeto("DISPLAY FM", (120, 80))
            circles = [
                {"id": "MASK_029", "type": "circle", "cx": 30, "cy": 40, "radius": 10},
                {"id": "MASK_030", "type": "circle", "cx": 90, "cy": 40, "radius": 10},
            ]
            repository.salvar_mascaras("DISPLAY FM", circles)
            checks = repository.listar_checks("DISPLAY FM")
            first, second = checks[:2]
            mask_ids = ("MASK_029", "MASK_030")
            self.assertTrue(repository.salvar_estados_check(
                "DISPLAY FM", first["id"],
                {mask_id: "off" for mask_id in mask_ids},
            ))
            self.assertTrue(repository.salvar_estados_check(
                "DISPLAY FM", second["id"],
                {mask_id: "on" for mask_id in mask_ids},
            ))
            frame_off = np.full((80, 120, 3), 20, dtype=np.uint8)
            frame_on = frame_off.copy()
            for cx in (30, 90):
                frame_on[30:51, cx-10:cx+11] = 250
            store = DisplayCheckPresenceReferenceStore(repository)
            self.assertIsNotNone(store.capture(
                "DISPLAY FM", first["id"], frame_off, (120, 80),
            ))
            self.assertIsNotNone(store.capture(
                "DISPLAY FM", second["id"], frame_on, (120, 80),
            ))

            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(
                return_value={**_ready_model_status(), "project_name": "DISPLAY FM"}
            )
            analyzer.neural_detector.predict = Mock(
                return_value=_inference(["uncertain", "uncertain"])
            )
            result = analyzer.analyze(frame_on, "DISPLAY FM", second["id"])
            self.assertTrue(result["ready"])
            self.assertTrue(result["approved"], result)
            self.assertEqual(2, result["matched_mask_count"])
            self.assertEqual(
                2, result["physical_same_mask_authoritative_count"],
            )
            self.assertEqual(
                {"physical_resolved_neural_uncertain"},
                {item["hybrid_resolution"] for item in result["mask_results"]},
            )

            # Os MESMOS LEDs acesos no CHECK que exige OFF devem divergir;
            # a alteração não pode introduzir falso OK.
            result_ng = analyzer.analyze(frame_on, "DISPLAY FM", first["id"])
            self.assertFalse(result_ng["approved"])
            self.assertTrue(all(
                item["classified"] == "on" and item["matched"] is False
                for item in result_ng["mask_results"]
            ))

    def test_fm_sem_par_fisico_local_permanece_incerto_e_nao_aprova(self):
        """Pool global não vira autoridade por causa de um LED aceso."""
        with tempfile.TemporaryDirectory() as temp:
            repository, h1, _ = _repository(Path(temp))
            repository.salvar_estados_check(
                "DISPLAY A", h1["id"],
                {"MASK_001": "on", "MASK_002": "on"},
            )
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(
                return_value=_ready_model_status()
            )
            analyzer.neural_detector.predict = Mock(
                return_value=_inference(["uncertain", "uncertain"])
            )
            pool_analysis = _physical_analysis(["on", "on"])
            for mask in pool_analysis["mask_results"]:
                mask["reference_source"] = "f3_check_photos_class_pool"
            with patch.object(
                F3SameMaskReferenceAnalyzer,
                "analyze",
                return_value=pool_analysis,
            ):
                result = analyzer.analyze(_frame(), "DISPLAY A", h1["id"])

            self.assertFalse(result["approved"])
            self.assertEqual(2, result["uncertain_mask_count"])
            self.assertTrue(all(
                item["hybrid_resolution"] == "neural_uncertain_without_local_physical"
                and item["matched"] is None
                for item in result["mask_results"]
            ))

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

    def test_first_check_uses_hybrid_authority_with_neural_when_physical_unavailable(self):
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
            self.assertTrue(result["hybrid_visual_authority"])
            self.assertFalse(result["physical_same_mask_evidence_ready"])
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

    def test_blue_uses_neural_and_same_mask_inside_one_hybrid_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, _h1, blue = _repository(
                Path(temp)
            )
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(
                return_value=_ready_model_status()
            )
            analyzer.neural_detector.predict = Mock(
                return_value=_inference(["off", "on"])
            )

            with patch.object(
                F3SameMaskReferenceAnalyzer,
                "analyze",
                return_value=_physical_analysis(["off", "on"]),
            ) as physical:
                result = analyzer.analyze(
                    _frame(),
                    "DISPLAY A",
                    blue["id"],
                )

            self.assertTrue(result["ready"])
            self.assertTrue(result["approved"])
            self.assertTrue(result["hybrid_visual_authority"])
            self.assertTrue(result["physical_same_mask_evidence_ready"])
            self.assertEqual(2, result["physical_same_mask_authoritative_count"])
            self.assertEqual(1, result["neural_check_index"])
            self.assertEqual("HYBRID_ALL_CHECKS_V1", result["neural_stage"])
            self.assertEqual(
                neural_module.F3_HYBRID_CHECK_SCOPE,
                result["hybrid_check_scope"],
            )
            self.assertFalse(result["conventional_visual_authority_used"])
            physical.assert_called_once()

    def test_usb_and_aux_are_also_hybrid_without_hardcoded_migration_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, _h1, _blue = _repository(Path(temp))
            checks = repository.listar_checks("DISPLAY A")
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(
                return_value=_ready_model_status()
            )

            for expected_index, check in enumerate(checks[2:], start=2):
                self.assertTrue(
                    repository.salvar_estados_check(
                        "DISPLAY A",
                        check["id"],
                        {"MASK_001": "on", "MASK_002": "off"},
                    )
                )
                expected_states = ["on", "off"]
                analyzer.neural_detector.predict = Mock(
                    return_value=_inference(expected_states)
                )
                with patch.object(
                    F3SameMaskReferenceAnalyzer,
                    "analyze",
                    return_value=_physical_analysis(expected_states),
                ):
                    result = analyzer.analyze(
                        _frame(),
                        "DISPLAY A",
                        check["id"],
                    )

                self.assertTrue(result["hybrid_visual_authority"])
                self.assertEqual(expected_index, result["neural_check_index"])
                self.assertEqual(
                    neural_module.F3_HYBRID_CHECK_SCOPE,
                    result["hybrid_check_scope"],
                )

    def test_future_check_enters_hybrid_scope_automatically(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, _h1, _blue = _repository(Path(temp))
            new_id = repository.adicionar_check("DISPLAY A", "NOVO")
            self.assertIsNotNone(new_id)
            self.assertTrue(
                repository.salvar_estados_check(
                    "DISPLAY A",
                    new_id,
                    {"MASK_001": "on", "MASK_002": "off"},
                )
            )
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(
                return_value=_ready_model_status()
            )
            analyzer.neural_detector.predict = Mock(
                return_value=_inference(["on", "off"])
            )
            with patch.object(
                F3SameMaskReferenceAnalyzer,
                "analyze",
                return_value=_physical_analysis(["on", "off"]),
            ):
                result = analyzer.analyze(
                    _frame(),
                    "DISPLAY A",
                    new_id,
                )

            self.assertTrue(result["approved"])
            self.assertEqual(4, result["neural_check_index"])
            self.assertEqual(
                "all_configured_checks_hybrid_v1",
                result["hybrid_check_scope"],
            )

    def test_same_mask_resolves_neural_uncertain_without_retraining(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, h1, _blue = _repository(Path(temp))
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(
                return_value=_ready_model_status()
            )
            analyzer.neural_detector.predict = Mock(
                return_value=_inference(["uncertain", "off"])
            )
            with patch.object(
                F3SameMaskReferenceAnalyzer,
                "analyze",
                return_value=_physical_analysis(["on", "off"]),
            ):
                result = analyzer.analyze(
                    _frame(),
                    "DISPLAY A",
                    h1["id"],
                )

            by_id = {
                item["mask_id"]: item
                for item in result["mask_results"]
            }
            resolved = by_id["MASK_001"]
            self.assertFalse(resolved["neural_certain"])
            self.assertTrue(resolved["semantic_certain"])
            self.assertEqual("on", resolved["classified"])
            self.assertTrue(resolved["matched"])
            self.assertEqual(
                "physical_resolved_neural_uncertain",
                resolved["hybrid_resolution"],
            )
            self.assertTrue(result["approved"])
            self.assertEqual(0, result["uncertain_mask_count"])

    def test_tracking_h1_mask_008_saturated_core_does_not_block_real_on(self):
        from src.models.led_features import LedFeatures
        from src.platform.display_f3_same_mask_reference_fix import (
            _same_mask_core_emission_evidence,
        )

        def core(v):
            return LedFeatures(
                inner_area_pixels=25,
                inner_v_mean=float(v),
            )

        with tempfile.TemporaryDirectory() as temp:
            repository, h1, _blue = _repository(Path(temp))
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(
                return_value=_ready_model_status()
            )
            analyzer.neural_detector.predict = Mock(
                return_value=_inference(["uncertain", "off"])
            )
            physical = _physical_analysis(["on", "off"], confidence=0.841)
            physical["mask_results"][0]["core_emission_evidence"] = (
                _same_mask_core_emission_evidence(
                    core(251.3566),
                    [core(251.7147), core(252.0),
                     core(252.1), core(251.85)],
                    [core(250.9), core(251.4503)],
                )
            )
            with patch.object(
                F3SameMaskReferenceAnalyzer, "analyze",
                return_value=physical,
            ):
                result = analyzer.analyze(
                    _frame(), "DISPLAY A", h1["id"],
                    mask_geometry_override=[
                        {"id": "MASK_001", "type": "circle",
                         "cx": 42, "cy": 48, "radius": 9},
                        {"id": "MASK_002", "type": "circle",
                         "cx": 118, "cy": 48, "radius": 9},
                    ],
                    mask_geometry_resolution=(160, 96),
                )
            self.assertTrue(result["approved"])
            self.assertEqual(2, result["matched_mask_count"])
            row = result["mask_results"][0]
            self.assertEqual("on", row["classified"])
            self.assertFalse(row["physical_disagreed_with_core"])
            self.assertEqual(
                "physical_resolved_neural_uncertain",
                row["hybrid_resolution"],
            )
            self.assertEqual(
                "same_mask_core_gap_below_reliable_separation",
                row["physical_core_emission"]["reason"],
            )
            decision = decidir_analise_display_f3(
                result, reference_gate=True
            )
            self.assertEqual("ok", decision["decision"])

    def test_tracked_renderer_obeys_first_green_visual_hold_before_repaint(self):
        # O renderer instalado na instância F3 ignora o método de desenho da
        # classe Window. O hold deve ser aplicado no próprio renderer ativo.
        import src.platform.display_f3_object_tracking as tracking

        source = inspect.getsource(
            tracking.instalar_autoridade_final_instancia_rastreamento_f3
        )
        tracked = source.split("def tracked_window_update(", 1)[1].split(
            "window.update_camera_preview = MethodType(", 1
        )[0]
        self.assertIn("_f3_snapshot_preview_hold_active(app)", tracked)
        self.assertIn('"visual_hold_no_repaint"', tracked)
        self.assertLess(
            tracked.index("_f3_snapshot_preview_hold_active(app)"),
            tracked.index("geometry = getattr("),
        )
        self.assertLess(
            tracked.index('"visual_hold_no_repaint"'),
            tracked.index("self_window.update_preview("),
        )
        self.assertIn(
            'text="FOTO CONGELADA • ANALISANDO CHECK"',
            tracked,
        )

    def test_tracking_green_preview_and_capture_share_exact_cache_identity(self):
        # Quando aparece verde na câmera, a geometria e o frame-token
        # precisam ser exatamente os que o capturador verifica. Um id puro
        # em vez da tupla ('tracked', id) impedia o congelamento rápido.
        import src.platform.display_f3_object_tracking as tracking

        source = inspect.getsource(
            tracking.instalar_autoridade_final_instancia_rastreamento_f3
        )
        tracked = source.split("def tracked_window_update(", 1)[1].split(
            "window.update_camera_preview = MethodType(", 1
        )[0]
        capture_source = inspect.getsource(
            tracking._submit_first_green_from_preview
        )
        self.assertIn(
            'geometry_token=("tracked", id(geometry))', tracked,
        )
        self.assertIn(
            'self_window._display_last_overlay_context = dict(', tracked,
        )
        self.assertIn('repr(("tracked", id(geometry)))', capture_source)
        self.assertIn('visual.get("live_visual_frame_token") != frame_token', capture_source)
        self.assertIn("raw_frame.copy()", capture_source)
        self.assertIn("_submit_live_semantic_job(", capture_source)

    def test_preview_freeze_is_only_visual_and_clears_after_semantic(self):
        import src.platform.display_live_roi_overlay as overlay

        now = 110.0
        future = SimpleNamespace(done=lambda: False)
        class _Check:
            def snapshot(self):
                return {"current_check": {"id": "CHECK_001"}}
        app = SimpleNamespace(
            display_check_runtime=_Check(),
            _display_f3_semantic_future=future,
            _display_f3_first_green_visual_hold={
                "check_id": "CHECK_001", "started_s": 109.9,
            },
        )
        self.assertTrue(overlay._f3_snapshot_preview_hold_active(app, now))
        self.assertIsNotNone(app._display_f3_first_green_visual_hold)
        self.assertFalse(
            overlay._f3_snapshot_preview_hold_active(app, now + 2.8)
        )
        self.assertIsNone(app._display_f3_first_green_visual_hold)
        app._display_f3_first_green_visual_hold = {
            "check_id": "CHECK_001", "started_s": now,
        }
        app._display_f3_semantic_future = SimpleNamespace(done=lambda: True)
        self.assertFalse(overlay._f3_snapshot_preview_hold_active(app, now))
        self.assertIsNone(app._display_f3_first_green_visual_hold)

    def test_blue_intermittent_green_freezes_same_snapshot_with_visible_status(self):
        import src.platform.display_f3_object_tracking as tracking

        raw = np.zeros((64, 100, 3), dtype=np.uint8)
        raw[24:36, 40:52] = 250
        geometry = {
            "locked": True,
            "check_id": "CHECK_002",
            "masks": [{"id": "MASK_024", "type": "circle",
                       "cx": 45, "cy": 30, "radius": 8}],
        }
        ledger = []
        legend = SimpleNamespace(
            configure=lambda **kw: ledger.append(("legend", kw))
        )
        window = SimpleNamespace(
            update_camera_preview=lambda image, visual_rotation=0: (
                ledger.append(("preview", image, visual_rotation)) or True
            ),
            preview_legend=legend,
            PREVIEW_MUTED="#94A3B8",
        )
        app = SimpleNamespace(
            display_f3_window=window,
            _display_f3_tracking_live_geometry=None,
            _display_auto_current_context=lambda: {
                "project_name": "DISPLAY A", "check_id": "CHECK_002",
                "check_name": "BLUE", "intermittent": True,
            },
            _obter_rotacao_visual_display_f3=lambda: 180,
        )
        payload = {
            "raw_frame": raw,
            "geometry": geometry,
            "frame_token": ("camera", 801),
            "snapshot_capture_trigger": {
                "ready": True, "triggered": True,
                "mask_ids": ("MASK_020",), "source": "tracked_same_frame_live_green",
            },
        }
        future = SimpleNamespace(done=lambda: False)
        self.assertTrue(
            tracking._show_worker_green_snapshot_during_analysis(
                app, payload, future
            )
        )
        self.assertEqual("preview", ledger[0][0])
        self.assertIs(raw, ledger[0][1])
        self.assertEqual(180, ledger[0][2])
        self.assertEqual("legend", ledger[1][0])
        self.assertEqual(
            "FOTO CONGELADA • ANALISANDO CHECK",
            ledger[1][1]["text"],
        )
        self.assertEqual(
            "CHECK_002", app._display_f3_first_green_visual_hold["check_id"]
        )
        self.assertTrue(
            app._display_f3_first_green_snapshot_debug["intermittent"]
        )
        self.assertEqual(
            ("MASK_020",),
            app._display_f3_first_green_snapshot_debug["mask_ids"],
        )

    def test_blue_frozen_luminous_snapshot_survives_next_dark_phase_only_in_same_check(self):
        import src.platform.display_f3_object_tracking as tracking

        payload = {
            "frame_token": ("camera", 100),
            "age_ms": 1700.0,
            "context": {"project_name": "DISPLAY A", "check_id": "CHECK_002"},
            "analysis": {
                "ready": True, "tracking_snapshot_explicit": True,
                "project_name": "DISPLAY A", "check_id": "CHECK_002",
                "mask_results": [
                    {"mask_id": "MASK_020", "expected": "on",
                     "classified": "on", "matched": True},
                    {"mask_id": "MASK_024", "expected": "on",
                     "classified": "off", "matched": False},
                ],
            },
        }
        blue = {
            "project_name": "DISPLAY A", "check_id": "CHECK_002",
            "check_name": "BLUE", "intermittent": True,
        }
        self.assertTrue(
            tracking._intermittent_snapshot_acceptable(
                payload, blue, ("camera", 155)
            )
        )
        # A fase ON fotografada ainda deve passar ao julgamento do BLUE.
        # Nem a fase OFF atual nem uma foto de outro CHECK ganham autoridade.
        self.assertFalse(
            tracking._intermittent_snapshot_acceptable(
                payload, {**blue, "check_id": "CHECK_004"}, ("camera", 155)
            )
        )
        self.assertFalse(
            tracking._intermittent_snapshot_acceptable(
                payload, {**blue, "intermittent": False}, ("camera", 155)
            )
        )
        self.assertFalse(
            tracking._intermittent_snapshot_acceptable(
                {**payload, "age_ms": 2600.0}, blue, ("camera", 155)
            )
        )
        self.assertFalse(
            tracking._intermittent_snapshot_acceptable(
                payload, blue, ("camera", 225)
            )
        )

    def test_tracking_worker_first_green_paints_snapshot_before_visual_hold(self):
        import src.platform.display_f3_object_tracking as tracking

        raw = np.full((64, 100, 3), 42, dtype=np.uint8)
        geometry = {
            "locked": True, "check_id": "CHECK_001",
            "masks": [{"id": "MASK_008", "type": "circle",
                       "cx": 50, "cy": 30, "radius": 6}],
        }
        earlier_geometry = {"locked": True, "old": True}
        render = []

        def display(image, visual_rotation=0):
            render.append((
                image, visual_rotation, app._display_f3_tracking_live_geometry
            ))
            return True

        app = SimpleNamespace(
            display_f3_window=SimpleNamespace(update_camera_preview=display),
            _display_f3_tracking_live_geometry=earlier_geometry,
            _display_auto_current_context=lambda: {
                "project_name": "DISPLAY A", "check_id": "CHECK_001",
            },
            _obter_rotacao_visual_display_f3=lambda: 180,
        )
        payload = {
            "raw_frame": raw, "geometry": geometry,
            "frame_token": ("camera", 71),
            "snapshot_capture_trigger": {
                "triggered": True,
                "mask_ids": ("MASK_008",),
                "source": "tracked_same_frame_live_green",
            },
        }
        future = SimpleNamespace(done=lambda: False)
        with patch.object(tracking.time, "perf_counter", return_value=50.0):
            self.assertTrue(
                tracking._show_worker_green_snapshot_during_analysis(
                    app, payload, future
                )
            )
        self.assertEqual(1, len(render))
        self.assertIs(render[0][0], raw)
        self.assertEqual(180, render[0][1])
        self.assertIs(render[0][2], geometry)
        self.assertIs(
            earlier_geometry, app._display_f3_tracking_live_geometry
        )
        self.assertEqual(
            ("camera", 71),
            app._display_f3_first_green_visual_hold["frame_token"],
        )
        self.assertTrue(
            app._display_f3_first_green_snapshot_debug["visual_hold_applied"]
        )
        self.assertEqual(
            "tracking_worker_same_frame_green_to_semantic",
            app._display_f3_first_green_snapshot_debug["capture_path"],
        )

    def test_tracking_worker_dark_or_unaligned_never_starts_visual_hold(self):
        import src.platform.display_f3_object_tracking as tracking

        raw = np.zeros((32, 48, 3), dtype=np.uint8)
        window = SimpleNamespace(update_camera_preview=Mock(return_value=True))
        app = SimpleNamespace(
            display_f3_window=window,
            _display_auto_current_context=lambda: {
                "project_name": "DISPLAY A", "check_id": "CHECK_001",
            },
        )
        future = SimpleNamespace(done=lambda: False)
        payload = {
            "raw_frame": raw,
            "frame_token": ("camera", 77),
            "geometry": {
                "locked": False,
                "check_id": "CHECK_001",
                "masks": [{"id": "MASK_008"}],
            },
            "snapshot_capture_trigger": {"triggered": True},
        }
        self.assertFalse(
            tracking._show_worker_green_snapshot_during_analysis(
                app, payload, future
            )
        )
        payload["geometry"]["locked"] = True
        payload["snapshot_capture_trigger"]["triggered"] = False
        self.assertFalse(
            tracking._show_worker_green_snapshot_during_analysis(
                app, payload, future
            )
        )
        window.update_camera_preview.assert_not_called()
        self.assertIsNone(
            getattr(app, "_display_f3_first_green_visual_hold", None)
        )

    def test_preview_first_green_fast_handoff_uses_same_visual_frame(self):
        import src.platform.display_f3_object_tracking as tracking

        raw = np.zeros((96, 160, 3), dtype=np.uint8)
        geometry = {
            "locked": True, "check_id": "CHECK_001",
            "alignment_required": True, "spatial_alignment_ready": True,
            "resolution": (160, 96),
            "masks": [
                {"id": "MASK_001", "type": "circle",
                 "cx": 42, "cy": 48, "radius": 10},
            ],
        }
        token = ("camera", 110)
        captured = {}
        now = tracking.time.perf_counter()
        cache = {
            "key": (
                repr(token), "DISPLAY A", "CHECK_001",
                repr(("tracked", id(geometry))), raw.shape,
            ),
            "value": {"ready": True, "mask_ids": ("MASK_001",)},
        }
        window = SimpleNamespace(
            _display_last_overlay_context={
                "tracking_active": True, "tracking_locked": True,
                "project_name": "DISPLAY A",
                "check_id": "CHECK_001",
                "live_visual_sample_ready": True,
                "live_visual_frame_token": token,
            },
            _display_f3_live_visual_sample_cache=cache,
        )
        app = SimpleNamespace(
            _display_f3_tracking_live_geometry=geometry,
            _display_f3_tracking_last_verified_pose_s=now,
            _display_f3_tracking_last_verified_pose_frame_token=("camera", 109),
            _display_f3_semantic_future=None,
            display_f3_window=window,
            _display_auto_current_context=lambda: {
                "project_name": "DISPLAY A",
                "check_id": "CHECK_001",
            },
            _display_auto_frame_token=lambda _frame: token,
        )

        def capture(_app, image, payload):
            captured["image"] = image
            captured["payload"] = payload
            return object()

        with patch.object(tracking, "_submit_live_semantic_job",
                          side_effect=capture) as submit:
            self.assertTrue(
                tracking._submit_first_green_from_preview(app, raw)
            )
            submit.assert_called_once()
        self.assertIsNot(raw, captured["image"])
        self.assertTrue(np.array_equal(raw, captured["image"]))
        self.assertEqual(token, captured["payload"]["frame_token"])
        self.assertEqual(geometry, captured["payload"]["geometry"])
        self.assertEqual(
            "same_preview_first_green_snapshot",
            captured["payload"]["snapshot_capture_trigger"]["source"],
        )

    def test_preview_fast_handoff_rejects_stale_pose_and_dark_or_other_check(self):
        import src.platform.display_f3_object_tracking as tracking

        raw = np.zeros((96, 160, 3), dtype=np.uint8)
        geometry = {
            "locked": True,
            "check_id": "CHECK_001",
            "masks": [{"id": "MASK_001"}],
        }
        token = ("camera", 110)
        window = SimpleNamespace(
            _display_last_overlay_context={
                "tracking_active": True,
                "tracking_locked": True,
                "live_visual_sample_ready": True,
                "live_visual_frame_token": token,
                "project_name": "DISPLAY A",
                "check_id": "CHECK_001",
            },
            _display_f3_live_visual_sample_cache={
                "key": (
                    repr(token), "DISPLAY A", "CHECK_001",
                    repr(("tracked", id(geometry))), raw.shape,
                ),
                "value": {"ready": True, "mask_ids": ("MASK_001",)},
            },
        )
        app = SimpleNamespace(
            _display_f3_tracking_live_geometry=geometry,
            _display_f3_tracking_last_verified_pose_s=(
                tracking.time.perf_counter() - 3.0
            ),
            _display_f3_tracking_last_verified_pose_frame_token=("camera", 109),
            _display_f3_semantic_future=None,
            display_f3_window=window,
            _display_auto_current_context=lambda: {
                "project_name": "DISPLAY A",
                "check_id": "CHECK_001",
            },
            _display_auto_frame_token=lambda _frame: token,
        )
        with patch.object(tracking, "_submit_live_semantic_job") as submit:
            self.assertFalse(
                tracking._submit_first_green_from_preview(app, raw)
            )
            app._display_f3_tracking_last_verified_pose_s = (
                tracking.time.perf_counter()
            )
            window._display_f3_live_visual_sample_cache["value"] = {
                "ready": True, "mask_ids": (),
            }
            self.assertFalse(
                tracking._submit_first_green_from_preview(app, raw)
            )
            window._display_f3_live_visual_sample_cache["value"] = {
                "ready": True, "mask_ids": ("MASK_001",),
            }
            geometry["check_id"] = "CHECK_002"
            self.assertFalse(
                tracking._submit_first_green_from_preview(app, raw)
            )
            submit.assert_not_called()

    def test_first_green_capture_uses_same_tracked_raw_and_masks(self):
        import src.platform.display_f3_object_tracking as tracking

        raw = np.zeros((96, 160, 3), dtype=np.uint8)
        raw[35:61, 28:57] = 255
        geometry = {
            "locked": True, "check_id": "CHECK_001",
            "alignment_required": True, "spatial_alignment_ready": True,
            "resolution": (160, 96),
            "masks": [
                {"id": f"MASK_{i:03d}", "type": "circle",
                 "cx": cx, "cy": 48, "radius": 13}
                for i, cx in enumerate((42, 75, 110), start=1)
            ],
        }
        trigger = tracking._f3_first_green_snapshot_trigger(
            raw, geometry
        )
        self.assertTrue(trigger["ready"])
        self.assertTrue(trigger["triggered"])
        self.assertIn("MASK_001", trigger["mask_ids"])

        raw_dark = np.zeros_like(raw)
        no_trigger = tracking._f3_first_green_snapshot_trigger(
            raw_dark, geometry
        )
        self.assertFalse(no_trigger["triggered"])

        no_lock = tracking._f3_first_green_snapshot_trigger(
            raw, {**geometry, "locked": False}
        )
        self.assertFalse(no_lock["triggered"])

        no_align = tracking._f3_first_green_snapshot_trigger(
            raw, {**geometry, "spatial_alignment_ready": False}
        )
        self.assertFalse(no_align["triggered"])

    def test_frozen_green_snapshot_keeps_intermittent_on_phase_temporarily(self):
        import src.platform.display_f3_object_tracking as tracking

        payload = {
            "age_ms": 1400.0,
            "frame_token": ("camera", 200),
            "geometry": {
                "locked": True, "check_id": "CHECK_002",
                "alignment_required": True,
                "spatial_alignment_ready": True,
            },
            "snapshot_capture_trigger": {
                "ready": True, "triggered": True,
                "mask_ids": ("MASK_024",),
            },
        }
        check = {
            "project_name": "DISPLAY A",
            "check_id": "CHECK_002", "intermittent": True,
        }
        self.assertTrue(
            tracking._intermittent_snapshot_acceptable(
                payload, check, ("camera", 238)
            )
        )
        self.assertFalse(
            tracking._intermittent_snapshot_acceptable(
                payload, {**check, "check_id": "CHECK_001"},
                ("camera", 238),
            )
        )
        self.assertFalse(
            tracking._intermittent_snapshot_acceptable(
                payload, {**check, "intermittent": False},
                ("camera", 238),
            )
        )
        self.assertFalse(
            tracking._intermittent_snapshot_acceptable(
                {**payload, "age_ms": 2600.0},
                check, ("camera", 238),
            )
        )

    def test_first_green_snapshot_pipeline_is_tracking_opt_in_and_one_shot(self):
        import src.platform.display_f3_object_tracking as tracking

        submit_code = inspect.getsource(
            tracking.instalar_autoridade_final_instancia_rastreamento_f3
        )
        worker_code = inspect.getsource(
            tracking._run_live_tracking_heavy_job
        )
        semantic_code = inspect.getsource(
            tracking._run_live_semantic_job
        )
        auto_code = inspect.getsource(
            DisplayAutomaticCheckF3Mixin._process_display_auto_check
        )
        self.assertIn("_f3_first_green_snapshot_trigger(", worker_code)
        self.assertIn('"snapshot_capture_trigger": snapshot_capture_trigger', worker_code)
        self.assertIn('capture_trigger.get("triggered")', submit_code)
        self.assertIn("_submit_live_semantic_job(", submit_code)
        self.assertIn("and semantic_future is None", submit_code)
        self.assertIn('"raw_frame": raw_frame', semantic_code)
        self.assertIn("frozen_tracking_capture", auto_code)
        self.assertIn("and not frozen_tracking_capture", auto_code)
        self.assertIn("return previous_preview()", submit_code)
        self.assertIn("if use_tracking and _valid_frame(raw_latest)", submit_code)

    def test_first_green_trigger_held_lock_cannot_invent_capture(self):
        import src.platform.display_f3_object_tracking as tracking

        raw = np.ones((60, 100, 3), dtype=np.uint8) * 255
        result = SimpleNamespace(
            evidence_current=False,
            source_type="luminous_segment_grid",
            luminous_validated_mask_ids=("MASK_001",),
        )
        self.assertFalse(
            tracking._f3_first_green_snapshot_trigger(
                raw, None, result
            )["triggered"]
        )

    def test_tracking_h1_mask_020_real_near_on_overrides_coinflip_off(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, h1, _ = _repository(Path(temp))
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(return_value=_ready_model_status())
            inference = _inference(["off", "off"])
            inference["observations"][0]["confidence"] = 0.504946
            inference["observations"][0]["probabilities"] = {
                "off": 0.504946, "on": 0.495054
            }
            analyzer.neural_detector.predict = Mock(return_value=inference)
            physical = _physical_analysis(["on", "off"], confidence=0.9854)
            physical["mask_results"][0]["reference_separation"] = 0.9907
            physical["mask_results"][0]["core_emission_evidence"] = {
                "state": "uncertain",
                "reason": "same_mask_physical_core_ranges",
                "current_inner_v_mean": 251.0197,
                "off_reference_ceiling": 17.2862,
                "on_reference_floor": 252.1907,
                "reference_on_count": 5,
                "reference_off_count": 1,
            }
            with patch.object(F3SameMaskReferenceAnalyzer, "analyze",
                              return_value=physical):
                result = analyzer.analyze(
                    _frame(), "DISPLAY A", h1["id"],
                    mask_geometry_override=[
                        {"id": "MASK_001", "type": "circle",
                         "cx": 42, "cy": 48, "radius": 9},
                        {"id": "MASK_002", "type": "circle",
                         "cx": 118, "cy": 48, "radius": 9},
                    ],
                    mask_geometry_resolution=(160, 96),
                )
            self.assertTrue(result["approved"])
            row = result["mask_results"][0]
            self.assertEqual("on", row["classified"])
            self.assertTrue(row["calibrated_near_on_core_over_weak_neural"])
            self.assertEqual("near_on_core_resolved_weak_neural",
                             row["hybrid_resolution"])

    def test_near_on_core_does_not_allow_unexpected_on_as_ok(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, _h1, blue = _repository(Path(temp))
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(return_value=_ready_model_status())
            inference = _inference(["off", "on"])
            inference["observations"][0]["confidence"] = 0.504946
            inference["observations"][0]["probabilities"] = {
                "off": 0.504946, "on": 0.495054
            }
            analyzer.neural_detector.predict = Mock(return_value=inference)
            physical = _physical_analysis(["on", "on"], confidence=0.9854)
            physical["mask_results"][0]["reference_separation"] = 0.9907
            physical["mask_results"][0]["core_emission_evidence"] = {
                "state": "uncertain",
                "reason": "same_mask_physical_core_ranges",
                "current_inner_v_mean": 251.0197,
                "off_reference_ceiling": 17.2862,
                "on_reference_floor": 252.1907,
                "reference_on_count": 5, "reference_off_count": 1,
            }
            with patch.object(F3SameMaskReferenceAnalyzer, "analyze",
                              return_value=physical):
                result = analyzer.analyze(
                    _frame(), "DISPLAY A", blue["id"],
                    mask_geometry_override=[
                        {"id": "MASK_001", "type": "circle",
                         "cx": 42, "cy": 48, "radius": 9},
                        {"id": "MASK_002", "type": "circle",
                         "cx": 118, "cy": 48, "radius": 9},
                    ],
                    mask_geometry_resolution=(160, 96),
                )
            self.assertFalse(result["approved"])
            first = result["mask_results"][0]
            self.assertEqual("on", first["classified"])
            self.assertFalse(first["matched"])
            self.assertEqual("ng",
                             decidir_analise_display_f3(
                                 result, reference_gate=False
                             )["decision"])

    def test_near_on_core_requires_bright_edge_and_not_strong_cnn_off(self):
        for core_value, cnn_off in ((150.0, 0.504946),
                                    (251.0197, 0.97)):
            with self.subTest(core_value=core_value, cnn_off=cnn_off):
                with tempfile.TemporaryDirectory() as temp:
                    repository, h1, _ = _repository(Path(temp))
                    analyzer = F3HybridCheckAnalyzer(repository)
                    analyzer.neural_detector.prepare = Mock(
                        return_value=_ready_model_status()
                    )
                    inference = _inference(["off", "off"])
                    inference["observations"][0]["confidence"] = cnn_off
                    inference["observations"][0]["probabilities"] = {
                        "off": cnn_off, "on": 1.0 - cnn_off
                    }
                    analyzer.neural_detector.predict = Mock(return_value=inference)
                    physical = _physical_analysis(["on", "off"], confidence=0.9854)
                    physical["mask_results"][0]["core_emission_evidence"] = {
                        "state": "uncertain",
                        "reason": "same_mask_physical_core_ranges",
                        "current_inner_v_mean": core_value,
                        "off_reference_ceiling": 17.2862,
                        "on_reference_floor": 252.1907,
                        "reference_on_count": 5, "reference_off_count": 1,
                    }
                    with patch.object(F3SameMaskReferenceAnalyzer, "analyze",
                                      return_value=physical):
                        result = analyzer.analyze(
                            _frame(), "DISPLAY A", h1["id"],
                            mask_geometry_override=[
                                {"id": "MASK_001", "type": "circle",
                                 "cx": 42, "cy": 48, "radius": 9},
                                {"id": "MASK_002", "type": "circle",
                                 "cx": 118, "cy": 48, "radius": 9},
                            ],
                            mask_geometry_resolution=(160, 96),
                        )
                    self.assertFalse(result["approved"])
                    self.assertEqual(
                        "uncertain", result["mask_results"][0]["classified"]
                    )
                    self.assertFalse(
                        result["mask_results"][0][
                            "calibrated_near_on_core_over_weak_neural"
                        ]
                    )

    def test_near_on_core_without_pair_or_tracking_off_stays_uncertain(self):
        for tracking, ref_off_count in ((True, 0), (False, 1)):
            with self.subTest(tracking=tracking, ref_off_count=ref_off_count):
                with tempfile.TemporaryDirectory() as temp:
                    repository, h1, _ = _repository(Path(temp))
                    analyzer = F3HybridCheckAnalyzer(repository)
                    analyzer.neural_detector.prepare = Mock(
                        return_value=_ready_model_status()
                    )
                    inference = _inference(["off", "off"])
                    inference["observations"][0]["confidence"] = 0.504946
                    inference["observations"][0]["probabilities"] = {
                        "off": 0.504946, "on": 0.495054
                    }
                    analyzer.neural_detector.predict = Mock(return_value=inference)
                    physical = _physical_analysis(["on", "off"], confidence=0.9854)
                    physical["mask_results"][0]["core_emission_evidence"] = {
                        "state": "uncertain",
                        "reason": "same_mask_physical_core_ranges",
                        "current_inner_v_mean": 251.0197,
                        "off_reference_ceiling": 17.2862,
                        "on_reference_floor": 252.1907,
                        "reference_on_count": 5,
                        "reference_off_count": ref_off_count,
                    }
                    with patch.object(F3SameMaskReferenceAnalyzer, "analyze",
                                      return_value=physical):
                        extra = (
                            {
                                "mask_geometry_override": [
                                    {"id": "MASK_001", "type": "circle",
                                     "cx": 42, "cy": 48, "radius": 9},
                                    {"id": "MASK_002", "type": "circle",
                                     "cx": 118, "cy": 48, "radius": 9},
                                ],
                                "mask_geometry_resolution": (160, 96),
                            }
                            if tracking else {}
                        )
                        result = analyzer.analyze(
                            _frame(), "DISPLAY A", h1["id"], **extra
                        )
                    self.assertFalse(result["approved"])
                    self.assertFalse(result["mask_results"][0][
                        "calibrated_near_on_core_over_weak_neural"
                    ])

    def test_tracking_core_emission_resolves_false_physical_on_as_h1_off(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, h1, _blue = _repository(Path(temp))
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(
                return_value=_ready_model_status()
            )
            # A primeira máscara H1 é ON e a segunda é OFF.
            analyzer.neural_detector.predict = Mock(
                return_value=_inference(["on", "off"])
            )
            physical = _physical_analysis(["on", "on"])
            physical["mask_results"][1]["core_emission_evidence"] = {
                "state": "off",
                "reason": "same_mask_physical_core_ranges",
                "current_inner_v_mean": 14.0,
                "off_reference_ceiling": 20.0,
                "on_reference_floor": 180.0,
            }
            with patch.object(
                F3SameMaskReferenceAnalyzer,
                "analyze",
                return_value=physical,
            ):
                result = analyzer.analyze(
                    _frame(), "DISPLAY A", h1["id"],
                    mask_geometry_override=[
                        {"id": "MASK_001", "type": "circle", "cx": 42, "cy": 48, "radius": 9},
                        {"id": "MASK_002", "type": "circle", "cx": 118, "cy": 48, "radius": 9},
                    ],
                    mask_geometry_resolution=(160, 96),
                )
            mask = result["mask_results"][1]
            self.assertTrue(result["approved"])
            self.assertEqual("off", mask["classified"])
            self.assertTrue(mask["matched"])
            self.assertTrue(mask["physical_disagreed_with_core"])
            self.assertEqual(
                "neural_confirmed_by_same_mask_core",
                mask["hybrid_resolution"],
            )

    def test_tracking_core_emission_preserves_ng_for_real_off_segment(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, _h1, blue = _repository(Path(temp))
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(
                return_value=_ready_model_status()
            )
            analyzer.neural_detector.predict = Mock(
                return_value=_inference(["off", "off"])
            )
            physical = _physical_analysis(["off", "on"])
            physical["mask_results"][1]["core_emission_evidence"] = {
                "state": "off",
                "off_reference_ceiling": 18.0,
                "on_reference_floor": 190.0,
            }
            with patch.object(
                F3SameMaskReferenceAnalyzer, "analyze",
                return_value=physical,
            ):
                result = analyzer.analyze(
                    _frame(), "DISPLAY A", blue["id"],
                    mask_geometry_override=[
                        {"id": "MASK_001", "type": "circle", "cx": 42, "cy": 48, "radius": 9},
                        {"id": "MASK_002", "type": "circle", "cx": 118, "cy": 48, "radius": 9},
                    ],
                    mask_geometry_resolution=(160, 96),
                )
            self.assertFalse(result["approved"])
            self.assertTrue(result["mask_results"][1]["semantic_certain"])
            self.assertEqual("off", result["mask_results"][1]["classified"])
            self.assertFalse(result["mask_results"][1]["matched"])

    def test_tracking_core_emission_detects_unexpected_on_as_ng(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, h1, _blue = _repository(Path(temp))
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(
                return_value=_ready_model_status()
            )
            # H1 espera OFF na segunda máscara; emissão ON real é defeito.
            analyzer.neural_detector.predict = Mock(
                return_value=_inference(["on", "on"])
            )
            physical = _physical_analysis(["on", "off"])
            physical["mask_results"][1]["core_emission_evidence"] = {
                "state": "on",
                "off_reference_ceiling": 20.0,
                "on_reference_floor": 180.0,
            }
            with patch.object(
                F3SameMaskReferenceAnalyzer, "analyze",
                return_value=physical,
            ):
                result = analyzer.analyze(
                    _frame(), "DISPLAY A", h1["id"],
                    mask_geometry_override=[
                        {"id": "MASK_001", "type": "circle", "cx": 42, "cy": 48, "radius": 9},
                        {"id": "MASK_002", "type": "circle", "cx": 118, "cy": 48, "radius": 9},
                    ],
                    mask_geometry_resolution=(160, 96),
                )
            self.assertFalse(result["approved"])
            mask = result["mask_results"][1]
            self.assertEqual("on", mask["classified"])
            self.assertTrue(mask["semantic_certain"])
            self.assertFalse(mask["matched"])
            self.assertTrue(mask["physical_disagreed_with_core"])
            decision = decidir_analise_display_f3(result, reference_gate=False)
            self.assertEqual("ng", decision["decision"])
            self.assertEqual("MASK_002", decision["failed_mask_id"])

    def test_tracking_core_emission_does_not_approve_when_neural_disagrees(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, h1, _blue = _repository(Path(temp))
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(
                return_value=_ready_model_status()
            )
            analyzer.neural_detector.predict = Mock(
                return_value=_inference(["on", "on"])
            )
            physical = _physical_analysis(["on", "on"])
            physical["mask_results"][1]["core_emission_evidence"] = {
                "state": "off",
                "off_reference_ceiling": 18.0,
                "on_reference_floor": 190.0,
            }
            with patch.object(
                F3SameMaskReferenceAnalyzer, "analyze",
                return_value=physical,
            ):
                result = analyzer.analyze(
                    _frame(), "DISPLAY A", h1["id"],
                    mask_geometry_override=[
                        {"id": "MASK_001", "type": "circle", "cx": 42, "cy": 48, "radius": 9},
                        {"id": "MASK_002", "type": "circle", "cx": 118, "cy": 48, "radius": 9},
                    ],
                    mask_geometry_resolution=(160, 96),
                )
            self.assertFalse(result["approved"])
            self.assertEqual("uncertain", result["mask_results"][1]["classified"])
            self.assertFalse(result["mask_results"][1]["semantic_certain"])


    def test_tracking_strong_emission_resolves_weak_certain_neural_off_h1(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, h1, _blue = _repository(Path(temp))
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(return_value=_ready_model_status())
            inference = _inference(["off", "off"])
            # A CNN real etiquetou OFF como certo, mas com P(OFF)=0.606771.
            inference["observations"][0]["confidence"] = 0.606771
            inference["observations"][0]["probabilities"] = {
                "off": 0.606771, "on": 0.393229,
            }
            analyzer.neural_detector.predict = Mock(return_value=inference)
            physical = _physical_analysis(["on", "off"])
            physical["mask_results"][0].update({
                "confidence": 0.9883,
                "reference_separation": 0.9965,
                "core_emission_evidence": {
                    "state": "on",
                    "reason": "same_mask_physical_core_ranges",
                    "current_inner_v_mean": 251.0306,
                    "off_reference_ceiling": 0.0,
                    "on_reference_floor": 106.2529,
                    "reference_on_count": 5,
                    "reference_off_count": 1,
                },
            })
            with patch.object(
                F3SameMaskReferenceAnalyzer, "analyze", return_value=physical
            ):
                result = analyzer.analyze(
                    _frame(), "DISPLAY A", h1["id"],
                    mask_geometry_override=[
                        {"id": "MASK_001", "type": "circle", "cx": 42, "cy": 48, "radius": 9},
                        {"id": "MASK_002", "type": "circle", "cx": 118, "cy": 48, "radius": 9},
                    ],
                    mask_geometry_resolution=(160, 96),
                )
            row = result["mask_results"][0]
            self.assertTrue(result["approved"])
            self.assertTrue(row["semantic_certain"])
            self.assertEqual("on", row["classified"])
            self.assertTrue(row["matched"])
            self.assertEqual(
                "calibrated_core_resolved_weak_neural", row["hybrid_resolution"]
            )
            self.assertTrue(row["calibrated_physical_over_weak_neural"])
            self.assertEqual("off", row["neural_classified"])
            self.assertAlmostEqual(0.606771, row["neural_confidence"])

    def test_tracking_real_unexpected_on_with_weak_cnn_still_emits_ng(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, h1, _blue = _repository(Path(temp))
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(return_value=_ready_model_status())
            inference = _inference(["on", "off"])
            inference["observations"][1]["confidence"] = 0.606771
            analyzer.neural_detector.predict = Mock(return_value=inference)
            physical = _physical_analysis(["on", "on"])
            physical["mask_results"][1].update({
                "confidence": 0.9883,
                "core_emission_evidence": {
                    "state": "on",
                    "reason": "same_mask_physical_core_ranges",
                    "current_inner_v_mean": 251.0,
                    "off_reference_ceiling": 0.0,
                    "on_reference_floor": 106.0,
                    "reference_on_count": 5,
                    "reference_off_count": 1,
                },
            })
            with patch.object(
                F3SameMaskReferenceAnalyzer, "analyze", return_value=physical
            ):
                result = analyzer.analyze(
                    _frame(), "DISPLAY A", h1["id"],
                    mask_geometry_override=[
                        {"id": "MASK_001", "type": "circle", "cx": 42, "cy": 48, "radius": 9},
                        {"id": "MASK_002", "type": "circle", "cx": 118, "cy": 48, "radius": 9},
                    ],
                    mask_geometry_resolution=(160, 96),
                )
            self.assertFalse(result["approved"])
            row = result["mask_results"][1]
            self.assertTrue(row["semantic_certain"])
            self.assertEqual("on", row["classified"])
            self.assertFalse(row["matched"])
            self.assertEqual("calibrated_core_resolved_weak_neural",
                             row["hybrid_resolution"])
            decision = decidir_analise_display_f3(result, reference_gate=False)
            self.assertEqual("ng", decision["decision"])
            self.assertEqual("MASK_002", decision["failed_mask_id"])

    def test_tracking_core_resolves_false_low_light_with_local_pair(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, h1, _blue = _repository(Path(temp))
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(return_value=_ready_model_status())
            analyzer.neural_detector.predict = Mock(
                return_value=_inference(["uncertain", "off"])
            )
            physical = _physical_analysis(["low_light", "off"])
            physical["mask_results"][0]["core_emission_evidence"] = {
                "state": "on", "reason": "same_mask_physical_core_ranges",
                "current_inner_v_mean": 252.0,
                "off_reference_ceiling": 45.0,
                "on_reference_floor": 220.0,
                "reference_on_count": 5, "reference_off_count": 1,
            }
            with patch.object(F3SameMaskReferenceAnalyzer, "analyze",
                              return_value=physical):
                result = analyzer.analyze(
                    _frame(), "DISPLAY A", h1["id"],
                    mask_geometry_override=[
                        {"id": "MASK_001", "type": "circle",
                         "cx": 42, "cy": 48, "radius": 9},
                        {"id": "MASK_002", "type": "circle",
                         "cx": 118, "cy": 48, "radius": 9},
                    ],
                    mask_geometry_resolution=(160, 96),
                )
            self.assertTrue(result["approved"])
            mask = result["mask_results"][0]
            self.assertTrue(mask["calibrated_core_over_low_light"])
            self.assertEqual("on", mask["classified"])
            self.assertEqual("same_mask_core_resolved_low_light",
                             mask["hybrid_resolution"])

    def test_tracking_core_low_light_off_waits_for_power_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, _h1, blue = _repository(Path(temp))
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(return_value=_ready_model_status())
            analyzer.neural_detector.predict = Mock(
                return_value=_inference(["off", "uncertain"])
            )
            physical = _physical_analysis(["off", "low_light"])
            physical["mask_results"][1]["core_emission_evidence"] = {
                "state": "off", "reason": "same_mask_physical_core_ranges",
                "current_inner_v_mean": 15.0,
                "off_reference_ceiling": 45.0,
                "on_reference_floor": 220.0,
                "reference_on_count": 3, "reference_off_count": 2,
            }
            with patch.object(F3SameMaskReferenceAnalyzer, "analyze",
                              return_value=physical):
                result = analyzer.analyze(
                    _frame(), "DISPLAY A", blue["id"],
                    mask_geometry_override=[
                        {"id": "MASK_001", "type": "circle",
                         "cx": 42, "cy": 48, "radius": 9},
                        {"id": "MASK_002", "type": "circle",
                         "cx": 118, "cy": 48, "radius": 9},
                    ],
                    mask_geometry_resolution=(160, 96),
                )
            self.assertFalse(result["approved"])
            mask = result["mask_results"][1]
            self.assertTrue(mask["semantic_certain"])
            self.assertEqual("off", mask["classified"])
            self.assertFalse(mask["matched"])
            # A leitura OFF da MASK_002 é conclusiva, mas nenhuma outra
            # máscara desse fixture BLUE está ON; por segurança, NG terminal
            # aguarda evidência de placa alimentada no MESMO frame.
            decision = decidir_analise_display_f3(result, reference_gate=False)
            self.assertEqual("searching", decision["decision"])
            self.assertEqual("aguardando_evidencia_placa_ligada",
                             decision["reason"])
            self.assertEqual(["MASK_002"], decision["failed_mask_ids"])

    def test_tracking_core_low_light_no_complete_pair_cannot_resolve(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, h1, _blue = _repository(Path(temp))
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(return_value=_ready_model_status())
            analyzer.neural_detector.predict = Mock(
                return_value=_inference(["uncertain", "off"])
            )
            physical = _physical_analysis(["low_light", "off"])
            physical["mask_results"][0]["core_emission_evidence"] = {
                "state": "unavailable", "reason": "local_pair_incomplete",
                "reference_on_count": 5, "reference_off_count": 0,
            }
            with patch.object(F3SameMaskReferenceAnalyzer, "analyze",
                              return_value=physical):
                result = analyzer.analyze(
                    _frame(), "DISPLAY A", h1["id"],
                    mask_geometry_override=[
                        {"id": "MASK_001", "type": "circle",
                         "cx": 42, "cy": 48, "radius": 9},
                        {"id": "MASK_002", "type": "circle",
                         "cx": 118, "cy": 48, "radius": 9},
                    ],
                    mask_geometry_resolution=(160, 96),
                )
            self.assertFalse(result["approved"])
            self.assertFalse(result["mask_results"][0]["calibrated_core_over_low_light"])
            self.assertEqual("low_light", result["mask_results"][0]["classified"])

    def test_tracking_core_low_light_strong_neural_opposition_stays_low_light(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, h1, _blue = _repository(Path(temp))
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(return_value=_ready_model_status())
            analyzer.neural_detector.predict = Mock(
                return_value=_inference(["off", "off"])
            )
            physical = _physical_analysis(["low_light", "off"])
            physical["mask_results"][0]["core_emission_evidence"] = {
                "state": "on", "reason": "same_mask_physical_core_ranges",
                "reference_on_count": 5, "reference_off_count": 1,
            }
            with patch.object(F3SameMaskReferenceAnalyzer, "analyze",
                              return_value=physical):
                result = analyzer.analyze(
                    _frame(), "DISPLAY A", h1["id"],
                    mask_geometry_override=[
                        {"id": "MASK_001", "type": "circle",
                         "cx": 42, "cy": 48, "radius": 9},
                        {"id": "MASK_002", "type": "circle",
                         "cx": 118, "cy": 48, "radius": 9},
                    ],
                    mask_geometry_resolution=(160, 96),
                )
            self.assertFalse(result["approved"])
            self.assertFalse(result["mask_results"][0]["calibrated_core_over_low_light"])
            self.assertTrue(result["mask_results"][0]["strong_low_light_core_conflict"])
            self.assertEqual("uncertain", result["mask_results"][0]["classified"])
            self.assertEqual("strong_neural_core_low_light_conflict",
                             result["mask_results"][0]["hybrid_resolution"])

    def test_tracking_off_low_light_cannot_use_new_core_resolution(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, h1, _blue = _repository(Path(temp))
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(return_value=_ready_model_status())
            analyzer.neural_detector.predict = Mock(
                return_value=_inference(["uncertain", "off"])
            )
            physical = _physical_analysis(["low_light", "off"])
            physical["mask_results"][0]["core_emission_evidence"] = {
                "state": "on", "reason": "same_mask_physical_core_ranges",
                "reference_on_count": 5, "reference_off_count": 1,
            }
            with patch.object(F3SameMaskReferenceAnalyzer, "analyze",
                              return_value=physical):
                result = analyzer.analyze(_frame(), "DISPLAY A", h1["id"])
            self.assertFalse(result["approved"])
            self.assertFalse(result["mask_results"][0]["calibrated_core_over_low_light"])
            self.assertEqual("physical_low_light", result["mask_results"][0]["hybrid_resolution"])

    def test_tracking_strong_neural_conflict_stays_uncertain_even_with_core(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, h1, _blue = _repository(Path(temp))
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(return_value=_ready_model_status())
            inference = _inference(["off", "off"])  # OFF com 97%, não fraco.
            analyzer.neural_detector.predict = Mock(return_value=inference)
            physical = _physical_analysis(["on", "off"])
            physical["mask_results"][0]["core_emission_evidence"] = {
                "state": "on",
                "reason": "same_mask_physical_core_ranges",
                "current_inner_v_mean": 251.0,
                "off_reference_ceiling": 0.0,
                "on_reference_floor": 106.0,
                "reference_on_count": 5,
                "reference_off_count": 1,
            }
            with patch.object(
                F3SameMaskReferenceAnalyzer, "analyze", return_value=physical
            ):
                result = analyzer.analyze(
                    _frame(), "DISPLAY A", h1["id"],
                    mask_geometry_override=[
                        {"id": "MASK_001", "type": "circle", "cx": 42, "cy": 48, "radius": 9},
                        {"id": "MASK_002", "type": "circle", "cx": 118, "cy": 48, "radius": 9},
                    ],
                    mask_geometry_resolution=(160, 96),
                )
            row = result["mask_results"][0]
            self.assertFalse(result["approved"])
            self.assertFalse(row["semantic_certain"])
            self.assertEqual("uncertain", row["classified"])
            self.assertEqual("strong_source_conflict", row["hybrid_resolution"])

    def test_tracking_without_calibrated_core_keeps_conflict_uncertain(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, h1, _blue = _repository(Path(temp))
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(return_value=_ready_model_status())
            inference = _inference(["off", "off"])
            inference["observations"][0]["confidence"] = 0.606771
            analyzer.neural_detector.predict = Mock(return_value=inference)
            physical = _physical_analysis(["on", "off"])
            # Sem par local calibrado: a fonte física não pode desempatar.
            with patch.object(
                F3SameMaskReferenceAnalyzer, "analyze", return_value=physical
            ):
                result = analyzer.analyze(
                    _frame(), "DISPLAY A", h1["id"],
                    mask_geometry_override=[
                        {"id": "MASK_001", "type": "circle", "cx": 42, "cy": 48, "radius": 9},
                        {"id": "MASK_002", "type": "circle", "cx": 118, "cy": 48, "radius": 9},
                    ],
                    mask_geometry_resolution=(160, 96),
                )
            self.assertEqual(
                "strong_source_conflict", result["mask_results"][0]["hybrid_resolution"]
            )
            self.assertFalse(result["approved"])

    def test_strong_neural_physical_conflict_becomes_uncertain_not_ok_or_ng(self):
        with tempfile.TemporaryDirectory() as temp:
            repository, h1, _blue = _repository(Path(temp))
            analyzer = F3HybridCheckAnalyzer(repository)
            analyzer.neural_detector.prepare = Mock(
                return_value=_ready_model_status()
            )
            analyzer.neural_detector.predict = Mock(
                return_value=_inference(["on", "off"])
            )
            with patch.object(
                F3SameMaskReferenceAnalyzer,
                "analyze",
                return_value=_physical_analysis(["off", "off"]),
            ):
                result = analyzer.analyze(
                    _frame(),
                    "DISPLAY A",
                    h1["id"],
                )

            conflict = result["mask_results"][0]
            self.assertEqual("uncertain", conflict["classified"])
            self.assertFalse(conflict["semantic_certain"])
            self.assertIsNone(conflict["matched"])
            self.assertEqual(
                "strong_source_conflict",
                conflict["hybrid_resolution"],
            )
            self.assertFalse(result["approved"])

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
            "h1_hibrido_divergencia_confirmada",
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
            "classificacao_hibrida_incerta",
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
            "check_hibrido_divergencia_confirmada",
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
            "classificacao_hibrida_incerta",
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
                F3HybridCheckAnalyzer,
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
            "hybrid_check_owns_check_decision",
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

    def test_no_lock_board_off_requires_three_physical_observations_not_check(self):
        import src.platform.display_f3_runtime_authorities as physical

        app = SimpleNamespace(
            _display_f3_physical_pending_key="",
            _display_f3_physical_pending_frames=0,
        )
        authority = physical.F3RuntimeAuthorities.__new__(
            physical.F3RuntimeAuthorities
        )
        authority.app = app
        authority.repository = object()
        authority._matcher = object()
        authority._stable_key = ""
        authority._stable_state = None
        authority._pending_key = ""
        authority._pending_frames = 0

        raw_off = {
            "kind": "off",
            "physical_state_key": "off",
            "board_references_complete": True,
        }
        with patch.object(
            physical.transition_module,
            "classificar_estado_fisico_referencias_f3",
            return_value=raw_off,
        ):
            observations = [
                authority.observe_unlocked_support(_frame(), "CM_500_L")
                for _ in range(3)
            ]
        self.assertEqual(["unknown", "unknown", "off"],
                         [state["kind"] for state in observations])
        self.assertIn("CONFIRMANDO", observations[0]["text"])
        self.assertIn("DESLIGADA", observations[-1]["text"])
        self.assertTrue(all(not state["allow_auto"] for state in observations))

    def test_unlocked_camera_and_readout_share_no_live_evidence(self):
        import src.platform.display_f3_object_tracking as tracking

        worker = inspect.getsource(tracking._run_live_tracking_heavy_job)
        installer = inspect.getsource(
            tracking.instalar_autoridade_final_instancia_rastreamento_f3
        )
        self.assertIn("owner, \"observe_unlocked_support\"", worker)
        self.assertIn('"unlocked_support_state": unlocked_support_state', worker)
        self.assertIn('payload.get("unlocked_support_state")', installer)
        self.assertIn("operational_fresh", installer)
        self.assertIn("window.set_operational_reference_status(", installer)
        self.assertIn("self_window._display_last_overlay_context = None", installer)
        self.assertIn("self_window.suspend_display_readout_live_evidence()", installer)

    def test_bootstrap_installs_neural_authority_after_conventional_layers(self):
        source = inspect.getsource(
            DesktopProductionApp.__init__
        )
        neural_position = source.index(
            "instalar_autoridade_hibrida_display_f3()"
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


class DisplayF3H1ConsensusNGTests(unittest.TestCase):
    """Regressões D-092 para H1 real 28/30 sem relaxar OK/NG."""

    @staticmethod
    def _case():
        rows = []
        expected_on = {8, 9, 11, 12, 13, 17, 20}
        missing = {17, 20}
        for number in range(1, 31):
            mask_id = f"MASK_{number:03d}"
            expected = "on" if number in expected_on else "off"
            observed = "off" if number in missing else expected
            row = {
                "mask_id": mask_id,
                "expected": expected,
                "classified": observed,
                "matched": observed == expected,
                "confidence": 0.99,
                "semantic_certain": True,
            }
            if number in missing:
                row.update({
                    "hybrid_resolution": "neural_physical_consensus",
                    "neural_certain": True,
                    "neural_classified": "off",
                    "physical_evidence_available": True,
                    "physical_local_authoritative": True,
                    "physical_classified": "off",
                    "physical_reference_source": "f3_check_photos_same_mask",
                })
            rows.append(row)
        return {
            "ready": True,
            "approved": False,
            "neural_visual_authority": True,
            "tracking_snapshot_explicit": True,
            "effective_uncertain_mask_count": 0,
            "effective_confirmed_failed_mask_ids": ("MASK_017", "MASK_020"),
            "mask_results": rows,
        }

    def test_h1_cnn_e_fisico_concordam_nas_duas_falhas(self):
        from src.platform.display_f3_ng_fast_confirmation import (
            assinatura_ng_h1_consenso,
        )
        case = self._case()
        policy = decidir_analise_display_f3(case, reference_gate=True)
        self.assertEqual("ng", policy["decision"])
        self.assertEqual(
            ("MASK_017", "MASK_020"),
            assinatura_ng_h1_consenso(
                {"intermittent": False},
                case,
                policy,
                reference_gate=True,
                tracking_snapshot=True,
            ),
        )

    def test_h1_transicao_fraca_cnn_incerta_e_blue_nao_tem_atalho(self):
        from copy import deepcopy
        from src.platform.display_f3_ng_fast_confirmation import (
            assinatura_ng_h1_consenso,
        )
        case = self._case()
        policy = decidir_analise_display_f3(case, reference_gate=True)
        def evaluate(candidate, *, reference_gate=True, tracking=True, intermittent=False):
            return assinatura_ng_h1_consenso(
                {"intermittent": intermittent},
                candidate,
                policy,
                reference_gate=reference_gate,
                tracking_snapshot=tracking,
            )
        self.assertEqual((), evaluate(case, tracking=False))
        self.assertEqual((), evaluate(case, reference_gate=False))
        self.assertEqual((), evaluate(case, intermittent=True))
        weak = deepcopy(case)
        for row in weak["mask_results"]:
            if row["expected"] == "on" and row["mask_id"] != "MASK_008":
                row["classified"] = "off"
        self.assertEqual((), evaluate(weak))  # fase parcial do H1
        uncertain = deepcopy(case)
        uncertain["mask_results"][16]["neural_certain"] = False
        self.assertEqual((), evaluate(uncertain))
        contested = deepcopy(case)
        contested["mask_results"][19]["physical_classified"] = "on"
        self.assertEqual((), evaluate(contested))
        stale = deepcopy(case)
        stale["tracking_snapshot_explicit"] = False
        self.assertEqual((), evaluate(stale))
        unsupported = deepcopy(case)
        unsupported["effective_confirmed_failed_mask_ids"] = ("MASK_017",)
        self.assertEqual((), evaluate(unsupported))

    def test_runtime_h1_ng_termina_em_tres_fotos_distintas_sem_repetir(self):
        app = DisplayAutomaticCheckF3Mixin.__new__(DisplayAutomaticCheckF3Mixin)
        app.display_f3_ativo = True
        app.display_f3_result_after_id = None
        app.camera_frame_atual = np.zeros((16, 16, 3), dtype=np.uint8)
        app.camera_ultimo_frame_id = 103
        app._display_f3_tracking_instance_frame_prepared = True
        app._display_auto_analysis_frame_override = None
        app._display_auto_signature = ("DISPLAY A", "CHECK_001")
        app._display_auto_last_decision = None
        app._display_auto_stable_frames = 0
        app._display_auto_last_frame_token = None
        app._display_auto_transition_frames = 0
        app._display_auto_manual_entry_signature = None
        app._display_auto_manual_entry_label = ""
        app._display_auto_h1_fast_ng_signature = None
        app._display_auto_h1_fast_ng_frame_tokens = []
        app._display_auto_configuration_open = lambda: False
        app._display_auto_current_context = lambda: {
            "project_name": "DISPLAY A",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "intermittent": False,
        }
        app._display_auto_is_reference_gate = lambda _context: True
        app._display_auto_is_transient_check = lambda _context: False
        app._display_auto_has_reference_power_evidence = lambda _analysis: True
        app._display_auto_publish_effective_ui_authority = (
            lambda analysis, judgement_ready: analysis
        )
        app._display_auto_publish_segment_signature = (
            lambda _context, analysis: analysis
        )
        app._display_auto_update_intermittent_evidence = (
            lambda _context, _analysis: (True, 0, 0)
        )
        app._display_auto_clear_manual_entry_gate = lambda: None
        statuses = []
        app._display_auto_set_preview_status = (
            lambda text, color: statuses.append(str(text))
        )
        registered = []
        def register(approved):
            registered.append((
                approved,
                app._display_f3_pending_ng_frame_id,
                dict(app._display_f3_pending_ng_runtime or {}),
            ))
            return {"event": "board_ng"}
        app.registrar_resultado_check_display_f3 = register

        analysis = self._case()
        context = app._display_auto_current_context()
        for i, frame_id in enumerate((101, 101, 102, 103)):
            app._display_auto_precomputed_payload = {
                "frame_token": ("camera", frame_id),
                "context": dict(context),
                "analysis": analysis,
                "raw_frame": app.camera_frame_atual.copy(),
                "snapshot_capture_trigger": {
                    "triggered": True,
                    "mask_ids": ("MASK_008",),
                    "source": "tracked_same_frame_live_green",
                },
            }
            app._process_display_auto_check()
            if i < 3:
                self.assertEqual([], registered)
        self.assertEqual(1, len(registered))
        approved, frame, proof = registered[0]
        self.assertIs(approved, False)
        self.assertEqual(103, frame)
        self.assertEqual(3, proof["stable_frames"])
        self.assertEqual(3, proof["required_stable_frames"])
        self.assertEqual(
            ("MASK_017", "MASK_020"), proof["fast_h1_ng_mask_ids"]
        )
        self.assertTrue(proof["fast_h1_ng_consensus"])
        self.assertIn("validando NG • 1/3", statuses[0])
        self.assertIn("validando NG • 1/3", statuses[1])
        self.assertIn("validando NG • 2/3", statuses[2])
        self.assertIn("NG confirmado • 3/3", statuses[3])

    def test_h1_quorum_debug_explains_missing_third_frame_without_bypass(self):
        from src.platform.display_f3_ng_fast_confirmation import (
            tokens_corrobacao_fisica_h1,
        )
        case = self._case()
        states = {row["mask_id"]: row["classified"] for row in case["mask_results"]}
        def observed(frame_id, **changes):
            return {
                "frame_token": ("camera", frame_id),
                "project_name": "DISPLAY A",
                "check_id": "CHECK_001",
                "board_present": True,
                "powered_confirmed": True,
                "decision_allowed": True,
                "spatial_alignment_ready": True,
                "same_mask_comparison": True,
                "mask_classifications": states,
                **changes,
            }
        diagnosed = {}
        def check(history):
            return tokens_corrobacao_fisica_h1(
                case, ("MASK_017", "MASK_020"), history,
                snapshot_token=("camera", 414), diagnostics=diagnosed,
            )

        # O frame mais novo bloqueado NÃO pode ser ignorado para saltar
        # diretamente para três frames antigos válidos.
        blocked = [observed(415), observed(416), observed(417, decision_allowed=False)]
        self.assertEqual((), check(blocked))
        self.assertEqual("physical_authority_gate_blocked", diagnosed["stop_reason"])
        self.assertEqual(("camera", 417), diagnosed["stop_frame_token"])
        self.assertIn("decision_allowed", diagnosed["stop_details"]["failed_gates"])
        self.assertEqual(3, diagnosed["history_count"])

        stale = [observed(415), observed(460)]
        self.assertEqual((), check(stale))
        self.assertEqual("history_exceeds_45_frame_window", diagnosed["stop_reason"])
        self.assertEqual(46, diagnosed["stop_details"]["frame_gap"])

        altered = dict(states)
        altered["MASK_020"] = "on"
        self.assertEqual((), check([observed(415), observed(416, mask_classifications=altered)]))
        self.assertEqual("failed_masks_not_off_in_physical", diagnosed["stop_reason"])
        self.assertEqual(("MASK_020",), diagnosed["stop_details"]["mask_ids"])

        valid = [observed(415), observed(416), observed(417)]
        self.assertEqual(3, len(check(valid)))
        self.assertEqual("quorum_reached", diagnosed["stop_reason"])
        self.assertEqual(3, len(diagnosed["accepted_tokens"]))

    def test_power_owner_retains_distinct_frames_for_h1_without_new_classifiers(self):
        from src.platform.display_f3_runtime_authorities import F3PowerAuthority
        from src.platform.display_f3_ng_fast_confirmation import (
            tokens_corrobacao_fisica_h1,
        )
        board = SimpleNamespace()
        power = F3PowerAuthority(board)
        case = self._case()
        failed = ("MASK_017", "MASK_020")
        physical_states = {
            row["mask_id"]: row["classified"]
            for row in case["mask_results"]
        }
        for frame_id in (415, 416, 417):
            energy = {
                "frame_token": ("camera", frame_id),
                "powered_confirmed": True,
                "spatial_alignment_ready": True,
                "same_mask_comparison": True,
                "primary_authority": "same_physical_mask_on_off_learning",
                "mask_classifications": physical_states,
            }
            result = power.apply(
                {},
                {"board_present": True, "empty_confirmed": False},
                energy,
                project_name="DISPLAY A",
                context={"check_id": "CHECK_001", "check_name": "H1"},
            )
            self.assertTrue(result["allow_auto"])
        history = board._display_f3_recent_power_mask_frames
        self.assertEqual(3, len(history))
        # Handoff D-081 recarrega RAW antigo da foto; não pode substituir
        # observações posteriores já coletadas pela autoridade de energia.
        power.apply(
            {}, {"board_present": True, "empty_confirmed": False},
            {**energy, "frame_token": ("camera", 414)},
            project_name="DISPLAY A",
            context={"check_id": "CHECK_001", "check_name": "H1"},
        )
        history = board._display_f3_recent_power_mask_frames
        self.assertEqual([415, 416, 417], [
            int(item["frame_token"][1]) for item in history
        ])
        self.assertEqual(
            3, len(tokens_corrobacao_fisica_h1(
                case, failed, history, snapshot_token=("camera", 414)
            )),
        )
        # Frame duplicado não vira confirmação independente.
        duplicate = [history[0], history[1], history[1]]
        self.assertEqual(
            2, len(tokens_corrobacao_fisica_h1(
                case, failed, duplicate, snapshot_token=("camera", 414)
            )),
        )
        corrupted = [dict(item) for item in history]
        corrupted[-1]["mask_classifications"] = dict(physical_states)
        corrupted[-1]["mask_classifications"]["MASK_020"] = "on"
        self.assertEqual(
            0, len(tokens_corrobacao_fisica_h1(
                case, failed, corrupted, snapshot_token=("camera", 414)
            )),
        )
        wrong_check = power.apply(
            {}, {"board_present": True, "empty_confirmed": False},
            {**energy, "frame_token": ("camera", 418)},
            project_name="DISPLAY A",
            context={"check_id": "CHECK_002", "check_name": "BLUE"},
        )
        self.assertEqual("powered", wrong_check["kind"])
        self.assertEqual(1, len(board._display_f3_recent_power_mask_frames))
        power.reset()
        self.assertEqual([], board._display_f3_recent_power_mask_frames)

    def test_power_history_debug_explains_sparse_frames_without_creating_votes(self):
        from src.platform.display_f3_runtime_authorities import F3PowerAuthority

        app = SimpleNamespace()
        owner = F3PowerAuthority(app)
        def apply(frame, *, present=True):
            return owner.apply(
                {},
                {"board_present": present, "empty_confirmed": False},
                {
                    "frame_token": ("camera", frame),
                    "powered_confirmed": True,
                    "spatial_alignment_ready": True,
                    "same_mask_comparison": True,
                    "primary_authority": "same_physical_mask_on_off_learning",
                    "mask_classifications": {"MASK_017": "off", "MASK_020": "off"},
                },
                project_name="DISPLAY A",
                context={"check_id": "CHECK_001", "check_name": "H1"},
            )

        apply(288)
        apply(300)
        apply(300)
        apply(290)  # retorno semantico atrasado: nao conta novo frame
        self.assertEqual(
            [288, 300],
            [item["frame_token"][1]
             for item in app._display_f3_recent_power_mask_frames],
        )
        diagnostic = app._display_f3_power_history_diagnostics
        self.assertEqual(2, diagnostic["counts"]["frame_added"])
        self.assertEqual(1, diagnostic["counts"]["frame_replaced"])
        self.assertEqual(1, diagnostic["counts"]["frame_not_newer"])
        self.assertEqual(
            (("camera", 288), ("camera", 300)),
            diagnostic["history_frame_tokens"],
        )

        apply(310, present=False)
        self.assertEqual([], app._display_f3_recent_power_mask_frames)
        diagnostic = app._display_f3_power_history_diagnostics
        self.assertEqual("history_reset", diagnostic["events"][-2]["action"])
        self.assertEqual(
            "presence_not_confirmed", diagnostic["events"][-2]["reason"],
        )
        apply(320)
        self.assertEqual(
            [320],
            [item["frame_token"][1]
             for item in app._display_f3_recent_power_mask_frames],
        )
        self.assertEqual(1, diagnostic["counts"]["history_reset"])
        owner.reset()
        self.assertIsNone(app._display_f3_power_history_diagnostics)

    def _make_h1_production_runtime(self, history):
        app = DisplayAutomaticCheckF3Mixin.__new__(DisplayAutomaticCheckF3Mixin)
        app.display_f3_ativo = True
        app.display_f3_result_after_id = None
        app.camera_frame_atual = np.zeros((16, 16, 3), dtype=np.uint8)
        app.camera_ultimo_frame_id = 417
        app._display_f3_tracking_instance_frame_prepared = True
        app._display_auto_analysis_frame_override = None
        app._display_auto_signature = ("DISPLAY A", "CHECK_001")
        app._display_auto_last_decision = None
        app._display_auto_stable_frames = 0
        app._display_auto_last_frame_token = None
        app._display_auto_transition_frames = 0
        app._display_auto_manual_entry_signature = None
        app._display_auto_manual_entry_label = ""
        app._display_auto_h1_fast_ng_signature = None
        app._display_auto_h1_fast_ng_frame_tokens = []
        app._display_f3_recent_power_mask_frames = history
        app._display_auto_configuration_open = lambda: False
        app._display_auto_current_context = lambda: {
            "project_name": "DISPLAY A",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "intermittent": False,
        }
        app._display_auto_is_reference_gate = lambda _context: True
        app._display_auto_is_transient_check = lambda _context: False
        app._display_auto_has_reference_power_evidence = lambda _analysis: True
        app._display_auto_publish_effective_ui_authority = (
            lambda analysis, judgement_ready: analysis
        )
        app._display_auto_publish_segment_signature = (
            lambda _context, analysis: analysis
        )
        app._display_auto_update_intermittent_evidence = (
            lambda _context, _analysis: (True, 0, 0)
        )
        app._display_auto_clear_manual_entry_gate = lambda: None
        app._display_auto_set_preview_status = lambda *_args: None
        registered = []
        def register(approved):
            registered.append((
                approved,
                app._display_f3_pending_ng_frame_id,
                dict(app._display_f3_pending_ng_runtime or {}),
            ))
            return {"event": "board_ng"}
        app.registrar_resultado_check_display_f3 = register
        context = app._display_auto_current_context()
        return app, registered, context

    def test_h1_physical_history_confirms_one_cnn_photo_in_runtime(self):
        from src.platform.display_f3_ng_fast_confirmation import (
            tokens_corrobacao_fisica_h1,
        )
        case = self._case()
        physical_states = {
            row["mask_id"]: row["classified"]
            for row in case["mask_results"]
        }
        history = [
            {
                "frame_token": ("camera", frame_id),
                "project_name": "DISPLAY A",
                "check_id": "CHECK_001",
                "board_present": True,
                "powered_confirmed": True,
                "decision_allowed": True,
                "spatial_alignment_ready": True,
                "same_mask_comparison": True,
                "mask_classifications": physical_states,
            }
            for frame_id in (415, 416, 417)
        ]
        self.assertEqual(3, len(tokens_corrobacao_fisica_h1(
            case, ("MASK_017", "MASK_020"), history,
            snapshot_token=("camera", 414)
        )))
        app, registered, context = self._make_h1_production_runtime(history)
        app._display_auto_precomputed_payload = {
            "frame_token": ("camera", 414),
            "context": context,
            "analysis": case,
            "raw_frame": app.camera_frame_atual.copy(),
            "snapshot_capture_trigger": {
                "triggered": True,
                "mask_ids": ("MASK_008",),
            },
        }
        app._process_display_auto_check()
        self.assertEqual(1, len(registered))
        approved, frame_id, proof = registered[0]
        self.assertIs(approved, False)
        self.assertEqual(414, frame_id)
        self.assertTrue(proof["fast_h1_ng_consensus"])
        self.assertEqual(3, proof["fast_h1_ng_physical_frames"])
        self.assertEqual(3, proof["required_stable_frames"])
        self.assertEqual(
            "canonical_power_same_mask_history",
            proof["fast_h1_ng_confirmation_source"],
        )

    def test_h1_duas_cnns_mais_um_frame_fisico_distinto_finalizam_ng(self):
        # Reteste físico D-093: 2 snapshots CNN + 1 frame físico = 2/3
        # porque o runtime usava max(), em vez da união de tokens.
        case = self._case()
        states = {row["mask_id"]: row["classified"] for row in case["mask_results"]}
        physical = {
            "frame_token": ("camera", 369),
            "project_name": "DISPLAY A",
            "check_id": "CHECK_001",
            "board_present": True,
            "powered_confirmed": True,
            "decision_allowed": True,
            "spatial_alignment_ready": True,
            "same_mask_comparison": True,
            "mask_classifications": states,
        }
        app, registered, context = self._make_h1_production_runtime([physical])
        for i, frame_id in enumerate((365, 368)):
            app._display_auto_precomputed_payload = {
                "frame_token": ("camera", frame_id),
                "context": context,
                "analysis": case,
                "raw_frame": app.camera_frame_atual.copy(),
                "snapshot_capture_trigger": {
                    "triggered": True, "mask_ids": ("MASK_008",),
                },
            }
            app._process_display_auto_check()
            if i == 0:
                self.assertFalse(registered)
        self.assertEqual(1, len(registered))
        approved, frame_id, proof = registered[0]
        self.assertIs(approved, False)
        self.assertEqual(368, frame_id)
        self.assertEqual(3, proof["stable_frames"])
        self.assertEqual(1, proof["fast_h1_ng_physical_frames"])
        self.assertEqual(
            (("camera", 365), ("camera", 368), ("camera", 369)),
            proof["fast_h1_ng_distinct_frame_tokens"],
        )
        self.assertEqual(
            "hybrid_semantic_plus_physical_frames",
            proof["fast_h1_ng_confirmation_source"],
        )

    def test_h1_evidencia_fisica_repetida_antiga_ou_divergente_nao_fecha_ng(self):
        case = self._case()
        states = {row["mask_id"]: row["classified"] for row in case["mask_results"]}
        for invalid in ("duplicate", "stale", "different_mask", "power_off"):
            with self.subTest(invalid=invalid):
                physical = {
                    "frame_token": ("camera", 369),
                    "project_name": "DISPLAY A",
                    "check_id": "CHECK_001",
                    "board_present": True,
                    "powered_confirmed": True,
                    "decision_allowed": True,
                    "spatial_alignment_ready": True,
                    "same_mask_comparison": True,
                    "mask_classifications": dict(states),
                }
                if invalid == "duplicate":
                    physical["frame_token"] = ("camera", 368)
                elif invalid == "stale":
                    physical["frame_token"] = ("camera", 300)
                elif invalid == "different_mask":
                    physical["mask_classifications"]["MASK_020"] = "on"
                elif invalid == "power_off":
                    physical["powered_confirmed"] = False
                app, registered, context = self._make_h1_production_runtime([physical])
                for frame_id in (365, 368):
                    app._display_auto_precomputed_payload = {
                        "frame_token": ("camera", frame_id),
                        "context": context,
                        "analysis": case,
                        "raw_frame": app.camera_frame_atual.copy(),
                        "snapshot_capture_trigger": {
                            "triggered": True, "mask_ids": ("MASK_008",),
                        },
                    }
                    app._process_display_auto_check()
                self.assertEqual([], registered)
                self.assertEqual(
                    2, app._display_auto_last_decision_trace["fast_ng_distinct_frames"]
                )

    def test_h1_fast_requires_three_distinct_camera_frames_no_duplicate(self):
        # Contrato temporal: apenas tokens de captura independentes contam.
        source = inspect.getsource(DisplayAutomaticCheckF3Mixin._process_display_auto_check)
        self.assertIn("assinatura_ng_h1_consenso(", source)
        self.assertIn("if token_key is not None and token_key not in seen:", source)
        self.assertIn("set(semantic_tokens) | set(physical_tokens)", source)
        self.assertIn("tokens_corrobacao_fisica_h1(", source)
        self.assertIn("semantic_frame_count", source)
        self.assertIn("DISPLAY_AUTO_H1_CONSENSUS_NG_FRAMES", source)
        self.assertEqual(
            6, DisplayAutomaticCheckF3Mixin.DISPLAY_AUTO_NG_STABLE_FRAMES
        )
        self.assertEqual(
            3, DisplayAutomaticCheckF3Mixin.DISPLAY_AUTO_H1_CONSENSUS_NG_FRAMES
        )


if __name__ == "__main__":
    unittest.main()
