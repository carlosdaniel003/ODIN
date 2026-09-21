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
from types import MethodType

import cv2
import numpy as np

from src.platform.display_check_presence_reference import (
    DisplayCheckPresenceReferenceStore,
)
from src.platform.display_f3_mask_editor_reference import (
    DisplayMaskEditorReferenceStore,
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
F3_TRACKING_GEOMETRY_MIN_ANCHORS = 2
F3_TRACKING_GEOMETRY_MAX_REPROJECTION_PX = 18.0
F3_TRACKING_REFERENCE_SCALE_MIN = 0.55
F3_TRACKING_REFERENCE_SCALE_MAX = 1.80
F3_TRACKING_OVERLAY_BOARD_BGR = (255, 214, 56)
F3_TRACKING_TEMPLATE_MIN_SCORE = 0.42
F3_TRACKING_TEMPLATE_MIN_SIZE = 28
F3_TRACKING_TEMPLATE_PADDING_FRACTION = 0.035

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
        # O painel F3 consulta o mesmo sidecar diversas vezes durante uma única
        # abertura (estado, projeto, contorno e 3 orientações). No Raspberry,
        # reler/parsing JSON a cada consulta tornava a abertura da configuração
        # perceptivelmente lenta. Cache local invalidado por mtime/tamanho.
        self._cache_signature: tuple[int, int] | None = None
        self._cache_data: dict | None = None

    @staticmethod
    def _empty() -> dict:
        return {
            "schema_version": F3_TRACKING_SCHEMA_VERSION,
            F3_TRACKING_SETTING_KEY: False,
            "projects": {},
        }

    def _disk_signature(self) -> tuple[int, int] | None:
        try:
            stat = self.config_file.stat()
            return int(stat.st_mtime_ns), int(stat.st_size)
        except OSError:
            return None

    def _load_shared(self) -> dict:
        signature = self._disk_signature()
        if (
            self._cache_data is not None
            and signature == self._cache_signature
        ):
            return self._cache_data

        if signature is None:
            normalized = self._empty()
            self._cache_signature = None
            self._cache_data = normalized
            return normalized

        try:
            data = json.loads(self.config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            normalized = self._empty()
            self._cache_signature = signature
            self._cache_data = normalized
            return normalized
        if not isinstance(data, dict):
            normalized = self._empty()
            self._cache_signature = signature
            self._cache_data = normalized
            return normalized

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
                    normalized_entry = _normalize_orientation_entry(
                        raw_orientations.get(slot) if isinstance(raw_orientations, dict) else None,
                        slot,
                    )
                    if normalized_entry:
                        orientations[slot] = normalized_entry
                projects[name] = {
                    "board_points": board_points,
                    "orientations": orientations,
                    "updated_at": str(raw_project.get("updated_at") or ""),
                }

        normalized = {
            "schema_version": F3_TRACKING_SCHEMA_VERSION,
            F3_TRACKING_SETTING_KEY: bool(data.get(F3_TRACKING_SETTING_KEY, False)),
            "projects": projects,
        }
        self._cache_signature = signature
        self._cache_data = normalized
        return normalized

    def _load(self) -> dict:
        # Chamadores que irão editar o dicionário recebem uma cópia; consultas
        # de leitura usam _load_shared()/project() sem copiar o arquivo inteiro.
        return deepcopy(self._load_shared())

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
        self._cache_signature = self._disk_signature()
        self._cache_data = normalized

    def enabled(self) -> bool:
        return bool(self._load_shared().get(F3_TRACKING_SETTING_KEY, False))

    def set_enabled(self, enabled: bool) -> None:
        data = self._load()
        data[F3_TRACKING_SETTING_KEY] = bool(enabled)
        self._write(data)

    def project(self, project_name: str) -> dict:
        name = normalizar_nome_projeto_display(project_name)
        raw = self._load_shared().get("projects", {}).get(name, {})
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


def _mask_center(mask: dict) -> tuple[float, float] | None:
    if not isinstance(mask, dict):
        return None
    item = converter_mascara_legada_para_editor(mask)
    kind = str(item.get("type") or "").lower()
    try:
        if kind in {"circle", "segment"}:
            return float(item.get("cx", 0)), float(item.get("cy", 0))
        points = pontos_mascara_display(item)
        if not points:
            return None
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    except (TypeError, ValueError):
        return None


def _reference_masks_from_overrides(
    project: dict,
    overrides,
    *,
    explicit_only: bool = False,
) -> list[dict]:
    """Geometria desenhada sobre uma foto de referência.

    Quando não existe override para um id, preserva a máscara canônica apenas
    como fallback. Para estimar pose, os pares com override explícito recebem
    prioridade via centros por id.
    """
    source = overrides if isinstance(overrides, dict) else {}
    result = []
    for base in project.get("masks", []) or []:
        if not isinstance(base, dict):
            continue
        mask_id = str(base.get("id") or "")
        raw = source.get(mask_id)
        if explicit_only and not isinstance(raw, dict):
            continue
        item = deepcopy(raw) if isinstance(raw, dict) else deepcopy(base)
        item["id"] = mask_id
        result.append(converter_mascara_legada_para_editor(item))
    return result


def _estimate_affine_partial(source_points, target_points):
    try:
        source = np.asarray(source_points, dtype=np.float32).reshape(-1, 2)
        target = np.asarray(target_points, dtype=np.float32).reshape(-1, 2)
    except Exception:
        return None
    if len(source) < F3_TRACKING_GEOMETRY_MIN_ANCHORS or len(source) != len(target):
        return None

    try:
        matrix, inliers = cv2.estimateAffinePartial2D(
            source.reshape(-1, 1, 2),
            target.reshape(-1, 1, 2),
            method=cv2.RANSAC,
            ransacReprojThreshold=F3_TRACKING_GEOMETRY_MAX_REPROJECTION_PX,
            maxIters=3000,
            confidence=0.995,
            refineIters=20,
        )
    except Exception:
        return None
    if matrix is None:
        return None

    scale = affine_scale(matrix)
    if not (F3_TRACKING_REFERENCE_SCALE_MIN <= scale <= F3_TRACKING_REFERENCE_SCALE_MAX):
        return None

    projected = cv2.transform(
        source.reshape(-1, 1, 2),
        np.asarray(matrix, dtype=np.float32),
    ).reshape(-1, 2)
    errors = np.linalg.norm(projected - target, axis=1)
    if len(errors) and float(np.median(errors)) > F3_TRACKING_GEOMETRY_MAX_REPROJECTION_PX:
        return None

    if inliers is not None and int(np.count_nonzero(inliers)) < min(2, len(source)):
        return None
    return np.asarray(matrix, dtype=np.float32).reshape(2, 3)


def _best_board_correspondence(
    reference_board,
    canonical_board,
    hint_matrix=None,
):
    reference = _normalize_points(reference_board, minimum=3)
    canonical = _normalize_points(canonical_board, minimum=3)
    if len(reference) != len(canonical) or len(reference) < 3:
        return None

    ref = np.asarray(reference, dtype=np.float32)
    can = np.asarray(canonical, dtype=np.float32)
    best = None
    n = len(ref)
    hint = None
    if hint_matrix is not None:
        try:
            hint = np.asarray(hint_matrix, dtype=np.float32).reshape(2, 3)
        except Exception:
            hint = None

    for reverse in (False, True):
        ordered = ref[::-1].copy() if reverse else ref.copy()
        for shift in range(n):
            candidate = np.roll(ordered, shift, axis=0)
            if hint is not None:
                projected = cv2.transform(
                    candidate.reshape(-1, 1, 2),
                    hint,
                ).reshape(-1, 2)
                error = float(np.median(np.linalg.norm(projected - can, axis=1)))
            else:
                matrix = _estimate_affine_partial(candidate, can)
                if matrix is None:
                    continue
                projected = cv2.transform(
                    candidate.reshape(-1, 1, 2),
                    matrix,
                ).reshape(-1, 2)
                error = float(np.median(np.linalg.norm(projected - can, axis=1)))
            if best is None or error < best[0]:
                best = (error, candidate.tolist(), can.tolist())
    return best


def estimate_reference_to_canonical(
    project: dict,
    store: F3TrackingConfigStore,
    reference_board,
    reference_masks,
) -> np.ndarray | None:
    """Estima REFERÊNCIA -> CANÔNICO usando a geometria já desenhada pelo usuário.

    As máscaras são pareadas pelo id, portanto a placa pode estar em outra posição,
    escala ou rotação em cada foto. O contorno entra como reforço quando possui a
    mesma quantidade de vértices do contorno canônico.
    """
    canonical_board = canonical_board_points(project, store)
    canonical_masks = {
        str(mask.get("id") or ""): converter_mascara_legada_para_editor(mask)
        for mask in (project.get("masks", []) or [])
        if isinstance(mask, dict) and str(mask.get("id") or "")
    }
    reference_by_id = {
        str(mask.get("id") or ""): converter_mascara_legada_para_editor(mask)
        for mask in (reference_masks or [])
        if isinstance(mask, dict) and str(mask.get("id") or "")
    }

    source_points = []
    target_points = []
    for mask_id, canonical_mask in canonical_masks.items():
        reference_mask = reference_by_id.get(mask_id)
        if reference_mask is None:
            continue
        source_center = _mask_center(reference_mask)
        target_center = _mask_center(canonical_mask)
        if source_center is None or target_center is None:
            continue
        source_points.append(source_center)
        target_points.append(target_center)

    # Máscaras possuem IDs estáveis e por isso dão a orientação inicial sem
    # ambiguidade. Um retângulo de placa sozinho pode encaixar igualmente em
    # 0/90/180/270 graus; usamos os centros das máscaras para escolher a ordem
    # correta dos vértices antes de acrescentar o contorno ao ajuste final.
    mask_matrix = _estimate_affine_partial(source_points, target_points)
    board_match = _best_board_correspondence(
        reference_board,
        canonical_board,
        hint_matrix=mask_matrix,
    )
    if board_match is not None:
        _error, ref_board_ordered, can_board_ordered = board_match
        source_points.extend(ref_board_ordered)
        target_points.extend(can_board_ordered)

    matrix = _estimate_affine_partial(source_points, target_points)
    if matrix is not None:
        return matrix

    if mask_matrix is not None:
        return mask_matrix

    # Se não houver máscaras suficientes, o contorno sozinho ainda resolve pose
    # quando sua correspondência não é ambígua.
    if board_match is not None:
        return _estimate_affine_partial(board_match[1], board_match[2])
    return None


def compose_affine(after, before) -> np.ndarray | None:
    """Composição 2x3: resultado = after(before(ponto))."""
    try:
        a = np.vstack(
            [np.asarray(after, dtype=np.float32).reshape(2, 3), [0.0, 0.0, 1.0]]
        )
        b = np.vstack(
            [np.asarray(before, dtype=np.float32).reshape(2, 3), [0.0, 0.0, 1.0]]
        )
        return (a @ b)[:2].astype(np.float32)
    except Exception:
        return None


def _current_check(app):
    runtime = getattr(app, "display_check_runtime", None)
    if runtime is None:
        return None
    try:
        current = runtime.snapshot().get("current_check")
    except Exception:
        return None
    return current if isinstance(current, dict) else None


def _check_reference_geometry(
    project: dict,
    check: dict | None,
) -> tuple[list[list[float]], list[dict]]:
    if not isinstance(check, dict):
        return [], []
    board = _normalize_points(check.get("board_points_reference"), minimum=3)
    masks = _reference_masks_from_overrides(
        project,
        check.get("mask_overrides_reference", {}),
    )
    return board, masks


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
    board_thickness: int = 3,
    mask_thickness: int = 2,
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
            max(1, int(board_thickness)),
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
                cv2.circle(
                    overlay,
                    center,
                    radius,
                    color,
                    max(1, int(mask_thickness)),
                    cv2.LINE_AA,
                )
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
                    max(1, int(mask_thickness)),
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
    current_to_canonical: object | None = None
    source_type: str = ""


class F3DisplayObjectTracker:
    """ORB/RANSAC independente, sempre produz CURRENT -> CANÔNICO."""

    def __init__(self, repository: DisplayProjectRepository) -> None:
        self.repository = repository
        self.store = F3TrackingConfigStore(repository)
        self.check_store = DisplayCheckPresenceReferenceStore(repository)
        self.project_presence_store = DisplayProjectPresenceReferenceStore(repository)
        self.mask_reference_store = DisplayMaskEditorReferenceStore(repository)
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

    def _calibrated_reference_specs(self, project: dict) -> list[dict]:
        """Monta o banco multivista F3 a partir de TODAS as geometrias salvas.

        Cada foto traz sua própria posição da placa. Por isso nenhuma foto de
        CHECK/placa desligada é tratada como identidade: o contorno e as máscaras
        desenhadas naquela foto estimam REFERÊNCIA -> CANÔNICO.
        """
        project_name = str(project.get("name") or "")
        canonical_board = canonical_board_points(project, self.store)
        canonical_masks = [
            converter_mascara_legada_para_editor(mask)
            for mask in (project.get("masks", []) or [])
            if isinstance(mask, dict)
        ]
        specs: list[dict] = []

        # A foto estática de "Máscaras" define o espaço canônico: nela foram
        # desenhados o contorno compartilhado e as máscaras principais.
        mask_metadata = self.mask_reference_store.get(project_name)
        mask_path = str((mask_metadata or {}).get("image_path") or "").strip()
        if mask_path and canonical_board:
            specs.append(
                {
                    "key": "mask_reference",
                    "path": mask_path,
                    "board": deepcopy(canonical_board),
                    "masks": deepcopy(canonical_masks),
                    "reference_to_canonical": np.asarray(
                        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                        dtype=np.float32,
                    ),
                    "angle": 0.0,
                    "real_orientation": False,
                    "source_type": "mask_reference",
                }
            )

        # PLACA DESLIGADA NO SUPORTE: usa exatamente a geometria desenhada
        # naquela foto para descobrir sua pose relativa ao espaço canônico.
        board_off = self.project_presence_store.get(
            project_name,
            DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
        )
        board_off_path = str((board_off or {}).get("image_path") or "").strip()
        if board_off_path:
            board_ref = _normalize_points(
                (board_off or {}).get("board_points_reference"),
                minimum=3,
            )
            overrides = (board_off or {}).get("mask_overrides_reference", {})
            masks_ref = _reference_masks_from_overrides(
                project,
                overrides,
            )
            pose_masks = _reference_masks_from_overrides(
                project,
                overrides,
                explicit_only=True,
            )
            mapping = estimate_reference_to_canonical(
                project,
                self.store,
                board_ref,
                pose_masks,
            )
            if mapping is not None:
                specs.append(
                    {
                        "key": "board_off",
                        "path": board_off_path,
                        "board": board_ref,
                        "masks": masks_ref,
                        "reference_to_canonical": mapping,
                        "angle": affine_rotation_deg(mapping),
                        "real_orientation": False,
                        "source_type": "board_off",
                    }
                )

        # Cada CHECK é também uma vista válida da mesma placa: H1/BLUE/USB/AUX
        # podem estar em posições e rotações diferentes, mas seus ids de máscara
        # e o contorno desenhado fornecem correspondências geométricas.
        checks = (
            project.get("checks", [])
            if isinstance(project.get("checks"), list)
            else []
        )
        for check in checks:
            if not isinstance(check, dict):
                continue
            check_id = str(check.get("id") or "")
            if not check_id:
                continue
            metadata = self.check_store.get(project_name, check_id)
            path = str((metadata or {}).get("image_path") or "").strip()
            if not path:
                continue
            board_ref, masks_ref = _check_reference_geometry(project, check)
            pose_masks = _reference_masks_from_overrides(
                project,
                check.get("mask_overrides_reference", {}),
                explicit_only=True,
            )
            mapping = estimate_reference_to_canonical(
                project,
                self.store,
                board_ref,
                pose_masks,
            )
            if mapping is None:
                continue
            specs.append(
                {
                    "key": f"check:{check_id}",
                    "path": path,
                    "board": board_ref,
                    "masks": masks_ref,
                    "reference_to_canonical": mapping,
                    "angle": affine_rotation_deg(mapping),
                    "real_orientation": False,
                    "source_type": "check",
                    "check_id": check_id,
                }
            )

        return specs

    @staticmethod
    def _file_signature(path_value: str) -> tuple[str, int, int]:
        path = Path(str(path_value or ""))
        try:
            stat = path.stat()
            return str(path), int(stat.st_mtime_ns), int(stat.st_size)
        except OSError:
            return str(path), 0, 0

    def _signature(self, project: dict, board, orientations) -> tuple:
        reference_specs = self._calibrated_reference_specs(project)
        reference_files = tuple(
            (
                str(spec.get("key") or ""),
                self._file_signature(str(spec.get("path") or "")),
                repr(spec.get("board")),
                repr(spec.get("masks")),
                repr(
                    np.asarray(
                        spec.get("reference_to_canonical"),
                        dtype=np.float32,
                    ).reshape(2, 3).round(5).tolist()
                ),
            )
            for spec in reference_specs
        )
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
            reference_files,
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
        source_type: str = "reference",
        board_points=None,
    ) -> None:
        gray = self._gray(image)
        if gray is None:
            return

        reference_to_canonical = np.asarray(
            reference_to_canonical,
            dtype=np.float32,
        ).reshape(2, 3)

        descriptors = None
        canonical_points = np.empty((0, 2), dtype=np.float32)
        orb = cv2.ORB_create(
            nfeatures=F3_TRACKING_ORB_FEATURES,
            scaleFactor=1.2,
            nlevels=8,
            edgeThreshold=12,
            fastThreshold=7,
        )
        keypoints, detected = orb.detectAndCompute(gray, tracking_mask)
        if detected is not None and len(keypoints) >= F3_TRACKING_MIN_MATCHES:
            points = np.asarray(
                [kp.pt for kp in keypoints],
                dtype=np.float32,
            ).reshape(-1, 1, 2)
            try:
                canonical_points = cv2.transform(
                    points,
                    reference_to_canonical,
                ).reshape(-1, 2)
                descriptors = detected
            except Exception:
                descriptors = None
                canonical_points = np.empty((0, 2), dtype=np.float32)

        template_edges = None
        template_origin = None
        normalized_board = _normalize_points(board_points, minimum=3)
        if normalized_board:
            xs = [float(p[0]) for p in normalized_board]
            ys = [float(p[1]) for p in normalized_board]
            x1, x2 = min(xs), max(xs)
            y1, y2 = min(ys), max(ys)
            pad_x = max(3.0, (x2 - x1) * F3_TRACKING_TEMPLATE_PADDING_FRACTION)
            pad_y = max(3.0, (y2 - y1) * F3_TRACKING_TEMPLATE_PADDING_FRACTION)
            ix1 = max(0, int(math.floor(x1 - pad_x)))
            iy1 = max(0, int(math.floor(y1 - pad_y)))
            ix2 = min(gray.shape[1], int(math.ceil(x2 + pad_x)))
            iy2 = min(gray.shape[0], int(math.ceil(y2 + pad_y)))
            if (
                ix2 - ix1 >= F3_TRACKING_TEMPLATE_MIN_SIZE
                and iy2 - iy1 >= F3_TRACKING_TEMPLATE_MIN_SIZE
            ):
                edges = cv2.Canny(gray, 45, 135)
                crop = edges[iy1:iy2, ix1:ix2]
                if crop.size and float(np.std(crop)) >= 8.0:
                    template_edges = crop.copy()
                    template_origin = (float(ix1), float(iy1))

        # Uma referência pode ser útil mesmo com pouco ORB. O fallback por
        # template de bordas resolve translação quando câmera/suporte são fixos,
        # exatamente o cenário produtivo do F3.
        if descriptors is None and template_edges is None:
            return

        refs[key] = {
            "descriptors": descriptors,
            "canonical_points": canonical_points,
            "angle_deg": float(angle),
            "real_orientation": bool(real_orientation),
            "source_type": str(source_type or "reference"),
            "reference_to_canonical": reference_to_canonical,
            "template_edges": template_edges,
            "template_origin": template_origin,
        }

    def _template_candidate(self, current_edges, key: str):
        ref = self.references.get(key, {})
        template = ref.get("template_edges")
        origin = ref.get("template_origin")
        if (
            current_edges is None
            or template is None
            or origin is None
            or template.shape[0] > current_edges.shape[0]
            or template.shape[1] > current_edges.shape[1]
        ):
            return None
        try:
            response = cv2.matchTemplate(
                current_edges,
                template,
                cv2.TM_CCOEFF_NORMED,
            )
            _min_value, max_value, _min_loc, max_loc = cv2.minMaxLoc(response)
        except Exception:
            return None
        score = float(max_value)
        if score < F3_TRACKING_TEMPLATE_MIN_SCORE:
            return None

        ref_x, ref_y = float(origin[0]), float(origin[1])
        cur_x, cur_y = float(max_loc[0]), float(max_loc[1])
        current_to_reference = np.asarray(
            [
                [1.0, 0.0, ref_x - cur_x],
                [0.0, 1.0, ref_y - cur_y],
            ],
            dtype=np.float32,
        )
        matrix = compose_affine(
            ref.get("reference_to_canonical"),
            current_to_reference,
        )
        if matrix is None:
            return None
        scale = affine_scale(matrix)
        if not (F3_TRACKING_MIN_SCALE <= scale <= F3_TRACKING_MAX_SCALE):
            return None

        source_type = str(ref.get("source_type") or "reference")
        return {
            "reference": key,
            "matrix": matrix.astype(np.float32),
            "matches": 0,
            "inliers": 0,
            "ratio": score,
            "rotation_deg": affine_rotation_deg(matrix),
            "scale": scale,
            # ORB deve ganhar sempre que existir; template é fallback.
            "score": 2.0 + score * 8.0,
            "source_type": source_type,
            "fallback": "edge_template",
        }

    def configure(self, project_name: str | None = None) -> bool:
        name = normalizar_nome_projeto_display(
            project_name or self.repository.obter_projeto_ativo()
        )
        # O editor/configuração chama reset() sempre que qualquer dado do Projeto
        # Display muda. Enquanto o projeto é o mesmo e o tracker continua pronto,
        # não releia JSON, imagens nem calcule descritores em cada frame.
        if self.ready and self.project == name and self.signature is not None:
            return True

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

        refs: dict[str, dict] = {}

        # Banco multivista real: foto canônica de Máscaras, placa desligada e
        # todos os CHECKS. Cada uma usa SEU contorno e SUAS máscaras desenhadas,
        # portanto a posição física da placa na foto não precisa coincidir.
        for spec in self._calibrated_reference_specs(project):
            path = str(spec.get("path") or "")
            image = cv2.imread(path, cv2.IMREAD_COLOR)
            if not _valid_frame(image) or image.shape[:2] != (height, width):
                continue
            tracking_mask = build_tracking_mask(
                width,
                height,
                spec.get("board", []),
                spec.get("masks", []),
            )
            if tracking_mask is None:
                continue
            self._add_reference(
                refs,
                key=str(spec.get("key") or ""),
                image=image,
                tracking_mask=tracking_mask,
                reference_to_canonical=spec.get("reference_to_canonical"),
                angle=float(spec.get("angle", 0.0) or 0.0),
                real_orientation=bool(spec.get("real_orientation", False)),
                source_type=str(spec.get("source_type") or "reference"),
                board_points=spec.get("board", []),
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
                source_type="orientation",
                board_points=board_ref,
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
        descriptors = ref.get("descriptors")
        if descriptors is None or current_desc is None:
            return None
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
        source_type = str(ref.get("source_type") or "reference")
        if bool(ref.get("real_orientation")):
            score += 5.0
        elif source_type == "mask_reference":
            score += 4.0
        elif source_type == "check":
            score += 3.0
        elif source_type == "board_off":
            score += 2.0
        return {
            "reference": key,
            "matrix": matrix.astype(np.float32),
            "matches": len(good),
            "inliers": inliers,
            "ratio": ratio,
            "rotation_deg": rotation,
            "scale": scale,
            "score": score,
            "source_type": source_type,
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
                current_to_canonical=self.last_matrix.copy(),
                source_type=self.last_result.source_type,
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
        orb_available = bool(
            current_desc is not None
            and len(current_kp) >= F3_TRACKING_MIN_MATCHES
        )

        candidates = []
        if orb_available:
            for key in tuple(self.references):
                candidate = self._candidate(current_kp, current_desc, key)
                if candidate is not None:
                    candidates.append(candidate)

        # Câmera e suporte são fixos: se o PCB tiver poucos corners ORB, use as
        # bordas do contorno desenhado como fallback de translação. Os slots
        # 0/90/180/270 e CHECKS fornecem as orientações reais disponíveis.
        if not candidates:
            try:
                current_edges = cv2.Canny(gray, 45, 135)
            except Exception:
                current_edges = None
            for key in tuple(self.references):
                candidate = self._template_candidate(current_edges, key)
                if candidate is not None:
                    candidates.append(candidate)

        if not candidates:
            self.last_matrix = None
            self._last_reference = ""
            result = F3TrackingResult(
                False,
                frame,
                reason=(
                    "current_features_insufficient"
                    if not orb_available
                    else "object_not_locked"
                ),
            )
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
            reason=(
                "locked_template"
                if str(best.get("fallback") or "") == "edge_template"
                else "locked"
            ),
            current_to_canonical=matrix.copy(),
            source_type=str(best.get("source_type") or ""),
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
    # Não consulte o JSON a cada frame do F3. O valor é carregado uma vez ao
    # construir o runtime e atualizado imediatamente pelo checkbox da UI.
    if hasattr(app, "_display_f3_object_tracking_enabled"):
        return bool(getattr(app, "_display_f3_object_tracking_enabled"))
    enabled = bool(runtime.store.enabled())
    app._display_f3_object_tracking_enabled = enabled
    return enabled


def _canonical_masks_for_orientation(
    runtime: F3DisplayObjectTracker,
    project: dict,
    reference: str,
) -> list[dict] | None:
    """Converte os ajustes locais do slot angular de volta ao sistema canônico.

    Assim os segmentos ajustados em "Desenhar placa" não servem apenas de guia
    visual/ORB: quando aquele slot real vence o rastreamento, o mesmo ajuste é
    usado pelo pipeline F3 que lê as máscaras no frame já alinhado.
    """
    if reference not in F3_ORIENTATION_SLOTS:
        return None
    project_name = normalizar_nome_projeto_display(project.get("name"))
    entry = runtime.store.orientations(project_name).get(reference, {})
    matrix = matrix_np(entry)
    overrides = entry.get("mask_overrides_reference", {}) if isinstance(entry, dict) else {}
    if matrix is None or not isinstance(overrides, dict) or not overrides:
        return None
    try:
        inverse = cv2.invertAffineTransform(matrix)
    except Exception:
        return None

    original_masks = normalizar_mascaras_display(project.get("masks", []))
    corrected: list[dict] = []
    for original in original_masks:
        mask_id = str(original.get("id") or "")
        override = _normalize_mask_override(overrides.get(mask_id))
        if override is None:
            corrected.append(deepcopy(original))
            continue
        canonical = transform_mask(override, inverse)
        if canonical is None:
            corrected.append(deepcopy(original))
            continue
        canonical["id"] = mask_id
        corrected.append(canonical)

    return corrected if len(corrected) == len(original_masks) else None


def _install_orientation_project_view(app, reference: str):
    """Aplica máscaras angulares somente durante um ciclo do runtime F3.

    Retorna uma função de restauração. O JSON do Projeto Display nunca é alterado.
    """
    runtime = get_tracking_runtime(app)
    repository = getattr(app, "display_project_repository", None)
    if (
        runtime is None
        or repository is None
        or reference not in F3_ORIENTATION_SLOTS
    ):
        return lambda: None

    original_loader = getattr(repository, "carregar_projeto", None)
    if not callable(original_loader):
        return lambda: None
    repository_dict = getattr(repository, "__dict__", {})
    had_instance_loader = (
        isinstance(repository_dict, dict)
        and "carregar_projeto" in repository_dict
    )
    previous_instance_loader = (
        repository_dict.get("carregar_projeto")
        if had_instance_loader
        else None
    )

    active_name = normalizar_nome_projeto_display(repository.obter_projeto_ativo())
    base_project = original_loader(active_name)
    if not isinstance(base_project, dict):
        return lambda: None
    corrected_masks = _canonical_masks_for_orientation(
        runtime,
        base_project,
        reference,
    )
    if not corrected_masks:
        return lambda: None

    entry = runtime.store.orientations(active_name).get(reference, {})
    orientation_stamp = str((entry or {}).get("updated_at") or "")

    def load_with_orientation(name: str | None = None):
        project = original_loader(name)
        if not isinstance(project, dict):
            return project
        project_name = normalizar_nome_projeto_display(project.get("name"))
        if project_name != active_name:
            return project
        result = deepcopy(project)
        result["masks"] = deepcopy(corrected_masks)
        result["updated_at"] = (
            f"{str(project.get('updated_at') or '')}"
            f"|f3-tracking:{reference}:{orientation_stamp}"
        )
        result["_f3_tracking_orientation_reference"] = reference
        return result

    try:
        repository.carregar_projeto = load_with_orientation
    except Exception:
        return lambda: None

    def restore() -> None:
        try:
            if had_instance_loader:
                repository.carregar_projeto = previous_instance_loader
            else:
                delattr(repository, "carregar_projeto")
        except Exception:
            # Fallback seguro para objetos/repositórios que não permitem delattr.
            try:
                repository.carregar_projeto = original_loader
            except Exception:
                pass

    return restore


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
    app._display_f3_tracking_raw_preview_frame = None
    app._display_f3_tracking_result = None
    app._display_f3_tracking_live_geometry = None
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
        "source_type": str(result.source_type or ""),
        "reason": result.reason,
    }
    return (result.frame if result.locked else frame), result


def _analysis_alignment_for_current_check(
    app,
    raw_frame,
    result: F3TrackingResult | None,
):
    """Alinha somente a ANÁLISE ao frame de referência do CHECK atual.

    O tracker localiza qualquer vista -> canônico. Em seguida, para analisar H1,
    BLUE, AUX etc., compomos CANÔNICO -> FOTO DO CHECK. Assim as máscaras que o
    usuário desenhou naquela foto continuam coincidindo pixel a pixel, mesmo que
    cada CHECK tenha sido fotografado em uma posição diferente.
    """
    if (
        result is None
        or not result.locked
        or result.current_to_canonical is None
        or not _valid_frame(raw_frame)
    ):
        return None, None

    runtime = get_tracking_runtime(app)
    current = _current_check(app)
    if runtime is None or not isinstance(current, dict):
        return result.frame, result.current_to_canonical

    check_id = str(current.get("id") or "")
    reference = runtime.references.get(f"check:{check_id}")
    mapping = (
        reference.get("reference_to_canonical")
        if isinstance(reference, dict)
        else None
    )
    if mapping is None:
        return result.frame, result.current_to_canonical

    try:
        canonical_to_check = cv2.invertAffineTransform(
            np.asarray(mapping, dtype=np.float32).reshape(2, 3)
        )
    except Exception:
        return result.frame, result.current_to_canonical

    current_to_check = compose_affine(
        canonical_to_check,
        result.current_to_canonical,
    )
    if current_to_check is None:
        return result.frame, result.current_to_canonical

    tracker = runtime
    aligned = cv2.warpAffine(
        raw_frame,
        current_to_check,
        (int(tracker.width), int(tracker.height)),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT101,
    )
    return aligned, current_to_check


def _update_tracking_live_geometry(
    app,
    raw_frame,
    result: F3TrackingResult | None,
) -> None:
    """Projeta contorno+ROIs para a câmera REAL, como bounding boxes móveis."""
    if (
        result is None
        or not result.locked
        or result.current_to_canonical is None
        or not _valid_frame(raw_frame)
    ):
        app._display_f3_tracking_live_geometry = None
        return

    runtime = get_tracking_runtime(app)
    repository = getattr(app, "display_project_repository", None)
    if runtime is None or repository is None:
        app._display_f3_tracking_live_geometry = None
        return

    project_name = repository.obter_projeto_ativo()
    project = repository.carregar_projeto(project_name)
    if not isinstance(project, dict):
        app._display_f3_tracking_live_geometry = None
        return

    source_board = canonical_board_points(project, runtime.store)
    source_masks = [
        converter_mascara_legada_para_editor(mask)
        for mask in (project.get("masks", []) or [])
        if isinstance(mask, dict)
    ]
    source_to_current = None
    geometry_space = "canonical"

    current = _current_check(app)
    if isinstance(current, dict):
        check_id = str(current.get("id") or "")
        try:
            check = repository.carregar_check(project_name, check_id)
        except Exception:
            check = None
        reference = runtime.references.get(f"check:{check_id}")
        ref_to_canonical = (
            reference.get("reference_to_canonical")
            if isinstance(reference, dict)
            else None
        )
        if isinstance(check, dict) and ref_to_canonical is not None:
            check_board, check_masks = _check_reference_geometry(project, check)
            if check_board:
                source_board = check_board
            if check_masks:
                source_masks = check_masks
            analysis_frame, current_to_check = _analysis_alignment_for_current_check(
                app,
                raw_frame,
                result,
            )
            del analysis_frame
            if current_to_check is not None:
                try:
                    source_to_current = cv2.invertAffineTransform(
                        np.asarray(current_to_check, dtype=np.float32).reshape(2, 3)
                    )
                    geometry_space = f"check:{check_id}"
                except Exception:
                    source_to_current = None

    if source_to_current is None:
        try:
            source_to_current = cv2.invertAffineTransform(
                np.asarray(
                    result.current_to_canonical,
                    dtype=np.float32,
                ).reshape(2, 3)
            )
        except Exception:
            app._display_f3_tracking_live_geometry = None
            return

    board_current = transform_points(source_board, source_to_current)
    masks_current = []
    for mask in source_masks:
        transformed = transform_mask(mask, source_to_current)
        if transformed is not None:
            masks_current.append(transformed)

    h, w = raw_frame.shape[:2]
    app._display_f3_tracking_live_geometry = {
        "locked": True,
        "reference": str(result.reference or ""),
        "source_type": str(result.source_type or ""),
        "geometry_space": geometry_space,
        "resolution": (int(w), int(h)),
        "board_points": board_current,
        "masks": masks_current,
        "matches": int(result.matches),
        "inliers": int(result.inliers),
        "inlier_ratio": float(result.inlier_ratio),
    }


def _tracking_h1_power_gate(app) -> tuple[bool, str]:
    """Fail-safe independente da cadeia histórica de wrappers do F3."""
    status = getattr(app, "_display_f3_object_tracking_last_status", None)
    if not isinstance(status, dict) or not bool(status.get("locked")):
        return False, "rastreamento_sem_lock"

    analysis = getattr(app, "_display_auto_last_analysis", None)
    try:
        context = app._display_auto_current_context()
    except Exception:
        context = None
    if not isinstance(context, dict) or not isinstance(analysis, dict):
        return False, "analise_h1_ausente"
    if (
        str(analysis.get("project_name") or "")
        and str(analysis.get("project_name") or "")
        != str(context.get("project_name") or "")
    ):
        return False, "analise_projeto_antiga"
    if (
        str(analysis.get("check_id") or "")
        and str(analysis.get("check_id") or "")
        != str(context.get("check_id") or "")
    ):
        return False, "analise_check_antiga"

    results = [
        item
        for item in (analysis.get("mask_results") or [])
        if isinstance(item, dict)
    ]
    on_evidence = False
    for item in results:
        if str(item.get("expected") or "") != "on":
            continue
        try:
            confidence = float(item.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if (
            str(item.get("classified") or "") == "on"
            and item.get("matched") is not False
            and confidence >= 0.50
        ):
            on_evidence = True
            break
    if not on_evidence:
        return False, "h1_sem_segmento_aceso"

    power = getattr(app, "_display_f3_power_authority_status", None)
    energy = power.get("energy") if isinstance(power, dict) else None
    if not (
        isinstance(power, dict)
        and power.get("board_present") is True
        and power.get("decision_allowed") is True
        and isinstance(energy, dict)
        and energy.get("powered_confirmed") is True
    ):
        return False, "energia_fisica_nao_confirmada"
    return True, "h1_ligado_confirmado"


def _draw_tracking_geometry_visual(
    frame,
    geometry: dict | None,
    visual_rotation: int,
):
    """Desenha somente geometria móvel sobre a câmera real."""
    from src.platform.display_visual_rotation import (
        preparar_check_visual_display,
        preparar_frame_visual_display,
        preparar_pontos_visuais_display,
    )

    visual = preparar_frame_visual_display(frame, int(visual_rotation or 0) % 360)
    if not _valid_frame(visual):
        return frame

    if not isinstance(geometry, dict) or not bool(geometry.get("locked")):
        return visual

    resolution = geometry.get("resolution")
    if not (
        isinstance(resolution, (list, tuple))
        and len(resolution) >= 2
    ):
        return visual
    width = max(1, int(resolution[0]))
    height = max(1, int(resolution[1]))
    rotation = int(visual_rotation or 0) % 360

    try:
        _, visual_resolution, visual_masks = preparar_check_visual_display(
            None,
            (width, height),
            geometry.get("masks") or [],
            rotation,
        )
        visual_board = preparar_pontos_visuais_display(
            geometry.get("board_points") or [],
            width,
            height,
            rotation,
        )
    except Exception:
        return visual

    result = visual.copy()
    vh, vw = result.shape[:2]
    rw = max(1.0, float(visual_resolution[0]))
    rh = max(1.0, float(visual_resolution[1]))
    sx = vw / rw
    sy = vh / rh
    color = (248, 189, 56)  # ciano #38BDF8 em BGR

    if len(visual_board) >= 3:
        points = np.asarray(
            [
                [round(float(p[0]) * sx), round(float(p[1]) * sy)]
                for p in visual_board
            ],
            dtype=np.int32,
        )
        cv2.polylines(result, [points], True, color, 3, cv2.LINE_AA)

    for raw_mask in visual_masks or []:
        if not isinstance(raw_mask, dict):
            continue
        mask = converter_mascara_legada_para_editor(raw_mask)
        kind = str(mask.get("type") or "").lower()
        try:
            if kind == "circle":
                center = (
                    int(round(float(mask.get("cx", 0)) * sx)),
                    int(round(float(mask.get("cy", 0)) * sy)),
                )
                radius = max(
                    1,
                    int(
                        round(
                            float(mask.get("radius", 1))
                            * ((sx + sy) / 2.0)
                        )
                    ),
                )
                cv2.circle(result, center, radius, color, 1, cv2.LINE_AA)
                continue
            points = pontos_mascara_display(mask)
            if len(points) < 3:
                continue
            polygon = np.asarray(
                [
                    [round(float(p[0]) * sx), round(float(p[1]) * sy)]
                    for p in points
                ],
                dtype=np.int32,
            )
            cv2.polylines(result, [polygon], True, color, 1, cv2.LINE_AA)
        except Exception:
            continue
    return result


def instalar_autoridade_final_instancia_rastreamento_f3(app) -> None:
    """Autoridade final no OBJETO real criado por main_rpi.

    Evita que wrappers históricos na MRO escondam o tracker. Também protege a
    própria máquina de sequência, portanto nenhum caminho alternativo consegue
    aprovar CHECKS sem passar pela confirmação física do H1.
    """
    if app is None or bool(
        getattr(app, "_display_f3_tracking_instance_authority", False)
    ):
        return

    runtime = get_tracking_runtime(app)
    if runtime is not None:
        app._display_f3_object_tracking_enabled = bool(runtime.store.enabled())

    previous_preview = app._atualizar_preview_display_f3

    def instance_preview(self):
        if tracking_enabled(self) and not bool(
            getattr(self, "_display_f3_tracking_config_open", False)
        ):
            raw = getattr(self, "camera_frame_atual", None)
            if _valid_frame(raw):
                self._display_f3_tracking_raw_authority_frame = raw
                _aligned, result = align_frame_for_f3(self, raw)
                self._display_f3_tracking_result = result
                _update_tracking_live_geometry(self, raw, result)
                locked = bool(result is not None and result.locked)
                if locked:
                    analysis_frame, _matrix = _analysis_alignment_for_current_check(
                        self,
                        raw,
                        result,
                    )
                    self._display_f3_tracking_analysis_frame = (
                        analysis_frame if _valid_frame(analysis_frame) else None
                    )
                else:
                    self._display_f3_tracking_analysis_frame = None
            else:
                self._display_f3_tracking_live_geometry = None
                self._display_f3_tracking_analysis_frame = None
        return previous_preview()

    app._atualizar_preview_display_f3 = MethodType(instance_preview, app)

    window = getattr(app, "display_f3_window", None)
    if window is not None:
        previous_window_update = window.update_camera_preview

        def tracked_window_update(self_window, frame, visual_rotation: int = 0):
            if not tracking_enabled(app):
                return previous_window_update(
                    frame,
                    visual_rotation=visual_rotation,
                )

            authority_frame = getattr(
                app,
                "_display_f3_tracking_raw_authority_frame",
                None,
            )
            source = authority_frame if _valid_frame(authority_frame) else frame
            if not _valid_frame(source):
                return previous_window_update(
                    frame,
                    visual_rotation=visual_rotation,
                )

            geometry = getattr(
                app,
                "_display_f3_tracking_live_geometry",
                None,
            )
            decorated = _draw_tracking_geometry_visual(
                source,
                geometry,
                visual_rotation,
            )
            locked = bool(
                isinstance(geometry, dict)
                and geometry.get("locked")
            )
            status = getattr(
                app,
                "_display_f3_object_tracking_last_status",
                {},
            )
            if locked:
                legend = (
                    "RASTREAMENTO F3 • LOCK • "
                    f"{str(status.get('reference') or '--')} • "
                    f"{int(status.get('inliers', 0) or 0)} inliers"
                )
                color = "#38BDF8"
            else:
                reason = str(status.get("reason") or "procurando")
                legend = f"RASTREAMENTO F3 • PROCURANDO PLACA • {reason}"
                color = "#FBBF24"

            try:
                self_window.preview_legend.configure(
                    text=legend,
                    fg=color,
                )
            except Exception:
                pass
            h, w = decorated.shape[:2]
            rendered = self_window.update_preview(decorated, leds=())
            if rendered:
                try:
                    self_window.show_camera_ready(
                        int(w),
                        int(h),
                        int(visual_rotation or 0) % 360,
                    )
                except Exception:
                    pass
            return rendered

        window.update_camera_preview = MethodType(
            tracked_window_update,
            window,
        )

    sequence = getattr(app, "display_check_runtime", None)
    if sequence is not None and not bool(
        getattr(sequence, "_odin_f3_tracking_sequence_guard", False)
    ):
        previous_register = sequence.registrar_resultado_check

        def guarded_register(self_sequence, aprovado: bool = True):
            if not tracking_enabled(app):
                return previous_register(aprovado)

            snapshot = self_sequence.snapshot()
            current = snapshot.get("current_check")
            if not isinstance(current, dict):
                return previous_register(aprovado)
            try:
                index = int(snapshot.get("current_index", 0) or 0)
            except (TypeError, ValueError):
                index = 0
            try:
                cycle = int(snapshot.get("total", 0) or 0)
            except (TypeError, ValueError):
                cycle = 0

            if index == 0:
                power_ok, reason = _tracking_h1_power_gate(app)
                if not power_ok:
                    try:
                        app._display_auto_set_preview_status(
                            "AUTO • H1 BLOQUEADO • "
                            + reason.replace("_", " "),
                            "#FDE68A",
                        )
                    except Exception:
                        pass
                    return {
                        "event": "waiting_check",
                        "blocked_by": reason,
                        "snapshot": snapshot,
                    }
                if not bool(aprovado):
                    return {
                        "event": "waiting_check",
                        "blocked_by": "h1_nao_gera_ng_antes_do_referencial",
                        "snapshot": snapshot,
                    }
                app._display_f3_tracking_h1_confirmed_cycle = cycle
            elif getattr(
                app,
                "_display_f3_tracking_h1_confirmed_cycle",
                None,
            ) != cycle:
                return {
                    "event": "waiting_check",
                    "blocked_by": "h1_nao_confirmado_neste_ciclo",
                    "snapshot": snapshot,
                }

            event = previous_register(aprovado)
            if (
                isinstance(event, dict)
                and str(event.get("event") or "")
                in {"plate_ok", "plate_ng", "plate_discarded"}
            ):
                app._display_f3_tracking_h1_confirmed_cycle = None
            return event

        sequence.registrar_resultado_check = MethodType(
            guarded_register,
            sequence,
        )
        sequence._odin_f3_tracking_sequence_guard = True

    app._display_f3_tracking_instance_authority = True


def instalar_runtime_rastreamento_objetos_display_f3() -> None:
    """Instala alinhamento opt-in envolvendo apenas o loop F3."""
    from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin
    from src.platform.display_production_f3 import DisplayProductionF3Mixin

    process_current = DisplayAutomaticCheckF3Mixin._process_display_auto_check
    if not bool(getattr(process_current, "_odin_f3_object_tracking_guard", False)):
        process_previous = process_current

        def process_with_tracking_guard(self):
            if tracking_enabled(self):
                # Configuração aberta: mantenha a câmera viva, mas não execute
                # ORB nem decisão automática em segundo plano. Isso evita disputar
                # CPU com a janela de Projeto Display no Raspberry.
                if bool(getattr(self, "_display_f3_tracking_config_open", False)):
                    try:
                        self._display_auto_set_preview_status(
                            "CONFIGURAÇÃO F3 ABERTA • análise automática pausada",
                            "#94A3B8",
                        )
                    except Exception:
                        pass
                    try:
                        self._reset_display_auto_stability(transition=False)
                    except Exception:
                        pass
                    return None

                status = getattr(self, "_display_f3_object_tracking_last_status", {})
                if not isinstance(status, dict) or not bool(status.get("locked")):
                    # Depois de OK/NG/SEGREGAR o F3 PRECISA continuar enxergando
                    # o suporte vazio para fazer o handoff físico. Nesse estado,
                    # deixe o guard terminal anterior rodar sobre o frame bruto.
                    # Ele não executa CHECK; apenas confirma EMPTY -> nova placa.
                    rearm_pending = bool(
                        getattr(self, "_display_f3_waiting_empty_rearm", False)
                        or getattr(
                            self,
                            "_display_f3_waiting_new_board_after_empty",
                            False,
                        )
                    )
                    if rearm_pending:
                        return process_previous(self)

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
            if tracking_enabled(self):
                self._display_f3_auto_decision_in_progress = True
                try:
                    return process_previous(self)
                finally:
                    self._display_f3_auto_decision_in_progress = False
            return process_previous(self)

        process_with_tracking_guard._odin_f3_object_tracking_guard = True
        process_with_tracking_guard._odin_f3_object_tracking_guard_base = process_previous
        DisplayAutomaticCheckF3Mixin._process_display_auto_check = process_with_tracking_guard

    # Fail-safe final: mesmo que alguma camada histórica tente registrar um
    # resultado diretamente, o modo automático com tracking não pode avançar
    # para além do H1 sem energia física confirmada no MESMO ciclo.
    register_current = DisplayProductionF3Mixin.registrar_resultado_check_display_f3
    if not bool(getattr(register_current, "_odin_f3_tracking_h1_guard", False)):
        register_previous = register_current

        def register_with_tracking_h1_guard(self, aprovado: bool = True):
            automatic = bool(
                getattr(self, "_display_f3_auto_decision_in_progress", False)
            )
            if tracking_enabled(self) and automatic:
                runtime = getattr(self, "display_check_runtime", None)
                snapshot = runtime.snapshot() if runtime is not None else {}
                try:
                    cycle_token = int(snapshot.get("total", 0) or 0)
                except (TypeError, ValueError):
                    cycle_token = 0

                try:
                    context = self._display_auto_current_context()
                except Exception:
                    context = None
                reference_gate = bool(
                    isinstance(context, dict)
                    and self._display_auto_is_reference_gate(context)
                )

                if reference_gate:
                    analysis = getattr(self, "_display_auto_last_analysis", None)
                    try:
                        optical_power = self._display_auto_has_reference_power_evidence(
                            analysis
                        )
                    except Exception:
                        optical_power = False

                    power_status = getattr(
                        self,
                        "_display_f3_power_authority_status",
                        None,
                    )
                    physical_power = bool(
                        isinstance(power_status, dict)
                        and power_status.get("board_present") is True
                        and power_status.get("decision_allowed") is True
                        and isinstance(power_status.get("energy"), dict)
                        and power_status["energy"].get("powered_confirmed") is True
                    )

                    if not bool(aprovado) or not (optical_power and physical_power):
                        try:
                            self._display_auto_set_preview_status(
                                "AUTO • H1 • aguardando placa realmente ligada",
                                "#FDE68A",
                            )
                        except Exception:
                            pass
                        return {
                            "event": "waiting_check",
                            "blocked_by": "tracking_h1_power_guard",
                            "snapshot": snapshot,
                        }

                    self._display_f3_tracking_h1_confirmed_cycle = cycle_token
                else:
                    confirmed_cycle = getattr(
                        self,
                        "_display_f3_tracking_h1_confirmed_cycle",
                        None,
                    )
                    if confirmed_cycle != cycle_token:
                        try:
                            self._display_auto_set_preview_status(
                                "AUTO • aguardando confirmação H1 desta placa",
                                "#FDE68A",
                            )
                        except Exception:
                            pass
                        return {
                            "event": "waiting_check",
                            "blocked_by": "tracking_h1_cycle_guard",
                            "snapshot": snapshot,
                        }

            event = register_previous(self, aprovado)
            if (
                tracking_enabled(self)
                and automatic
                and isinstance(event, dict)
                and str(event.get("event") or "")
                in {"plate_ok", "plate_ng", "plate_discarded"}
            ):
                self._display_f3_tracking_h1_confirmed_cycle = None
            return event

        register_with_tracking_h1_guard._odin_f3_tracking_h1_guard = True
        register_with_tracking_h1_guard._odin_f3_tracking_h1_guard_base = (
            register_previous
        )
        DisplayProductionF3Mixin.registrar_resultado_check_display_f3 = (
            register_with_tracking_h1_guard
        )

    # O rastreamento pode usar um frame corrigido/rotacionado internamente,
    # mas a câmera que o operador vê deve continuar sendo a imagem REAL. Antes,
    # camera_frame_atual era substituído pelo warp do tracker durante todo o
    # ciclo e o preview parecia girar/entortar quando a pose mudava.
    base_preview_current = DisplayProductionF3Mixin._atualizar_preview_display_f3
    if not bool(getattr(base_preview_current, "_odin_f3_raw_preview_guard", False)):
        base_preview_previous = base_preview_current

        def base_preview_with_raw_camera(self):
            raw_preview = getattr(
                self,
                "_display_f3_tracking_raw_preview_frame",
                None,
            )
            if not _valid_frame(raw_preview):
                return base_preview_previous(self)

            current = getattr(self, "camera_frame_atual", None)
            self.camera_frame_atual = raw_preview
            try:
                return base_preview_previous(self)
            finally:
                self.camera_frame_atual = current

        base_preview_with_raw_camera._odin_f3_raw_preview_guard = True
        base_preview_with_raw_camera._odin_f3_raw_preview_guard_base = (
            base_preview_previous
        )
        DisplayProductionF3Mixin._atualizar_preview_display_f3 = (
            base_preview_with_raw_camera
        )

    # O wrapper precisa ficar na camada MAIS EXTERNA do loop F3. O mixin
    # automático chama super()._atualizar_preview_display_f3() e somente depois
    # executa _process_display_auto_check(); se alinhássemos apenas a classe base,
    # o frame bruto seria restaurado antes da análise dos CHECKS. Envolvendo o
    # DisplayAutomaticCheckF3Mixin, preview, presença, referências, máscaras e
    # análise automática enxergam o MESMO frame canônico durante todo o ciclo.
    preview_current = DisplayAutomaticCheckF3Mixin._atualizar_preview_display_f3
    if not bool(getattr(preview_current, "_odin_f3_object_tracking_runtime", False)):
        preview_previous = preview_current

        def preview_with_tracking(self):
            if not tracking_enabled(self):
                # Contrato opt-in: desligado, o F3 percorre literalmente a cadeia
                # anterior, sem cópia, warp, bloqueio ou alteração de estado.
                return preview_previous(self)

            if bool(getattr(self, "_display_f3_tracking_config_open", False)):
                # A câmera continua atualizando a janela F3 e alimentando o
                # frame_provider das configurações, mas o rastreamento pesado
                # fica suspenso até fechar a janela.
                return preview_previous(self)

            raw = getattr(self, "camera_frame_atual", None)
            if not _valid_frame(raw):
                return preview_previous(self)

            aligned, result = align_frame_for_f3(self, raw)
            locked = bool(result is not None and result.locked)
            self._display_f3_tracking_result = result
            _update_tracking_live_geometry(self, raw, result)
            if not locked:
                # O preview ao vivo continua visível no frame bruto enquanto o
                # guard de _process_display_auto_check impede decisão produtiva.
                return preview_previous(self)

            # Para análise do CHECK atual, alinhe a câmera ao MESMO espaço da
            # foto do CHECK onde placa e máscaras foram ajustadas. O operador,
            # porém, continua vendo o frame bruto + geometria rastreada.
            analysis_aligned, _analysis_matrix = _analysis_alignment_for_current_check(
                self,
                raw,
                result,
            )
            if not _valid_frame(analysis_aligned):
                analysis_aligned = aligned

            self._display_f3_tracking_raw_preview_frame = raw
            self.camera_frame_atual = analysis_aligned
            self._display_f3_tracking_frame_override_depth = int(
                getattr(self, "_display_f3_tracking_frame_override_depth", 0) or 0
            ) + 1
            restore_project = _install_orientation_project_view(
                self,
                str(result.reference or ""),
            )
            try:
                return preview_previous(self)
            finally:
                try:
                    restore_project()
                finally:
                    self.camera_frame_atual = raw
                    self._display_f3_tracking_raw_preview_frame = None
                    self._display_f3_tracking_frame_override_depth = max(
                        0,
                        int(getattr(self, "_display_f3_tracking_frame_override_depth", 1) or 1) - 1,
                    )

        preview_with_tracking._odin_f3_object_tracking_runtime = True
        preview_with_tracking._odin_f3_object_tracking_runtime_base = preview_previous
        DisplayAutomaticCheckF3Mixin._atualizar_preview_display_f3 = preview_with_tracking

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
