from __future__ import annotations

"""Inferência neural leve para aquisição geométrica do Display F3.

Este módulo NÃO decide ON/OFF nem OK/NG. A rede prevê apenas quatro âncoras
geométricas do contorno canônico no frame atual. A pose final ainda precisa ser
validada/snapada pela geometria estrutural do tracker antes de virar LOCK.

Treino é offline. Produção usa somente OpenCV DNN + ONNX local.
"""

import hashlib
import json
import math
import re
import time
from pathlib import Path

import cv2
import numpy as np


F3_NEURAL_TRACKING_SCHEMA_VERSION = 1
F3_NEURAL_TRACKING_MODEL_TYPE = "f3_display_pose_regressor"
F3_NEURAL_TRACKING_INPUT_WIDTH = 192
F3_NEURAL_TRACKING_INPUT_HEIGHT = 108
F3_NEURAL_TRACKING_MODEL_REFRESH_S = 1.0
F3_NEURAL_TRACKING_OUTPUT_MIN_NORMALIZED = -0.35
F3_NEURAL_TRACKING_OUTPUT_MAX_NORMALIZED = 1.35


def _slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip())
    return text.strip("_").lower() or "display"


def f3_neural_tracking_model_path(repository, project_name: str) -> Path:
    config_file = Path(
        getattr(
            repository,
            "config_file",
            "data/config/odin_display_projects.json",
        )
    )
    parent = config_file.parent
    if parent.name == "config" and parent.parent.name == "data":
        root = parent.parent / "models" / "f3_tracking"
    else:
        root = parent / "models" / "f3_tracking"
    return root / f"{_slug(project_name)}_pose.onnx"


def f3_neural_tracking_metadata_path(repository, project_name: str) -> Path:
    return f3_neural_tracking_model_path(
        repository,
        project_name,
    ).with_suffix(".json")


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


def _valid_frame(frame) -> bool:
    return frame is not None and getattr(frame, "size", 0) > 0


def _ordered_quad(points) -> np.ndarray | None:
    try:
        data = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    except Exception:
        return None
    if len(data) < 3 or not np.all(np.isfinite(data)):
        return None

    if len(data) != 4:
        try:
            rect = cv2.minAreaRect(data.reshape(-1, 1, 2))
            data = cv2.boxPoints(rect).astype(np.float32)
        except Exception:
            return None

    center = np.mean(data, axis=0)
    angles = np.arctan2(data[:, 1] - center[1], data[:, 0] - center[0])
    order = np.argsort(angles)
    ordered = data[order]
    start = int(np.argmin(np.sum(ordered, axis=1)))
    ordered = np.roll(ordered, -start, axis=0)

    # Mantém sempre a mesma orientação do ciclo.
    signed = 0.0
    for index in range(4):
        x1, y1 = ordered[index]
        x2, y2 = ordered[(index + 1) % 4]
        signed += float(x1 * y2 - x2 * y1)
    if signed < 0.0:
        ordered = np.concatenate(
            (ordered[:1], ordered[:0:-1]),
            axis=0,
        )
    return np.ascontiguousarray(ordered, dtype=np.float32)


def canonical_pose_anchors(canonical_board) -> np.ndarray | None:
    """Quatro âncoras canônicas estáveis usadas por treino e runtime."""
    return _ordered_quad(canonical_board)


