from __future__ import annotations

"""Rastreamento de objetos exclusivo do Display F3.

Este módulo não reutiliza nem modifica estado, arquivos ou classes de runtime do F2.
O F3 possui:
- flag própria ``display_f3_object_tracking_enabled``;
- arquivo próprio ``odin_display_tracking.json`` para flag + contorno canônico;
- contorno da placa/display salvo em "Placa + Máscaras";
- rastreamento estrutural para localizar a região da placa/filtro;
- refinamento da pose pelos segmentos luminosos esperados no CHECK atual;
- reprojeção das máscaras antes da classificação semântica ON/OFF/POUCA LUZ.

Não existe banco produtivo de imagens angulares 90°/180°/270°. Quando a opção
está desligada, o pipeline F3 recebe literalmente o mesmo frame que recebia antes
deste módulo.
"""

import base64
import json
import math
import shutil
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
from src.platform.display_f3_heavy_executor import (
    F3HeavyWorkPriority,
)
from src.platform.display_f3_mask_editor_reference import (
    DisplayMaskEditorReferenceStore,
)
from src.platform.display_mask_geometry import (
    bbox_mascara_display,
    converter_mascara_legada_para_editor,
    pontos_mascara_display,
    sincronizar_colecao_mascaras_display,
    sincronizar_formato_mascara_display,
)
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_ON,
    DisplayProjectRepository,
    normalizar_mascaras_display,
    normalizar_nome_projeto_display,
    normalizar_resolucao_display,
)
from src.platform.display_visual_reference_status import (
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
    DisplayProjectPresenceReferenceStore,
)


F3_TRACKING_SCHEMA_VERSION = 2
F3_TRACKING_CONFIG_FILENAME = "odin_display_tracking.json"
F3_TRACKING_SETTING_KEY = "display_f3_object_tracking_enabled"

F3_TRACKING_REFRESH_S = 0.12
# 1200 mantém margem ampla de correspondências nas referências reais e reduz
# custo de detectAndCompute em 1920x1080. O fallback temporal/template permanece.
F3_TRACKING_ORB_FEATURES = 1200
F3_TRACKING_RATIO_TEST = 0.75
F3_TRACKING_MIN_MATCHES = 12
F3_TRACKING_MIN_INLIERS = 8
F3_TRACKING_MIN_INLIER_RATIO = 0.34
# Segundo descritor usado somente para reacquisition quando o ORB falha.
# AKAZE é mais caro, porém mais robusto a contraste, escala e pequenas rotações;
# por isso não roda no caminho nominal de todos os frames.
F3_TRACKING_AKAZE_THRESHOLD = 0.0008
F3_TRACKING_AKAZE_RATIO_TEST = 0.80
F3_TRACKING_AKAZE_MIN_MATCHES = 8
F3_TRACKING_AKAZE_MIN_INLIERS = 6
F3_TRACKING_AKAZE_MIN_INLIER_RATIO = 0.28
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
# Quando o CHECK lógico já é conhecido, a foto dele pode recuperar SOMENTE a
# pose geométrica. O conteúdo dos segmentos fica excluído pelo support mask e
# jamais aprova o CHECK. Isso permite relock em displays com segmento defeituoso.
F3_TRACKING_CURRENT_CHECK_TEMPLATE_MIN_SCORE = 0.30
# BOARD_OFF é uma excelente âncora estrutural quando a placa está presente mas
# o display ainda não acendeu. Usá-la para pose NÃO declara estado de energia.
F3_TRACKING_BOARD_OFF_TEMPLATE_MIN_SCORE = 0.30
F3_TRACKING_TEMPLATE_MIN_SIZE = 28
F3_TRACKING_TEMPLATE_PADDING_FRACTION = 0.035
# Último recurso estrutural: poucas variantes controladas, executadas somente
# para a referência direta quando ORB/AKAZE/template nominal falharem.
F3_TRACKING_ADAPTIVE_TEMPLATE_SCALES = (0.90, 1.00, 1.10)
F3_TRACKING_ADAPTIVE_TEMPLATE_ANGLES_DEG = (-12.0, 0.0, 12.0)

# Continuidade temporal: a placa pode se mover, mas câmera e suporte são fixos.
# ORB/multivista continua sendo a autoridade absoluta; fluxo óptico cobre os
# intervalos em que uma referência perde contraste por poucos frames.
F3_TRACKING_TEMPORAL_MAX_CORNERS = 320
F3_TRACKING_TEMPORAL_MIN_POINTS = 12
F3_TRACKING_TEMPORAL_MIN_INLIERS = 8
F3_TRACKING_TEMPORAL_MIN_INLIER_RATIO = 0.46
F3_TRACKING_TEMPORAL_MAX_ROTATION_DEG = 24.0
F3_TRACKING_TEMPORAL_MIN_SCALE = 0.82
F3_TRACKING_TEMPORAL_MAX_SCALE = 1.22
F3_TRACKING_TEMPORAL_MAX_TRANSLATION_FRACTION = 0.22
F3_TRACKING_LOCK_GRACE_FRAMES = 5
F3_TRACKING_LOCK_GRACE_S = 0.72
F3_TRACKING_REFERENCE_STICK_BONUS = 2.5
F3_TRACKING_CONTINUITY_BONUS = 5.0
# A placa pode deslocar e girar gradualmente, mas um salto instantâneo próximo de
# 90° entre duas poses verificadas é uma hipótese geométrica ambígua, não movimento
# físico plausível do suporte. O anchor é limpo somente no reset/rearme do ciclo.
F3_TRACKING_MAX_ABRUPT_ROTATION_DELTA_DEG = 35.0

F3_TRACKING_EXECUTOR_OWNER = "f3-live-tracking"
F3_TRACKING_EXECUTOR_KEY = "latest-frame"
F3_SEMANTIC_EXECUTOR_KEY = "semantic-latest"
# Resultados de visão podem terminar depois que dezenas de frames novos já
# chegaram. Geometria antiga pode servir como hint visual, mas nunca deve
# substituir a câmera atual nem alimentar decisão produtiva muito atrasada.
F3_TRACKING_MAX_OPERATIONAL_RESULT_AGE_MS = 1200.0
F3_TRACKING_MAX_OPERATIONAL_FRAME_GAP = 24

F3_TRACKING_MASK_BGR = (21, 204, 250)
F3_TRACKING_BOARD_BGR = (248, 189, 56)
F3_TRACKING_SELECTED_BGR = (94, 234, 212)

# Reaquisição/refino guiado somente pelos segmentos que realmente emitem luz.
# O contorno salvo passa a representar o filtro preto: ele limita a busca, mas
# nunca fixa as 28 máscaras no frame atual. As máscaras configuradas são o
# modelo canônico que os pontos luminosos precisam reencontrar.
F3_TRACKING_FILTER_SEARCH_MAX_WIDTH = 960
F3_TRACKING_FILTER_MIN_AREA_FACTOR = 0.28
F3_TRACKING_FILTER_MAX_AREA_FACTOR = 3.60
F3_TRACKING_FILTER_MIN_RECTANGULARITY = 0.46
F3_TRACKING_FILTER_MIN_ASPECT_SCORE = 0.50
F3_TRACKING_FILTER_MAX_CANDIDATES = 6
F3_TRACKING_LUMINOUS_MIN_DYNAMIC_RANGE = 32.0
F3_TRACKING_LUMINOUS_MIN_COMPONENTS = 3
F3_TRACKING_LUMINOUS_MIN_MATCH_RATIO = 0.55
F3_TRACKING_LUMINOUS_COARSE_GATE_FRACTION = 0.16
F3_TRACKING_LUMINOUS_FINAL_GATE_FRACTION = 0.055
F3_TRACKING_LUMINOUS_MIN_COMPONENT_AREA_FRACTION = 0.00010
F3_TRACKING_LUMINOUS_MAX_COMPONENT_AREA_FRACTION = 0.055
# Blooming do display pode unir dois ou mais segmentos em um único contorno.
# Com lock estrutural atual, pixels luminosos são repartidos entre os centros ON
# esperados para recuperar landmarks sem reduzir o quorum espacial do CHECK.
F3_TRACKING_LUMINOUS_LOCAL_GATE_FRACTION = 0.09
F3_TRACKING_LUMINOUS_LOCAL_MIN_HOT_PIXELS = 6
# Com o filtro/placa já localizado, três segmentos luminosos identificáveis
# bastam para corrigir a pose fina. Isso é geometria, não aprovação do CHECK.
F3_TRACKING_LUMINOUS_STRUCTURAL_MIN_MATCHES = 3
F3_TRACKING_LUMINOUS_LOCAL_MASK_PADDING_FRACTION = 0.55
F3_TRACKING_LUMINOUS_LOCAL_MASK_PADDING_MIN_PX = 6.0
F3_TRACKING_LUMINOUS_LOCAL_MIN_SPAN_FRACTION = 0.06
F3_TRACKING_LUMINOUS_LOCAL_RANSAC_PX = 6.0

# O contorno/filtro é a autoridade da pose grossa. A luz pode corrigir o
# alinhamento fino, mas nunca pode torcer o conjunto inteiro por um casamento
# errado entre poucos segmentos.
F3_TRACKING_LUMINOUS_MAX_ROTATION_DELTA_DEG = 8.0
F3_TRACKING_LUMINOUS_MIN_SCALE_RATIO_TO_COARSE = 0.88
F3_TRACKING_LUMINOUS_MAX_SCALE_RATIO_TO_COARSE = 1.12
F3_TRACKING_LUMINOUS_MAX_CENTER_SHIFT_FRACTION = 0.10


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_frame(frame) -> bool:
    return frame is not None and getattr(frame, "size", 0) > 0


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


