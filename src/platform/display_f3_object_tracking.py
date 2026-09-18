from __future__ import annotations

"""Rastreamento de objetos exclusivo do Display F3.

Este módulo não reutiliza nem modifica estado, arquivos ou classes de runtime do F2.
O F3 possui:
- flag própria ``display_f3_object_tracking_enabled``;
- arquivo próprio ``odin_display_tracking.json``;
- referências reais 90°/180°/270° por Projeto Display;
- rastreador ORB/RANSAC próprio;
- alinhamento do frame atual para o sistema canônico do Projeto Display.

Quando a opção está desligada, o pipeline F3 recebe literalmente o mesmo frame que
recebia antes deste módulo.
"""

import base64
import json
import math
import re
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from src.platform.display_check_presence_reference import (
    DisplayCheckPresenceReferenceStore,
)
from src.platform.display_mask_geometry import (
    bbox_mascara_display,
    converter_mascara_legada_para_editor,
    pontos_mascara_display,
)
from src.platform.display_project_repository import (
    DisplayProjectRepository,
    normalizar_mascaras_display,
    normalizar_nome_projeto_display,
    normalizar_resolucao_display,
)
from src.platform.display_visual_reference_status import (
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
    DisplayProjectPresenceReferenceStore,
)


F3_TRACKING_SCHEMA_VERSION = 1
F3_TRACKING_CONFIG_FILENAME = "odin_display_tracking.json"
F3_TRACKING_IMAGE_DIRNAME = "display_tracking_orientations"
F3_TRACKING_SETTING_KEY = "display_f3_object_tracking_enabled"

F3_ORIENTATION_90 = "orientation_90"
F3_ORIENTATION_180 = "orientation_180"
F3_ORIENTATION_270 = "orientation_270"
F3_ORIENTATION_SLOTS = (
    F3_ORIENTATION_90,
    F3_ORIENTATION_180,
    F3_ORIENTATION_270,
)
F3_ORIENTATION_ANGLE = {
    F3_ORIENTATION_90: 90.0,
    F3_ORIENTATION_180: 180.0,
    F3_ORIENTATION_270: 270.0,
}
F3_ORIENTATION_UI = {
    F3_ORIENTATION_90: {
        "title": "Rotação real 90°",
        "short": "90°",
        "color": "#7DD3FC",
    },
    F3_ORIENTATION_180: {
        "title": "Rotação real 180°",
        "short": "180°",
        "color": "#C4B5FD",
    },
    F3_ORIENTATION_270: {
        "title": "Rotação real 270°",
        "short": "270°",
        "color": "#67E8F9",
    },
}

F3_TRACKING_REFRESH_S = 0.12
F3_TRACKING_ORB_FEATURES = 1600
F3_TRACKING_RATIO_TEST = 0.75
F3_TRACKING_MIN_MATCHES = 12
F3_TRACKING_MIN_INLIERS = 8
F3_TRACKING_MIN_INLIER_RATIO = 0.34
F3_TRACKING_RANSAC_THRESHOLD_PX = 4.0
F3_TRACKING_MIN_SCALE = 0.72
F3_TRACKING_MAX_SCALE = 1.38
F3_TRACKING_MAX_TRANSLATION_FRACTION = 1.25
F3_TRACKING_BOARD_PADDING_FRACTION = 0.10
F3_TRACKING_MASK_EXCLUSION_PADDING_PX = 7

F3_TRACKING_MASK_BGR = (21, 204, 250)
F3_TRACKING_BOARD_BGR = (248, 189, 56)
F3_TRACKING_SELECTED_BGR = (94, 234, 212)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str | None) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip())
    return text.strip("_").lower() or "display"


def _valid_frame(frame) -> bool:
    return frame is not None and getattr(frame, "size", 0) > 0


def _normalize_matrix(value) -> list[list[float]] | None:
    try:
        matrix = np.asarray(value, dtype=np.float32).reshape(2, 3)
    except Exception:
        return None
    if not np.all(np.isfinite(matrix)):
        return None
    return [[float(v) for v in row] for row in matrix]


def matrix_np(entry: dict | None) -> np.ndarray | None:
    if not isinstance(entry, dict):
        return None
    normalized = _normalize_matrix(entry.get("canonical_to_reference"))
    if normalized is None:
        return None
    return np.asarray(normalized, dtype=np.float32).reshape(2, 3)


def _normalize_points(value, minimum: int = 3) -> list[list[float]]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[list[float]] = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            x = float(item[0])
            y = float(item[1])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(x) or not math.isfinite(y):
            continue
        result.append([x, y])
    return result if len(result) >= int(minimum) else []


def _normalize_mask_override(mask) -> dict | None:
    if not isinstance(mask, dict):
        return None
    kind = str(mask.get("type") or "").strip().lower()
    mask_id = str(mask.get("id") or "").strip()
    if not mask_id:
        return None
    try:
        if kind == "circle":
            return {
                "id": mask_id,
                "type": "circle",
                "cx": float(mask.get("cx")),
                "cy": float(mask.get("cy")),
                "radius": max(1.0, float(mask.get("radius"))),
            }
        points = _normalize_points(mask.get("points"), minimum=3)
        if points:
            return {
                "id": mask_id,
                "type": "polygon",
                "points": points,
            }
    except (TypeError, ValueError):
        return None
    return None


