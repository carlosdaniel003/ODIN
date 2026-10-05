from __future__ import annotations

"""Autoridade neural incremental do Display F3.

Etapa N2:
- H1 e BLUE usam a mesma CNN local de estado ON/OFF por segmento;
- USB/AUX continuam delegados ao analisador convencional atual;
- o modelo ONNX é carregado uma única vez e reutilizado;
- as 28 ROIs são inferidas em um único batch;
- ausência/erro do modelo é fail-closed nos CHECKS já migrados, sem fallback
  convencional de ON/OFF.

BLUE continua intermitente. A CNN classifica cada frame, enquanto o runtime
temporal decide se o frame pertence à fase ON, OFF ou transição. Somente a fase
ON pode validar conformidade ou acumular uma divergência neural certa.

A rede decide apenas estado visual de segmento. Sequência, presença, energia,
rearme e UI continuam com as autoridades canônicas já existentes.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import cv2
import numpy as np

import src.platform.display_auto_check_runtime as runtime_module
import src.platform.display_f3_live_runtime_fix as live_runtime_module
from src.platform.display_auto_check_analyzer import DISPLAY_AUTO_CLASS_LABELS
from src.platform.display_check_presence_reference import (
    avaliar_referencia_presenca_display,
)
from src.platform.display_f3_neural_dataset import (
    F3_NEURAL_INPUT_SIZE,
    F3_NEURAL_MIN_PHYSICAL_H1_CALIBRATION_FRAMES,
    F3_NEURAL_MODEL_METADATA_SCHEMA_VERSION,
    F3_NEURAL_PHYSICAL_THRESHOLD_CALIBRATION_SOURCE,
    F3_NEURAL_THRESHOLD_CALIBRATION_SOURCE,
    F3_NEURAL_THRESHOLD_CALIBRATION_SOURCES,
    extrair_tensor_segmento_f3,
    f3_neural_model_path_for_repository,
)
from src.platform.display_f3_same_mask_reference_fix import (
    F3SameMaskReferenceAnalyzer,
)
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_IGNORE,
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
    mascaras_geometria_runtime_fixa_display,
    normalizar_resolucao_display,
)
from src.platform.display_visual_rotation import preparar_check_visual_display


# Identificador histórico preservado para compatibilidade com a calibração
# física H1 e DEBUGs já coletados. A instância agora é compartilhada por H1/BLUE.
F3_H1_NEURAL_AUTHORITY = "f3_h1_neural_segment_detector"
F3_H1_NEURAL_MODEL_TYPE = "f3_segment_on_off_cnn"
F3_NEURAL_UNCERTAIN_STATE = "uncertain"
F3_NEURAL_MODEL_REFRESH_S = 1.0
F3_NEURAL_MIGRATED_CHECK_COUNT = 2
F3_NEURAL_CHECK_SCOPE = "first_two_checks_n2"


def _strict_probability(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number) or number < 0.0 or number > 1.0:
        return None
    return number


def _file_signature(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
        return str(path), int(stat.st_mtime_ns), int(stat.st_size)
    except OSError:
        return str(path), 0, 0


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _softmax_logits(logits: np.ndarray) -> np.ndarray:
    values = np.asarray(logits, dtype=np.float32)
    values = values - np.max(values, axis=1, keepdims=True)
    exp = np.exp(values)
    denominator = np.maximum(
        np.sum(exp, axis=1, keepdims=True),
        np.float32(1e-9),
    )
    return exp / denominator


class F3NeuralSegmentDetector:
    """Carrega ONNX uma vez e classifica um batch de segmentos ON/OFF."""

    def __init__(self, repository) -> None:
        self.repository = repository
        self._project_name = ""
        self._model_path: Path | None = None
        self._metadata_path: Path | None = None
        self._model_signature = None
        self._metadata_signature = None
        self._metadata: dict = {}
        self._net = None
        self._last_check_s = 0.0
        self._last_status: dict = {
            "ready": False,
            "reason": "neural_model_not_loaded",
        }
        self.load_count = 0
        self.inference_count = 0

    def invalidate_model_cache(self) -> None:
        self._project_name = ""
        self._model_path = None
        self._metadata_path = None
        self._model_signature = None
        self._metadata_signature = None
        self._metadata = {}
        self._net = None
        self._last_check_s = 0.0
        self._last_status = {
            "ready": False,
            "reason": "neural_model_not_loaded",
        }

    @staticmethod
    def _read_metadata(path: Path) -> dict:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def prepare(self, project_name: str, *, force: bool = False) -> dict:
        name = str(project_name or "").strip()
        model_path = f3_neural_model_path_for_repository(
            self.repository,
            name,
        )
        metadata_path = model_path.with_suffix(".json")
        now = time.monotonic()

        same_paths = bool(
            self._project_name == name
            and self._model_path == model_path
            and self._metadata_path == metadata_path
        )
        if (
            not force
            and same_paths
            and (now - float(self._last_check_s or 0.0))
            < F3_NEURAL_MODEL_REFRESH_S
        ):
            return deepcopy(self._last_status)

        self._last_check_s = now
        model_signature = _file_signature(model_path)
        metadata_signature = _file_signature(metadata_path)
        previous_model_signature = self._model_signature
        previous_metadata_signature = self._metadata_signature

        self._project_name = name
        self._model_path = model_path
        self._metadata_path = metadata_path

        if model_signature[1] <= 0 or model_signature[2] <= 0:
            self._metadata = {}
            self._net = None
            self._model_signature = model_signature
            self._metadata_signature = metadata_signature
            self._last_status = {
                "ready": False,
                "reason": "neural_model_missing",
                "project_name": name,
                "model_path": str(model_path),
                "metadata_path": str(metadata_path),
                "load_count": int(self.load_count),
            }
            return deepcopy(self._last_status)

        if metadata_signature[1] <= 0 or metadata_signature[2] <= 0:
            self._metadata = {}
            self._net = None
            self._model_signature = model_signature
            self._metadata_signature = metadata_signature
            self._last_status = {
                "ready": False,
                "reason": "neural_metadata_missing",
                "project_name": name,
                "model_path": str(model_path),
                "metadata_path": str(metadata_path),
                "load_count": int(self.load_count),
            }
            return deepcopy(self._last_status)

        needs_reload = bool(
            self._net is None
            or not same_paths
            or model_signature != previous_model_signature
            or metadata_signature != previous_metadata_signature
        )

        if needs_reload:
            metadata = self._read_metadata(metadata_path)
            try:
                metadata_schema = int(metadata.get("schema_version", 0) or 0)
            except (TypeError, ValueError):
                metadata_schema = 0
            if metadata_schema != F3_NEURAL_MODEL_METADATA_SCHEMA_VERSION:
                self._metadata = metadata
                self._net = None
                self._model_signature = model_signature
                self._metadata_signature = metadata_signature
                self._last_status = {
                    "ready": False,
                    "reason": "neural_metadata_schema_unsupported",
                    "project_name": name,
                    "schema_version": metadata_schema,
                    "model_path": str(model_path),
                    "metadata_path": str(metadata_path),
                    "load_count": int(self.load_count),
                }
                return deepcopy(self._last_status)

            declared_project = str(
                metadata.get("project_name") or ""
            ).strip()
            if declared_project != name:
                self._metadata = metadata
                self._net = None
                self._model_signature = model_signature
                self._metadata_signature = metadata_signature
                self._last_status = {
                    "ready": False,
                    "reason": "neural_model_project_mismatch",
                    "project_name": name,
                    "declared_project_name": declared_project,
                    "model_path": str(model_path),
                    "metadata_path": str(metadata_path),
                    "load_count": int(self.load_count),
                }
                return deepcopy(self._last_status)

            model_type = str(
                metadata.get("model_type") or ""
            ).strip()
            if model_type != F3_H1_NEURAL_MODEL_TYPE:
                self._metadata = metadata
                self._net = None
                self._model_signature = model_signature
                self._metadata_signature = metadata_signature
                self._last_status = {
                    "ready": False,
                    "reason": "neural_model_type_unsupported",
                    "project_name": name,
                    "model_type": model_type,
                    "model_path": str(model_path),
                    "metadata_path": str(metadata_path),
                    "load_count": int(self.load_count),
                }
                return deepcopy(self._last_status)

            declared_hash = str(
                metadata.get("onnx_sha256") or ""
            ).strip().lower()
            if not declared_hash:
                self._metadata = metadata
                self._net = None
                self._model_signature = model_signature
                self._metadata_signature = metadata_signature
                self._last_status = {
                    "ready": False,
                    "reason": "neural_model_hash_missing",
                    "project_name": name,
                    "model_path": str(model_path),
                    "metadata_path": str(metadata_path),
                    "load_count": int(self.load_count),
                }
                return deepcopy(self._last_status)

            actual_hash = _sha256_file(model_path)
            if not actual_hash or actual_hash.lower() != declared_hash:
                self._metadata = metadata
                self._net = None
                self._model_signature = model_signature
                self._metadata_signature = metadata_signature
                self._last_status = {
                    "ready": False,
                    "reason": "neural_model_hash_mismatch",
                    "project_name": name,
                    "model_path": str(model_path),
                    "metadata_path": str(metadata_path),
                    "declared_sha256": declared_hash,
                    "actual_sha256": actual_hash,
                    "load_count": int(self.load_count),
                }
                return deepcopy(self._last_status)

            validation = (
                metadata.get("validation")
                if isinstance(metadata.get("validation"), dict)
                else {}
            )
            split = (
                metadata.get("split")
                if isinstance(metadata.get("split"), dict)
                else {}
            )
            try:
                checks = self.repository.listar_checks(name)
            except Exception:
                checks = []
            first_check_id = str(
                (
                    checks[0]
                    if isinstance(checks, list) and checks
                    and isinstance(checks[0], dict)
                    else {}
                ).get("id")
                or ""
            ).strip()
            if not (
                validation.get("accepted_for_physical_h1_retest") is True
                and str(split.get("strategy") or "")
                == "hold_out_first_check_for_n1"
                and first_check_id
                and str(split.get("validation_check_id") or "").strip()
                == first_check_id
            ):
                self._metadata = metadata
                self._net = None
                self._model_signature = model_signature
                self._metadata_signature = metadata_signature
                self._last_status = {
                    "ready": False,
                    "reason": "neural_model_not_validated_for_h1",
                    "project_name": name,
                    "first_check_id": first_check_id,
                    "validation_check_id": str(
                        split.get("validation_check_id") or ""
                    ),
                    "model_path": str(model_path),
                    "metadata_path": str(metadata_path),
                    "load_count": int(self.load_count),
                }
                return deepcopy(self._last_status)

            labels = (
                metadata.get("labels")
                if isinstance(metadata.get("labels"), dict)
                else {}
            )
            try:
                off_label = int(labels.get("off", -1))
                on_label = int(labels.get("on", -1))
            except (TypeError, ValueError):
                off_label = -1
                on_label = -1
            if (
                off_label != 0
                or on_label != 1
            ):
                self._metadata = metadata
                self._net = None
                self._model_signature = model_signature
                self._metadata_signature = metadata_signature
                self._last_status = {
                    "ready": False,
                    "reason": "neural_label_map_unsupported",
                    "project_name": name,
                    "labels": deepcopy(labels),
                    "model_path": str(model_path),
                    "metadata_path": str(metadata_path),
                    "load_count": int(self.load_count),
                }
                return deepcopy(self._last_status)

            thresholds = (
                metadata.get("suggested_thresholds")
                if isinstance(metadata.get("suggested_thresholds"), dict)
                else {}
            )
            calibration = (
                metadata.get("threshold_calibration")
                if isinstance(metadata.get("threshold_calibration"), dict)
                else {}
            )
            calibration_source = str(calibration.get("source") or "").strip()
            if (
                calibration_source not in F3_NEURAL_THRESHOLD_CALIBRATION_SOURCES
                or calibration.get("separable") is not True
            ):
                self._metadata = metadata
                self._net = None
                self._model_signature = model_signature
                self._metadata_signature = metadata_signature
                self._last_status = {
                    "ready": False,
                    "reason": "neural_threshold_calibration_missing",
                    "project_name": name,
                    "calibration_source": calibration_source,
                    "model_path": str(model_path),
                    "metadata_path": str(metadata_path),
                    "load_count": int(self.load_count),
                }
                return deepcopy(self._last_status)

            on_min = _strict_probability(thresholds.get("on_min_on_probability"))
            off_max = _strict_probability(thresholds.get("off_max_on_probability"))
            calibrated_max_off = _strict_probability(
                calibration.get("max_off_on_probability")
            )
            calibrated_min_on = _strict_probability(
                calibration.get("min_on_on_probability")
            )
            calibration_gap = _strict_probability(
                calibration.get("uncertainty_gap")
            )
            class_counts = (
                calibration.get("class_counts")
                if isinstance(calibration.get("class_counts"), dict)
                else {}
            )
            try:
                calibration_samples = int(calibration.get("sample_count", 0) or 0)
                calibration_references = int(
                    calibration.get("reference_sample_count", 0) or 0
                )
                calibration_augmentations = int(
                    calibration.get("augmentations_per_reference", 0) or 0
                )
                calibration_off_count = int(class_counts.get("off", 0) or 0)
                calibration_on_count = int(class_counts.get("on", 0) or 0)
            except (TypeError, ValueError):
                calibration_samples = 0
                calibration_references = 0
                calibration_augmentations = 0
                calibration_off_count = 0
                calibration_on_count = 0

            calibration_valid = bool(
                on_min is not None
                and off_max is not None
                and calibrated_max_off is not None
                and calibrated_min_on is not None
                and calibration_gap is not None
                and off_max < on_min
                and calibrated_max_off < calibrated_min_on
                and calibration_gap > 0.0
                and abs(off_max - calibrated_max_off) <= 1e-6
                and abs(on_min - calibrated_min_on) <= 1e-6
                and calibration_samples > 0
                and calibration_references > 0
                and calibration_augmentations > 0
                and calibration_off_count > 0
                and calibration_on_count > 0
                and calibration_samples
                == calibration_off_count + calibration_on_count
            )
            if not calibration_valid:
                self._metadata = metadata
                self._net = None
                self._model_signature = model_signature
                self._metadata_signature = metadata_signature
                self._last_status = {
                    "ready": False,
                    "reason": "neural_threshold_calibration_invalid",
                    "project_name": name,
                    "calibration_source": calibration_source,
                    "model_path": str(model_path),
                    "metadata_path": str(metadata_path),
                    "load_count": int(self.load_count),
                }
                return deepcopy(self._last_status)

            if (
                calibration_source
                == F3_NEURAL_PHYSICAL_THRESHOLD_CALIBRATION_SOURCE
            ):
                physical = (
                    calibration.get("physical_h1")
                    if isinstance(calibration.get("physical_h1"), dict)
                    else {}
                )
                base = (
                    calibration.get("base_augmented_calibration")
                    if isinstance(
                        calibration.get("base_augmented_calibration"),
                        dict,
                    )
                    else {}
                )
                frame_hashes = [
                    str(value or "").strip()
                    for value in (physical.get("frame_hashes") or ())
                    if str(value or "").strip()
                ]
                frames = [
                    value
                    for value in (physical.get("frames") or ())
                    if isinstance(value, dict)
                ]
                physical_counts = (
                    physical.get("class_counts")
                    if isinstance(physical.get("class_counts"), dict)
                    else {}
                )
                base_counts = (
                    base.get("class_counts")
                    if isinstance(base.get("class_counts"), dict)
                    else {}
                )
                try:
                    physical_frame_count = int(
                        physical.get("frame_count", 0) or 0
                    )
                    physical_sample_count = int(
                        physical.get("sample_count", 0) or 0
                    )
                    physical_off_count = int(
                        physical_counts.get("off", 0) or 0
                    )
                    physical_on_count = int(
                        physical_counts.get("on", 0) or 0
                    )
                    base_sample_count = int(
                        base.get("sample_count", 0) or 0
                    )
                    base_off_count = int(
                        base_counts.get("off", 0) or 0
                    )
                    base_on_count = int(
                        base_counts.get("on", 0) or 0
                    )
                except (TypeError, ValueError):
                    physical_frame_count = 0
                    physical_sample_count = 0
                    physical_off_count = 0
                    physical_on_count = 0
                    base_sample_count = 0
                    base_off_count = 0
                    base_on_count = 0

                physical_max_off = _strict_probability(
                    physical.get("max_off_on_probability")
                )
                physical_min_on = _strict_probability(
                    physical.get("min_on_on_probability")
                )
                physical_gap = _strict_probability(
                    physical.get("uncertainty_gap")
                )
                base_max_off = _strict_probability(
                    base.get("max_off_on_probability")
                )
                base_min_on = _strict_probability(
                    base.get("min_on_on_probability")
                )
                base_gap = _strict_probability(
                    base.get("uncertainty_gap")
                )

                physical_valid = bool(
                    str(base.get("source") or "").strip()
                    == F3_NEURAL_THRESHOLD_CALIBRATION_SOURCE
                    and base.get("separable") is True
                    and physical.get("separable") is True
                    and str(physical.get("project_name") or "").strip()
                    == name
                    and str(
                        physical.get("validation_check_id") or ""
                    ).strip()
                    == first_check_id
                    and str(physical.get("model_sha256") or "")
                    .strip()
                    .lower()
                    == declared_hash
                    and physical_frame_count
                    >= F3_NEURAL_MIN_PHYSICAL_H1_CALIBRATION_FRAMES
                    and len(frame_hashes) == physical_frame_count
                    and len(set(frame_hashes)) == physical_frame_count
                    and len(frames) == physical_frame_count
                    and physical_sample_count
                    == physical_off_count + physical_on_count
                    and physical_off_count > 0
                    and physical_on_count > 0
                    and base_sample_count == base_off_count + base_on_count
                    and base_off_count > 0
                    and base_on_count > 0
                    and calibration_samples
                    == base_sample_count + physical_sample_count
                    and calibration_off_count
                    == base_off_count + physical_off_count
                    and calibration_on_count
                    == base_on_count + physical_on_count
                    and physical_max_off is not None
                    and physical_min_on is not None
                    and physical_gap is not None
                    and physical_max_off < physical_min_on
                    and physical_gap > 0.0
                    and base_max_off is not None
                    and base_min_on is not None
                    and base_gap is not None
                    and base_max_off < base_min_on
                    and base_gap > 0.0
                    and abs(
                        calibrated_max_off
                        - max(base_max_off, physical_max_off)
                    )
                    <= 1e-6
                    and abs(
                        calibrated_min_on
                        - min(base_min_on, physical_min_on)
                    )
                    <= 1e-6
                )
                if not physical_valid:
                    self._metadata = metadata
                    self._net = None
                    self._model_signature = model_signature
                    self._metadata_signature = metadata_signature
                    self._last_status = {
                        "ready": False,
                        "reason": "neural_physical_h1_calibration_invalid",
                        "project_name": name,
                        "calibration_source": calibration_source,
                        "model_path": str(model_path),
                        "metadata_path": str(metadata_path),
                        "load_count": int(self.load_count),
                    }
                    return deepcopy(self._last_status)

            try:
                net = cv2.dnn.readNetFromONNX(str(model_path))
            except Exception as exc:
                self._net = None
                self._model_signature = model_signature
                self._metadata_signature = metadata_signature
                self._last_status = {
                    "ready": False,
                    "reason": "neural_model_load_error",
                    "project_name": name,
                    "model_path": str(model_path),
                    "metadata_path": str(metadata_path),
                    "error_type": type(exc).__name__,
                    "load_count": int(self.load_count),
                }
                return deepcopy(self._last_status)

            self._metadata = metadata
            self._net = net
            self._model_signature = model_signature
            self._metadata_signature = metadata_signature
            self.load_count += 1

        input_size = max(
            16,
            int(
                self._metadata.get(
                    "input_size",
                    F3_NEURAL_INPUT_SIZE,
                )
                or F3_NEURAL_INPUT_SIZE
            ),
        )
        thresholds = self._metadata["suggested_thresholds"]
        calibration = self._metadata["threshold_calibration"]
        on_min = float(thresholds["on_min_on_probability"])
        off_max = float(thresholds["off_max_on_probability"])

        self._last_status = {
            "ready": True,
            "reason": "neural_model_ready",
            "project_name": name,
            "model_path": str(self._model_path),
            "metadata_path": str(self._metadata_path),
            "model_type": F3_H1_NEURAL_MODEL_TYPE,
            "input_size": int(input_size),
            "on_min_on_probability": round(float(on_min), 6),
            "off_max_on_probability": round(float(off_max), 6),
            "threshold_calibration_source": str(
                calibration.get("source") or ""
            ),
            "threshold_calibration_gap": round(
                float(calibration.get("uncertainty_gap") or 0.0),
                6,
            ),
            "threshold_calibration_sample_count": int(
                calibration.get("sample_count", 0) or 0
            ),
            "threshold_calibration_augmentations_per_reference": int(
                calibration.get("augmentations_per_reference", 0) or 0
            ),
            "physical_h1_calibration_frame_count": int(
                (
                    calibration.get("physical_h1")
                    if isinstance(calibration.get("physical_h1"), dict)
                    else {}
                ).get("frame_count", 0)
                or 0
            ),
            "onnx_sha256": str(
                self._metadata.get("onnx_sha256") or ""
            ),
            "load_count": int(self.load_count),
        }
        return deepcopy(self._last_status)

    def predict(
        self,
        project_name: str,
        tensors,
    ) -> dict:
        status = self.prepare(project_name)
        if not bool(status.get("ready")):
            return {
                **status,
                "observations": [],
            }

        batch_items = [
            np.asarray(item, dtype=np.float32)
            for item in (tensors or ())
        ]
        if not batch_items:
            return {
                **status,
                "ready": False,
                "reason": "neural_batch_empty",
                "observations": [],
            }

        expected_size = int(status["input_size"])
        for item in batch_items:
            if item.shape != (4, expected_size, expected_size):
                return {
                    **status,
                    "ready": False,
                    "reason": "neural_tensor_shape_invalid",
                    "tensor_shape": list(item.shape),
                    "expected_shape": [
                        4,
                        expected_size,
                        expected_size,
                    ],
                    "observations": [],
                }

        batch = np.ascontiguousarray(
            np.stack(batch_items, axis=0),
            dtype=np.float32,
        )
        try:
            self._net.setInput(batch)
            logits = np.asarray(
                self._net.forward(),
                dtype=np.float32,
            )
        except Exception as exc:
            return {
                **status,
                "ready": False,
                "reason": "neural_inference_error",
                "error_type": type(exc).__name__,
                "observations": [],
            }

        expected_values = int(batch.shape[0]) * 2
        if logits.size != expected_values:
            return {
                **status,
                "ready": False,
                "reason": "neural_output_shape_invalid",
                "output_shape": list(logits.shape),
                "expected_values": expected_values,
                "observations": [],
            }
        logits = logits.reshape(int(batch.shape[0]), 2)
        probabilities = _softmax_logits(logits)

        on_min = float(status["on_min_on_probability"])
        off_max = float(status["off_max_on_probability"])
        observations = []
        for index, row in enumerate(probabilities):
            p_off = float(row[0])
            p_on = float(row[1])
            if p_on >= on_min:
                state = DISPLAY_CHECK_STATE_ON
                certain = True
                confidence = p_on
            elif p_on <= off_max:
                state = DISPLAY_CHECK_STATE_OFF
                certain = True
                confidence = p_off
            else:
                state = F3_NEURAL_UNCERTAIN_STATE
                certain = False
                confidence = max(p_on, p_off)

            observations.append(
                {
                    "index": int(index),
                    "state": state,
                    "certain": bool(certain),
                    "confidence": round(float(confidence), 6),
                    "probabilities": {
                        DISPLAY_CHECK_STATE_OFF: round(p_off, 6),
                        DISPLAY_CHECK_STATE_ON: round(p_on, 6),
                    },
                    "logits": [
                        round(float(logits[index, 0]), 6),
                        round(float(logits[index, 1]), 6),
                    ],
                }
            )

        self.inference_count += 1
        return {
            **status,
            "ready": True,
            "reason": "neural_inference_ready",
            "batch_size": len(observations),
            "inference_count": int(self.inference_count),
            "observations": observations,
        }


class F3NeuralCheckAnalyzer(F3SameMaskReferenceAnalyzer):
    """CNN para H1 + BLUE; CHECKS seguintes permanecem convencionais."""

    def __init__(self, repository) -> None:
        super().__init__(repository)
        self.neural_detector = F3NeuralSegmentDetector(repository)

    def invalidate_learning_cache(self) -> None:
        super().invalidate_learning_cache()
        self.neural_detector.invalidate_model_cache()

    def _neural_check_index(
        self,
        project_name: str,
        check_id: str,
    ) -> int | None:
        """Retorna o índice do CHECK migrado para IA nesta etapa N2."""
        try:
            checks = self.repository.listar_checks(project_name)
        except Exception:
            checks = []
        if not isinstance(checks, list):
            return None

        requested = str(check_id or "").strip()
        for index, check in enumerate(
            checks[:F3_NEURAL_MIGRATED_CHECK_COUNT]
        ):
            if (
                isinstance(check, dict)
                and str(check.get("id") or "").strip() == requested
            ):
                return int(index)
        return None

    @staticmethod
    def _not_ready_neural(
        reason: str,
        *,
        project_name: str,
        check_id: str,
        check_name: str = "",
        **extra,
    ) -> dict:
        return {
            "ready": False,
            "approved": None,
            "reason": str(reason),
            "project_name": str(project_name),
            "check_id": str(check_id),
            "check_name": str(check_name or check_id),
            "mask_results": [],
            "active_mask_count": 0,
            "matched_mask_count": 0,
            "neural_visual_authority": True,
            "neural_check_scope": F3_NEURAL_CHECK_SCOPE,
            "reference_authority": F3_H1_NEURAL_AUTHORITY,
            "conventional_visual_authority_used": False,
            **extra,
        }

    def analyze(
        self,
        frame,
        project_name: str,
        check_id: str,
        visual_rotation: int = 0,
        *,
        mask_geometry_override=None,
        mask_geometry_resolution=None,
        mask_geometry_source: str = "",
    ) -> dict:
        neural_check_index = self._neural_check_index(
            project_name,
            check_id,
        )
        if neural_check_index is None:
            return super().analyze(
                frame=frame,
                project_name=project_name,
                check_id=check_id,
                visual_rotation=visual_rotation,
                mask_geometry_override=mask_geometry_override,
                mask_geometry_resolution=mask_geometry_resolution,
                mask_geometry_source=mask_geometry_source,
            )

        if frame is None or getattr(frame, "size", 0) == 0:
            return self._not_ready_neural(
                "camera_sem_frame",
                project_name=project_name,
                check_id=check_id,
            )

        project = self.repository.carregar_projeto(project_name)
        if project is None:
            return self._not_ready_neural(
                "projeto_display_inexistente",
                project_name=project_name,
                check_id=check_id,
            )
        check = self.repository.carregar_check(
            project_name,
            check_id,
        )
        if check is None:
            return self._not_ready_neural(
                "check_display_inexistente",
                project_name=project_name,
                check_id=check_id,
            )

        check_name = str(
            check.get("name") or check_id
        )
        master_resolution = normalizar_resolucao_display(
            project.get("master_resolution")
        )
        if master_resolution is None:
            return self._not_ready_neural(
                "resolucao_mestra_ausente",
                project_name=project_name,
                check_id=check_id,
                check_name=check_name,
            )

        model_status = self.neural_detector.prepare(project_name)
        if not bool(model_status.get("ready")):
            return self._not_ready_neural(
                str(
                    model_status.get("reason")
                    or "neural_model_unavailable"
                ),
                project_name=project_name,
                check_id=check_id,
                check_name=check_name,
                neural_model=deepcopy(model_status),
            )

        masks = mascaras_geometria_runtime_fixa_display(project)
        states = (
            check.get("mask_states", {})
            if isinstance(check.get("mask_states"), dict)
            else {}
        )
        active_masks = [
            mask
            for mask in masks
            if states.get(str(mask.get("id"))) in (
                DISPLAY_CHECK_STATE_ON,
                DISPLAY_CHECK_STATE_OFF,
            )
        ]
        if not active_masks:
            return self._not_ready_neural(
                "check_sem_mascaras_ativas",
                project_name=project_name,
                check_id=check_id,
                check_name=check_name,
                neural_model=deepcopy(model_status),
            )

        use_geometry_override = bool(
            mask_geometry_override
            and frame is not None
            and getattr(frame, "size", 0) > 0
        )
        if use_geometry_override:
            visual_frame = frame
            visual_masks = [
                item
                for item in (mask_geometry_override or ())
                if isinstance(item, dict)
                and str(item.get("id") or "")
            ]
            frame_h, frame_w = visual_frame.shape[:2]
            visual_resolution = (
                int(frame_w),
                int(frame_h),
            )
            if (
                isinstance(
                    mask_geometry_resolution,
                    (list, tuple),
                )
                and len(mask_geometry_resolution) >= 2
            ):
                try:
                    expected_resolution = (
                        int(mask_geometry_resolution[0]),
                        int(mask_geometry_resolution[1]),
                    )
                except (TypeError, ValueError):
                    expected_resolution = visual_resolution
                if expected_resolution != visual_resolution:
                    use_geometry_override = False

        if not use_geometry_override:
            (
                visual_frame,
                visual_resolution,
                visual_masks,
            ) = preparar_check_visual_display(
                frame,
                master_resolution,
                masks,
                visual_rotation,
            )

        if (
            visual_frame is None
            or getattr(visual_frame, "size", 0) == 0
        ):
            return self._not_ready_neural(
                "camera_sem_frame_visual",
                project_name=project_name,
                check_id=check_id,
                check_name=check_name,
                neural_model=deepcopy(model_status),
            )

        target_width = max(
            1,
            int(visual_resolution[0]),
        )
        target_height = max(
            1,
            int(visual_resolution[1]),
        )
        if tuple(visual_frame.shape[:2]) != (
            target_height,
            target_width,
        ):
            interpolation = (
                cv2.INTER_AREA
                if (
                    visual_frame.shape[1] > target_width
                    or visual_frame.shape[0] > target_height
                )
                else cv2.INTER_LINEAR
            )
            visual_frame = cv2.resize(
                visual_frame,
                (target_width, target_height),
                interpolation=interpolation,
            )

        mask_by_id = {
            str(mask.get("id")): mask
            for mask in visual_masks
            if isinstance(mask, dict)
            and mask.get("id") is not None
        }

        input_size = int(
            model_status.get(
                "input_size",
                F3_NEURAL_INPUT_SIZE,
            )
            or F3_NEURAL_INPUT_SIZE
        )
        tensors = []
        rows = []
        for original_mask in active_masks:
            mask_id = str(
                original_mask.get("id") or ""
            )
            expected = str(
                states.get(mask_id) or ""
            )
            visual_mask = mask_by_id.get(mask_id)
            if visual_mask is None:
                return self._not_ready_neural(
                    "mascara_visual_nao_encontrada",
                    project_name=project_name,
                    check_id=check_id,
                    check_name=check_name,
                    mask_id=mask_id,
                    neural_model=deepcopy(model_status),
                )

            tensor = extrair_tensor_segmento_f3(
                visual_frame,
                visual_mask,
                input_size=input_size,
            )
            if tensor is None:
                return self._not_ready_neural(
                    "mascara_neural_fora_do_frame",
                    project_name=project_name,
                    check_id=check_id,
                    check_name=check_name,
                    mask_id=mask_id,
                    neural_model=deepcopy(model_status),
                )
            tensors.append(tensor)
            rows.append(
                {
                    "mask_id": mask_id,
                    "expected": expected,
                }
            )

        inference = self.neural_detector.predict(
            project_name,
            tensors,
        )
        if not bool(inference.get("ready")):
            return self._not_ready_neural(
                str(
                    inference.get("reason")
                    or "neural_inference_unavailable"
                ),
                project_name=project_name,
                check_id=check_id,
                check_name=check_name,
                neural_model=deepcopy(inference),
            )

        observations = list(
            inference.get("observations") or ()
        )
        if len(observations) != len(rows):
            return self._not_ready_neural(
                "neural_batch_size_mismatch",
                project_name=project_name,
                check_id=check_id,
                check_name=check_name,
                neural_model=deepcopy(inference),
            )

        results = []
        for row, observation in zip(rows, observations):
            state = str(
                observation.get("state")
                or F3_NEURAL_UNCERTAIN_STATE
            )
            certain = bool(
                observation.get("certain")
            )
            expected = str(row["expected"])
            matched = (
                bool(state == expected)
                if certain
                else None
            )
            result = {
                "mask_id": str(row["mask_id"]),
                "expected": expected,
                "expected_label": DISPLAY_AUTO_CLASS_LABELS[
                    expected
                ],
                "classified": state,
                "classified_label": (
                    DISPLAY_AUTO_CLASS_LABELS[state]
                    if state in DISPLAY_AUTO_CLASS_LABELS
                    else "INCERTO"
                ),
                "matched": matched,
                "raw_matched": matched,
                "confidence": float(
                    observation.get("confidence", 0.0)
                    or 0.0
                ),
                "neural_certain": certain,
                "neural_probabilities": deepcopy(
                    observation.get("probabilities") or {}
                ),
                "neural_logits": list(
                    observation.get("logits") or ()
                ),
                "classification_source": F3_H1_NEURAL_AUTHORITY,
                "reference_source": F3_H1_NEURAL_AUTHORITY,
                "luminous_core_confirmed": bool(
                    certain
                    and state == DISPLAY_CHECK_STATE_ON
                ),
            }
            results.append(result)

        uncertain_count = sum(
            1
            for item in results
            if not bool(item.get("neural_certain"))
        )
        matched_count = sum(
            1
            for item in results
            if item.get("matched") is True
        )
        approved = bool(
            results
            and uncertain_count == 0
            and matched_count == len(results)
        )

        reason_prefix = (
            "h1"
            if neural_check_index == 0
            else "blue"
        )
        if uncertain_count:
            reason = f"{reason_prefix}_neural_incerto"
        elif approved:
            reason = f"{reason_prefix}_neural_conforme"
        else:
            reason = f"{reason_prefix}_neural_divergente"

        metadata = self.presence_store.get(
            project_name,
            check_id,
        )
        presence = avaliar_referencia_presenca_display(
            frame,
            metadata,
        )
        presence["decision_authority"] = False
        presence["role"] = (
            "check_photo_diagnostic_only_neural"
        )

        return {
            "ready": True,
            "approved": bool(approved),
            "reason": reason,
            "project_name": str(project_name),
            "check_id": str(check_id),
            "check_name": check_name,
            "mask_results": results,
            "active_mask_count": len(results),
            "matched_mask_count": int(matched_count),
            "uncertain_mask_count": int(uncertain_count),
            "ignored_mask_count": sum(
                1
                for mask in masks
                if states.get(str(mask.get("id")))
                == DISPLAY_CHECK_STATE_IGNORE
            ),
            "reference_authority": F3_H1_NEURAL_AUTHORITY,
            "neural_visual_authority": True,
            "neural_check_scope": F3_NEURAL_CHECK_SCOPE,
            "neural_check_index": int(neural_check_index),
            "neural_stage": (
                "N1" if neural_check_index == 0 else "N2"
            ),
            "neural_batch_size": len(results),
            "neural_model": {
                key: deepcopy(value)
                for key, value in inference.items()
                if key != "observations"
            },
            "conventional_visual_authority_used": False,
            "presence_reference": presence,
            "live_geometry_override": bool(
                use_geometry_override
            ),
            "live_geometry_source": (
                str(mask_geometry_source or "")
                if use_geometry_override
                else ""
            ),
        }


# Compatibilidade de import para extensões externas antigas. Internamente, o
# proprietário canônico é F3NeuralCheckAnalyzer.
F3H1NeuralAnalyzer = F3NeuralCheckAnalyzer


_INSTALLED = False


def instalar_autoridade_neural_h1_blue_display_f3() -> None:
    """Torna a CNN a única autoridade semântica de H1 e BLUE."""
    global _INSTALLED

    # Reaplicado mesmo depois do guard, pois instaladores históricos alteram os
    # aliases durante o bootstrap. A autoridade neural deve ficar literalmente
    # por último para os CHECKS já migrados.
    runtime_module.DisplayAutomaticCheckAnalyzer = F3NeuralCheckAnalyzer
    live_runtime_module.DisplayAutomaticCheckAnalyzer = F3NeuralCheckAnalyzer
    runtime_module._display_f3_neural_authority = True
    # Marcadores nominais preservados somente para compatibilidade de telemetria.
    runtime_module._display_f3_h1_neural_authority = True
    runtime_module._display_f3_blue_neural_authority = True

    if _INSTALLED:
        return
    _INSTALLED = True


def instalar_autoridade_neural_h1_display_f3() -> None:
    """Compatibilidade: delega para a autoridade neural N2 canônica."""
    instalar_autoridade_neural_h1_blue_display_f3()