class F3TrackingConfigStore:
    """Sidecar exclusivo do tracking F3: flag global + contorno canônico por projeto."""

    def __init__(self, repository: DisplayProjectRepository) -> None:
        self.repository = repository
        config_file = Path(
            getattr(repository, "config_file", "data/config/odin_display_projects.json")
        )
        self.config_file = config_file.parent / F3_TRACKING_CONFIG_FILENAME
        self._cache_signature: tuple[int, int] | None = None
        self._cache_data: dict | None = None
        self._migrate_legacy_rotation_state()

    def _migrate_legacy_rotation_state(self) -> None:
        """Remove definitivamente o banco angular legado sem tocar outras referências."""

        legacy_image_dir = self.config_file.parent / "display_tracking_orientations"
        try:
            if legacy_image_dir.is_dir():
                shutil.rmtree(legacy_image_dir)
        except OSError:
            # Falha de limpeza não pode impedir a abertura do Projeto Display.
            pass

        if not self.config_file.is_file():
            return
        try:
            data = json.loads(self.config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return
        if not isinstance(data, dict):
            return

        try:
            schema_version = int(data.get("schema_version", 0) or 0)
        except (TypeError, ValueError):
            schema_version = 0

        projects = data.get("projects", {})
        has_legacy_orientations = bool(
            isinstance(projects, dict)
            and any(
                isinstance(project, dict) and "orientations" in project
                for project in projects.values()
            )
        )
        if schema_version < F3_TRACKING_SCHEMA_VERSION or has_legacy_orientations:
            # _write normaliza para flag + contorno canônico e elimina
            # imagens/contornos/máscaras pertencentes aos antigos slots.
            self._write(data)

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
        if self._cache_data is not None and signature == self._cache_signature:
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
                projects[name] = {
                    "board_points": _normalize_points(
                        raw_project.get("board_points"),
                        minimum=3,
                    ),
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
                normalized["projects"][name] = {
                    "board_points": _normalize_points(
                        raw_project.get("board_points"),
                        minimum=3,
                    ),
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
            "updated_at": "",
        }

    def board_points(self, project_name: str) -> list[list[float]]:
        return _normalize_points(
            self.project(project_name).get("board_points"),
            minimum=3,
        )

    def save_board_points(self, project_name: str, points) -> bool:
        name = normalizar_nome_projeto_display(project_name)
        normalized = _normalize_points(points, minimum=3)
        if not name or not normalized:
            return False
        data = self._load()
        project = data["projects"].setdefault(
            name,
            {"board_points": [], "updated_at": ""},
        )
        project["board_points"] = normalized
        project["updated_at"] = _utc_now()
        self._write(data)
        return True

    def rename_project(self, old_name: str, new_name: str) -> None:
        old = normalizar_nome_projeto_display(old_name)
        new = normalizar_nome_projeto_display(new_name)
        if not old or not new or old == new:
            return
        data = self._load()
        saved = data.get("projects", {}).pop(old, None)
        if isinstance(saved, dict):
            data["projects"][new] = saved
            self._write(data)

    def remove_project(self, project_name: str) -> None:
        name = normalizar_nome_projeto_display(project_name)
        if not name:
            return
        data = self._load()
        if data.get("projects", {}).pop(name, None) is not None:
            self._write(data)


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


def _angle_delta_deg(first: float, second: float) -> float:
    return abs((float(first) - float(second) + 180.0) % 360.0 - 180.0)


def _runtime_rotation_anchor_compatible(runtime, matrix) -> tuple[bool, float]:
    """Primitiva tolerante para runtime real e doubles de teste."""
    if matrix is None:
        return False, 0.0
    anchor = getattr(runtime, "last_verified_rotation_deg", None)
    if anchor is None:
        return True, 0.0
    current = affine_rotation_deg(matrix)
    delta = _angle_delta_deg(current, float(anchor))
    return (
        delta <= F3_TRACKING_MAX_ABRUPT_ROTATION_DELTA_DEG,
        float(delta),
    )


def _runtime_filter_abrupt_rotation_candidates(
    runtime,
    candidates,
    *,
    source: str,
) -> list[dict]:
    values = [
        item for item in (candidates or ())
        if isinstance(item, dict)
    ]
    if not values:
        return []

    accepted = []
    rejected = []
    for candidate in values:
        compatible, delta = _runtime_rotation_anchor_compatible(
            runtime,
            candidate.get("matrix"),
        )
        if compatible:
            accepted.append(candidate)
            continue
        rejected.append(
            {
                "source": str(source or ""),
                "reference": str(candidate.get("reference") or ""),
                "rotation_deg": round(
                    float(
                        candidate.get(
                            "rotation_deg",
                            affine_rotation_deg(candidate.get("matrix")),
                        )
                        or 0.0
                    ),
                    3,
                ),
                "rotation_delta_deg": round(float(delta), 3),
                "reason": "abrupt_rotation_jump_rejected",
            }
        )

    if rejected:
        history = getattr(
            runtime,
            "_last_rotation_jump_rejections",
            None,
        )
        if not isinstance(history, list):
            history = []
        history.extend(rejected)
        try:
            runtime._last_rotation_jump_rejections = history[-12:]
        except Exception:
            pass
    return accepted


def _luminous_refinement_within_coarse_guard(
    refined_matrix,
    coarse_matrix,
    canonical_board,
) -> tuple[bool, dict]:
    """Impede que landmarks luminosos substituam a pose estrutural por uma torta."""

    try:
        refined = np.asarray(refined_matrix, dtype=np.float32).reshape(2, 3)
        coarse = np.asarray(coarse_matrix, dtype=np.float32).reshape(2, 3)
        if not np.all(np.isfinite(refined)) or not np.all(np.isfinite(coarse)):
            raise ValueError("non_finite_matrix")

        refined_scale = affine_scale(refined)
        coarse_scale = affine_scale(coarse)
        scale_ratio = refined_scale / max(1e-6, coarse_scale)
        rotation_delta = _angle_delta_deg(
            affine_rotation_deg(refined),
            affine_rotation_deg(coarse),
        )

        board = np.asarray(
            _quad_from_points(canonical_board),
            dtype=np.float32,
        ).reshape(-1, 2)
        if len(board) != 4:
            raise ValueError("invalid_board")
        center = np.mean(board, axis=0).reshape(1, 1, 2)
        board_column = board.reshape(-1, 1, 2)

        coarse_to_current = cv2.invertAffineTransform(coarse)
        refined_to_current = cv2.invertAffineTransform(refined)
        coarse_center = cv2.transform(center, coarse_to_current).reshape(2)
        refined_center = cv2.transform(center, refined_to_current).reshape(2)
        coarse_board = cv2.transform(
            board_column,
            coarse_to_current,
        ).reshape(-1, 2)
        board_diagonal = max(
            1.0,
            float(
                np.linalg.norm(
                    np.max(coarse_board, axis=0)
                    - np.min(coarse_board, axis=0)
                )
            ),
        )
        center_shift = float(np.linalg.norm(refined_center - coarse_center))
        center_shift_fraction = center_shift / board_diagonal
    except Exception:
        return False, {"reason": "guard_geometry_invalid"}

    accepted = bool(
        rotation_delta <= F3_TRACKING_LUMINOUS_MAX_ROTATION_DELTA_DEG
        and F3_TRACKING_LUMINOUS_MIN_SCALE_RATIO_TO_COARSE
        <= scale_ratio
        <= F3_TRACKING_LUMINOUS_MAX_SCALE_RATIO_TO_COARSE
        and center_shift_fraction
        <= F3_TRACKING_LUMINOUS_MAX_CENTER_SHIFT_FRACTION
    )
    return accepted, {
        "reason": "" if accepted else "refinement_outside_structural_guard",
        "rotation_delta_deg": round(float(rotation_delta), 3),
        "scale_ratio_to_coarse": round(float(scale_ratio), 5),
        "center_shift_px": round(float(center_shift), 3),
        "center_shift_fraction": round(float(center_shift_fraction), 5),
    }


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

    if kind == "segment":
        point = affine @ np.asarray(
            [float(source.get("cx", 0)), float(source.get("cy", 0)), 1.0],
            dtype=np.float32,
        )
        scale = affine_scale(affine)
        angle = (
            float(source.get("angle", 0.0) or 0.0)
            + affine_rotation_deg(affine)
            + 180.0
        ) % 360.0 - 180.0
        return {
            "id": mask_id,
            "type": "segment",
            "cx": float(point[0]),
            "cy": float(point[1]),
            "width": max(1.0, float(source.get("width", 1)) * scale),
            "height": max(1.0, float(source.get("height", 1)) * scale),
            "angle": float(angle),
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
        item = (
            sincronizar_formato_mascara_display(base, raw)
            if isinstance(raw, dict)
            else deepcopy(base)
        )
        item["id"] = mask_id
        result.append(converter_mascara_legada_para_editor(item))
    return result


def _reference_masks_from_metadata(
    project: dict,
    metadata: dict | None,
    *,
    explicit_only: bool = False,
) -> list[dict]:
    value = metadata if isinstance(metadata, dict) else {}
    if "masks_reference" in value:
        local_masks = []
        for raw in value.get("masks_reference", []) or []:
            normalized = _normalize_mask_override(raw)
            if normalized is not None:
                local_masks.append(
                    converter_mascara_legada_para_editor(normalized)
                )
        return sincronizar_colecao_mascaras_display(
            project.get("masks", []) or [],
            local_masks,
            somente_ids_locais=True,
        )
    return _reference_masks_from_overrides(
        project,
        value.get("mask_overrides_reference", {}),
        explicit_only=explicit_only,
    )


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



def _quad_from_points(points) -> list[list[float]]:
    """Reduz um contorno salvo ao retângulo orientado usado como filtro."""
    normalized = _normalize_points(points, minimum=3)
    if len(normalized) < 3:
        return []
    try:
        rect = cv2.minAreaRect(
            np.asarray(normalized, dtype=np.float32).reshape(-1, 1, 2)
        )
        box = cv2.boxPoints(rect)
    except Exception:
        return []
    return [
        [float(point[0]), float(point[1])]
        for point in np.asarray(box, dtype=np.float32).reshape(-1, 2)
    ]


def _quad_metrics(points) -> tuple[float, float, float]:
    quad = _quad_from_points(points)
    if len(quad) != 4:
        return 0.0, 0.0, 0.0
    try:
        rect = cv2.minAreaRect(
            np.asarray(quad, dtype=np.float32).reshape(-1, 1, 2)
        )
        width, height = float(rect[1][0]), float(rect[1][1])
    except Exception:
        return 0.0, 0.0, 0.0
    major = max(width, height)
    minor = min(width, height)
    area = major * minor
    return major, minor, area


def _filter_board_matrix_candidates(current_board, canonical_board) -> list[np.ndarray]:
    """Gera CURRENT -> CANÔNICO para as orientações possíveis do filtro.

    Um retângulo isolado é ambíguo em 0/90/180/270 graus. A etapa luminosa
    escolhe depois qual hipótese faz os segmentos ACESOS coincidirem com o
    padrão ON do CHECK atual.
    """
    current = _quad_from_points(current_board)
    canonical = _quad_from_points(canonical_board)
    if len(current) != 4 or len(canonical) != 4:
        return []

    cur = np.asarray(current, dtype=np.float32)
    can = np.asarray(canonical, dtype=np.float32)
    matrices: list[np.ndarray] = []
    signatures: set[tuple] = set()

    for reverse in (False, True):
        ordered = cur[::-1].copy() if reverse else cur.copy()
        for shift in range(4):
            candidate = np.roll(ordered, shift, axis=0)
            matrix = _estimate_affine_partial(candidate, can)
            if matrix is None:
                continue
            key = tuple(
                np.asarray(matrix, dtype=np.float32).round(4).reshape(-1).tolist()
            )
            if key in signatures:
                continue
            signatures.add(key)
            matrices.append(
                np.asarray(matrix, dtype=np.float32).reshape(2, 3)
            )
    return matrices


def _detect_dark_filter_candidates(
    frame,
    canonical_board,
    canonical_resolution,
) -> list[dict]:
    """Localiza o retângulo preto sem usar a posição salva como posição atual."""
    if not _valid_frame(frame):
        return []
    resolution = normalizar_resolucao_display(canonical_resolution)
    if resolution is None:
        return []

    canonical_major, canonical_minor, canonical_area = _quad_metrics(
        canonical_board
    )
    if canonical_area <= 1.0 or canonical_minor <= 1.0:
        return []

    frame_h, frame_w = frame.shape[:2]
    canonical_frame_area = max(1.0, float(resolution[0] * resolution[1]))
    expected_area_fraction = canonical_area / canonical_frame_area
    expected_aspect = canonical_major / max(1.0, canonical_minor)

    search_scale = min(
        1.0,
        float(F3_TRACKING_FILTER_SEARCH_MAX_WIDTH) / max(1.0, float(frame_w)),
    )
    if search_scale < 0.999:
        search = cv2.resize(
            frame,
            (
                max(1, int(round(frame_w * search_scale))),
                max(1, int(round(frame_h * search_scale))),
            ),
            interpolation=cv2.INTER_AREA,
        )
    else:
        search = frame

    try:
        gray = cv2.cvtColor(search, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        _threshold, dark = cv2.threshold(
            gray,
            0,
            255,
            cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
        )
        dark = cv2.morphologyEx(
            dark,
            cv2.MORPH_CLOSE,
            np.ones((5, 5), dtype=np.uint8),
            iterations=1,
        )
        contours, _hierarchy = cv2.findContours(
            dark,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
    except Exception:
        return []

    search_h, search_w = gray.shape[:2]
    search_area = max(1.0, float(search_w * search_h))
    candidates: list[dict] = []

    for contour in contours:
        try:
            contour_area = float(cv2.contourArea(contour))
            rect = cv2.minAreaRect(contour)
            rw, rh = float(rect[1][0]), float(rect[1][1])
        except Exception:
            continue
        if contour_area <= 0.0 or rw <= 2.0 or rh <= 2.0:
            continue

        major = max(rw, rh)
        minor = min(rw, rh)
        rect_area = major * minor
        area_fraction = rect_area / search_area
        area_factor = area_fraction / max(1e-9, expected_area_fraction)
        if not (
            F3_TRACKING_FILTER_MIN_AREA_FACTOR
            <= area_factor
            <= F3_TRACKING_FILTER_MAX_AREA_FACTOR
        ):
            continue

        rectangularity = contour_area / max(1.0, rect_area)
        if rectangularity < F3_TRACKING_FILTER_MIN_RECTANGULARITY:
            continue

        aspect = major / max(1.0, minor)
        aspect_score = math.exp(
            -abs(math.log(max(1e-6, aspect / expected_aspect)))
        )
        if aspect_score < F3_TRACKING_FILTER_MIN_ASPECT_SCORE:
            continue

        box = cv2.boxPoints(rect).astype(np.float32)
        region = np.zeros_like(gray, dtype=np.uint8)
        cv2.fillConvexPoly(
            region,
            np.rint(box).astype(np.int32),
            255,
            lineType=cv2.LINE_AA,
        )
        pixels = gray[region > 0]
        if pixels.size < 64:
            continue
        darkness_score = max(
            0.0,
            min(1.0, 1.0 - float(np.median(pixels)) / 255.0),
        )
        area_score = math.exp(abs(math.log(max(1e-6, area_factor))) * -1.0)
        score = (
            aspect_score * 2.0
            + rectangularity
            + area_score
            + darkness_score
        )

        inv_scale = 1.0 / max(1e-9, search_scale)
        points = [
            [float(point[0]) * inv_scale, float(point[1]) * inv_scale]
            for point in box
        ]
        candidates.append(
            {
                "points": points,
                "score": float(score),
                "area_factor": float(area_factor),
                "aspect_score": float(aspect_score),
                "rectangularity": float(rectangularity),
                "darkness_score": float(darkness_score),
                "source": "dark_filter_detector",
            }
        )

    candidates.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    return candidates[:F3_TRACKING_FILTER_MAX_CANDIDATES]


def _detect_luminous_segment_centers(frame, filter_points) -> dict:
    """Detecta somente emissão luminosa dentro do filtro preto.

    Depois que o filtro foi localizado, nenhum processamento óptico de segmentos
    percorre a cena inteira: HSV, threshold, morfologia e componentes trabalham
    somente no bounding crop do filtro. Segmentos apagados não são procurados.
    """
    if not _valid_frame(frame):
        return {
            "available": False,
            "reason": "invalid_frame",
            "centers": [],
        }
    points = _normalize_points(filter_points, minimum=3)
    if len(points) < 3:
        return {
            "available": False,
            "reason": "filter_geometry_missing",
            "centers": [],
        }

    frame_h, frame_w = frame.shape[:2]
    polygon_global = np.rint(
        np.asarray(points, dtype=np.float32)
    ).astype(np.int32)
    try:
        bx, by, bw, bh = cv2.boundingRect(
            polygon_global.reshape(-1, 1, 2)
        )
    except Exception:
        return {
            "available": False,
            "reason": "filter_crop_invalid",
            "centers": [],
        }

    pad = max(2, int(round(max(bw, bh) * 0.01)))
    x1 = max(0, int(bx) - pad)
    y1 = max(0, int(by) - pad)
    x2 = min(int(frame_w), int(bx + bw) + pad)
    y2 = min(int(frame_h), int(by + bh) + pad)
    if x2 - x1 < 8 or y2 - y1 < 8:
        return {
            "available": False,
            "reason": "filter_crop_too_small",
            "centers": [],
        }

    crop = frame[y1:y2, x1:x2]
    if not _valid_frame(crop):
        return {
            "available": False,
            "reason": "filter_crop_invalid",
            "centers": [],
        }

    polygon = polygon_global.copy()
    polygon[:, 0] -= int(x1)
    polygon[:, 1] -= int(y1)
    crop_h, crop_w = crop.shape[:2]
    filter_mask = np.zeros((crop_h, crop_w), dtype=np.uint8)
    cv2.fillPoly(filter_mask, [polygon], 255, lineType=cv2.LINE_AA)
    if int(cv2.countNonZero(filter_mask)) < 128:
        return {
            "available": False,
            "reason": "filter_area_too_small",
            "centers": [],
        }

    # Remove a borda do filtro, que costuma produzir reflexo forte.
    filter_major, filter_minor, _filter_rect_area = _quad_metrics(points)
    erode_px = max(
        2,
        int(round(min(filter_major, filter_minor) * 0.018)),
    )
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (erode_px * 2 + 1, erode_px * 2 + 1),
    )
    inner_mask = cv2.erode(filter_mask, kernel, iterations=1)
    if int(cv2.countNonZero(inner_mask)) < 128:
        inner_mask = filter_mask

    try:
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        value = hsv[:, :, 2]
    except Exception:
        return {
            "available": False,
            "reason": "hsv_prepare_failed",
            "centers": [],
        }

    samples = value[inner_mask > 0]
    if samples.size < 128:
        return {
            "available": False,
            "reason": "filter_samples_insufficient",
            "centers": [],
        }

    median_v = float(np.percentile(samples, 50))
    p95_v = float(np.percentile(samples, 95))
    p995_v = float(np.percentile(samples, 99.5))
    dynamic_range = p995_v - median_v
    if dynamic_range < F3_TRACKING_LUMINOUS_MIN_DYNAMIC_RANGE:
        return {
            "available": False,
            "reason": "no_luminous_emission",
            "centers": [],
            "median_v": round(median_v, 3),
            "p95_v": round(p95_v, 3),
            "p995_v": round(p995_v, 3),
            "dynamic_range": round(dynamic_range, 3),
            "analysis_roi": (int(x1), int(y1), int(x2), int(y2)),
        }

    threshold = median_v + max(24.0, dynamic_range * 0.38)
    threshold = max(45.0, min(p995_v - 2.0, threshold))
    binary = np.zeros((crop_h, crop_w), dtype=np.uint8)
    binary[
        (value.astype(np.float32) >= float(threshold))
        & (inner_mask > 0)
    ] = 255
    binary = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        np.ones((2, 2), dtype=np.uint8),
        iterations=1,
    )
    binary = cv2.morphologyEx(
        binary,
        cv2.MORPH_CLOSE,
        np.ones((3, 3), dtype=np.uint8),
        iterations=1,
    )

    try:
        contours, _hierarchy = cv2.findContours(
            binary,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
    except Exception:
        contours = []

    filter_area = max(
        1.0,
        abs(float(cv2.contourArea(polygon.reshape(-1, 1, 2)))),
    )
    centers: list[list[float]] = []
    components: list[dict] = []

    for contour in contours:
        try:
            area = float(cv2.contourArea(contour))
            rect = cv2.minAreaRect(contour)
            (cx_local, cy_local), (rw, rh), angle = rect
        except Exception:
            continue
        if area <= 0.0 or rw <= 1.0 or rh <= 1.0:
            continue
        area_fraction = area / filter_area
        if not (
            F3_TRACKING_LUMINOUS_MIN_COMPONENT_AREA_FRACTION
            <= area_fraction
            <= F3_TRACKING_LUMINOUS_MAX_COMPONENT_AREA_FRACTION
        ):
            continue

        major = max(float(rw), float(rh))
        minor = min(float(rw), float(rh))
        elongation = major / max(1.0, minor)
        if elongation < 1.18:
            continue
        if major > max(12.0, filter_major * 0.38):
            continue
        if minor > max(10.0, filter_minor * 0.34):
            continue

        rectangularity = area / max(1.0, float(rw) * float(rh))
        if rectangularity < 0.18:
            continue

        center = [
            float(cx_local) + float(x1),
            float(cy_local) + float(y1),
        ]
        centers.append(center)
        components.append(
            {
                "center": center,
                "area": round(area, 3),
                "area_fraction": round(area_fraction, 6),
                "elongation": round(elongation, 4),
                "rectangularity": round(rectangularity, 4),
                "angle": round(float(angle), 3),
            }
        )

    return {
        "available": len(centers) >= F3_TRACKING_LUMINOUS_MIN_COMPONENTS,
        "reason": (
            "luminous_segments_detected"
            if len(centers) >= F3_TRACKING_LUMINOUS_MIN_COMPONENTS
            else "luminous_components_insufficient"
        ),
        "centers": centers,
        "components": components,
        "threshold_v": round(float(threshold), 3),
        "median_v": round(median_v, 3),
        "p95_v": round(p95_v, 3),
        "p995_v": round(p995_v, 3),
        "dynamic_range": round(dynamic_range, 3),
        "analysis_roi": (int(x1), int(y1), int(x2), int(y2)),
        "analysis_width": int(crop_w),
        "analysis_height": int(crop_h),
    }


def _robust_luminous_cluster_center(cluster) -> list[float] | None:
    """Centro robusto de uma emissão, resistente a blooming/reflexo assimétrico."""
    try:
        points = np.asarray(cluster, dtype=np.float32).reshape(-1, 2)
    except Exception:
        return None
    if len(points) < 1 or not np.all(np.isfinite(points)):
        return None

    median = np.median(points, axis=0)
    low = np.percentile(points, 12.0, axis=0)
    high = np.percentile(points, 88.0, axis=0)
    envelope_center = (low + high) / 2.0
    center = (median * 0.65) + (envelope_center * 0.35)
    return [float(center[0]), float(center[1])]


def _detect_expected_on_luminous_landmarks(
    frame,
    filter_points,
    expected_rows,
    current_to_fit,
    threshold_v,
) -> dict:
    """Recupera landmarks ON quando blooming funde segmentos em um só contorno.

    Este caminho só é válido com uma matriz estrutural CURRENT -> FIT atual.
    Ela fornece apenas a vizinhança grosseira de cada ON esperado. Os pixels
    realmente luminosos dentro do filtro são então atribuídos ao centro esperado
    mais próximo (Voronoi local), de modo que um blob conectado possa voltar a
    fornecer landmarks independentes sem fabricar OFF nem reduzir o quorum.
    """
    if not _valid_frame(frame):
        return {"available": False, "reason": "invalid_frame", "centers": []}

    points = _normalize_points(filter_points, minimum=3)
    if len(points) < 3:
        return {
            "available": False,
            "reason": "filter_geometry_missing",
            "centers": [],
        }
    if len(expected_rows) < F3_TRACKING_LUMINOUS_MIN_COMPONENTS:
        return {
            "available": False,
            "reason": "expected_on_segments_insufficient",
            "centers": [],
        }

    try:
        threshold = float(threshold_v)
        current_to_fit_matrix = np.asarray(
            current_to_fit,
            dtype=np.float32,
        ).reshape(2, 3)
        fit_to_current = cv2.invertAffineTransform(current_to_fit_matrix)
        expected = np.asarray(
            [row["center"] for row in expected_rows],
            dtype=np.float32,
        ).reshape(-1, 1, 2)
        predicted = cv2.transform(
            expected,
            fit_to_current,
        ).reshape(-1, 2)
        projected_masks = [
            (
                transform_mask(row.get("mask"), fit_to_current)
                if isinstance(row.get("mask"), dict)
                else None
            )
            for row in expected_rows
        ]
    except (TypeError, ValueError, cv2.error):
        return {
            "available": False,
            "reason": "local_landmark_projection_failed",
            "centers": [],
        }
    if not math.isfinite(threshold) or not np.all(np.isfinite(predicted)):
        return {
            "available": False,
            "reason": "local_landmark_projection_failed",
            "centers": [],
        }

    polygon_global = np.rint(
        np.asarray(points, dtype=np.float32)
    ).astype(np.int32)
    try:
        bx, by, bw, bh = cv2.boundingRect(
            polygon_global.reshape(-1, 1, 2)
        )
    except Exception:
        return {
            "available": False,
            "reason": "filter_crop_invalid",
            "centers": [],
        }

    frame_h, frame_w = frame.shape[:2]
    x1 = max(0, int(bx))
    y1 = max(0, int(by))
    x2 = min(int(frame_w), int(bx + bw))
    y2 = min(int(frame_h), int(by + bh))
    if x2 - x1 < 8 or y2 - y1 < 8:
        return {
            "available": False,
            "reason": "filter_crop_too_small",
            "centers": [],
        }

    crop = frame[y1:y2, x1:x2]
    if not _valid_frame(crop):
        return {
            "available": False,
            "reason": "filter_crop_invalid",
            "centers": [],
        }

    polygon = polygon_global.copy()
    polygon[:, 0] -= int(x1)
    polygon[:, 1] -= int(y1)
    filter_mask = np.zeros(crop.shape[:2], dtype=np.uint8)
    cv2.fillPoly(filter_mask, [polygon], 255, lineType=cv2.LINE_AA)

    try:
        value = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[:, :, 2]
    except Exception:
        return {
            "available": False,
            "reason": "hsv_prepare_failed",
            "centers": [],
        }

    hot_y, hot_x = np.nonzero(
        (value.astype(np.float32) >= threshold)
        & (filter_mask > 0)
    )
    if len(hot_x) < F3_TRACKING_LUMINOUS_LOCAL_MIN_HOT_PIXELS:
        return {
            "available": False,
            "reason": "local_hot_pixels_insufficient",
            "centers": [],
            "hot_pixel_count": int(len(hot_x)),
        }

    hot_points = np.column_stack(
        (
            hot_x.astype(np.float32) + float(x1),
            hot_y.astype(np.float32) + float(y1),
        )
    )
    distances = np.linalg.norm(
        hot_points[:, None, :] - predicted[None, :, :],
        axis=2,
    )
    nearest_expected = np.argmin(distances, axis=1)
    nearest_distance = np.min(distances, axis=1)

    filter_array = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    filter_diagonal = max(
        1.0,
        float(
            np.linalg.norm(
                np.max(filter_array, axis=0)
                - np.min(filter_array, axis=0)
            )
        ),
    )
    assignment_gate = max(
        10.0,
        filter_diagonal * F3_TRACKING_LUMINOUS_LOCAL_GATE_FRACTION,
    )

    centers: list[list[float]] = []
    details: list[dict] = []
    for expected_index, row in enumerate(expected_rows):
        selected = (
            (nearest_expected == int(expected_index))
            & (nearest_distance <= float(assignment_gate))
        )

        search_bbox = None
        projected_mask = (
            projected_masks[expected_index]
            if expected_index < len(projected_masks)
            else None
        )
        if isinstance(projected_mask, dict):
            try:
                mx1, my1, mx2, my2 = bbox_mascara_display(projected_mask)
                mask_w = max(1.0, float(mx2) - float(mx1))
                mask_h = max(1.0, float(my2) - float(my1))
                padding = max(
                    F3_TRACKING_LUMINOUS_LOCAL_MASK_PADDING_MIN_PX,
                    min(
                        24.0,
                        max(mask_w, mask_h)
                        * F3_TRACKING_LUMINOUS_LOCAL_MASK_PADDING_FRACTION,
                    ),
                )
                search_bbox = (
                    float(mx1) - padding,
                    float(my1) - padding,
                    float(mx2) + padding,
                    float(my2) + padding,
                )
                selected &= (
                    (hot_points[:, 0] >= search_bbox[0])
                    & (hot_points[:, 0] <= search_bbox[2])
                    & (hot_points[:, 1] >= search_bbox[1])
                    & (hot_points[:, 1] <= search_bbox[3])
                )
            except Exception:
                search_bbox = None

        selected_indices = np.flatnonzero(selected)
        if len(selected_indices) < F3_TRACKING_LUMINOUS_LOCAL_MIN_HOT_PIXELS:
            continue

        cluster = hot_points[selected_indices]
        center = _robust_luminous_cluster_center(cluster)
        if center is None:
            continue
        centers.append(center)
        details.append(
            {
                "mask_id": str(row.get("mask_id") or ""),
                "center": [
                    round(float(center[0]), 3),
                    round(float(center[1]), 3),
                ],
                "predicted_center": [
                    round(float(predicted[expected_index][0]), 3),
                    round(float(predicted[expected_index][1]), 3),
                ],
                "search_bbox": (
                    [round(float(value), 3) for value in search_bbox]
                    if search_bbox is not None
                    else None
                ),
                "hot_pixel_count": int(len(selected_indices)),
                "median_prediction_error_px": round(
                    float(np.median(nearest_distance[selected_indices])),
                    3,
                ),
                "center_correction_px": round(
                    float(
                        np.linalg.norm(
                            np.asarray(center, dtype=np.float32)
                            - predicted[expected_index]
                        )
                    ),
                    3,
                ),
            }
        )

    return {
        "available": len(centers) >= F3_TRACKING_LUMINOUS_MIN_COMPONENTS,
        "reason": (
            "expected_on_local_luminous_landmarks"
            if len(centers) >= F3_TRACKING_LUMINOUS_MIN_COMPONENTS
            else "expected_on_local_landmarks_insufficient"
        ),
        "centers": centers,
        "details": details,
        "threshold_v": round(float(threshold), 3),
        "assignment_gate_px": round(float(assignment_gate), 3),
        "hot_pixel_count": int(len(hot_x)),
    }


def _canonical_check_masks_for_luminous_tracking(
    runtime,
    project: dict,
    check: dict,
) -> list[dict]:
    """Retorna sempre a máscara canônica; o CHECK fornece somente ON/OFF esperado."""

    masks = getattr(runtime, "canonical_masks", None)
    if masks:
        return [
            converter_mascara_legada_para_editor(mask)
            for mask in masks
            if isinstance(mask, dict)
        ]
    return [
        converter_mascara_legada_para_editor(mask)
        for mask in (project.get("masks", []) or [])
        if isinstance(mask, dict)
    ]


def _luminous_fit_context(
    runtime,
    project: dict,
    check: dict,
) -> dict:
    """Usa pose local do CHECK para achar luz e volta ao modelo canônico."""
    canonical_board = (
        getattr(runtime, "canonical_board", None)
        or canonical_board_points(project, runtime.store)
    )
    canonical_masks = _canonical_check_masks_for_luminous_tracking(
        runtime,
        project,
        check,
    )
    fallback = {
        "space": "canonical",
        "board": deepcopy(canonical_board),
        "masks": deepcopy(canonical_masks),
        "fit_to_canonical": None,
        "canonical_to_fit": None,
    }

    check_id = str(check.get("id") or "")
    overrides = (
        check.get("mask_overrides_reference", {})
        if isinstance(check.get("mask_overrides_reference"), dict)
        else {}
    )
    explicit_board = _normalize_points(
        check.get("board_points_reference"),
        minimum=3,
    )
    if not check_id or not bool(explicit_board or overrides):
        return fallback

    reference = (
        runtime.references.get(f"check:{check_id}")
        if isinstance(getattr(runtime, "references", None), dict)
        else None
    )
    fit_to_canonical = (
        reference.get("reference_to_canonical")
        if isinstance(reference, dict)
        else None
    )
    if fit_to_canonical is None:
        return fallback

    try:
        fit_to_canonical = np.asarray(
            fit_to_canonical,
            dtype=np.float32,
        ).reshape(2, 3)
        canonical_to_fit = cv2.invertAffineTransform(fit_to_canonical)
    except Exception:
        return fallback

    board = (
        deepcopy(explicit_board)
        if explicit_board
        else transform_points(canonical_board, canonical_to_fit)
    )
    if len(board) < 3:
        return fallback

    local_masks = []
    for base in canonical_masks:
        if not isinstance(base, dict):
            continue
        mask_id = str(base.get("id") or "")
        override = overrides.get(mask_id)
        if isinstance(override, dict):
            local = sincronizar_formato_mascara_display(base, override)
        else:
            local = transform_mask(base, canonical_to_fit)
        if isinstance(local, dict):
            local["id"] = mask_id
            local_masks.append(local)

    if len(local_masks) < F3_TRACKING_LUMINOUS_STRUCTURAL_MIN_MATCHES:
        return fallback

    return {
        "space": f"check:{check_id}",
        "board": board,
        "masks": local_masks,
        "fit_to_canonical": fit_to_canonical,
        "canonical_to_fit": canonical_to_fit,
    }


def _expected_on_rows(masks, states) -> list[dict]:
    state_map = states if isinstance(states, dict) else {}
    rows: list[dict] = []
    for mask in masks or []:
        if not isinstance(mask, dict):
            continue
        mask_id = str(mask.get("id") or "")
        if state_map.get(mask_id) != DISPLAY_CHECK_STATE_ON:
            continue
        center = _mask_center(mask)
        if center is None:
            continue
        rows.append(
            {
                "mask_id": mask_id,
                "center": [float(center[0]), float(center[1])],
                "mask": deepcopy(mask),
            }
        )
    return rows


def _greedy_point_matches(
    expected_points,
    observed_points,
    gate_px: float,
) -> list[tuple[int, int, float]]:
    expected = np.asarray(expected_points, dtype=np.float32).reshape(-1, 2)
    observed = np.asarray(observed_points, dtype=np.float32).reshape(-1, 2)
    if not len(expected) or not len(observed):
        return []

    pairs: list[tuple[float, int, int]] = []
    for expected_index, expected_point in enumerate(expected):
        distances = np.linalg.norm(observed - expected_point, axis=1)
        for observed_index, distance in enumerate(distances):
            if float(distance) <= float(gate_px):
                pairs.append(
                    (float(distance), int(expected_index), int(observed_index))
                )
    pairs.sort(key=lambda item: item[0])

    used_expected: set[int] = set()
    used_observed: set[int] = set()
    matched: list[tuple[int, int, float]] = []
    for distance, expected_index, observed_index in pairs:
        if expected_index in used_expected or observed_index in used_observed:
            continue
        used_expected.add(expected_index)
        used_observed.add(observed_index)
        matched.append((expected_index, observed_index, distance))
    return matched


def _fit_direct_luminous_pose(
    canonical_board,
    expected_rows,
    local_landmarks: dict,
    coarse_matrix,
    diagnostics: dict | None = None,
) -> dict | None:
    """Refina a pose mantendo a identidade MASK_ID de cada emissão local."""
    diagnostic = diagnostics if isinstance(diagnostics, dict) else None
    details = [
        item for item in (local_landmarks.get("details") or [])
        if isinstance(item, dict)
    ]
    expected_by_id = {
        str(row.get("mask_id") or ""): row
        for row in expected_rows
        if isinstance(row, dict) and str(row.get("mask_id") or "")
    }

    source_points = []
    target_points = []
    matched_ids = []
    for item in details:
        mask_id = str(item.get("mask_id") or "")
        row = expected_by_id.get(mask_id)
        center = item.get("center")
        if (
            row is None
            or not isinstance(center, (list, tuple))
            or len(center) < 2
        ):
            continue
        try:
            source_points.append([float(center[0]), float(center[1])])
            target_points.append(
                [float(row["center"][0]), float(row["center"][1])]
            )
            matched_ids.append(mask_id)
        except (TypeError, ValueError, KeyError, IndexError):
            continue

    required = F3_TRACKING_LUMINOUS_STRUCTURAL_MIN_MATCHES
    if diagnostic is not None:
        diagnostic.clear()
        diagnostic.update(
            {
                "expected_on_count": int(len(expected_rows)),
                "observed_component_count": int(len(source_points)),
                "required_match_count": int(required),
                "hypothesis_count": 1,
                "best_coarse_match_count": int(len(source_points)),
                "best_final_match_count": 0,
                "failure_stage": "not_started",
                "fit_mode": "mask_id_local_landmarks",
            }
        )

    if len(source_points) < required:
        if diagnostic is not None:
            diagnostic["failure_stage"] = "local_landmarks_insufficient"
        return None

    board = np.asarray(
        _quad_from_points(canonical_board),
        dtype=np.float32,
    ).reshape(-1, 2)
    source_all = np.asarray(source_points, dtype=np.float32).reshape(-1, 2)
    target_all = np.asarray(target_points, dtype=np.float32).reshape(-1, 2)
    if len(board) != 4:
        if diagnostic is not None:
            diagnostic["failure_stage"] = "invalid_board_geometry"
        return None

    # Reflexo pode cair dentro da vizinhança de uma máscara que deveria estar ON
    # mas não acendeu. Como a identidade MASK_ID é conhecida, RANSAC aqui serve
    # apenas para eliminar essas correspondências luminosas falsas antes do fit.
    try:
        matrix, inlier_mask = cv2.estimateAffinePartial2D(
            source_all.reshape(-1, 1, 2),
            target_all.reshape(-1, 1, 2),
            method=cv2.RANSAC,
            ransacReprojThreshold=F3_TRACKING_LUMINOUS_LOCAL_RANSAC_PX,
            maxIters=2400,
            confidence=0.995,
            refineIters=20,
        )
    except Exception:
        matrix, inlier_mask = None, None
    if matrix is None:
        if diagnostic is not None:
            diagnostic["failure_stage"] = "refined_affine_rejected"
        return None

    if inlier_mask is None:
        inliers = np.ones(len(source_all), dtype=bool)
    else:
        inliers = np.asarray(inlier_mask).reshape(-1).astype(bool)
    inlier_count = int(np.count_nonzero(inliers))
    if inlier_count < required:
        if diagnostic is not None:
            diagnostic.update(
                {
                    "failure_stage": "local_landmark_inliers_insufficient",
                    "best_final_match_count": inlier_count,
                    "ransac_inlier_count": inlier_count,
                }
            )
        return None

    source = source_all[inliers]
    target = target_all[inliers]
    matched_ids = [
        mask_id
        for mask_id, is_inlier in zip(matched_ids, inliers.tolist())
        if bool(is_inlier)
    ]

    scale = affine_scale(matrix)
    if not (
        F3_TRACKING_REFERENCE_SCALE_MIN
        <= scale
        <= F3_TRACKING_REFERENCE_SCALE_MAX
    ):
        if diagnostic is not None:
            diagnostic["failure_stage"] = "refined_affine_rejected"
        return None

    board_diagonal = max(
        1.0,
        float(np.linalg.norm(np.max(board, axis=0) - np.min(board, axis=0))),
    )
    target_span = float(
        np.linalg.norm(np.max(target, axis=0) - np.min(target, axis=0))
    )
    minimum_span = max(
        8.0,
        board_diagonal * F3_TRACKING_LUMINOUS_LOCAL_MIN_SPAN_FRACTION,
    )
    if target_span < minimum_span:
        if diagnostic is not None:
            diagnostic.update(
                {
                    "failure_stage": "local_landmarks_spatial_span_insufficient",
                    "landmark_span_px": round(target_span, 3),
                    "minimum_landmark_span_px": round(minimum_span, 3),
                    "ransac_inlier_count": inlier_count,
                }
            )
        return None

    matrix = np.asarray(matrix, dtype=np.float32).reshape(2, 3)
    allowed, guard = _luminous_refinement_within_coarse_guard(
        matrix,
        coarse_matrix,
        canonical_board,
    )
    if not allowed:
        if diagnostic is not None:
            diagnostic.update(
                {
                    "failure_stage": "refined_pose_outside_filter_guard",
                    "refinement_guard": deepcopy(guard),
                }
            )
        return None

    projected = cv2.transform(
        source.reshape(-1, 1, 2),
        np.asarray(matrix, dtype=np.float32).reshape(2, 3),
    ).reshape(-1, 2)
    errors = np.linalg.norm(projected - target, axis=1)
    median_error = float(np.median(errors)) if len(errors) else float("inf")
    matched_set = set(matched_ids)
    missing_ids = [
        str(row.get("mask_id") or "")
        for row in expected_rows
        if str(row.get("mask_id") or "") not in matched_set
    ]
    match_ratio = len(matched_ids) / max(1, len(expected_rows))
    score = (
        float(len(matched_ids)) * 4.0
        + float(match_ratio) * 10.0
        - median_error / 4.0
    )

    if diagnostic is not None:
        diagnostic.update(
            {
                "failure_stage": "",
                "best_final_match_count": int(len(matched_ids)),
                "ransac_inlier_count": int(len(matched_ids)),
                "ransac_candidate_count": int(len(source_all)),
                "matched_mask_ids": list(matched_ids),
                "median_error_px": round(float(median_error), 3),
                "landmark_span_px": round(target_span, 3),
                "minimum_landmark_span_px": round(minimum_span, 3),
                "refinement_guard": deepcopy(guard),
            }
        )

    return {
        "matrix": np.asarray(matrix, dtype=np.float32).reshape(2, 3),
        "matched_mask_ids": list(matched_ids),
        "missing_expected_on_mask_ids": missing_ids,
        "matched_count": int(len(matched_ids)),
        "expected_on_count": int(len(expected_rows)),
        "match_ratio": float(match_ratio),
        "median_error_px": float(median_error),
        "coarse_gate_px": float(
            local_landmarks.get("assignment_gate_px", 0.0) or 0.0
        ),
        "final_gate_px": float(
            local_landmarks.get("assignment_gate_px", 0.0) or 0.0
        ),
        "score": float(score),
        "required_match_count": int(required),
    }


def _fit_luminous_pose(
    canonical_board,
    expected_rows,
    luminous_centers,
    coarse_matrices,
    diagnostics: dict | None = None,
    required_match_count: int | None = None,
) -> dict | None:
    expected_count = int(len(expected_rows))
    observed_count = int(len(luminous_centers))
    default_required = max(
        F3_TRACKING_LUMINOUS_MIN_COMPONENTS,
        int(math.ceil(
            expected_count * F3_TRACKING_LUMINOUS_MIN_MATCH_RATIO
        )),
    )
    if required_match_count is None:
        required = default_required
    else:
        required = min(
            expected_count,
            max(
                F3_TRACKING_LUMINOUS_MIN_COMPONENTS,
                int(required_match_count),
            ),
        )

    diagnostic = diagnostics if isinstance(diagnostics, dict) else None
    if diagnostic is not None:
        diagnostic.clear()
        diagnostic.update(
            {
                "expected_on_count": expected_count,
                "observed_component_count": observed_count,
                "required_match_count": int(required),
                "hypothesis_count": 0,
                "best_coarse_match_count": 0,
                "best_final_match_count": 0,
                "failure_stage": "not_started",
                "stage_counts": {
                    "coarse_projection_failed": 0,
                    "coarse_matches_insufficient": 0,
                    "refined_affine_rejected": 0,
                    "refined_pose_outside_filter_guard": 0,
                    "refined_projection_failed": 0,
                    "final_matches_insufficient": 0,
                    "success": 0,
                },
            }
        )

    if (
        expected_count < F3_TRACKING_LUMINOUS_MIN_COMPONENTS
        or observed_count < F3_TRACKING_LUMINOUS_MIN_COMPONENTS
    ):
        if diagnostic is not None:
            diagnostic["failure_stage"] = "insufficient_points"
        return None

    canonical_points = np.asarray(
        [row["center"] for row in expected_rows],
        dtype=np.float32,
    ).reshape(-1, 2)
    observed = np.asarray(luminous_centers, dtype=np.float32).reshape(-1, 2)
    board_quad = _quad_from_points(canonical_board)
    if len(board_quad) != 4:
        if diagnostic is not None:
            diagnostic["failure_stage"] = "invalid_board_geometry"
        return None
    canonical_board_array = np.asarray(
        board_quad,
        dtype=np.float32,
    ).reshape(-1, 1, 2)

    if diagnostic is not None:
        diagnostic["expected_centers"] = [
            {
                "mask_id": str(row.get("mask_id") or ""),
                "center": [
                    round(float(point[0]), 3),
                    round(float(point[1]), 3),
                ],
            }
            for row, point in zip(expected_rows, canonical_points)
        ]
        diagnostic["observed_centers"] = [
            [round(float(point[0]), 3), round(float(point[1]), 3)]
            for point in observed
        ]

    matrices = list(coarse_matrices) if coarse_matrices is not None else []
    stage_counts = (
        diagnostic["stage_counts"]
        if diagnostic is not None
        else {
            "coarse_projection_failed": 0,
            "coarse_matches_insufficient": 0,
            "refined_affine_rejected": 0,
            "refined_pose_outside_filter_guard": 0,
            "refined_projection_failed": 0,
            "final_matches_insufficient": 0,
            "success": 0,
        }
    )
    best_summary = None
    best_summary_rank = (-1, -1, float("-inf"))
    best_coarse_match_count = 0
    best_final_match_count = 0

    best = None
    for hypothesis_index, coarse in enumerate(matrices):
        try:
            matrix = np.asarray(coarse, dtype=np.float32).reshape(2, 3)
            canonical_to_current = cv2.invertAffineTransform(matrix)
            predicted = cv2.transform(
                canonical_points.reshape(-1, 1, 2),
                canonical_to_current,
            ).reshape(-1, 2)
            current_board = cv2.transform(
                canonical_board_array,
                canonical_to_current,
            ).reshape(-1, 2)
        except Exception:
            stage_counts["coarse_projection_failed"] += 1
            continue

        board_diagonal = max(
            1.0,
            float(
                np.linalg.norm(
                    np.max(current_board, axis=0)
                    - np.min(current_board, axis=0)
                )
            ),
        )
        coarse_gate = max(
            10.0,
            board_diagonal * F3_TRACKING_LUMINOUS_COARSE_GATE_FRACTION,
        )
        coarse_matches = _greedy_point_matches(
            predicted,
            observed,
            coarse_gate,
        )
        best_coarse_match_count = max(
            best_coarse_match_count,
            int(len(coarse_matches)),
        )

        nearest_distances = [
            float(np.min(np.linalg.norm(observed - point, axis=1)))
            for point in predicted
        ]
        median_nearest = (
            float(np.median(np.asarray(nearest_distances, dtype=np.float32)))
            if nearest_distances
            else float("inf")
        )
        summary = {
            "hypothesis_index": int(hypothesis_index),
            "coarse_gate_px": round(float(coarse_gate), 3),
            "coarse_match_count": int(len(coarse_matches)),
            "median_nearest_distance_px": (
                round(median_nearest, 3)
                if math.isfinite(median_nearest)
                else None
            ),
            "nearest_distance_by_mask": [
                {
                    "mask_id": str(expected_rows[index].get("mask_id") or ""),
                    "distance_px": round(float(distance), 3),
                }
                for index, distance in enumerate(nearest_distances)
            ],
        }
        summary_rank = (
            0,
            int(len(coarse_matches)),
            -median_nearest if math.isfinite(median_nearest) else float("-inf"),
        )
        if summary_rank > best_summary_rank:
            best_summary = deepcopy(summary)
            best_summary_rank = summary_rank

        if len(coarse_matches) < F3_TRACKING_LUMINOUS_MIN_COMPONENTS:
            stage_counts["coarse_matches_insufficient"] += 1
            continue

        source_points = [
            observed[observed_index].tolist()
            for _expected_index, observed_index, _distance in coarse_matches
        ]
        target_points = [
            canonical_points[expected_index].tolist()
            for expected_index, _observed_index, _distance in coarse_matches
        ]
        refined = _estimate_affine_partial(source_points, target_points)
        if refined is None:
            stage_counts["refined_affine_rejected"] += 1
            summary["failure_stage"] = "refined_affine_rejected"
            if summary_rank >= best_summary_rank:
                best_summary = deepcopy(summary)
                best_summary_rank = summary_rank
            continue

        refinement_allowed, refinement_guard = (
            _luminous_refinement_within_coarse_guard(
                refined,
                matrix,
                canonical_board,
            )
        )
        summary["refinement_guard"] = deepcopy(refinement_guard)
        if not refinement_allowed:
            stage_counts["refined_pose_outside_filter_guard"] += 1
            summary["failure_stage"] = "refined_pose_outside_filter_guard"
            if summary_rank >= best_summary_rank:
                best_summary = deepcopy(summary)
                best_summary_rank = summary_rank
            continue

        try:
            refined_inverse = cv2.invertAffineTransform(refined)
            predicted_refined = cv2.transform(
                canonical_points.reshape(-1, 1, 2),
                refined_inverse,
            ).reshape(-1, 2)
            refined_board = cv2.transform(
                canonical_board_array,
                refined_inverse,
            ).reshape(-1, 2)
        except Exception:
            stage_counts["refined_projection_failed"] += 1
            summary["failure_stage"] = "refined_projection_failed"
            if summary_rank >= best_summary_rank:
                best_summary = deepcopy(summary)
            continue

        refined_diagonal = max(
            1.0,
            float(
                np.linalg.norm(
                    np.max(refined_board, axis=0)
                    - np.min(refined_board, axis=0)
                )
            ),
        )
        final_gate = max(
            6.0,
            refined_diagonal * F3_TRACKING_LUMINOUS_FINAL_GATE_FRACTION,
        )
        final_matches = _greedy_point_matches(
            predicted_refined,
            observed,
            final_gate,
        )
        best_final_match_count = max(
            best_final_match_count,
            int(len(final_matches)),
        )
        summary.update(
            {
                "final_gate_px": round(float(final_gate), 3),
                "final_match_count": int(len(final_matches)),
                "required_match_count": int(required),
            }
        )
        summary_rank = (
            int(len(final_matches)),
            int(len(coarse_matches)),
            -median_nearest if math.isfinite(median_nearest) else float("-inf"),
        )
        if summary_rank > best_summary_rank:
            best_summary = deepcopy(summary)
            best_summary_rank = summary_rank

        if len(final_matches) < required:
            stage_counts["final_matches_insufficient"] += 1
            summary["failure_stage"] = "final_matches_insufficient"
            if summary_rank >= best_summary_rank:
                best_summary = deepcopy(summary)
                best_summary_rank = summary_rank
            continue

        final_source = [
            observed[observed_index].tolist()
            for _expected_index, observed_index, _distance in final_matches
        ]
        final_target = [
            canonical_points[expected_index].tolist()
            for expected_index, _observed_index, _distance in final_matches
        ]
        final_matrix = _estimate_affine_partial(
            final_source,
            final_target,
        )
        if final_matrix is None:
            final_matrix = refined

        final_allowed, final_guard = _luminous_refinement_within_coarse_guard(
            final_matrix,
            matrix,
            canonical_board,
        )
        summary["final_refinement_guard"] = deepcopy(final_guard)
        if not final_allowed:
            stage_counts["refined_pose_outside_filter_guard"] += 1
            summary["failure_stage"] = "refined_pose_outside_filter_guard"
            if summary_rank >= best_summary_rank:
                best_summary = deepcopy(summary)
                best_summary_rank = summary_rank
            continue

        final_errors = [float(item[2]) for item in final_matches]
        median_error = (
            float(np.median(np.asarray(final_errors, dtype=np.float32)))
            if final_errors
            else final_gate
        )
        match_ratio = len(final_matches) / max(1, expected_count)
        matched_indices = {
            expected_index
            for expected_index, _observed_index, _distance in final_matches
        }
        matched_ids = [
            str(expected_rows[index]["mask_id"])
            for index in sorted(matched_indices)
        ]
        missing_ids = [
            str(row["mask_id"])
            for index, row in enumerate(expected_rows)
            if index not in matched_indices
        ]
        score = (
            float(len(final_matches)) * 3.0
            + float(match_ratio) * 12.0
            - median_error / max(1.0, final_gate)
        )

        stage_counts["success"] += 1
        summary.update(
            {
                "failure_stage": "",
                "match_ratio": round(float(match_ratio), 4),
                "median_error_px": round(float(median_error), 3),
            }
        )
        if summary_rank >= best_summary_rank:
            best_summary = deepcopy(summary)
            best_summary_rank = summary_rank

        candidate = {
            "matrix": np.asarray(final_matrix, dtype=np.float32).reshape(2, 3),
            "matched_mask_ids": matched_ids,
            "missing_expected_on_mask_ids": missing_ids,
            "matched_count": int(len(final_matches)),
            "expected_on_count": expected_count,
            "match_ratio": float(match_ratio),
            "median_error_px": float(median_error),
            "coarse_gate_px": float(coarse_gate),
            "final_gate_px": float(final_gate),
            "score": float(score),
        }
        if best is None or float(candidate["score"]) > float(best["score"]):
            best = candidate

    if diagnostic is not None:
        diagnostic["hypothesis_count"] = int(len(matrices))
        diagnostic["best_coarse_match_count"] = int(best_coarse_match_count)
        diagnostic["best_final_match_count"] = int(best_final_match_count)
        diagnostic["best_hypothesis"] = deepcopy(best_summary)
        if best is not None:
            diagnostic["failure_stage"] = ""
        elif stage_counts["final_matches_insufficient"]:
            diagnostic["failure_stage"] = "final_matches_insufficient"
        elif stage_counts["refined_projection_failed"]:
            diagnostic["failure_stage"] = "refined_projection_failed"
        elif stage_counts["refined_pose_outside_filter_guard"]:
            diagnostic["failure_stage"] = "refined_pose_outside_filter_guard"
        elif stage_counts["refined_affine_rejected"]:
            diagnostic["failure_stage"] = "refined_affine_rejected"
        elif stage_counts["coarse_matches_insufficient"]:
            diagnostic["failure_stage"] = "coarse_matches_insufficient"
        elif stage_counts["coarse_projection_failed"]:
            diagnostic["failure_stage"] = "coarse_projection_failed"
        else:
            diagnostic["failure_stage"] = "no_valid_hypothesis"

    return best


def _find_luminous_segment_pose(
    frame,
    canonical_board,
    expected_rows,
    canonical_resolution,
    *,
    base_matrix=None,
) -> dict:
    """Filtro preto -> emissão -> encaixe dos ON esperados -> pose dinâmica."""
    if not _valid_frame(frame):
        return {
            "available": False,
            "reason": "invalid_frame",
        }
    resolution = normalizar_resolucao_display(canonical_resolution)
    if resolution is None:
        return {
            "available": False,
            "reason": "master_resolution_missing",
        }
    if len(expected_rows) < F3_TRACKING_LUMINOUS_MIN_COMPONENTS:
        return {
            "available": False,
            "reason": "expected_on_segments_insufficient",
            "expected_on_count": int(len(expected_rows)),
        }

    filter_candidates: list[dict] = []
    if base_matrix is not None:
        try:
            inverse = cv2.invertAffineTransform(
                np.asarray(base_matrix, dtype=np.float32).reshape(2, 3)
            )
            projected = transform_points(canonical_board, inverse)
        except Exception:
            projected = []
        if len(projected) >= 3:
            filter_candidates.append(
                {
                    "points": projected,
                    "score": 100.0,
                    "source": "tracked_filter",
                }
            )
    else:
        filter_candidates.extend(
            _detect_dark_filter_candidates(
                frame,
                canonical_board,
                resolution,
            )
        )

    if not filter_candidates:
        return {
            "available": False,
            "reason": "filter_not_found",
            "filter_candidate_count": 0,
        }

    best = None
    attempts = []
    for filter_candidate in filter_candidates:
        filter_points = filter_candidate.get("points") or []
        luminous = _detect_luminous_segment_centers(
            frame,
            filter_points,
        )
        attempt = {
            "filter_source": str(
                filter_candidate.get("source") or "unknown"
            ),
            "filter_score": round(
                float(filter_candidate.get("score", 0.0) or 0.0),
                4,
            ),
            "luminous_reason": str(luminous.get("reason") or ""),
            "luminous_component_count": int(
                len(luminous.get("centers") or [])
            ),
            "threshold_v": luminous.get("threshold_v"),
            "dynamic_range": luminous.get("dynamic_range"),
        }
        coarse_matrices = []
        normalized_base_matrix = None
        if base_matrix is not None:
            try:
                normalized_base_matrix = np.asarray(
                    base_matrix,
                    dtype=np.float32,
                ).reshape(2, 3)
                coarse_matrices.append(normalized_base_matrix)
            except Exception:
                normalized_base_matrix = None
        coarse_matrices.extend(
            _filter_board_matrix_candidates(
                filter_points,
                canonical_board,
            )
        )

        fit = None
        fit_diagnostics: dict = {}
        fit_landmark_source = "global_connected_components"
        local_landmarks = {
            "available": False,
            "reason": "structural_base_matrix_missing",
            "centers": [],
        }
        local_fit_diagnostics: dict = {}

        if (
            normalized_base_matrix is not None
            and luminous.get("threshold_v") is not None
        ):
            local_landmarks = _detect_expected_on_luminous_landmarks(
                frame,
                filter_points,
                expected_rows,
                normalized_base_matrix,
                luminous.get("threshold_v"),
            )
            if bool(local_landmarks.get("available")):
                fit = _fit_direct_luminous_pose(
                    canonical_board,
                    expected_rows,
                    local_landmarks,
                    normalized_base_matrix,
                    diagnostics=local_fit_diagnostics,
                )
                if fit is not None:
                    fit_diagnostics = local_fit_diagnostics
                    fit_landmark_source = "expected_on_local_emission"

        global_fit_diagnostics: dict = {}
        if fit is None and bool(luminous.get("available")):
            fit = _fit_luminous_pose(
                canonical_board,
                expected_rows,
                luminous.get("centers") or [],
                coarse_matrices,
                diagnostics=global_fit_diagnostics,
            )
            if fit is not None:
                fit_diagnostics = global_fit_diagnostics
                fit_landmark_source = "global_connected_components"
            elif not fit_diagnostics:
                fit_diagnostics = global_fit_diagnostics
        elif fit is None and normalized_base_matrix is None:
            attempt["fit_diagnostics"] = {}
            attempt["fit"] = False
            attempts.append(attempt)
            continue

        attempt["global_fit_diagnostics"] = deepcopy(
            global_fit_diagnostics
        )
        attempt["local_fit_diagnostics"] = deepcopy(
            local_fit_diagnostics
        )

        attempt["fit_landmark_source"] = fit_landmark_source
        attempt["local_luminous_landmark_count"] = int(
            len(local_landmarks.get("centers") or [])
        )
        attempt["local_luminous_reason"] = str(
            local_landmarks.get("reason") or ""
        )
        attempt["local_luminous_details"] = deepcopy(
            local_landmarks.get("details") or []
        )
        attempt["fit_diagnostics"] = deepcopy(fit_diagnostics)
        attempt["coarse_matched_count"] = int(
            fit_diagnostics.get("best_coarse_match_count", 0) or 0
        )
        attempt["matched_count"] = int(
            fit_diagnostics.get("best_final_match_count", 0) or 0
        )
        attempt["required_match_count"] = int(
            fit_diagnostics.get("required_match_count", 0) or 0
        )
        attempt["fit_failure_stage"] = str(
            fit_diagnostics.get("failure_stage") or ""
        )
        if fit is None:
            attempt["fit"] = False
            attempts.append(attempt)
            continue

        attempt.update(
            {
                "fit": True,
                "matched_count": int(fit.get("matched_count", 0) or 0),
                "expected_on_count": int(
                    fit.get("expected_on_count", 0) or 0
                ),
                "match_ratio": round(
                    float(fit.get("match_ratio", 0.0) or 0.0),
                    4,
                ),
                "median_error_px": round(
                    float(fit.get("median_error_px", 0.0) or 0.0),
                    3,
                ),
                "required_match_count": int(
                    fit_diagnostics.get("required_match_count", 0) or 0
                ),
                "fit_failure_stage": "",
            }
        )
        attempts.append(attempt)
        candidate = {
            **fit,
            "filter_points": deepcopy(filter_points),
            "filter_source": str(
                filter_candidate.get("source") or "unknown"
            ),
            "filter_score": float(
                filter_candidate.get("score", 0.0) or 0.0
            ),
            "luminous_component_count": int(
                len(luminous.get("centers") or [])
            ),
            "local_luminous_landmark_count": int(
                len(local_landmarks.get("centers") or [])
            ),
            "fit_landmark_source": fit_landmark_source,
            "threshold_v": luminous.get("threshold_v"),
            "dynamic_range": luminous.get("dynamic_range"),
            "fit_diagnostics": deepcopy(fit_diagnostics),
        }
        if best is None or float(candidate["score"]) > float(best["score"]):
            best = candidate

    if best is None:
        reasons = [
            str(item.get("luminous_reason") or "")
            for item in attempts
        ]
        no_emission = bool(
            reasons
            and all(
                reason in {
                    "no_luminous_emission",
                    "luminous_components_insufficient",
                }
                for reason in reasons
            )
        )
        best_failed = max(
            attempts,
            key=lambda item: (
                int(item.get("matched_count", 0) or 0),
                int(item.get("coarse_matched_count", 0) or 0),
                int(item.get("luminous_component_count", 0) or 0),
            ),
            default={},
        )
        return {
            "available": False,
            "reason": (
                "filter_found_without_luminous_segments"
                if no_emission
                else "luminous_grid_not_fitted"
            ),
            "filter_candidate_count": int(len(filter_candidates)),
            "attempts": attempts,
            "expected_on_count": int(len(expected_rows)),
            "luminous_component_count": max(
                (
                    int(item.get("luminous_component_count", 0) or 0)
                    for item in attempts
                ),
                default=0,
            ),
            "local_luminous_landmark_count": max(
                (
                    int(item.get("local_luminous_landmark_count", 0) or 0)
                    for item in attempts
                ),
                default=0,
            ),
            "fit_landmark_source": str(
                best_failed.get("fit_landmark_source") or ""
            ),
            "coarse_matched_count": int(
                best_failed.get("coarse_matched_count", 0) or 0
            ),
            "matched_count": int(
                best_failed.get("matched_count", 0) or 0
            ),
            "required_match_count": int(
                best_failed.get("required_match_count", 0) or 0
            ),
            "fit_failure_stage": str(
                best_failed.get("fit_failure_stage") or ""
            ),
            "fit_diagnostics": deepcopy(
                best_failed.get("fit_diagnostics") or {}
            ),
        }

    result = dict(best)
    result.update(
        {
            "available": True,
            "reason": "luminous_segment_grid_fitted",
            "filter_candidate_count": int(len(filter_candidates)),
            "attempts": attempts,
        }
    )
    return result


def _rescue_luminous_segment_tracking_lock(
    app,
    frame,
    runtime,
    base_result: "F3TrackingResult | None" = None,
    *,
    frame_token=None,
):
    """Refina/reconstrói a pose usando somente segmentos ACESOS do CHECK atual.

    O encaixe luminoso prefere o espaço da própria foto de referência do CHECK.
    Isso impede que um lock estrutural obtido por AUX/USB/BOARD_OFF transfira
    pequenos erros de pose para as máscaras do H1.

    O detector nunca procura segmentos apagados. Se um ON esperado estiver
    ausente, os landmarks restantes ainda podem sustentar a geometria; o
    analyzer produtivo decide depois se a ausência é NG.
    """
    if runtime is None or not _valid_frame(frame):
        return None

    repository = getattr(app, "display_project_repository", None)
    if repository is None:
        return None
    project_name = repository.obter_projeto_ativo()
    project = repository.carregar_projeto(project_name)
    current = _current_check(app)
    if not isinstance(project, dict) or not isinstance(current, dict):
        return None

    check_id = str(current.get("id") or "")
    try:
        check = repository.carregar_check(project_name, check_id)
    except Exception:
        check = current
    if not isinstance(check, dict):
        check = current

    fit_context = _luminous_fit_context(
        runtime,
        project,
        check,
    )
    fit_board = fit_context.get("board") or []
    fit_masks = fit_context.get("masks") or []
    fit_space = str(fit_context.get("space") or "canonical")
    fit_to_canonical = fit_context.get("fit_to_canonical")
    canonical_to_fit = fit_context.get("canonical_to_fit")

    expected_rows = _expected_on_rows(
        fit_masks,
        check.get("mask_states", {}),
    )

    base_matrix_canonical = None
    if (
        base_result is not None
        and bool(getattr(base_result, "locked", False))
        and getattr(base_result, "current_to_canonical", None) is not None
    ):
        try:
            base_matrix_canonical = np.asarray(
                base_result.current_to_canonical,
                dtype=np.float32,
            ).reshape(2, 3)
        except Exception:
            base_matrix_canonical = None

    base_matrix = base_matrix_canonical
    if (
        base_matrix_canonical is not None
        and canonical_to_fit is not None
    ):
        base_matrix = compose_affine(
            canonical_to_fit,
            base_matrix_canonical,
        )

    pose = _find_luminous_segment_pose(
        frame,
        fit_board,
        expected_rows,
        (int(runtime.width), int(runtime.height)),
        base_matrix=base_matrix,
    )
    attempts = [
        item for item in (pose.get("attempts") or ())
        if isinstance(item, dict)
    ]
    luminous_emission_detected = bool(
        pose.get("available")
        or any(
            (
                str(item.get("luminous_reason") or "")
                == "luminous_segments_detected"
                and int(item.get("luminous_component_count", 0) or 0)
                >= F3_TRACKING_LUMINOUS_MIN_COMPONENTS
            )
            or int(item.get("local_luminous_landmark_count", 0) or 0)
            >= F3_TRACKING_LUMINOUS_STRUCTURAL_MIN_MATCHES
            for item in attempts
        )
    )
    alignment_required = bool(
        len(expected_rows) >= F3_TRACKING_LUMINOUS_MIN_COMPONENTS
    )
    alignment_ready = bool(
        pose.get("available") and pose.get("matrix") is not None
    )
    luminous_component_count = int(
        pose.get("luminous_component_count", 0)
        or max(
            (
                int(item.get("luminous_component_count", 0) or 0)
                for item in attempts
            ),
            default=0,
        )
    )
    matched_count = int(
        pose.get("matched_count", 0)
        or max(
            (
                int(item.get("matched_count", 0) or 0)
                for item in attempts
            ),
            default=0,
        )
    )
    coarse_matched_count = int(
        pose.get("coarse_matched_count", 0)
        or max(
            (
                int(item.get("coarse_matched_count", 0) or 0)
                for item in attempts
            ),
            default=0,
        )
    )

    telemetry = {
        key: (
            value.tolist()
            if isinstance(value, np.ndarray)
            else deepcopy(value)
        )
        for key, value in pose.items()
        if key != "matrix"
    }
    telemetry.update(
        {
            "source": "f3_luminous_segment_tracking",
            "project_name": str(project_name or ""),
            "check_id": check_id,
            "check_name": str(check.get("name") or check_id),
            "frame_id": (
                int(frame_token[1])
                if isinstance(frame_token, tuple)
                and len(frame_token) >= 2
                and frame_token[0] == "camera"
                else getattr(app, "camera_ultimo_frame_id", None)
            ),
            "frame_token": deepcopy(frame_token),
            "base_locked": bool(
                base_result is not None
                and getattr(base_result, "locked", False)
            ),
            "fit_space": fit_space,
            "fit_composed_to_canonical": bool(
                fit_to_canonical is not None
            ),
            "fine_tracking_mode": (
                "plate_contour_plus_luminous_segments"
                if base_matrix is not None
                else "luminous_reacquisition"
            ),
            "structural_luminous_min_matches": int(
                F3_TRACKING_LUMINOUS_STRUCTURAL_MIN_MATCHES
            ),
            "expected_on_count": int(len(expected_rows)),
            "luminous_component_count": luminous_component_count,
            "local_luminous_landmark_count": int(
                pose.get("local_luminous_landmark_count", 0) or 0
            ),
            "fit_landmark_source": str(
                pose.get("fit_landmark_source") or ""
            ),
            "coarse_matched_count": coarse_matched_count,
            "matched_count": matched_count,
            "required_match_count": int(
                pose.get("required_match_count", 0) or 0
            ),
            "fit_failure_stage": str(
                pose.get("fit_failure_stage") or ""
            ),
            "minimum_luminous_components": int(
                F3_TRACKING_LUMINOUS_MIN_COMPONENTS
            ),
            "luminous_emission_detected": luminous_emission_detected,
            "alignment_required": alignment_required,
            "alignment_ready": alignment_ready,
            "uses_only_luminous_segments": True,
            "searches_off_segments": False,
        }
    )
    app._display_f3_luminous_tracking_debug = telemetry

    if not alignment_ready:
        return None

    try:
        fit_matrix = np.asarray(
            pose.get("matrix"), dtype=np.float32
        ).reshape(2, 3)
    except Exception:
        return None
    if not np.all(np.isfinite(fit_matrix)):
        return None

    matrix = np.asarray(fit_matrix, dtype=np.float32).reshape(2, 3)
    if fit_to_canonical is not None:
        composed = compose_affine(
            fit_to_canonical,
            matrix,
        )
        if composed is None:
            return None
        matrix = np.asarray(composed, dtype=np.float32).reshape(2, 3)
    if not np.all(np.isfinite(matrix)):
        return None

    rotation_allowed, rotation_delta = _runtime_rotation_anchor_compatible(
        runtime,
        matrix,
    )
    if not rotation_allowed:
        rejection = {
            "source": "luminous_rescue",
            "reference": f"luminous:{check_id}",
            "rotation_deg": round(
                float(affine_rotation_deg(matrix)),
                3,
            ),
            "rotation_delta_deg": round(float(rotation_delta), 3),
            "reason": "abrupt_rotation_jump_rejected",
        }
        history = getattr(
            runtime,
            "_last_rotation_jump_rejections",
            None,
        )
        if not isinstance(history, list):
            history = []
        history.append(rejection)
        runtime._last_rotation_jump_rejections = history[-12:]
        telemetry.update(
            {
                "available": False,
                "alignment_ready": False,
                "reason": "luminous_pose_rotation_jump_rejected",
                "rotation_jump_delta_deg": round(
                    float(rotation_delta),
                    3,
                ),
            }
        )
        app._display_f3_luminous_tracking_debug = telemetry
        return None

    scale = affine_scale(matrix)
    if not (F3_TRACKING_MIN_SCALE <= scale <= F3_TRACKING_MAX_SCALE):
        return None
    if abs(float(matrix[0, 2])) > runtime.width * F3_TRACKING_MAX_TRANSLATION_FRACTION:
        return None
    if abs(float(matrix[1, 2])) > runtime.height * F3_TRACKING_MAX_TRANSLATION_FRACTION:
        return None

    try:
        aligned = cv2.warpAffine(
            frame,
            matrix,
            (int(runtime.width), int(runtime.height)),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT101,
        )
    except Exception:
        return None

    now = time.monotonic()
    gray = runtime._gray(frame)
    result_reference = f"luminous:{check_id}"
    runtime.last_matrix = matrix.copy()
    runtime.last_verified_rotation_deg = float(
        affine_rotation_deg(matrix)
    )
    runtime._last_reference = result_reference
    runtime.last_compute_s = now
    runtime.last_frame_id = (
        int(frame_token[1])
        if isinstance(frame_token, tuple)
        and len(frame_token) >= 2
        and frame_token[0] == "camera"
        else getattr(app, "camera_ultimo_frame_id", None)
    )
    runtime.last_gray = gray.copy() if isinstance(gray, np.ndarray) else None
    runtime.last_verified_s = now
    runtime.consecutive_misses = 0
    runtime.ready = True
    runtime.reason = "ready"

    reason = (
        "locked_luminous_segments_refined"
        if base_matrix is not None
        else "locked_luminous_segments_reacquired"
    )
    result = F3TrackingResult(
        True,
        aligned,
        reference=result_reference,
        matches=int(pose.get("matched_count", 0) or 0),
        inliers=int(pose.get("matched_count", 0) or 0),
        inlier_ratio=float(pose.get("match_ratio", 0.0) or 0.0),
        rotation_deg=float(affine_rotation_deg(matrix)),
        scale=float(scale),
        reason=reason,
        current_to_canonical=matrix.copy(),
        source_type="luminous_segment_grid",
        evidence_current=True,
    )
    runtime.last_result = result
    return result


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
    evidence_current: bool = False


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
        self.canonical_board: list[list[float]] = []
        self.canonical_masks: list[dict] = []
        self.last_gray = None
        self.last_verified_s = 0.0
        self.last_verified_rotation_deg: float | None = None
        self._last_rotation_jump_rejections: list[dict] = []
        self.consecutive_misses = 0

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
            masks_ref = _reference_masks_from_metadata(
                project,
                board_off,
            )
            pose_masks = _reference_masks_from_metadata(
                project,
                board_off,
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

    def _signature(self, project: dict, board) -> tuple:
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
        return (
            str(project.get("name") or ""),
            repr(project.get("master_resolution")),
            repr(board),
            repr(project.get("masks", [])),
            reference_files,
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

        akaze_descriptors = None
        akaze_canonical_points = np.empty((0, 2), dtype=np.float32)
        try:
            akaze = cv2.AKAZE_create(
                threshold=F3_TRACKING_AKAZE_THRESHOLD,
                nOctaves=4,
                nOctaveLayers=4,
            )
            akaze_keypoints, akaze_detected = akaze.detectAndCompute(
                gray,
                tracking_mask,
            )
        except Exception:
            akaze_keypoints, akaze_detected = [], None
        if (
            akaze_detected is not None
            and len(akaze_keypoints) >= F3_TRACKING_AKAZE_MIN_MATCHES
        ):
            points = np.asarray(
                [kp.pt for kp in akaze_keypoints],
                dtype=np.float32,
            ).reshape(-1, 1, 2)
            try:
                akaze_canonical_points = cv2.transform(
                    points,
                    reference_to_canonical,
                ).reshape(-1, 2)
                akaze_descriptors = akaze_detected
            except Exception:
                akaze_descriptors = None
                akaze_canonical_points = np.empty((0, 2), dtype=np.float32)

        template_edges = None
        template_origin = None
        template_support_mask = None
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
                support = (
                    tracking_mask[iy1:iy2, ix1:ix2]
                    if isinstance(tracking_mask, np.ndarray)
                    and tracking_mask.shape == gray.shape
                    else None
                )
                support_ok = bool(
                    isinstance(support, np.ndarray)
                    and support.shape == crop.shape
                    and int(cv2.countNonZero(support)) >= 200
                )
                structural_crop = (
                    cv2.bitwise_and(crop, crop, mask=support)
                    if support_ok
                    else crop
                )
                if (
                    structural_crop.size
                    and float(np.std(structural_crop)) >= 8.0
                ):
                    template_edges = structural_crop.copy()
                    template_origin = (float(ix1), float(iy1))
                    template_support_mask = (
                        support.copy() if support_ok else None
                    )

        # Uma referência pode ser útil mesmo com pouco ORB. O fallback por
        # template de bordas resolve translação quando câmera/suporte são fixos,
        # exatamente o cenário produtivo do F3.
        if (
            descriptors is None
            and akaze_descriptors is None
            and template_edges is None
        ):
            return

        refs[key] = {
            "descriptors": descriptors,
            "canonical_points": canonical_points,
            "akaze_descriptors": akaze_descriptors,
            "akaze_canonical_points": akaze_canonical_points,
            "angle_deg": float(angle),
            "source_type": str(source_type or "reference"),
            "reference_to_canonical": reference_to_canonical,
            "template_edges": template_edges,
            "template_origin": template_origin,
            "template_support_mask": template_support_mask,
        }

    def _template_candidate(
        self,
        current_edges,
        key: str,
        min_score: float | None = None,
    ):
        ref = self.references.get(key, {})
        template = ref.get("template_edges")
        origin = ref.get("template_origin")
        support = ref.get("template_support_mask")
        if (
            current_edges is None
            or template is None
            or origin is None
            or template.shape[0] > current_edges.shape[0]
            or template.shape[1] > current_edges.shape[1]
        ):
            return None
        masked = bool(
            isinstance(support, np.ndarray)
            and support.shape == template.shape
            and int(cv2.countNonZero(support)) >= 200
        )
        try:
            if masked:
                response = cv2.matchTemplate(
                    current_edges,
                    template,
                    cv2.TM_CCORR_NORMED,
                    mask=support,
                )
                response = np.nan_to_num(
                    response,
                    nan=-1.0,
                    posinf=-1.0,
                    neginf=-1.0,
                )
            else:
                response = cv2.matchTemplate(
                    current_edges,
                    template,
                    cv2.TM_CCOEFF_NORMED,
                )
            _min_value, max_value, _min_loc, max_loc = cv2.minMaxLoc(response)
        except Exception:
            return None
        score = float(max_value)
        threshold = (
            F3_TRACKING_TEMPLATE_MIN_SCORE
            if min_score is None
            else max(0.0, min(1.0, float(min_score)))
        )
        if score < threshold:
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
            "template_masked_for_segments": masked,
            "template_threshold": float(threshold),
        }

    def _adaptive_template_candidate(
        self,
        current_edges,
        key: str,
        min_score: float | None = None,
    ):
        """Reacquire estrutural tolerante a escala/rotação.

        O template continua excluindo as ROIs dos segmentos. Cada variante
        representa apenas a estrutura da placa; a transformação encontrada é
        convertida de CURRENT -> REFERÊNCIA -> CANÔNICO.
        """
        ref = self.references.get(str(key or ""), {})
        template = ref.get("template_edges")
        origin = ref.get("template_origin")
        support = ref.get("template_support_mask")
        if current_edges is None or template is None or origin is None:
            return None

        threshold = (
            F3_TRACKING_TEMPLATE_MIN_SCORE
            if min_score is None
            else max(0.0, min(1.0, float(min_score)))
        )
        masked_base = bool(
            isinstance(support, np.ndarray)
            and support.shape == template.shape
            and int(cv2.countNonZero(support)) >= 200
        )
        best = None
        h0, w0 = template.shape[:2]

        for requested_scale in F3_TRACKING_ADAPTIVE_TEMPLATE_SCALES:
            sw = max(
                F3_TRACKING_TEMPLATE_MIN_SIZE,
                int(round(w0 * float(requested_scale))),
            )
            sh = max(
                F3_TRACKING_TEMPLATE_MIN_SIZE,
                int(round(h0 * float(requested_scale))),
            )
            if sw >= current_edges.shape[1] or sh >= current_edges.shape[0]:
                continue
            sx = float(sw) / max(1.0, float(w0))
            sy = float(sh) / max(1.0, float(h0))
            scaled = cv2.resize(
                template,
                (sw, sh),
                interpolation=cv2.INTER_NEAREST,
            )
            scaled_support = (
                cv2.resize(
                    support,
                    (sw, sh),
                    interpolation=cv2.INTER_NEAREST,
                )
                if masked_base
                else None
            )
            scale_matrix = np.asarray(
                [[sx, 0.0, 0.0], [0.0, sy, 0.0]],
                dtype=np.float32,
            )

            for angle in F3_TRACKING_ADAPTIVE_TEMPLATE_ANGLES_DEG:
                if abs(float(requested_scale) - 1.0) < 1e-6 and abs(float(angle)) < 1e-6:
                    continue
                center = ((sw - 1.0) * 0.5, (sh - 1.0) * 0.5)
                rotation = cv2.getRotationMatrix2D(
                    center,
                    float(angle),
                    1.0,
                ).astype(np.float32)
                cos_v = abs(float(rotation[0, 0]))
                sin_v = abs(float(rotation[0, 1]))
                rw = max(
                    F3_TRACKING_TEMPLATE_MIN_SIZE,
                    int(math.ceil(sh * sin_v + sw * cos_v)),
                )
                rh = max(
                    F3_TRACKING_TEMPLATE_MIN_SIZE,
                    int(math.ceil(sh * cos_v + sw * sin_v)),
                )
                if rw >= current_edges.shape[1] or rh >= current_edges.shape[0]:
                    continue
                rotation[0, 2] += (rw - 1.0) * 0.5 - center[0]
                rotation[1, 2] += (rh - 1.0) * 0.5 - center[1]
                variant = cv2.warpAffine(
                    scaled,
                    rotation,
                    (rw, rh),
                    flags=cv2.INTER_NEAREST,
                    borderMode=cv2.BORDER_CONSTANT,
                    borderValue=0,
                )
                variant_support = (
                    cv2.warpAffine(
                        scaled_support,
                        rotation,
                        (rw, rh),
                        flags=cv2.INTER_NEAREST,
                        borderMode=cv2.BORDER_CONSTANT,
                        borderValue=0,
                    )
                    if isinstance(scaled_support, np.ndarray)
                    else None
                )
                masked = bool(
                    isinstance(variant_support, np.ndarray)
                    and variant_support.shape == variant.shape
                    and int(cv2.countNonZero(variant_support)) >= 150
                )
                try:
                    if masked:
                        response = cv2.matchTemplate(
                            current_edges,
                            variant,
                            cv2.TM_CCORR_NORMED,
                            mask=variant_support,
                        )
                        response = np.nan_to_num(
                            response,
                            nan=-1.0,
                            posinf=-1.0,
                            neginf=-1.0,
                        )
                    else:
                        response = cv2.matchTemplate(
                            current_edges,
                            variant,
                            cv2.TM_CCOEFF_NORMED,
                        )
                    _min_v, max_v, _min_l, max_loc = cv2.minMaxLoc(response)
                except Exception:
                    continue
                score = float(max_v)
                if score < threshold:
                    continue

                original_to_variant = compose_affine(
                    rotation,
                    scale_matrix,
                )
                if original_to_variant is None:
                    continue
                try:
                    variant_to_original = cv2.invertAffineTransform(
                        np.asarray(
                            original_to_variant,
                            dtype=np.float32,
                        ).reshape(2, 3)
                    )
                except Exception:
                    continue

                current_to_variant = np.asarray(
                    [
                        [1.0, 0.0, -float(max_loc[0])],
                        [0.0, 1.0, -float(max_loc[1])],
                    ],
                    dtype=np.float32,
                )
                current_to_crop = compose_affine(
                    variant_to_original,
                    current_to_variant,
                )
                crop_to_reference = np.asarray(
                    [
                        [1.0, 0.0, float(origin[0])],
                        [0.0, 1.0, float(origin[1])],
                    ],
                    dtype=np.float32,
                )
                current_to_reference = compose_affine(
                    crop_to_reference,
                    current_to_crop,
                )
                matrix = compose_affine(
                    ref.get("reference_to_canonical"),
                    current_to_reference,
                )
                if matrix is None:
                    continue
                final_scale = affine_scale(matrix)
                if not (
                    F3_TRACKING_MIN_SCALE
                    <= final_scale
                    <= F3_TRACKING_MAX_SCALE
                ):
                    continue

                candidate = {
                    "reference": str(key or ""),
                    "matrix": matrix.astype(np.float32),
                    "matches": 0,
                    "inliers": 0,
                    "ratio": score,
                    "rotation_deg": affine_rotation_deg(matrix),
                    "scale": final_scale,
                    "score": 2.5 + score * 8.0,
                    "source_type": str(
                        ref.get("source_type") or "reference"
                    ),
                    "fallback": "adaptive_edge_template",
                    "template_masked_for_segments": masked,
                    "template_threshold": float(threshold),
                    "template_variant_scale": float(requested_scale),
                    "template_variant_angle_deg": float(angle),
                }
                if best is None or score > float(best.get("ratio", 0.0)):
                    best = candidate
        return best

    def _temporal_tracking_mask(self):
        """Máscara da placa no frame anterior, excluindo as ROIs do display."""
        if self.last_matrix is None or not self.canonical_board:
            return None
        try:
            canonical_to_previous = cv2.invertAffineTransform(
                np.asarray(self.last_matrix, dtype=np.float32).reshape(2, 3)
            )
        except Exception:
            return None

        board_previous = transform_points(
            self.canonical_board,
            canonical_to_previous,
        )
        masks_previous = []
        for mask in self.canonical_masks:
            transformed = transform_mask(mask, canonical_to_previous)
            if transformed is not None:
                masks_previous.append(transformed)
        return build_tracking_mask(
            self.width,
            self.height,
            board_previous,
            masks_previous,
        )

    @staticmethod
    def _angle_delta_deg(first: float, second: float) -> float:
        value = (float(first) - float(second) + 180.0) % 360.0 - 180.0
        return abs(value)

    def _rotation_anchor_compatible(self, matrix) -> tuple[bool, float]:
        return _runtime_rotation_anchor_compatible(self, matrix)

    def _filter_abrupt_rotation_candidates(
        self,
        candidates,
        *,
        source: str,
    ) -> list[dict]:
        return _runtime_filter_abrupt_rotation_candidates(
            self,
            candidates,
            source=source,
        )

    def _matrix_continuity(self, matrix) -> tuple[bool, float]:
        """Compara a pose nova com a última sem exigir a mesma referência."""
        if self.last_matrix is None or matrix is None or not self.canonical_board:
            return False, 0.0
        try:
            previous_inverse = cv2.invertAffineTransform(
                np.asarray(self.last_matrix, dtype=np.float32).reshape(2, 3)
            )
            current_inverse = cv2.invertAffineTransform(
                np.asarray(matrix, dtype=np.float32).reshape(2, 3)
            )
            board = np.asarray(self.canonical_board, dtype=np.float32).reshape(-1, 2)
            center = np.mean(board, axis=0).reshape(1, 1, 2)
            previous_center = cv2.transform(
                center,
                previous_inverse,
            ).reshape(2)
            current_center = cv2.transform(
                center,
                current_inverse,
            ).reshape(2)
            distance = float(np.linalg.norm(current_center - previous_center))
        except Exception:
            return False, 0.0

        diagonal = max(
            1.0,
            math.hypot(float(self.width), float(self.height)),
        )
        max_distance = diagonal * 0.20
        previous_rotation = affine_rotation_deg(self.last_matrix)
        current_rotation = affine_rotation_deg(matrix)
        rotation_delta = self._angle_delta_deg(
            current_rotation,
            previous_rotation,
        )
        previous_scale = max(1e-6, affine_scale(self.last_matrix))
        current_scale = max(1e-6, affine_scale(matrix))
        scale_ratio = current_scale / previous_scale

        compatible = bool(
            distance <= max_distance
            and rotation_delta <= 32.0
            and 0.72 <= scale_ratio <= 1.38
        )
        closeness = max(0.0, 1.0 - distance / max_distance)
        return compatible, closeness

    def _candidate_rank(self, candidate: dict) -> float:
        rank = float(candidate.get("score", 0.0) or 0.0)
        if str(candidate.get("reference") or "") == self._last_reference:
            rank += F3_TRACKING_REFERENCE_STICK_BONUS
        compatible, closeness = self._matrix_continuity(
            candidate.get("matrix")
        )
        if compatible:
            rank += F3_TRACKING_CONTINUITY_BONUS * closeness
        return rank

    def _temporal_candidate(self, gray):
        """Segue a placa entre frames usando LK apenas dentro do contorno anterior.

        Isso não substitui as referências. Serve para atravessar pequenas perdas
        de ORB causadas por blur, reflexo ou mudança de LEDs sem piscar LOCK/SEARCH.
        """
        if (
            gray is None
            or self.last_gray is None
            or self.last_matrix is None
            or self.last_gray.shape != gray.shape
        ):
            return None

        tracking_mask = self._temporal_tracking_mask()
        if tracking_mask is None:
            return None

        try:
            previous_points = cv2.goodFeaturesToTrack(
                self.last_gray,
                maxCorners=F3_TRACKING_TEMPORAL_MAX_CORNERS,
                qualityLevel=0.01,
                minDistance=6,
                mask=tracking_mask,
                blockSize=7,
            )
        except Exception:
            return None
        if (
            previous_points is None
            or len(previous_points) < F3_TRACKING_TEMPORAL_MIN_POINTS
        ):
            return None

        try:
            current_points, forward_status, _forward_error = cv2.calcOpticalFlowPyrLK(
                self.last_gray,
                gray,
                previous_points,
                None,
                winSize=(25, 25),
                maxLevel=3,
                criteria=(
                    cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
                    30,
                    0.01,
                ),
            )
            backward_points, backward_status, _backward_error = cv2.calcOpticalFlowPyrLK(
                gray,
                self.last_gray,
                current_points,
                None,
                winSize=(25, 25),
                maxLevel=3,
                criteria=(
                    cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
                    30,
                    0.01,
                ),
            )
        except Exception:
            return None
        if current_points is None or backward_points is None:
            return None

        previous_flat = previous_points.reshape(-1, 2)
        current_flat = current_points.reshape(-1, 2)
        backward_flat = backward_points.reshape(-1, 2)
        forward_ok = forward_status.reshape(-1).astype(bool)
        backward_ok = backward_status.reshape(-1).astype(bool)
        fb_error = np.linalg.norm(previous_flat - backward_flat, axis=1)
        finite = (
            np.isfinite(previous_flat).all(axis=1)
            & np.isfinite(current_flat).all(axis=1)
            & np.isfinite(backward_flat).all(axis=1)
        )
        valid = forward_ok & backward_ok & finite & (fb_error <= 1.8)
        previous_good = previous_flat[valid]
        current_good = current_flat[valid]
        if len(previous_good) < F3_TRACKING_TEMPORAL_MIN_POINTS:
            return None

        try:
            # CURRENT -> PREVIOUS. Depois compomos PREVIOUS -> CANÔNICO.
            motion, inlier_mask = cv2.estimateAffinePartial2D(
                current_good.reshape(-1, 1, 2),
                previous_good.reshape(-1, 1, 2),
                method=cv2.RANSAC,
                ransacReprojThreshold=3.0,
                maxIters=1600,
                confidence=0.995,
                refineIters=10,
            )
        except Exception:
            return None
        if motion is None or inlier_mask is None:
            return None

        inliers = int(np.count_nonzero(inlier_mask))
        ratio = float(inliers / max(1, len(previous_good)))
        if (
            inliers < F3_TRACKING_TEMPORAL_MIN_INLIERS
            or ratio < F3_TRACKING_TEMPORAL_MIN_INLIER_RATIO
        ):
            return None

        motion_scale = affine_scale(motion)
        motion_rotation = abs(affine_rotation_deg(motion))
        motion_translation = math.hypot(
            float(motion[0, 2]),
            float(motion[1, 2]),
        )
        max_translation = (
            max(float(self.width), float(self.height))
            * F3_TRACKING_TEMPORAL_MAX_TRANSLATION_FRACTION
        )
        if not (
            F3_TRACKING_TEMPORAL_MIN_SCALE
            <= motion_scale
            <= F3_TRACKING_TEMPORAL_MAX_SCALE
        ):
            return None
        if motion_rotation > F3_TRACKING_TEMPORAL_MAX_ROTATION_DEG:
            return None
        if motion_translation > max_translation:
            return None

        matrix = compose_affine(self.last_matrix, motion)
        if matrix is None:
            return None
        final_scale = affine_scale(matrix)
        if not (F3_TRACKING_MIN_SCALE <= final_scale <= F3_TRACKING_MAX_SCALE):
            return None
        if abs(float(matrix[0, 2])) > self.width * F3_TRACKING_MAX_TRANSLATION_FRACTION:
            return None
        if abs(float(matrix[1, 2])) > self.height * F3_TRACKING_MAX_TRANSLATION_FRACTION:
            return None

        source_type = (
            str(self.last_result.source_type or "temporal")
            if self.last_result is not None
            else "temporal"
        )
        return {
            "reference": self._last_reference,
            "matrix": matrix.astype(np.float32),
            "matches": int(len(previous_good)),
            "inliers": inliers,
            "ratio": ratio,
            "rotation_deg": affine_rotation_deg(matrix),
            "scale": final_scale,
            "score": 4.0 + ratio * 10.0 + min(12.0, inliers * 0.25),
            "source_type": source_type,
            "fallback": "temporal_flow",
        }

    def _held_lock_result(self, frame, now: float):
        """Mantém a última pose por poucos ciclos, apenas para estabilidade visual."""
        if (
            self.last_matrix is None
            or self.last_result is None
            or not self.last_result.locked
        ):
            return None
        if self.consecutive_misses > F3_TRACKING_LOCK_GRACE_FRAMES:
            return None
        if now - float(self.last_verified_s or 0.0) > F3_TRACKING_LOCK_GRACE_S:
            return None

        aligned = cv2.warpAffine(
            frame,
            self.last_matrix,
            (self.width, self.height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT101,
        )
        return F3TrackingResult(
            True,
            aligned,
            reference=str(self.last_result.reference or self._last_reference),
            matches=int(self.last_result.matches),
            inliers=int(self.last_result.inliers),
            inlier_ratio=float(self.last_result.inlier_ratio),
            rotation_deg=float(self.last_result.rotation_deg),
            scale=float(self.last_result.scale),
            reason="lock_held",
            current_to_canonical=self.last_matrix.copy(),
            source_type=str(self.last_result.source_type or ""),
            evidence_current=False,
        )

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
        signature = self._signature(project, board)
        if signature == self.signature:
            return self.ready

        self.reset()
        self.project = name
        self.signature = signature
        self.width = width
        self.height = height
        self.canonical_board = deepcopy(board)
        self.canonical_masks = [
            converter_mascara_legada_para_editor(mask)
            for mask in normalizar_mascaras_display(project.get("masks", []))
            if isinstance(mask, dict)
        ]

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
                source_type=str(spec.get("source_type") or "reference"),
                board_points=spec.get("board", []),
            )

        if not refs:
            self.reason = "reference_features_insufficient"
            return False

        self.references = refs
        self.ready = True
        self.reason = "ready"
        return True

    def _feature_candidate(
        self,
        current_kp,
        current_desc,
        key: str,
        *,
        descriptor_key: str,
        canonical_key: str,
        ratio_test: float,
        min_matches: int,
        min_inliers: int,
        min_inlier_ratio: float,
        fallback: str = "",
    ):
        ref = self.references.get(str(key or ""), {})
        descriptors = ref.get(descriptor_key)
        canonical = ref.get(canonical_key)
        if (
            descriptors is None
            or current_desc is None
            or canonical is None
            or len(canonical) == 0
        ):
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
            if first.distance < float(ratio_test) * second.distance:
                good.append(first)
        if len(good) < int(min_matches):
            return None

        try:
            current_points = np.float32(
                [current_kp[item.trainIdx].pt for item in good]
            ).reshape(-1, 1, 2)
            canonical_points = np.float32(
                [canonical[item.queryIdx] for item in good]
            ).reshape(-1, 1, 2)
        except (IndexError, TypeError, ValueError):
            return None

        try:
            matrix, inlier_mask = cv2.estimateAffinePartial2D(
                current_points,
                canonical_points,
                method=cv2.RANSAC,
                ransacReprojThreshold=F3_TRACKING_RANSAC_THRESHOLD_PX,
                maxIters=3000,
                confidence=0.995,
                refineIters=12,
            )
        except Exception:
            return None
        if matrix is None or inlier_mask is None:
            return None

        inliers = int(np.count_nonzero(inlier_mask))
        ratio = float(inliers / max(1, len(good)))
        if inliers < int(min_inliers) or ratio < float(min_inlier_ratio):
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
        if source_type == "mask_reference":
            score += 4.0
        elif source_type == "check":
            score += 3.0
        elif source_type == "board_off":
            score += 2.0
        if fallback == "akaze_reacquire":
            score += 1.5

        result = {
            "reference": str(key or ""),
            "matrix": matrix.astype(np.float32),
            "matches": len(good),
            "inliers": inliers,
            "ratio": ratio,
            "rotation_deg": rotation,
            "scale": scale,
            "score": score,
            "source_type": source_type,
        }
        if fallback:
            result["fallback"] = fallback
        return result

    def _candidate(self, current_kp, current_desc, key: str):
        return self._feature_candidate(
            current_kp,
            current_desc,
            key,
            descriptor_key="descriptors",
            canonical_key="canonical_points",
            ratio_test=F3_TRACKING_RATIO_TEST,
            min_matches=F3_TRACKING_MIN_MATCHES,
            min_inliers=F3_TRACKING_MIN_INLIERS,
            min_inlier_ratio=F3_TRACKING_MIN_INLIER_RATIO,
        )

    def _akaze_candidate(self, current_kp, current_desc, key: str):
        return self._feature_candidate(
            current_kp,
            current_desc,
            key,
            descriptor_key="akaze_descriptors",
            canonical_key="akaze_canonical_points",
            ratio_test=F3_TRACKING_AKAZE_RATIO_TEST,
            min_matches=F3_TRACKING_AKAZE_MIN_MATCHES,
            min_inliers=F3_TRACKING_AKAZE_MIN_INLIERS,
            min_inlier_ratio=F3_TRACKING_AKAZE_MIN_INLIER_RATIO,
            fallback="akaze_reacquire",
        )

    def candidate_for_reference(
        self,
        frame,
        key: str,
        current_tracking_mask=None,
        *,
        template_min_score: float | None = None,
    ) -> dict | None:
        """Calcula a pose contra UMA referência sem alterar o lock global.

        É usado após a identidade do CHECK estar conhecida. O tracker global
        continua livre para escolher board_off/mask_reference/orientação, mas a
        geometria fina das ROIs pode ser recalculada diretamente contra a foto do
        CHECK atual. A máscara corrente exclui os segmentos para que LEDs ligados
        ou reflexos não puxem a transformação geométrica.
        """
        if (
            not _valid_frame(frame)
            or not self.ready
            or frame.shape[:2] != (self.height, self.width)
            or str(key or "") not in self.references
        ):
            return None

        gray = self._gray(frame)
        if gray is None:
            return None

        orb = cv2.ORB_create(
            nfeatures=F3_TRACKING_ORB_FEATURES,
            scaleFactor=1.2,
            nlevels=8,
            edgeThreshold=12,
            fastThreshold=7,
        )
        try:
            current_kp, current_desc = orb.detectAndCompute(
                gray,
                current_tracking_mask,
            )
        except Exception:
            current_kp, current_desc = [], None

        if (
            current_desc is not None
            and len(current_kp) >= F3_TRACKING_MIN_MATCHES
        ):
            candidate = self._candidate(
                current_kp,
                current_desc,
                str(key),
            )
            if candidate is not None:
                candidate = dict(candidate)
                candidate["direct_reference_refinement"] = True
                candidate["current_masked_for_segments"] = bool(
                    current_tracking_mask is not None
                )
                return candidate

        # Reacquisition absoluto mais tolerante a contraste/escala/rotação.
        try:
            akaze = cv2.AKAZE_create(
                threshold=F3_TRACKING_AKAZE_THRESHOLD,
                nOctaves=4,
                nOctaveLayers=4,
            )
            akaze_kp, akaze_desc = akaze.detectAndCompute(
                gray,
                current_tracking_mask,
            )
        except Exception:
            akaze_kp, akaze_desc = [], None
        if (
            akaze_desc is not None
            and len(akaze_kp) >= F3_TRACKING_AKAZE_MIN_MATCHES
        ):
            candidate = self._akaze_candidate(
                akaze_kp,
                akaze_desc,
                str(key),
            )
            if candidate is not None:
                candidate = dict(candidate)
                candidate["direct_reference_refinement"] = True
                candidate["current_masked_for_segments"] = bool(
                    current_tracking_mask is not None
                )
                return candidate

        # Câmera/suporte fixos: mantém o fallback por bordas apenas se os
        # descritores não produzirem correspondências suficientes.
        try:
            current_edges = cv2.Canny(gray, 45, 135)
        except Exception:
            current_edges = None
        candidate = self._template_candidate(
            current_edges,
            str(key),
            min_score=template_min_score,
        )
        if candidate is None:
            candidate = self._adaptive_template_candidate(
                current_edges,
                str(key),
                min_score=template_min_score,
            )
        if candidate is None:
            return None
        candidate = dict(candidate)
        candidate["direct_reference_refinement"] = True
        candidate["current_masked_for_segments"] = False
        return candidate

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
                evidence_current=bool(self.last_result.evidence_current),
            )
            self.last_result = result
            self.last_frame_id = frame_id
            return result

        gray = self._gray(frame)
        self._last_rotation_jump_rejections = []
        if gray is None:
            self.consecutive_misses += 1
            held = self._held_lock_result(frame, now)
            if held is not None:
                self.last_result = held
                self.last_frame_id = frame_id
                self.last_compute_s = now
                return held
            self.last_matrix = None
            self.last_gray = None
            self.last_verified_s = 0.0
            self.consecutive_misses = 0
            self._last_reference = ""
            result = F3TrackingResult(
                False,
                frame,
                reason="gray_prepare_failed",
                evidence_current=False,
            )
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
            candidates = self._filter_abrupt_rotation_candidates(
                candidates,
                source="orb",
            )

        # Quando nenhuma referência absoluta vence, tente continuidade óptica
        # entre o último frame confirmado e o atual, restrita ao contorno da placa.
        if not candidates:
            temporal = self._temporal_candidate(gray)
            if temporal is not None:
                candidates.append(temporal)

        # Se ORB e continuidade temporal falharem, faça uma reacquisition
        # absoluta com AKAZE. É deliberadamente tardia para preservar FPS.
        akaze_available = False
        if not candidates:
            try:
                akaze = cv2.AKAZE_create(
                    threshold=F3_TRACKING_AKAZE_THRESHOLD,
                    nOctaves=4,
                    nOctaveLayers=4,
                )
                akaze_kp, akaze_desc = akaze.detectAndCompute(gray, None)
            except Exception:
                akaze_kp, akaze_desc = [], None
            akaze_available = bool(
                akaze_desc is not None
                and len(akaze_kp) >= F3_TRACKING_AKAZE_MIN_MATCHES
            )
            if akaze_available:
                for key in tuple(self.references):
                    candidate = self._akaze_candidate(
                        akaze_kp,
                        akaze_desc,
                        key,
                    )
                    if candidate is not None:
                        candidates.append(candidate)
                candidates = self._filter_abrupt_rotation_candidates(
                    candidates,
                    source="akaze",
                )

        # Câmera e suporte são fixos: se o PCB tiver poucos corners ORB, use as
        # bordas do contorno desenhado como fallback de translação. O contorno
        # retangular é angularmente ambíguo; a pose aceita precisa permanecer
        # coerente com a última orientação verificada da placa.
        if not candidates:
            try:
                current_edges = cv2.Canny(gray, 45, 135)
            except Exception:
                current_edges = None
            for key in tuple(self.references):
                candidate = self._template_candidate(current_edges, key)
                if candidate is not None:
                    candidates.append(candidate)
            candidates = self._filter_abrupt_rotation_candidates(
                candidates,
                source="edge_template",
            )

        if not candidates:
            self.consecutive_misses += 1
            held = self._held_lock_result(frame, now)
            if held is not None:
                self.last_result = held
                self.last_frame_id = frame_id
                self.last_compute_s = now
                return held

            self.last_matrix = None
            self.last_gray = None
            self.last_verified_s = 0.0
            self.consecutive_misses = 0
            self._last_reference = ""
            result = F3TrackingResult(
                False,
                frame,
                reason=(
                    "current_features_insufficient"
                    if not orb_available and not akaze_available
                    else "object_not_locked"
                ),
                evidence_current=False,
            )
            self.last_result = result
            self.last_frame_id = frame_id
            self.last_compute_s = now
            return result

        best = max(candidates, key=self._candidate_rank)
        matrix = best["matrix"]
        continuous, _closeness = self._matrix_continuity(matrix)
        if self.last_matrix is not None and continuous:
            alpha = (
                0.72
                if str(best.get("fallback") or "") == "temporal_flow"
                else 0.54
            )
            matrix = (
                (1.0 - alpha) * self.last_matrix.astype(np.float32)
                + alpha * matrix.astype(np.float32)
            ).astype(np.float32)

        self.last_matrix = matrix
        self.last_verified_rotation_deg = float(
            affine_rotation_deg(matrix)
        )
        self._last_reference = str(best["reference"])
        self.last_compute_s = now
        self.last_frame_id = frame_id
        self.last_gray = gray.copy()
        self.last_verified_s = now
        self.consecutive_misses = 0

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
                else (
                    "locked_adaptive_template"
                    if str(best.get("fallback") or "") == "adaptive_edge_template"
                    else (
                        "locked_akaze"
                        if str(best.get("fallback") or "") == "akaze_reacquire"
                        else (
                            "locked_temporal"
                            if str(best.get("fallback") or "") == "temporal_flow"
                            else "locked"
                        )
                    )
                )
            ),
            current_to_canonical=matrix.copy(),
            source_type=str(best.get("source_type") or ""),
            evidence_current=True,
        )
        self.last_result = result
        return result


def get_tracking_runtime(app):
    owner = getattr(app, "_display_f3_tracking_authority", None)
    owned_runtime = getattr(owner, "runtime", None)
    if isinstance(owned_runtime, F3DisplayObjectTracker):
        return owned_runtime
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

    # A flag persistida é a autoridade final. O store possui cache por
    # mtime/tamanho, então esta leitura não reprocessa JSON a cada frame. Isso
    # evita um estado perigoso em que o checkbox fica marcado no arquivo, mas uma
    # cópia antiga em memória mantém o tracking efetivamente desligado.
    enabled = bool(runtime.store.enabled())
    cached = bool(
        getattr(app, "_display_f3_object_tracking_enabled", enabled)
    )
    if cached != enabled or not hasattr(
        app,
        "_display_f3_object_tracking_enabled",
    ):
        app._display_f3_object_tracking_enabled = enabled
        if cached != enabled:
            runtime.reset()
            app._display_f3_object_tracking_last_status = {
                "enabled": enabled,
                "locked": False,
                "reason": "setting_resynchronized",
            }
    return enabled


def set_tracking_enabled(app, enabled: bool) -> bool:
    runtime = get_tracking_runtime(app)
    if runtime is None:
        return False
    runtime.store.set_enabled(bool(enabled))
    app._display_f3_object_tracking_enabled = bool(enabled)
    reset_tracking_runtime(app)
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
    executor = getattr(app, "_display_f3_heavy_executor", None)
    if executor is not None:
        try:
            executor.cancel_owner(F3_TRACKING_EXECUTOR_OWNER)
        except Exception:
            pass
    app._display_f3_tracking_job_generation = int(
        getattr(app, "_display_f3_tracking_job_generation", 0) or 0
    ) + 1
    app._display_f3_tracking_future = None
    app._display_f3_semantic_future = None
    app._display_auto_precomputed_payload = None
    app._display_auto_analysis_frame_override = None
    app._display_f3_tracking_raw_preview_frame = None
    app._display_f3_tracking_result = None
    app._display_f3_tracking_live_geometry = None
    # O F3 usa pipeline cooperativo em dois ciclos do Tk: rastreamento primeiro,
    # classificação depois. Nunca deixe um frame pendente sobreviver a reset,
    # troca de projeto, fechamento do F3 ou perda de rastreamento.
    app._display_f3_tracking_analysis_frame = None
    app._display_f3_tracking_analysis_pending = False
    app._display_f3_tracking_pending_raw_frame = None
    app._display_f3_object_tracking_last_status = {
        "enabled": tracking_enabled(app),
        "locked": False,
        "reason": "reset",
    }


def _rescue_current_check_tracking_lock(
    app,
    frame,
    runtime: F3DisplayObjectTracker,
) -> F3TrackingResult | None:
    """Recupera a pose por referências estruturais sem usar LEDs como estado.

    Primeiro tentamos a foto do CHECK lógico atual. Se ela não localizar a placa,
    tentamos BOARD_OFF, que é particularmente útil antes de H1 acender. Em ambos
    os casos as ROIs dos segmentos ficam excluídas do template; a referência
    escolhida serve SOMENTE para CURRENT -> CANÔNICO e nunca prova ON/OFF/OK/NG.
    """
    if runtime is None or not _valid_frame(frame) or not runtime.ready:
        return None

    current = _current_check(app)
    check_id = str((current or {}).get("id") or "") if isinstance(current, dict) else ""

    specs: list[tuple[str, float]] = []
    if check_id:
        specs.append(
            (
                f"check:{check_id}",
                F3_TRACKING_CURRENT_CHECK_TEMPLATE_MIN_SCORE,
            )
        )
    specs.append(
        (
            "board_off",
            F3_TRACKING_BOARD_OFF_TEMPLATE_MIN_SCORE,
        )
    )

    # Evita repetir a mesma chave e registra cada tentativa para o DEBUG.
    unique_specs: list[tuple[str, float]] = []
    seen = set()
    for key, threshold in specs:
        if key in seen or key not in runtime.references:
            continue
        seen.add(key)
        unique_specs.append((key, threshold))

    attempts = []
    candidates = []
    for key, threshold in unique_specs:
        candidate = runtime.candidate_for_reference(
            frame,
            key,
            template_min_score=threshold,
        )
        attempt = {
            "reference": key,
            "template_min_score": float(threshold),
            "candidate": bool(isinstance(candidate, dict)),
        }
        if isinstance(candidate, dict):
            attempt.update(
                {
                    "score": round(float(candidate.get("score", 0.0) or 0.0), 4),
                    "matches": int(candidate.get("matches", 0) or 0),
                    "inliers": int(candidate.get("inliers", 0) or 0),
                    "inlier_ratio": round(
                        float(candidate.get("ratio", 0.0) or 0.0),
                        4,
                    ),
                    "fallback": str(candidate.get("fallback") or ""),
                    "template_masked_for_segments": bool(
                        candidate.get("template_masked_for_segments", False)
                    ),
                }
            )
            enriched = dict(candidate)
            enriched["_rescue_reference"] = key
            enriched["_rescue_threshold"] = float(threshold)
            candidates.append(enriched)
        attempts.append(attempt)

    had_structural_candidate = bool(candidates)
    candidates = _runtime_filter_abrupt_rotation_candidates(
        runtime,
        candidates,
        source="structural_rescue",
    )
    if not candidates:
        app._display_f3_tracking_rescue_debug = {
            "available": False,
            "reason": (
                "structural_rescue_rotation_jump_rejected"
                if had_structural_candidate
                else "no_structural_rescue_candidate"
            ),
            "check_id": check_id,
            "attempts": attempts,
            "rotation_jump_rejections": deepcopy(
                getattr(runtime, "_last_rotation_jump_rejections", [])
            ),
        }
        return None

    candidate = max(candidates, key=runtime._candidate_rank)
    key = str(candidate.get("_rescue_reference") or candidate.get("reference") or "")

    try:
        matrix = np.asarray(
            candidate.get("matrix"),
            dtype=np.float32,
        ).reshape(2, 3)
    except Exception:
        return None
    if not np.all(np.isfinite(matrix)):
        return None

    scale = affine_scale(matrix)
    if not (F3_TRACKING_MIN_SCALE <= scale <= F3_TRACKING_MAX_SCALE):
        return None
    if abs(float(matrix[0, 2])) > runtime.width * F3_TRACKING_MAX_TRANSLATION_FRACTION:
        return None
    if abs(float(matrix[1, 2])) > runtime.height * F3_TRACKING_MAX_TRANSLATION_FRACTION:
        return None

    aligned = cv2.warpAffine(
        frame,
        matrix,
        (int(runtime.width), int(runtime.height)),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT101,
    )
    now = time.monotonic()
    gray = runtime._gray(frame)

    runtime.last_matrix = matrix.copy()
    runtime.last_verified_rotation_deg = float(
        affine_rotation_deg(matrix)
    )
    runtime._last_reference = key
    runtime.last_compute_s = now
    runtime.last_frame_id = getattr(app, "camera_ultimo_frame_id", None)
    runtime.last_gray = gray.copy() if isinstance(gray, np.ndarray) else None
    runtime.last_verified_s = now
    runtime.consecutive_misses = 0

    source_label = (
        "board_off"
        if key == "board_off"
        else "current_check"
    )
    reason = (
        f"locked_{source_label}_template_rescue"
        if str(candidate.get("fallback") or "") == "edge_template"
        else f"locked_{source_label}_orb_rescue"
    )

    app._display_f3_tracking_rescue_debug = {
        "available": True,
        "selected_reference": key,
        "selected_reason": reason,
        "selected_score": round(float(candidate.get("score", 0.0) or 0.0), 4),
        "selected_fallback": str(candidate.get("fallback") or ""),
        "check_id": check_id,
        "attempts": attempts,
    }

    result = F3TrackingResult(
        True,
        aligned,
        reference=key,
        matches=int(candidate.get("matches", 0) or 0),
        inliers=int(candidate.get("inliers", 0) or 0),
        inlier_ratio=float(candidate.get("ratio", 0.0) or 0.0),
        rotation_deg=float(candidate.get("rotation_deg", 0.0) or 0.0),
        scale=float(candidate.get("scale", scale) or scale),
        reason=reason,
        current_to_canonical=matrix.copy(),
        source_type=str(candidate.get("source_type") or ""),
        evidence_current=True,
    )
    runtime.last_result = result
    return result


def _invalidate_spatial_authority_after_tracking_loss(
    app,
    reason: str,
) -> None:
    """Nenhuma classificação espacial antiga sobrevive a um lock perdido."""
    app._display_auto_last_analysis = None
    app._display_f3_tracking_analysis_frame = None

    previous = getattr(app, "_display_f3_power_authority_status", None)
    presence = (
        deepcopy(previous.get("presence"))
        if isinstance(previous, dict)
        and isinstance(previous.get("presence"), dict)
        else None
    )
    board_present = (
        previous.get("board_present")
        if isinstance(previous, dict)
        else None
    )
    app._display_f3_power_authority_status = {
        "source": "f3_tracking_spatial_gate",
        "board_present": board_present,
        "presence": presence,
        "energy": {
            "available": False,
            "energy_state": "unconfirmed",
            "powered_confirmed": False,
            "off_confirmed": False,
            "reason": str(reason or "tracking_not_locked"),
        },
        "decision_allowed": False,
        "reason": str(reason or "tracking_not_locked"),
    }

    operational = getattr(app, "_display_f3_operational_state", None)
    if isinstance(operational, dict):
        updated = deepcopy(operational)
        updated.update(
            {
                "kind": "unknown",
                "text": "RASTREAMENTO F3 • PROCURANDO PLACA",
                "allow_auto": False,
                "powered_board_confirmed": False,
                "power_gate_blocked": True,
                "power_gate_reason": str(reason or "tracking_not_locked"),
            }
        )
        app._display_f3_operational_state = updated


def align_frame_for_f3(app, frame, *, frame_token=None):
    if not tracking_enabled(app):
        return frame, None
    runtime = get_tracking_runtime(app)
    if runtime is None:
        return frame, None
    project_name = runtime.repository.obter_projeto_ativo()
    if frame_token is None:
        try:
            token_fn = getattr(app, "_display_auto_frame_token", None)
            frame_token = token_fn(frame) if callable(token_fn) else None
        except Exception:
            frame_token = None
    analysis_frame_id = (
        int(frame_token[1])
        if isinstance(frame_token, tuple)
        and len(frame_token) >= 2
        and frame_token[0] == "camera"
        else getattr(app, "camera_ultimo_frame_id", None)
    )
    configured = runtime.configure(project_name)
    if not configured:
        # Mesmo quando ORB/AKAZE/template não geram uma referência utilizável,
        # o projeto pode ter contorno + máscaras + estados suficientes para
        # reencontrar o display pelos segmentos que realmente acenderam.
        result = F3TrackingResult(
            False,
            frame,
            reason=runtime.reason,
        )
        luminous = _rescue_luminous_segment_tracking_lock(
            app,
            frame,
            runtime,
            base_result=None,
            frame_token=frame_token,
        )
        if luminous is None:
            status = {
                "enabled": True,
                "locked": False,
                "reason": runtime.reason,
            }
            app._display_f3_object_tracking_last_status = status
            return frame, result
        result = luminous
    else:
        result = runtime.align(
            frame,
            frame_id=analysis_frame_id,
        )
        if not bool(result.locked):
            rescued = _rescue_current_check_tracking_lock(
                app,
                frame,
                runtime,
            )
            if rescued is not None:
                result = rescued

        # Com ou sem lock estrutural, os segmentos ACESOS podem corrigir a pose
        # fina. Isso é o que permite às 28 máscaras seguirem o display móvel em
        # vez de permanecerem presas às coordenadas configuradas.
        luminous = _rescue_luminous_segment_tracking_lock(
            app,
            frame,
            runtime,
            base_result=result if bool(result.locked) else None,
            frame_token=frame_token,
        )
        if luminous is not None:
            result = luminous

    app._display_f3_object_tracking_last_status = {
        "enabled": True,
        "locked": bool(result.locked),
        "frame_id": analysis_frame_id,
        "frame_token": deepcopy(frame_token),
        "reference": result.reference,
        "matches": int(result.matches),
        "inliers": int(result.inliers),
        "inlier_ratio": round(float(result.inlier_ratio), 4),
        "rotation_deg": round(float(result.rotation_deg), 3),
        "scale": round(float(result.scale), 5),
        "source_type": str(result.source_type or ""),
        "reason": result.reason,
        "evidence_current": bool(result.evidence_current),
        "misses": int(getattr(runtime, "consecutive_misses", 0) or 0),
        "rotation_anchor_deg": getattr(
            runtime,
            "last_verified_rotation_deg",
            None,
        ),
        "rotation_jump_rejections": deepcopy(
            getattr(runtime, "_last_rotation_jump_rejections", [])
        ),
    }
    if not bool(result.locked):
        _invalidate_spatial_authority_after_tracking_loss(
            app,
            str(result.reason or "tracking_not_locked"),
        )
    return (result.frame if result.locked else frame), result


def _analysis_transform_for_current_check(
    app,
    result: F3TrackingResult | None,
):
    """Retorna CURRENT -> espaço de análise sem gerar imagem."""
    if (
        result is None
        or not result.locked
        or result.current_to_canonical is None
    ):
        return None, "canonical"

    runtime = get_tracking_runtime(app)
    current = _current_check(app)
    if runtime is None or not isinstance(current, dict):
        return result.current_to_canonical, "canonical"

    check_id = str(current.get("id") or "")
    reference = runtime.references.get(f"check:{check_id}")
    mapping = (
        reference.get("reference_to_canonical")
        if isinstance(reference, dict)
        else None
    )
    if mapping is None:
        return result.current_to_canonical, "canonical"

    try:
        canonical_to_check = cv2.invertAffineTransform(
            np.asarray(mapping, dtype=np.float32).reshape(2, 3)
        )
    except Exception:
        return result.current_to_canonical, "canonical"

    current_to_check = compose_affine(
        canonical_to_check,
        result.current_to_canonical,
    )
    if current_to_check is None:
        return result.current_to_canonical, "canonical"
    return current_to_check, f"check:{check_id}"


def _analysis_alignment_for_current_check(
    app,
    raw_frame,
    result: F3TrackingResult | None,
):
    """Gera o frame de análise somente uma vez, fora do thread Tk quando possível."""
    if not _valid_frame(raw_frame):
        return None, None

    matrix, _space = _analysis_transform_for_current_check(app, result)
    if matrix is None:
        return None, None

    runtime = get_tracking_runtime(app)
    if runtime is None:
        return None, None

    aligned = cv2.warpAffine(
        raw_frame,
        np.asarray(matrix, dtype=np.float32).reshape(2, 3),
        (int(runtime.width), int(runtime.height)),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT101,
    )
    return aligned, matrix


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

    geometry_space = "canonical"
    board_current = transform_points(source_board, source_to_current)
    masks_current = []
    for mask in source_masks:
        transformed = transform_mask(mask, source_to_current)
        if transformed is None:
            continue
        # A pose pode mover/rotacionar/escalar o conjunto, mas o desenho volta
        # sempre ao formato canônico da máscara (segmento continua segmento).
        masks_current.append(
            sincronizar_formato_mascara_display(mask, transformed)
        )

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
    if not bool(status.get("evidence_current", False)):
        return False, "rastreamento_lock_mantido_sem_evidencia_atual"

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
        and energy.get("raw_analysis_ready") is True
        and int(energy.get("powered_votes", 0) or 0) >= 1
        and str(energy.get("project_name") or "")
        == str(context.get("project_name") or "")
        and str(energy.get("check_id") or "")
        == str(context.get("check_id") or "")
    ):
        return False, "energia_fisica_nao_confirmada"
    return True, "h1_ligado_confirmado"


def _fit_live_preview_before_overlay(frame, window):
    """Reduz o frame ao tamanho realmente visível antes de desenhar 28 ROIs.

    O renderer semântico já escala máscaras pela resolução do contexto, portanto
    não há perda de precisão visual ao desenhar no frame reduzido. A análise
    produtiva continua usando o frame RAW em resolução total.
    """
    if not _valid_frame(frame):
        return frame
    try:
        frame_h, frame_w = frame.shape[:2]
        canvas_w, canvas_h = window._get_canvas_size()
        scale = min(
            max(1, int(canvas_w)) / float(frame_w),
            max(1, int(canvas_h)) / float(frame_h),
            1.0,
        )
        if scale >= 0.995:
            return frame
        target_w = max(1, int(round(frame_w * scale)))
        target_h = max(1, int(round(frame_h * scale)))
        return cv2.resize(
            frame,
            (target_w, target_h),
            interpolation=cv2.INTER_AREA,
        )
    except Exception:
        return frame


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



def _run_live_tracking_heavy_job(
    app,
    raw_frame,
    generation: int,
    frame_token,
    submitted_at_s: float,
) -> dict:
    """Executa ORB/AKAZE/warp no executor pesado; não toca widgets Tk."""
    started = time.perf_counter()
    aligned, result = align_frame_for_f3(
        app,
        raw_frame,
        frame_token=frame_token,
    )
    geometry = None
    analysis_frame = None
    if result is not None and bool(result.locked):
        # A geometria usa apenas matrizes; o único warp adicional cria o frame
        # de análise do CHECK atual e também fica fora do Tk.
        previous_geometry = getattr(app, "_display_f3_tracking_live_geometry", None)
        try:
            _update_tracking_live_geometry(app, raw_frame, result)
            geometry = deepcopy(
                getattr(app, "_display_f3_tracking_live_geometry", None)
            )
        finally:
            app._display_f3_tracking_live_geometry = previous_geometry
        analysis_frame, _matrix = _analysis_alignment_for_current_check(
            app,
            raw_frame,
            result,
        )
        if not _valid_frame(analysis_frame):
            analysis_frame = aligned
    current_generation = int(
        getattr(app, "_display_f3_tracking_job_generation", 0) or 0
    )
    if int(generation) != current_generation:
        runtime = get_tracking_runtime(app)
        if runtime is not None:
            runtime.reset()

    return {
        "generation": int(generation),
        "frame_token": frame_token,
        "elapsed_ms": round(
            max(0.0, (time.perf_counter() - started) * 1000.0),
            2,
        ),
        "age_ms": round(
            max(0.0, (time.perf_counter() - float(submitted_at_s)) * 1000.0),
            2,
        ),
        "raw_frame": raw_frame,
        "result": result,
        "geometry": geometry,
        "analysis_frame": analysis_frame,
    }


def _submit_live_tracking_job(app, raw_frame):
    executor = getattr(app, "_display_f3_heavy_executor", None)
    if executor is None:
        ensure = getattr(app, "_ensure_f3_heavy_executor", None)
        executor = ensure() if callable(ensure) else None
    if executor is None:
        return None

    generation = int(
        getattr(app, "_display_f3_tracking_job_generation", 0) or 0
    )
    token_fn = getattr(app, "_display_auto_frame_token", None)
    try:
        frame_token = token_fn(raw_frame) if callable(token_fn) else None
    except Exception:
        frame_token = None
    try:
        frame_snapshot = raw_frame.copy()
    except Exception:
        frame_snapshot = raw_frame
    submitted_at_s = time.perf_counter()

    future = executor.submit(
        lambda: _run_live_tracking_heavy_job(
            app,
            frame_snapshot,
            generation,
            frame_token,
            submitted_at_s,
        ),
        priority=F3HeavyWorkPriority.HIGH,
        name="f3-live-tracking",
        owner=F3_TRACKING_EXECUTOR_OWNER,
        key=F3_TRACKING_EXECUTOR_KEY,
        replace_pending=True,
    )
    app._display_f3_tracking_future = future
    return future


def _run_live_semantic_job(
    analyzer,
    analysis_frame,
    raw_frame,
    tracking_geometry,
    context: dict,
    visual_rotation: int,
    generation: int,
    frame_token,
    source_age_ms: float,
    submitted_at_s: float,
) -> dict:
    """Classificação pesada do CHECK fora do thread Tk.

    Frame RAW e geometria são snapshots do MESMO job de tracking. O worker não
    relê esses dados do app porque eles podem ter avançado antes da execução.
    """
    started = time.perf_counter()
    snapshot_analyze = getattr(
        analyzer,
        "analyze_tracking_snapshot",
        None,
    )
    if (
        callable(snapshot_analyze)
        and _valid_frame(raw_frame)
        and isinstance(tracking_geometry, dict)
    ):
        analysis = snapshot_analyze(
            analysis_frame=analysis_frame,
            raw_frame=raw_frame,
            tracking_geometry=tracking_geometry,
            project_name=str(context.get("project_name") or ""),
            check_id=str(context.get("check_id") or ""),
            visual_rotation=int(visual_rotation or 0),
        )
    else:
        analysis = analyzer.analyze(
            frame=analysis_frame,
            project_name=str(context.get("project_name") or ""),
            check_id=str(context.get("check_id") or ""),
            visual_rotation=int(visual_rotation or 0),
        )
    elapsed_ms = max(
        0.0,
        (time.perf_counter() - started) * 1000.0,
    )
    return {
        "generation": int(generation),
        "frame_token": frame_token,
        "age_ms": round(max(0.0, float(source_age_ms)) + elapsed_ms, 2),
        "semantic_elapsed_ms": round(elapsed_ms, 2),
        "queue_age_ms": round(
            max(0.0, (time.perf_counter() - float(submitted_at_s)) * 1000.0),
            2,
        ),
        "analysis_frame": analysis_frame,
        "context": deepcopy(context),
        "analysis": analysis,
    }


def _submit_live_semantic_job(
    app,
    analysis_frame,
    tracking_payload: dict,
):
    if not _valid_frame(analysis_frame):
        return None

    executor = getattr(app, "_display_f3_heavy_executor", None)
    if executor is None:
        ensure = getattr(app, "_ensure_f3_heavy_executor", None)
        executor = ensure() if callable(ensure) else None
    if executor is None:
        return None

    context_fn = getattr(app, "_display_auto_current_context", None)
    try:
        context = context_fn() if callable(context_fn) else None
    except Exception:
        context = None
    if not isinstance(context, dict):
        return None

    analyzer = getattr(app, "_display_auto_analyzer", None)
    repository = getattr(app, "display_project_repository", None)
    if analyzer is None or getattr(analyzer, "repository", None) is not repository:
        rebuild = getattr(app, "_rebuild_display_auto_analyzer", None)
        if callable(rebuild):
            rebuild()
        analyzer = getattr(app, "_display_auto_analyzer", None)
    if analyzer is None:
        return None

    try:
        visual_rotation = int(
            app._obter_rotacao_visual_display_f3()
        )
    except Exception:
        visual_rotation = 0
    try:
        frame_snapshot = analysis_frame.copy()
    except Exception:
        frame_snapshot = analysis_frame

    generation = int(
        getattr(app, "_display_f3_tracking_job_generation", 0) or 0
    )
    submitted_at_s = time.perf_counter()
    source_age_ms = float(tracking_payload.get("age_ms", 0.0) or 0.0)
    frame_token = tracking_payload.get("frame_token")
    # Estes dois objetos nasceram no MESMO _run_live_tracking_heavy_job.
    # Não substitua por campos do app: camera_frame_atual/geometry podem já
    # pertencer a outro frame quando o job semântico começar.
    raw_snapshot = tracking_payload.get("raw_frame")
    geometry_snapshot = deepcopy(tracking_payload.get("geometry"))

    future = executor.submit(
        lambda: _run_live_semantic_job(
            analyzer,
            frame_snapshot,
            raw_snapshot,
            geometry_snapshot,
            deepcopy(context),
            visual_rotation,
            generation,
            frame_token,
            source_age_ms,
            submitted_at_s,
        ),
        priority=F3HeavyWorkPriority.HIGH,
        name="f3-live-semantic",
        owner=F3_TRACKING_EXECUTOR_OWNER,
        key=F3_SEMANTIC_EXECUTOR_KEY,
        replace_pending=True,
    )
    app._display_f3_semantic_future = future
    return future


def _tracking_result_operationally_fresh(
    payload: dict,
    current_token,
) -> bool:
    """Impede CHECK automático baseado em frame preso vários segundos no worker."""
    try:
        age_ms = float(
            payload.get(
                "age_ms",
                payload.get("elapsed_ms", 0.0),
            )
            or 0.0
        )
    except (TypeError, ValueError):
        return False
    if age_ms > F3_TRACKING_MAX_OPERATIONAL_RESULT_AGE_MS:
        return False

    payload_token = payload.get("frame_token")
    if (
        isinstance(payload_token, tuple)
        and isinstance(current_token, tuple)
        and len(payload_token) >= 2
        and len(current_token) >= 2
        and payload_token[0] == "camera"
        and current_token[0] == "camera"
    ):
        try:
            gap = abs(int(current_token[1]) - int(payload_token[1]))
        except (TypeError, ValueError):
            return False
        if gap > F3_TRACKING_MAX_OPERATIONAL_FRAME_GAP:
            return False
    return True


def instalar_autoridade_final_instancia_rastreamento_f3(app) -> None:
    """Autoridade final na instância real de DesktopProductionApp.

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
        raw_latest = getattr(self, "camera_frame_atual", None)
        use_tracking = bool(
            tracking_enabled(self)
            and not bool(
                getattr(self, "_display_f3_tracking_config_open", False)
            )
        )
        rearm_pending = bool(
            getattr(self, "_display_f3_waiting_empty_rearm", False)
            or getattr(
                self,
                "_display_f3_waiting_new_board_after_empty",
                False,
            )
        )

        # O rearme terminal precisa analisar o suporte vazio no frame RAW.
        # Nesse estado não há motivo para pagar ORB/warp nem manter uma análise
        # de CHECK pendente.
        if use_tracking and rearm_pending:
            self._display_f3_tracking_analysis_pending = False
            self._display_f3_tracking_analysis_frame = None
            self._display_f3_tracking_pending_raw_frame = None
            if _valid_frame(raw_latest):
                self._display_f3_tracking_raw_authority_frame = raw_latest

            previous_frame = getattr(self, "camera_frame_atual", None)
            self._display_f3_skip_auto_analysis_this_preview = False
            self._display_f3_tracking_instance_frame_prepared = True
            try:
                return previous_preview()
            finally:
                self._display_f3_tracking_instance_frame_prepared = False
                self._display_f3_skip_auto_analysis_this_preview = False
                self.camera_frame_atual = (
                    raw_latest if _valid_frame(raw_latest) else previous_frame
                )

        semantic_future = getattr(
            self,
            "_display_f3_semantic_future",
            None,
        )
        ready_semantic = None
        if (
            use_tracking
            and semantic_future is not None
            and semantic_future.done()
        ):
            self._display_f3_semantic_future = None
            try:
                payload = semantic_future.result()
            except Exception as exc:
                payload = None
                self._display_f3_object_tracking_last_status = {
                    "enabled": True,
                    "locked": False,
                    "reason": f"semantic_worker_error:{type(exc).__name__}",
                }

            generation = int(
                getattr(self, "_display_f3_tracking_job_generation", 0) or 0
            )
            if (
                isinstance(payload, dict)
                and int(payload.get("generation", -1)) == generation
                and bool(getattr(self, "display_f3_ativo", False))
            ):
                current_token = None
                token_fn = getattr(self, "_display_auto_frame_token", None)
                if callable(token_fn) and _valid_frame(raw_latest):
                    try:
                        current_token = token_fn(raw_latest)
                    except Exception:
                        current_token = None
                current_context = None
                context_fn = getattr(self, "_display_auto_current_context", None)
                if callable(context_fn):
                    try:
                        current_context = context_fn()
                    except Exception:
                        current_context = None
                payload_context = payload.get("context")
                same_context = bool(
                    isinstance(current_context, dict)
                    and isinstance(payload_context, dict)
                    and str(current_context.get("project_name") or "")
                    == str(payload_context.get("project_name") or "")
                    and str(current_context.get("check_id") or "")
                    == str(payload_context.get("check_id") or "")
                )
                if (
                    same_context
                    and _tracking_result_operationally_fresh(
                        payload,
                        current_token,
                    )
                    and isinstance(payload.get("analysis"), dict)
                    and _valid_frame(payload.get("analysis_frame"))
                ):
                    ready_semantic = payload

        if isinstance(ready_semantic, dict):
            self._display_auto_precomputed_payload = {
                "frame_token": ready_semantic.get("frame_token"),
                "context": deepcopy(ready_semantic.get("context") or {}),
                "analysis": deepcopy(ready_semantic.get("analysis") or {}),
            }
            self._display_auto_analysis_frame_override = ready_semantic.get(
                "analysis_frame"
            )
            self._display_f3_skip_auto_analysis_this_preview = False
            self._display_f3_tracking_instance_frame_prepared = True
            try:
                # Preview usa camera_frame_atual (latest). Somente o motor
                # automático lê _display_auto_analysis_frame_override.
                return previous_preview()
            finally:
                self._display_auto_precomputed_payload = None
                self._display_auto_analysis_frame_override = None
                self._display_f3_tracking_instance_frame_prepared = False
                self._display_f3_skip_auto_analysis_this_preview = False
                if _valid_frame(raw_latest):
                    self._display_f3_tracking_raw_authority_frame = raw_latest

        pending = bool(
            use_tracking
            and getattr(
                self,
                "_display_f3_tracking_analysis_pending",
                False,
            )
        )
        pending_frame = getattr(
            self,
            "_display_f3_tracking_analysis_frame",
            None,
        )
        pending_raw = getattr(
            self,
            "_display_f3_tracking_pending_raw_frame",
            None,
        )

        # Compatibilidade: se uma camada anterior ainda sinalizar análise
        # pendente, o frame analisado é fornecido por override privado. A câmera
        # visível permanece SEMPRE em latest-frame-wins.
        if pending and _valid_frame(pending_frame):
            cycle_raw = pending_raw if _valid_frame(pending_raw) else raw_latest
            if _valid_frame(cycle_raw):
                self._display_f3_tracking_raw_authority_frame = cycle_raw

            self._display_auto_analysis_frame_override = pending_frame
            self._display_f3_skip_auto_analysis_this_preview = False
            self._display_f3_tracking_instance_frame_prepared = True
            try:
                return previous_preview()
            finally:
                self._display_auto_analysis_frame_override = None
                self._display_f3_tracking_analysis_pending = False
                self._display_f3_tracking_analysis_frame = None
                self._display_f3_tracking_pending_raw_frame = None
                self._display_f3_tracking_instance_frame_prepared = False
                self._display_f3_skip_auto_analysis_this_preview = False
                if _valid_frame(raw_latest):
                    self._display_f3_tracking_raw_authority_frame = raw_latest

        analysis_frame = None
        heavy_due = True
        due_fn = getattr(self, "_display_auto_analysis_due_now", None)
        if callable(due_fn):
            try:
                heavy_due = bool(due_fn())
            except Exception:
                heavy_due = True

        # Sem pose anterior, o primeiro frame precisa localizar a placa
        # imediatamente. Depois disso, os frames intermediários só fazem preview.
        if getattr(self, "_display_f3_tracking_result", None) is None:
            heavy_due = True

        if use_tracking and _valid_frame(raw_latest):
            # Autoridade RAW é atualizada em TODOS os frames para que o preview
            # nunca mostre uma imagem antiga.
            self._display_f3_tracking_raw_authority_frame = raw_latest

            tracking_future = getattr(
                self,
                "_display_f3_tracking_future",
                None,
            )
            if tracking_future is not None and tracking_future.done():
                self._display_f3_tracking_future = None
                try:
                    payload = tracking_future.result()
                except Exception as exc:
                    payload = None
                    self._display_f3_object_tracking_last_status = {
                        "enabled": True,
                        "locked": False,
                        "reason": f"tracking_worker_error:{type(exc).__name__}",
                    }

                generation = int(
                    getattr(self, "_display_f3_tracking_job_generation", 0) or 0
                )
                if (
                    isinstance(payload, dict)
                    and int(payload.get("generation", -1)) == generation
                    and bool(getattr(self, "display_f3_ativo", False))
                ):
                    result = payload.get("result")
                    job_raw = payload.get("raw_frame")
                    analysis_frame = payload.get("analysis_frame")
                    self._display_f3_tracking_result = result
                    self._display_f3_tracking_live_geometry = payload.get("geometry")
                    compute_ms = float(payload.get("elapsed_ms", 0.0) or 0.0)
                    self._display_f3_tracking_last_compute_ms = compute_ms

                    # A câmera visível é sempre latest-frame-wins. O frame que
                    # entrou no worker pode ter segundos de idade e jamais volta
                    # a ser autoridade visual quando o job termina.
                    if _valid_frame(raw_latest):
                        self._display_f3_tracking_raw_authority_frame = raw_latest

                    # Decisão operacional não pode usar um frame que ficou preso
                    # no worker por vários segundos. A geometria pode continuar
                    # como hint até o próximo job, mas a análise do CHECK espera
                    # um resultado suficientemente recente.
                    current_token = None
                    token_fn = getattr(self, "_display_auto_frame_token", None)
                    if callable(token_fn) and _valid_frame(raw_latest):
                        try:
                            current_token = token_fn(raw_latest)
                        except Exception:
                            current_token = None
                    operational_fresh = _tracking_result_operationally_fresh(
                        payload,
                        current_token,
                    )

                    if operational_fresh and _valid_frame(analysis_frame):
                        self._display_f3_tracking_analysis_frame = None
                        self._display_f3_tracking_pending_raw_frame = None
                        self._display_f3_tracking_analysis_pending = False
                        if getattr(self, "_display_f3_semantic_future", None) is None:
                            _submit_live_semantic_job(
                                self,
                                analysis_frame,
                                payload,
                            )
                    else:
                        self._display_f3_tracking_analysis_frame = None
                        self._display_f3_tracking_pending_raw_frame = None
                        self._display_f3_tracking_analysis_pending = False

            tracking_future = getattr(
                self,
                "_display_f3_tracking_future",
                None,
            )
            semantic_future = getattr(
                self,
                "_display_f3_semantic_future",
                None,
            )
            if (
                heavy_due
                and tracking_future is None
                and semantic_future is None
                and not bool(
                    getattr(
                        self,
                        "_display_f3_tracking_analysis_pending",
                        False,
                    )
                )
            ):
                _submit_live_tracking_job(self, raw_latest)
        elif use_tracking:
            self._display_f3_tracking_live_geometry = None
            self._display_f3_tracking_analysis_frame = None
            self._display_f3_tracking_pending_raw_frame = None
            self._display_f3_tracking_analysis_pending = False
        else:
            # Tracking desligado mantém literalmente o pipeline anterior.
            self._display_f3_tracking_analysis_frame = None
            self._display_f3_tracking_pending_raw_frame = None
            self._display_f3_tracking_analysis_pending = False

        # Com tracking ligado, este callback é somente preview/rastreamento.
        # A análise automática é liberada exclusivamente no callback pendente
        # acima, evitando empilhar as duas fases pesadas no mesmo evento Tk.
        self._display_f3_skip_auto_analysis_this_preview = bool(use_tracking)

        previous_frame = getattr(self, "camera_frame_atual", None)
        self._display_f3_tracking_instance_frame_prepared = bool(use_tracking)
        try:
            return previous_preview()
        finally:
            self._display_f3_tracking_instance_frame_prepared = False
            self._display_f3_skip_auto_analysis_this_preview = False
            if use_tracking and _valid_frame(raw_latest):
                self.camera_frame_atual = raw_latest
            else:
                self.camera_frame_atual = previous_frame

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

            # Nunca renderize o frame que entrou no worker de tracking. Ele pode
            # ter muitos segundos quando ORB/AKAZE/reacquisition são caros.
            # O argumento recebido vem do camera_frame_atual e é a única
            # autoridade visual da câmera ao vivo.
            source = frame
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
            locked = bool(
                isinstance(geometry, dict)
                and geometry.get("locked")
            )

            # Sem LOCK não existem ROIs móveis válidas. Nesse estado de startup,
            # renderize somente o frame real reduzido: não recarregue projeto,
            # máscaras e contexto semântico a cada repaint enquanto o worker
            # ainda procura a placa.
            if not locked:
                try:
                    from src.platform.display_visual_rotation import (
                        preparar_frame_visual_display,
                    )

                    decorated = preparar_frame_visual_display(
                        source,
                        int(visual_rotation or 0) % 360,
                    )
                    decorated = _fit_live_preview_before_overlay(
                        decorated,
                        self_window,
                    )
                except Exception:
                    decorated = source
            else:
                # Com LOCK, o preview operacional usa a máscara clássica:
                # geometria canônica móvel e verde somente onde existe luz.
                try:
                    from src.platform.display_f3_preview_clarity_fix import (
                        _effective_phase_mask_ids_for_current_check,
                        _mask_snapshot_for_current_check,
                        _project_preview_context,
                        renderizar_preview_claro_display_f3,
                    )
                    from src.platform.display_visual_rotation import (
                        preparar_frame_visual_display,
                    )

                    visual = preparar_frame_visual_display(
                        source,
                        int(visual_rotation or 0) % 360,
                    )
                    visual = _fit_live_preview_before_overlay(
                        visual,
                        self_window,
                    )
                    semantic_context = _project_preview_context(
                        self_window,
                        int(visual_rotation or 0) % 360,
                    )
                    if isinstance(semantic_context, dict):
                        classifications, failed_mask_ids = _mask_snapshot_for_current_check(
                            self_window,
                            project_name=str(semantic_context.get("project_name") or ""),
                            check_id=str(semantic_context.get("check_id") or ""),
                            base=semantic_context,
                        )
                        semantic_context = dict(semantic_context)
                        project_name = str(
                            semantic_context.get("project_name") or ""
                        )
                        check_id = str(
                            semantic_context.get("check_id") or ""
                        )
                        confirmed_failed_ids, validating_ids = (
                            _effective_phase_mask_ids_for_current_check(
                                self_window,
                                project_name=project_name,
                                check_id=check_id,
                            )
                        )
                        if not confirmed_failed_ids and not validating_ids:
                            if bool(semantic_context.get("intermittent", False)):
                                validating_ids = set(failed_mask_ids)
                            else:
                                confirmed_failed_ids = set(failed_mask_ids)

                        semantic_context["classifications"] = classifications
                        semantic_context["effective_classifications"] = dict(
                            classifications
                        )
                        semantic_context["failed_mask_ids"] = tuple(
                            sorted(failed_mask_ids)
                        )
                        semantic_context["effective_failed_mask_ids"] = tuple(
                            sorted(failed_mask_ids)
                        )
                        semantic_context[
                            "effective_confirmed_failed_mask_ids"
                        ] = tuple(sorted(confirmed_failed_ids))
                        semantic_context[
                            "effective_validating_mask_ids"
                        ] = tuple(sorted(validating_ids))
                        semantic_context["ui_mask_authority"] = (
                            "effective_mask_results_v1"
                        )
                        semantic_context["has_any_on"] = any(
                            str(value).strip().lower() == "on"
                            for value in classifications.values()
                        )
                        power = getattr(
                            app,
                            "_display_f3_power_authority_status",
                            None,
                        )
                        energy = power.get("energy") if isinstance(power, dict) else None
                        semantic_context["power_confirmed"] = bool(
                            isinstance(energy, dict)
                            and energy.get("powered_confirmed") is True
                        )
                        semantic_context["power_off_confirmed"] = bool(
                            isinstance(energy, dict)
                            and energy.get("off_confirmed") is True
                        )
                        semantic_context["energy_state"] = (
                            str(energy.get("energy_state") or "").strip().lower()
                            if isinstance(energy, dict)
                            else ""
                        )
                        try:
                            self_window.set_display_readout_context(
                                semantic_context
                            )
                        except (AttributeError, TypeError):
                            pass
                        decorated = renderizar_preview_claro_display_f3(
                            visual,
                            semantic_context,
                        )
                    else:
                        try:
                            self_window.set_display_readout_context(None)
                        except (AttributeError, TypeError):
                            pass
                        decorated = _draw_tracking_geometry_visual(
                            source,
                            geometry,
                            visual_rotation,
                        )
                except Exception:
                    decorated = _draw_tracking_geometry_visual(
                        source,
                        geometry,
                        visual_rotation,
                    )

            status = getattr(
                app,
                "_display_f3_object_tracking_last_status",
                {},
            )
            if locked:
                if bool(status.get("evidence_current", False)):
                    legend = (
                        "LOCK ESTÁVEL • MÁSCARA CLÁSSICA • "
                        "VERDE = LUZ IDENTIFICADA"
                    )
                    color = "#E2E8F0"
                else:
                    legend = (
                        "LOCK MANTIDO • confirmando novamente a placa • "
                        "ROIs preservadas"
                    )
                    color = "#FDE68A"
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
            preview_h, preview_w = decorated.shape[:2]
            rendered = self_window.update_preview(decorated, leds=())
            if rendered:
                try:
                    raw_h, raw_w = source.shape[:2]
                    rotation = int(visual_rotation or 0) % 360
                    camera_w, camera_h = (
                        (raw_h, raw_w)
                        if rotation in (90, 270)
                        else (raw_w, raw_h)
                    )
                    self_window.show_camera_ready(
                        int(camera_w),
                        int(camera_h),
                        rotation,
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
                if (
                    isinstance(status, dict)
                    and bool(status.get("locked"))
                    and not bool(status.get("evidence_current", False))
                ):
                    try:
                        self._display_auto_set_preview_status(
                            "RASTREAMENTO F3 • LOCK MANTIDO • confirmando evidência óptica",
                            "#FDE68A",
                        )
                    except Exception:
                        pass
                    try:
                        self._reset_display_auto_stability(transition=False)
                    except Exception:
                        pass
                    return None

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
            # A autoridade final aplicada diretamente à instância já preparou
            # frame de análise + geometria móvel. Não rastreie uma segunda vez.
            if bool(
                getattr(
                    self,
                    "_display_f3_tracking_instance_frame_prepared",
                    False,
                )
            ):
                return preview_previous(self)

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
            try:
                return preview_previous(self)
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