def _normalize_orientation_entry(value, slot: str) -> dict:
    if not isinstance(value, dict):
        return {}
    image_path = str(value.get("image_path") or "").strip()
    if not image_path:
        return {}
    try:
        width = max(0, int(value.get("width") or 0))
        height = max(0, int(value.get("height") or 0))
    except (TypeError, ValueError):
        width = height = 0

    matrix = _normalize_matrix(value.get("canonical_to_reference"))
    board_points = _normalize_points(value.get("board_points_reference"), minimum=3)
    overrides = {}
    raw_overrides = value.get("mask_overrides_reference", {})
    if isinstance(raw_overrides, dict):
        for key, raw in raw_overrides.items():
            normalized = _normalize_mask_override(raw)
            if normalized is not None:
                normalized["id"] = str(key or normalized.get("id") or "").strip()
                if normalized["id"]:
                    overrides[normalized["id"]] = normalized

    result = {
        "image_path": image_path,
        "width": width,
        "height": height,
        "angle_deg": float(F3_ORIENTATION_ANGLE.get(slot, 0.0)),
        "canonical_to_reference": matrix,
        "calibrated": bool(value.get("calibrated", False) and matrix is not None),
        "updated_at": str(value.get("updated_at") or ""),
    }
    if board_points:
        result["board_points_reference"] = board_points
    if overrides:
        result["mask_overrides_reference"] = overrides
    return result