def canonical_pose_anchor_digest(canonical_board) -> str:
    anchors = canonical_pose_anchors(canonical_board)
    if anchors is None:
        return ""
    payload = json.dumps(
        np.round(anchors.astype(np.float64), 4).tolist(),
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalized_input(frame, width: int, height: int) -> np.ndarray | None:
    if not _valid_frame(frame):
        return None
    try:
        bgr = frame
        if frame.ndim == 2:
            bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif frame.ndim == 3 and frame.shape[2] == 4:
            bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        elif frame.ndim != 3 or frame.shape[2] != 3:
            return None
        resized = cv2.resize(
            bgr,
            (int(width), int(height)),
            interpolation=(
                cv2.INTER_AREA
                if bgr.shape[1] > int(width) or bgr.shape[0] > int(height)
                else cv2.INTER_LINEAR
            ),
        )
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    except Exception:
        return None
    tensor = rgb.astype(np.float32) / np.float32(255.0)
    return np.ascontiguousarray(
        tensor.transpose(2, 0, 1)[None, ...],
        dtype=np.float32,
    )


class F3NeuralPoseDetector:
    """Carrega uma CNN local de pose e prevê âncoras do Display no frame RAW."""

    def __init__(self, repository) -> None:
        self.repository = repository
        self._project_name = ""
        self._model_signature = None
        self._net = None
        self._metadata: dict = {}
        self._status: dict = {}
        self._last_prepare_s = 0.0

    def invalidate(self) -> None:
        self._project_name = ""
        self._model_signature = None
        self._net = None
        self._metadata = {}
        self._status = {}
        self._last_prepare_s = 0.0

    @staticmethod
    def _file_signature(path: Path) -> tuple[str, int, int]:
        try:
            stat = path.stat()
            return str(path), int(stat.st_mtime_ns), int(stat.st_size)
        except OSError:
            return str(path), 0, 0

    def prepare(self, project_name: str, canonical_board) -> dict:
        name = str(project_name or "").strip()
        model_path = f3_neural_tracking_model_path(self.repository, name)
        metadata_path = f3_neural_tracking_metadata_path(self.repository, name)
        signature = (
            self._file_signature(model_path),
            self._file_signature(metadata_path),
            canonical_pose_anchor_digest(canonical_board),
        )

        now = time.monotonic()
        if (
            self._model_signature == signature
            and self._project_name == name
            and self._status
            and (
                bool(self._status.get("ready"))
                or now - float(self._last_prepare_s or 0.0)
                < F3_NEURAL_TRACKING_MODEL_REFRESH_S
            )
        ):
            return dict(self._status)

        self._last_prepare_s = now
        self._project_name = name
        self._model_signature = signature
        self._net = None
        self._metadata = {}

        if not name:
            self._status = {
                "ready": False,
                "reason": "neural_tracking_project_missing",
            }
            return dict(self._status)
        if not model_path.is_file() or not metadata_path.is_file():
            self._status = {
                "ready": False,
                "reason": "neural_tracking_model_missing",
                "model_path": str(model_path),
                "metadata_path": str(metadata_path),
            }
            return dict(self._status)

        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            self._status = {
                "ready": False,
                "reason": "neural_tracking_metadata_invalid",
            }
            return dict(self._status)

        if (
            int(metadata.get("schema_version", 0) or 0)
            != F3_NEURAL_TRACKING_SCHEMA_VERSION
            or str(metadata.get("model_type") or "")
            != F3_NEURAL_TRACKING_MODEL_TYPE
        ):
            self._status = {
                "ready": False,
                "reason": "neural_tracking_metadata_incompatible",
            }
            return dict(self._status)

        expected_digest = canonical_pose_anchor_digest(canonical_board)
        if (
            not expected_digest
            or str(metadata.get("canonical_anchor_digest") or "")
            != expected_digest
        ):
            self._status = {
                "ready": False,
                "reason": "neural_tracking_geometry_changed",
            }
            return dict(self._status)

        expected_hash = str(metadata.get("onnx_sha256") or "")
        actual_hash = _sha256_file(model_path)
        if not expected_hash or expected_hash != actual_hash:
            self._status = {
                "ready": False,
                "reason": "neural_tracking_model_hash_mismatch",
            }
            return dict(self._status)

        validation = (
            metadata.get("validation")
            if isinstance(metadata.get("validation"), dict)
            else {}
        )
        if validation.get("accepted_for_runtime") is not True:
            self._status = {
                "ready": False,
                "reason": "neural_tracking_model_not_validated",
            }
            return dict(self._status)

        input_width = int(
            metadata.get("input_width", F3_NEURAL_TRACKING_INPUT_WIDTH)
            or F3_NEURAL_TRACKING_INPUT_WIDTH
        )
        input_height = int(
            metadata.get("input_height", F3_NEURAL_TRACKING_INPUT_HEIGHT)
            or F3_NEURAL_TRACKING_INPUT_HEIGHT
        )
        if input_width < 32 or input_height < 32:
            self._status = {
                "ready": False,
                "reason": "neural_tracking_input_invalid",
            }
            return dict(self._status)

        try:
            net = cv2.dnn.readNetFromONNX(str(model_path))
        except Exception:
            self._status = {
                "ready": False,
                "reason": "neural_tracking_onnx_load_failed",
            }
            return dict(self._status)

        self._net = net
        self._metadata = metadata
        self._status = {
            "ready": True,
            "reason": "neural_tracking_model_ready",
            "model_path": str(model_path),
            "metadata_path": str(metadata_path),
            "input_width": input_width,
            "input_height": input_height,
            "validation": dict(validation),
        }
        return dict(self._status)

    def predict(
        self,
        frame,
        *,
        project_name: str,
        canonical_board,
    ) -> dict:
        status = self.prepare(project_name, canonical_board)
        if not bool(status.get("ready")) or self._net is None:
            return dict(status)
        if not _valid_frame(frame):
            return {
                **status,
                "ready": False,
                "reason": "neural_tracking_frame_invalid",
            }

        input_width = int(status["input_width"])
        input_height = int(status["input_height"])
        tensor = _normalized_input(frame, input_width, input_height)
        if tensor is None:
            return {
                **status,
                "ready": False,
                "reason": "neural_tracking_preprocess_failed",
            }

        started = time.perf_counter()
        try:
            self._net.setInput(tensor)
            output = np.asarray(
                self._net.forward(),
                dtype=np.float32,
            ).reshape(-1)
        except Exception:
            return {
                **status,
                "ready": False,
                "reason": "neural_tracking_inference_failed",
            }
        elapsed_ms = max(
            0.0,
            (time.perf_counter() - started) * 1000.0,
        )
        if output.size != 8 or not np.all(np.isfinite(output)):
            return {
                **status,
                "ready": False,
                "reason": "neural_tracking_output_invalid",
                "inference_ms": round(elapsed_ms, 3),
            }

        normalized = output.reshape(4, 2)
        # O contorno físico pode tocar/sair levemente do frame quando a placa
        # muda de pose. O modelo D-067 é treinado explicitamente para essa faixa
        # estendida; ainda rejeitamos qualquer artefato que projete pontos
        # absurdamente distantes da imagem.
        try:
            output_min = float(
                self._metadata.get(
                    "output_min_normalized",
                    F3_NEURAL_TRACKING_OUTPUT_MIN_NORMALIZED,
                )
            )
            output_max = float(
                self._metadata.get(
                    "output_max_normalized",
                    F3_NEURAL_TRACKING_OUTPUT_MAX_NORMALIZED,
                )
            )
        except (TypeError, ValueError):
            output_min = F3_NEURAL_TRACKING_OUTPUT_MIN_NORMALIZED
            output_max = F3_NEURAL_TRACKING_OUTPUT_MAX_NORMALIZED
        if (
            float(np.min(normalized)) < output_min - 0.02
            or float(np.max(normalized)) > output_max + 0.02
        ):
            return {
                **status,
                "ready": False,
                "reason": "neural_tracking_output_out_of_range",
                "inference_ms": round(elapsed_ms, 3),
            }

        frame_h, frame_w = frame.shape[:2]
        current_anchors = normalized.copy()
        current_anchors[:, 0] *= float(frame_w)
        current_anchors[:, 1] *= float(frame_h)

        canonical = canonical_pose_anchors(canonical_board)
        if canonical is None:
            return {
                **status,
                "ready": False,
                "reason": "neural_tracking_canonical_anchors_invalid",
                "inference_ms": round(elapsed_ms, 3),
            }

        try:
            matrix, _inliers = cv2.estimateAffinePartial2D(
                current_anchors.reshape(-1, 1, 2),
                canonical.reshape(-1, 1, 2),
                method=cv2.LMEDS,
            )
        except Exception:
            matrix = None
        if matrix is None:
            return {
                **status,
                "ready": False,
                "reason": "neural_tracking_affine_failed",
                "inference_ms": round(elapsed_ms, 3),
            }

        projected = cv2.transform(
            current_anchors.reshape(-1, 1, 2),
            np.asarray(matrix, dtype=np.float32).reshape(2, 3),
        ).reshape(-1, 2)
        errors = np.linalg.norm(projected - canonical, axis=1)
        mean_error = float(np.mean(errors))
        max_error = float(np.max(errors))

        return {
            **status,
            "ready": True,
            "reason": "neural_tracking_pose_prior_ready",
            "matrix": np.asarray(matrix, dtype=np.float32).reshape(2, 3),
            "current_anchors": np.asarray(
                current_anchors,
                dtype=np.float32,
            ),
            "canonical_anchors": np.asarray(canonical, dtype=np.float32),
            "anchor_fit_mean_px": round(mean_error, 4),
            "anchor_fit_max_px": round(max_error, 4),
            "inference_ms": round(elapsed_ms, 3),
            "model_validation_mean_px": (
                self._metadata.get("validation", {})
                .get("augmented_mean_anchor_error_px")
            ),
            "model_validation_p95_px": (
                self._metadata.get("validation", {})
                .get("augmented_p95_anchor_error_px")
            ),
        }