class F3TrackingConfigStore:
    """Sidecar exclusivo do rastreamento do Display F3."""

    def __init__(self, repository: DisplayProjectRepository) -> None:
        self.repository = repository
        config_file = Path(
            getattr(repository, "config_file", "data/config/odin_display_projects.json")
        )
        self.config_file = config_file.parent / F3_TRACKING_CONFIG_FILENAME
        self.image_dir = config_file.parent / F3_TRACKING_IMAGE_DIRNAME

    @staticmethod
    def _empty() -> dict:
        return {
            "schema_version": F3_TRACKING_SCHEMA_VERSION,
            F3_TRACKING_SETTING_KEY: False,
            "projects": {},
        }

    def _load(self) -> dict:
        if not self.config_file.exists():
            return self._empty()
        try:
            data = json.loads(self.config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return self._empty()
        if not isinstance(data, dict):
            return self._empty()

        projects = {}
        source_projects = data.get("projects", {})
        if isinstance(source_projects, dict):
            for raw_name, raw_project in source_projects.items():
                name = normalizar_nome_projeto_display(raw_name)
                if not name or not isinstance(raw_project, dict):
                    continue
                board_points = _normalize_points(
                    raw_project.get("board_points"),
                    minimum=3,
                )
                raw_orientations = raw_project.get("orientations", {})
                orientations = {}
                for slot in F3_ORIENTATION_SLOTS:
                    normalized = _normalize_orientation_entry(
                        raw_orientations.get(slot) if isinstance(raw_orientations, dict) else None,
                        slot,
                    )
                    if normalized:
                        orientations[slot] = normalized
                projects[name] = {
                    "board_points": board_points,
                    "orientations": orientations,
                    "updated_at": str(raw_project.get("updated_at") or ""),
                }

        return {
            "schema_version": F3_TRACKING_SCHEMA_VERSION,
            F3_TRACKING_SETTING_KEY: bool(data.get(F3_TRACKING_SETTING_KEY, False)),
            "projects": projects,
        }

    def _write(self, data: dict) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        normalized = self._empty()
        normalized[F3_TRACKING_SETTING_KEY] = bool(
            data.get(F3_TRACKING_SETTING_KEY, False)
        )
        source_projects = data.get("projects", {})
        if isinstance(source_projects, dict):
            for raw_name, raw_project in source_projects.items():
                name = normalizar_nome_projeto_display(raw_name)
                if not name or not isinstance(raw_project, dict):
                    continue
                board_points = _normalize_points(raw_project.get("board_points"), minimum=3)
                orientations = {}
                raw_orientations = raw_project.get("orientations", {})
                for slot in F3_ORIENTATION_SLOTS:
                    entry = _normalize_orientation_entry(
                        raw_orientations.get(slot) if isinstance(raw_orientations, dict) else None,
                        slot,
                    )
                    if entry:
                        orientations[slot] = entry
                normalized["projects"][name] = {
                    "board_points": board_points,
                    "orientations": orientations,
                    "updated_at": str(raw_project.get("updated_at") or ""),
                }

        temporary = self.config_file.with_suffix(self.config_file.suffix + ".tmp")
        temporary.write_text(
            json.dumps(normalized, indent=4, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self.config_file)

    def enabled(self) -> bool:
        return bool(self._load().get(F3_TRACKING_SETTING_KEY, False))

    def set_enabled(self, enabled: bool) -> None:
        data = self._load()
        data[F3_TRACKING_SETTING_KEY] = bool(enabled)
        self._write(data)

    def project(self, project_name: str) -> dict:
        name = normalizar_nome_projeto_display(project_name)
        raw = self._load().get("projects", {}).get(name, {})
        return deepcopy(raw) if isinstance(raw, dict) else {
            "board_points": [],
            "orientations": {},
            "updated_at": "",
        }

    def board_points(self, project_name: str) -> list[list[float]]:
        return _normalize_points(self.project(project_name).get("board_points"), minimum=3)

    def save_board_points(self, project_name: str, points) -> bool:
        name = normalizar_nome_projeto_display(project_name)
        normalized = _normalize_points(points, minimum=3)
        if not name or not normalized:
            return False
        data = self._load()
        project = data["projects"].setdefault(
            name,
            {"board_points": [], "orientations": {}, "updated_at": ""},
        )
        project["board_points"] = normalized
        project["updated_at"] = _utc_now()
        self._write(data)
        return True

    def orientations(self, project_name: str) -> dict[str, dict]:
        project = self.project(project_name)
        raw = project.get("orientations", {})
        return {
            slot: deepcopy(raw.get(slot, {})) if isinstance(raw, dict) else {}
            for slot in F3_ORIENTATION_SLOTS
        }

    def save_orientation(
        self,
        project_name: str,
        slot: str,
        entry: dict | None,
    ) -> bool:
        name = normalizar_nome_projeto_display(project_name)
        if not name or slot not in F3_ORIENTATION_SLOTS:
            return False
        data = self._load()
        project = data["projects"].setdefault(
            name,
            {"board_points": [], "orientations": {}, "updated_at": ""},
        )
        orientations = project.setdefault("orientations", {})
        if entry is None:
            orientations.pop(slot, None)
        else:
            normalized = _normalize_orientation_entry(entry, slot)
            if not normalized:
                return False
            orientations[slot] = normalized
        project["updated_at"] = _utc_now()
        self._write(data)
        return True

    def managed_image_path(self, project_name: str, slot: str) -> Path:
        directory = self.image_dir / _slug(project_name)
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{slot}.png"

    def remove_orientation(self, project_name: str, slot: str) -> bool:
        entry = self.orientations(project_name).get(slot, {})
        changed = self.save_orientation(project_name, slot, None)
        path = Path(str(entry.get("image_path") or ""))
        try:
            if path.is_file() and self.image_dir.resolve() in path.resolve().parents:
                path.unlink()
        except OSError:
            pass
        return changed


def canonical_board_points(project: dict, store: F3TrackingConfigStore) -> list[list[float]]:
    """Retorna o contorno compartilhado do display/placa em coordenadas mestre."""
    project_name = str(project.get("name") or "")
    saved = store.board_points(project_name)
    if saved:
        return saved

    resolution = normalizar_resolucao_display(project.get("master_resolution"))
    masks = [
        converter_mascara_legada_para_editor(mask)
        for mask in normalizar_mascaras_display(project.get("masks", []))
    ]
    if resolution is None or not masks:
        return []
    width, height = int(resolution[0]), int(resolution[1])

    boxes = [bbox_mascara_display(mask) for mask in masks]
    min_x = min(item[0] for item in boxes)
    min_y = min(item[1] for item in boxes)
    max_x = max(item[2] for item in boxes)
    max_y = max(item[3] for item in boxes)
    span_x = max(1.0, max_x - min_x)
    span_y = max(1.0, max_y - min_y)
    padding_x = max(18.0, span_x * F3_TRACKING_BOARD_PADDING_FRACTION)
    padding_y = max(18.0, span_y * F3_TRACKING_BOARD_PADDING_FRACTION)
    x1 = max(0.0, min_x - padding_x)
    y1 = max(0.0, min_y - padding_y)
    x2 = min(float(width - 1), max_x + padding_x)
    y2 = min(float(height - 1), max_y + padding_y)
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def transform_points(points, matrix) -> list[list[float]]:
    source = _normalize_points(points, minimum=1)
    if not source:
        return []
    try:
        affine = np.asarray(matrix, dtype=np.float32).reshape(2, 3)
        values = np.asarray(source, dtype=np.float32).reshape(-1, 1, 2)
        transformed = cv2.transform(values, affine).reshape(-1, 2)
        return [[float(x), float(y)] for x, y in transformed]
    except Exception:
        return []


def affine_scale(matrix) -> float:
    try:
        affine = np.asarray(matrix, dtype=np.float32).reshape(2, 3)
        sx = math.hypot(float(affine[0, 0]), float(affine[1, 0]))
        sy = math.hypot(float(affine[0, 1]), float(affine[1, 1]))
        return max(1e-6, (sx + sy) / 2.0)
    except Exception:
        return 1.0


def affine_rotation_deg(matrix) -> float:
    try:
        affine = np.asarray(matrix, dtype=np.float32).reshape(2, 3)
        return math.degrees(
            math.atan2(float(affine[1, 0]), float(affine[0, 0]))
        )
    except Exception:
        return 0.0


def nominal_orientation_matrix(
    project: dict,
    store: F3TrackingConfigStore,
    slot: str,
) -> np.ndarray | None:
    resolution = normalizar_resolucao_display(project.get("master_resolution"))
    points = canonical_board_points(project, store)
    if resolution is None or not points or slot not in F3_ORIENTATION_SLOTS:
        return None
    width, height = int(resolution[0]), int(resolution[1])
    values = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    center = np.mean(values, axis=0)
    matrix = cv2.getRotationMatrix2D(
        (float(center[0]), float(center[1])),
        float(F3_ORIENTATION_ANGLE[slot]),
        1.0,
    ).astype(np.float32)

    rotated = cv2.transform(values.reshape(-1, 1, 2), matrix).reshape(-1, 2)
    bbox_center = np.asarray(
        [
            (float(np.min(rotated[:, 0])) + float(np.max(rotated[:, 0]))) / 2.0,
            (float(np.min(rotated[:, 1])) + float(np.max(rotated[:, 1]))) / 2.0,
        ],
        dtype=np.float32,
    )
    target = np.asarray([width / 2.0, height / 2.0], dtype=np.float32)
    delta = target - bbox_center
    matrix[0, 2] += float(delta[0])
    matrix[1, 2] += float(delta[1])
    return matrix


def transform_mask(mask: dict, matrix) -> dict | None:
    if not isinstance(mask, dict):
        return None
    source = converter_mascara_legada_para_editor(mask)
    kind = str(source.get("type") or "").lower()
    mask_id = str(source.get("id") or "")
    if not mask_id:
        return None
    try:
        affine = np.asarray(matrix, dtype=np.float32).reshape(2, 3)
    except Exception:
        return None

    if kind == "circle":
        point = affine @ np.asarray(
            [float(source.get("cx", 0)), float(source.get("cy", 0)), 1.0],
            dtype=np.float32,
        )
        return {
            "id": mask_id,
            "type": "circle",
            "cx": float(point[0]),
            "cy": float(point[1]),
            "radius": max(1.0, float(source.get("radius", 1)) * affine_scale(affine)),
        }

    points = pontos_mascara_display(source)
    transformed = transform_points(points, affine)
    if len(transformed) < 3:
        return None
    return {
        "id": mask_id,
        "type": "polygon",
        "points": transformed,
    }


def transformed_masks(project: dict, matrix) -> list[dict]:
    result = []
    for mask in normalizar_mascaras_display(project.get("masks", [])):
        item = transform_mask(mask, matrix)
        if item is not None:
            result.append(item)
    return result


def reference_geometry(
    project: dict,
    store: F3TrackingConfigStore,
    slot: str,
    entry: dict | None = None,
) -> tuple[list[list[float]], list[dict]]:
    current = entry if isinstance(entry, dict) else store.orientations(
        str(project.get("name") or "")
    ).get(slot, {})
    matrix = matrix_np(current)
    if matrix is None:
        matrix = nominal_orientation_matrix(project, store, slot)
    if matrix is None:
        return [], []

    board = _normalize_points(
        (current or {}).get("board_points_reference"),
        minimum=3,
    )
    if not board:
        board = transform_points(canonical_board_points(project, store), matrix)

    defaults = transformed_masks(project, matrix)
    overrides = (current or {}).get("mask_overrides_reference", {})
    if not isinstance(overrides, dict):
        overrides = {}
    masks = []
    for mask in defaults:
        override = _normalize_mask_override(overrides.get(str(mask.get("id") or "")))
        masks.append(override if override is not None else mask)
    return board, masks


def draw_reference_geometry(
    image,
    board_points,
    masks,
    *,
    alpha: float = 0.42,
    selected_mask_id: str | None = None,
):
    if not _valid_frame(image):
        return image
    base = image.copy()
    overlay = image.copy()

    board = _normalize_points(board_points, minimum=3)
    if board:
        polygon = np.rint(np.asarray(board, dtype=np.float32)).astype(np.int32)
        cv2.polylines(
            overlay,
            [polygon],
            True,
            F3_TRACKING_BOARD_BGR,
            3,
            cv2.LINE_AA,
        )

    for mask in tuple(masks or ()):
        if not isinstance(mask, dict):
            continue
        color = (
            F3_TRACKING_SELECTED_BGR
            if str(mask.get("id") or "") == str(selected_mask_id or "")
            else F3_TRACKING_MASK_BGR
        )
        kind = str(mask.get("type") or "").lower()
        try:
            if kind == "circle":
                center = (
                    int(round(float(mask.get("cx", 0)))),
                    int(round(float(mask.get("cy", 0)))),
                )
                radius = max(1, int(round(float(mask.get("radius", 1)))))
                cv2.circle(overlay, center, radius, color, 2, cv2.LINE_AA)
            else:
                points = _normalize_points(mask.get("points"), minimum=3)
                if not points:
                    continue
                polygon = np.rint(np.asarray(points, dtype=np.float32)).astype(np.int32)
                cv2.polylines(
                    overlay,
                    [polygon],
                    True,
                    color,
                    2,
                    cv2.LINE_AA,
                )
        except Exception:
            continue

    return cv2.addWeighted(
        overlay,
        max(0.0, min(1.0, float(alpha))),
        base,
        1.0 - max(0.0, min(1.0, float(alpha))),
        0.0,
    )


def photo_from_bgr(image, width: int, height: int):
    if not _valid_frame(image):
        return None
    h, w = image.shape[:2]
    scale = min(max(1, int(width)) / float(w), max(1, int(height)) / float(h))
    tw = max(1, int(round(w * scale)))
    th = max(1, int(round(h * scale)))
    resized = cv2.resize(image, (tw, th), interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".png", resized)
    if not ok:
        return None
    import tkinter as tk
    return tk.PhotoImage(data=base64.b64encode(buffer).decode("ascii"))


def _draw_polygon_mask(
    target: np.ndarray,
    points,
    value: int,
    padding: int = 0,
) -> None:
    normalized = _normalize_points(points, minimum=3)
    if not normalized:
        return
    polygon = np.rint(np.asarray(normalized, dtype=np.float32)).astype(np.int32)
    cv2.fillPoly(target, [polygon], int(value), lineType=cv2.LINE_AA)
    if padding > 0:
        x, y, w, h = cv2.boundingRect(polygon)
        cv2.rectangle(
            target,
            (max(0, x - padding), max(0, y - padding)),
            (
                min(target.shape[1] - 1, x + w + padding),
                min(target.shape[0] - 1, y + h + padding),
            ),
            int(value),
            -1,
        )


def build_tracking_mask(
    width: int,
    height: int,
    board_points,
    masks,
) -> np.ndarray | None:
    if width < 1 or height < 1:
        return None
    mask = np.zeros((int(height), int(width)), dtype=np.uint8)
    _draw_polygon_mask(mask, board_points, 255)
    if int(cv2.countNonZero(mask)) < 800:
        return None

    for item in tuple(masks or ()):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "").lower()
        try:
            if kind == "circle":
                center = (
                    int(round(float(item.get("cx", 0)))),
                    int(round(float(item.get("cy", 0)))),
                )
                radius = max(1, int(round(float(item.get("radius", 1)))))
                cv2.circle(
                    mask,
                    center,
                    radius + F3_TRACKING_MASK_EXCLUSION_PADDING_PX,
                    0,
                    -1,
                )
            else:
                _draw_polygon_mask(
                    mask,
                    item.get("points"),
                    0,
                    padding=F3_TRACKING_MASK_EXCLUSION_PADDING_PX,
                )
        except Exception:
            continue

    if int(cv2.countNonZero(mask)) < 500:
        return None
    return mask


@dataclass
class F3TrackingResult:
    locked: bool
    frame: object
    reference: str = ""
    matches: int = 0
    inliers: int = 0
    inlier_ratio: float = 0.0
    rotation_deg: float = 0.0
    scale: float = 1.0
    reason: str = ""


class F3DisplayObjectTracker:
    """ORB/RANSAC independente, sempre produz CURRENT -> CANÔNICO."""

    def __init__(self, repository: DisplayProjectRepository) -> None:
        self.repository = repository
        self.store = F3TrackingConfigStore(repository)
        self.check_store = DisplayCheckPresenceReferenceStore(repository)
        self.project_presence_store = DisplayProjectPresenceReferenceStore(repository)
        self.reset()

    def reset(self) -> None:
        self.project = ""
        self.signature = None
        self.width = 0
        self.height = 0
        self.references: dict[str, dict] = {}
        self.ready = False
        self.reason = "not_configured"
        self.last_matrix: np.ndarray | None = None
        self.last_compute_s = 0.0
        self.last_result: F3TrackingResult | None = None
        self.last_frame_id = None
        self._last_reference = ""

    @staticmethod
    def _gray(image):
        if not _valid_frame(image):
            return None
        try:
            gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            return clahe.apply(gray)
        except Exception:
            return None

    def _canonical_reference_paths(self, project: dict) -> list[tuple[str, str]]:
        project_name = str(project.get("name") or "")
        values: list[tuple[str, str]] = []
        for check in project.get("checks", []) if isinstance(project.get("checks"), list) else []:
            check_id = str((check or {}).get("id") or "")
            if not check_id:
                continue
            metadata = self.check_store.get(project_name, check_id)
            path = str((metadata or {}).get("image_path") or "").strip()
            if path:
                values.append((f"check:{check_id}", path))

        board_off = self.project_presence_store.get(
            project_name,
            DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
        )
        path = str((board_off or {}).get("image_path") or "").strip()
        if path:
            values.append(("board_off", path))
        return values

    @staticmethod
    def _file_signature(path_value: str) -> tuple[str, int, int]:
        path = Path(str(path_value or ""))
        try:
            stat = path.stat()
            return str(path), int(stat.st_mtime_ns), int(stat.st_size)
        except OSError:
            return str(path), 0, 0

    def _signature(self, project: dict, board, orientations) -> tuple:
        canonical = self._canonical_reference_paths(project)
        orientation_files = []
        for slot in F3_ORIENTATION_SLOTS:
            entry = orientations.get(slot, {})
            orientation_files.append(
                (
                    slot,
                    self._file_signature(str(entry.get("image_path") or "")),
                    repr(entry.get("canonical_to_reference")),
                    repr(entry.get("board_points_reference")),
                    repr(entry.get("mask_overrides_reference")),
                )
            )
        return (
            str(project.get("name") or ""),
            repr(project.get("master_resolution")),
            repr(board),
            repr(project.get("masks", [])),
            tuple((key, self._file_signature(path)) for key, path in canonical),
            tuple(orientation_files),
        )

    def _add_reference(
        self,
        refs: dict,
        *,
        key: str,
        image,
        tracking_mask,
        reference_to_canonical,
        angle: float,
        real_orientation: bool,
    ) -> None:
        gray = self._gray(image)
        if gray is None:
            return
        orb = cv2.ORB_create(
            nfeatures=F3_TRACKING_ORB_FEATURES,
            scaleFactor=1.2,
            nlevels=8,
            edgeThreshold=12,
            fastThreshold=7,
        )
        keypoints, descriptors = orb.detectAndCompute(gray, tracking_mask)
        if descriptors is None or len(keypoints) < F3_TRACKING_MIN_MATCHES:
            return

        points = np.asarray([kp.pt for kp in keypoints], dtype=np.float32).reshape(-1, 1, 2)
        try:
            canonical_points = cv2.transform(
                points,
                np.asarray(reference_to_canonical, dtype=np.float32).reshape(2, 3),
            ).reshape(-1, 2)
        except Exception:
            return

        refs[key] = {
            "descriptors": descriptors,
            "canonical_points": canonical_points,
            "angle_deg": float(angle),
            "real_orientation": bool(real_orientation),
        }

    def configure(self, project_name: str | None = None) -> bool:
        name = normalizar_nome_projeto_display(project_name or self.repository.obter_projeto_ativo())
        project = self.repository.carregar_projeto(name)
        if project is None:
            self.reset()
            self.reason = "project_missing"
            return False
        resolution = normalizar_resolucao_display(project.get("master_resolution"))
        if resolution is None:
            self.reset()
            self.reason = "master_resolution_missing"
            return False
        width, height = int(resolution[0]), int(resolution[1])
        board = canonical_board_points(project, self.store)
        if not board:
            self.reset()
            self.reason = "display_shape_missing"
            return False
        orientations = self.store.orientations(name)
        signature = self._signature(project, board, orientations)
        if signature == self.signature:
            return self.ready

        self.reset()
        self.project = name
        self.signature = signature
        self.width = width
        self.height = height

        canonical_masks = [
            converter_mascara_legada_para_editor(mask)
            for mask in normalizar_mascaras_display(project.get("masks", []))
        ]
        canonical_tracking_mask = build_tracking_mask(
            width,
            height,
            board,
            canonical_masks,
        )
        refs: dict[str, dict] = {}

        if canonical_tracking_mask is not None:
            identity = np.asarray(
                [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                dtype=np.float32,
            )
            for key, path in self._canonical_reference_paths(project):
                image = cv2.imread(path, cv2.IMREAD_COLOR)
                if not _valid_frame(image) or image.shape[:2] != (height, width):
                    continue
                self._add_reference(
                    refs,
                    key=key,
                    image=image,
                    tracking_mask=canonical_tracking_mask,
                    reference_to_canonical=identity,
                    angle=0.0,
                    real_orientation=False,
                )

        for slot in F3_ORIENTATION_SLOTS:
            entry = orientations.get(slot, {})
            matrix = matrix_np(entry)
            path = str(entry.get("image_path") or "")
            if not bool(entry.get("calibrated")) or matrix is None or not path:
                continue
            image = cv2.imread(path, cv2.IMREAD_COLOR)
            if not _valid_frame(image) or image.shape[:2] != (height, width):
                continue
            board_ref, masks_ref = reference_geometry(project, self.store, slot, entry)
            tracking_mask = build_tracking_mask(
                width,
                height,
                board_ref,
                masks_ref,
            )
            if tracking_mask is None:
                continue
            try:
                reference_to_canonical = cv2.invertAffineTransform(matrix)
            except Exception:
                continue
            self._add_reference(
                refs,
                key=slot,
                image=image,
                tracking_mask=tracking_mask,
                reference_to_canonical=reference_to_canonical,
                angle=F3_ORIENTATION_ANGLE[slot],
                real_orientation=True,
            )

        if not refs:
            self.reason = "reference_features_insufficient"
            return False

        self.references = refs
        self.ready = True
        self.reason = "ready"
        return True

    def _candidate(self, current_kp, current_desc, key: str):
        ref = self.references[key]
        descriptors = ref["descriptors"]
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        try:
            pairs = matcher.knnMatch(descriptors, current_desc, k=2)
        except Exception:
            return None

        good = []
        for pair in pairs:
            if len(pair) < 2:
                continue
            first, second = pair[0], pair[1]
            if first.distance < F3_TRACKING_RATIO_TEST * second.distance:
                good.append(first)
        if len(good) < F3_TRACKING_MIN_MATCHES:
            return None

        current_points = np.float32(
            [current_kp[item.trainIdx].pt for item in good]
        ).reshape(-1, 1, 2)
        canonical_points = np.float32(
            [ref["canonical_points"][item.queryIdx] for item in good]
        ).reshape(-1, 1, 2)
        matrix, inlier_mask = cv2.estimateAffinePartial2D(
            current_points,
            canonical_points,
            method=cv2.RANSAC,
            ransacReprojThreshold=F3_TRACKING_RANSAC_THRESHOLD_PX,
            maxIters=2500,
            confidence=0.995,
            refineIters=12,
        )
        if matrix is None or inlier_mask is None:
            return None
        inliers = int(np.count_nonzero(inlier_mask))
        ratio = float(inliers / max(1, len(good)))
        if inliers < F3_TRACKING_MIN_INLIERS or ratio < F3_TRACKING_MIN_INLIER_RATIO:
            return None

        scale = affine_scale(matrix)
        rotation = affine_rotation_deg(matrix)
        dx = float(matrix[0, 2])
        dy = float(matrix[1, 2])
        if not (F3_TRACKING_MIN_SCALE <= scale <= F3_TRACKING_MAX_SCALE):
            return None
        if abs(dx) > self.width * F3_TRACKING_MAX_TRANSLATION_FRACTION:
            return None
        if abs(dy) > self.height * F3_TRACKING_MAX_TRANSLATION_FRACTION:
            return None

        score = float(inliers) + ratio * 12.0
        if bool(ref.get("real_orientation")):
            score += 5.0
        return {
            "reference": key,
            "matrix": matrix.astype(np.float32),
            "matches": len(good),
            "inliers": inliers,
            "ratio": ratio,
            "rotation_deg": rotation,
            "scale": scale,
            "score": score,
        }

    def align(self, frame, frame_id=None) -> F3TrackingResult:
        if not _valid_frame(frame):
            return F3TrackingResult(False, frame, reason="invalid_frame")
        if not self.ready:
            return F3TrackingResult(False, frame, reason=self.reason)
        if frame.shape[:2] != (self.height, self.width):
            return F3TrackingResult(False, frame, reason="resolution_mismatch")
        if frame_id is not None and frame_id == self.last_frame_id and self.last_result is not None:
            return self.last_result

        now = time.monotonic()
        if (
            self.last_matrix is not None
            and self.last_result is not None
            and self.last_result.locked
            and now - self.last_compute_s < F3_TRACKING_REFRESH_S
        ):
            aligned = cv2.warpAffine(
                frame,
                self.last_matrix,
                (self.width, self.height),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT101,
            )
            result = F3TrackingResult(
                True,
                aligned,
                reference=self.last_result.reference,
                matches=self.last_result.matches,
                inliers=self.last_result.inliers,
                inlier_ratio=self.last_result.inlier_ratio,
                rotation_deg=self.last_result.rotation_deg,
                scale=self.last_result.scale,
                reason="cached_transform",
            )
            self.last_result = result
            self.last_frame_id = frame_id
            return result

        gray = self._gray(frame)
        if gray is None:
            result = F3TrackingResult(False, frame, reason="gray_prepare_failed")
            self.last_result = result
            self.last_frame_id = frame_id
            return result

        orb = cv2.ORB_create(
            nfeatures=F3_TRACKING_ORB_FEATURES,
            scaleFactor=1.2,
            nlevels=8,
            edgeThreshold=12,
            fastThreshold=7,
        )
        current_kp, current_desc = orb.detectAndCompute(gray, None)
        if current_desc is None or len(current_kp) < F3_TRACKING_MIN_MATCHES:
            self.last_matrix = None
            result = F3TrackingResult(False, frame, reason="current_features_insufficient")
            self.last_result = result
            self.last_frame_id = frame_id
            self.last_compute_s = now
            return result

        candidates = []
        for key in tuple(self.references):
            candidate = self._candidate(current_kp, current_desc, key)
            if candidate is not None:
                candidates.append(candidate)
        if not candidates:
            self.last_matrix = None
            self._last_reference = ""
            result = F3TrackingResult(False, frame, reason="object_not_locked")
            self.last_result = result
            self.last_frame_id = frame_id
            self.last_compute_s = now
            return result

        best = max(candidates, key=lambda item: float(item["score"]))
        matrix = best["matrix"]
        if self.last_matrix is not None and self._last_reference == best["reference"]:
            alpha = 0.58
            matrix = (
                (1.0 - alpha) * self.last_matrix.astype(np.float32)
                + alpha * matrix.astype(np.float32)
            ).astype(np.float32)

        self.last_matrix = matrix
        self._last_reference = str(best["reference"])
        self.last_compute_s = now
        self.last_frame_id = frame_id

        aligned = cv2.warpAffine(
            frame,
            matrix,
            (self.width, self.height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT101,
        )
        result = F3TrackingResult(
            True,
            aligned,
            reference=str(best["reference"]),
            matches=int(best["matches"]),
            inliers=int(best["inliers"]),
            inlier_ratio=float(best["ratio"]),
            rotation_deg=float(best["rotation_deg"]),
            scale=float(best["scale"]),
            reason="locked",
        )
        self.last_result = result
        return result


def get_tracking_runtime(app):
    runtime = getattr(app, "_display_f3_object_tracker", None)
    repository = getattr(app, "display_project_repository", None)
    if repository is None:
        return None
    if not isinstance(runtime, F3DisplayObjectTracker) or runtime.repository is not repository:
        runtime = F3DisplayObjectTracker(repository)
        app._display_f3_object_tracker = runtime
        app._display_f3_object_tracking_enabled = runtime.store.enabled()
        app._display_f3_object_tracking_last_status = {
            "enabled": bool(app._display_f3_object_tracking_enabled),
            "locked": False,
            "reason": "initialized",
        }
    return runtime


def tracking_enabled(app) -> bool:
    runtime = get_tracking_runtime(app)
    if runtime is None:
        return False
    return bool(getattr(app, "_display_f3_object_tracking_enabled", runtime.store.enabled()))


def set_tracking_enabled(app, enabled: bool) -> bool:
    runtime = get_tracking_runtime(app)
    if runtime is None:
        return False
    runtime.store.set_enabled(bool(enabled))
    app._display_f3_object_tracking_enabled = bool(enabled)
    runtime.reset()
    app._display_f3_object_tracking_last_status = {
        "enabled": bool(enabled),
        "locked": False,
        "reason": "setting_changed",
    }
    return True


def reset_tracking_runtime(app) -> None:
    runtime = get_tracking_runtime(app)
    if runtime is not None:
        runtime.reset()
    app._display_f3_object_tracking_last_status = {
        "enabled": tracking_enabled(app),
        "locked": False,
        "reason": "reset",
    }


def align_frame_for_f3(app, frame):
    if not tracking_enabled(app):
        return frame, None
    runtime = get_tracking_runtime(app)
    if runtime is None:
        return frame, None
    project_name = runtime.repository.obter_projeto_ativo()
    if not runtime.configure(project_name):
        status = {
            "enabled": True,
            "locked": False,
            "reason": runtime.reason,
        }
        app._display_f3_object_tracking_last_status = status
        return frame, F3TrackingResult(False, frame, reason=runtime.reason)

    result = runtime.align(
        frame,
        frame_id=getattr(app, "camera_ultimo_frame_id", None),
    )
    app._display_f3_object_tracking_last_status = {
        "enabled": True,
        "locked": bool(result.locked),
        "reference": result.reference,
        "matches": int(result.matches),
        "inliers": int(result.inliers),
        "inlier_ratio": round(float(result.inlier_ratio), 4),
        "rotation_deg": round(float(result.rotation_deg), 3),
        "scale": round(float(result.scale), 5),
        "reason": result.reason,
    }
    return (result.frame if result.locked else frame), result


def instalar_runtime_rastreamento_objetos_display_f3() -> None:
    """Instala alinhamento opt-in envolvendo apenas o loop F3."""
    from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin
    from src.platform.display_production_f3 import DisplayProductionF3Mixin

    process_current = DisplayAutomaticCheckF3Mixin._process_display_auto_check
    if not bool(getattr(process_current, "_odin_f3_object_tracking_guard", False)):
        process_previous = process_current

        def process_with_tracking_guard(self):
            if tracking_enabled(self):
                status = getattr(self, "_display_f3_object_tracking_last_status", {})
                if not isinstance(status, dict) or not bool(status.get("locked")):
                    try:
                        self._display_auto_set_preview_status(
                            "RASTREAMENTO F3 ATIVO • procurando e alinhando o Display",
                            "#FBBF24",
                        )
                    except Exception:
                        pass
                    try:
                        self._reset_display_auto_stability(transition=False)
                    except Exception:
                        pass
                    return None
            return process_previous(self)

        process_with_tracking_guard._odin_f3_object_tracking_guard = True
        process_with_tracking_guard._odin_f3_object_tracking_guard_base = process_previous
        DisplayAutomaticCheckF3Mixin._process_display_auto_check = process_with_tracking_guard

    preview_current = DisplayProductionF3Mixin._atualizar_preview_display_f3
    if not bool(getattr(preview_current, "_odin_f3_object_tracking_runtime", False)):
        preview_previous = preview_current

        def preview_with_tracking(self):
            if not tracking_enabled(self):
                return preview_previous(self)

            raw = getattr(self, "camera_frame_atual", None)
            if not _valid_frame(raw):
                return preview_previous(self)

            aligned, result = align_frame_for_f3(self, raw)
            locked = bool(result is not None and result.locked)
            if not locked:
                return preview_previous(self)

            self.camera_frame_atual = aligned
            self._display_f3_tracking_frame_override_depth = int(
                getattr(self, "_display_f3_tracking_frame_override_depth", 0) or 0
            ) + 1
            try:
                return preview_previous(self)
            finally:
                self.camera_frame_atual = raw
                self._display_f3_tracking_frame_override_depth = max(
                    0,
                    int(getattr(self, "_display_f3_tracking_frame_override_depth", 1) or 1) - 1,
                )

        preview_with_tracking._odin_f3_object_tracking_runtime = True
        preview_with_tracking._odin_f3_object_tracking_runtime_base = preview_previous
        DisplayProductionF3Mixin._atualizar_preview_display_f3 = preview_with_tracking

    open_current = DisplayProductionF3Mixin._ativar_tela_producao_display_f3
    if not bool(getattr(open_current, "_odin_f3_object_tracking_reset", False)):
        open_previous = open_current

        def open_with_tracking_reset(self):
            reset_tracking_runtime(self)
            return open_previous(self)

        open_with_tracking_reset._odin_f3_object_tracking_reset = True
        open_with_tracking_reset._odin_f3_object_tracking_reset_base = open_previous
        DisplayProductionF3Mixin._ativar_tela_producao_display_f3 = open_with_tracking_reset

    close_current = DisplayProductionF3Mixin.fechar_tela_producao_display_f3
    if not bool(getattr(close_current, "_odin_f3_object_tracking_reset", False)):
        close_previous = close_current

        def close_with_tracking_reset(self):
            try:
                reset_tracking_runtime(self)
            except Exception:
                pass
            return close_previous(self)

        close_with_tracking_reset._odin_f3_object_tracking_reset = True
        close_with_tracking_reset._odin_f3_object_tracking_reset_base = close_previous
        DisplayProductionF3Mixin.fechar_tela_producao_display_f3 = close_with_tracking_reset
