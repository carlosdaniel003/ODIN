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
from src.platform.display_f3_h1_registration import (
    register_h1_with_filter_homography,
)
from src.platform.display_f3_mask_editor_reference import (
    DisplayMaskEditorReferenceStore,
)
from src.platform.display_f3_neural_tracking import (
    F3NeuralPoseDetector,
    canonical_pose_anchors,
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
# CHECK intermitente é um evento temporal: o frame ON precisa continuar válido
# enquanto o worker termina, mesmo que a câmera já esteja mostrando a fase OFF
# seguinte. O valor acompanha o hold de energia intermitente do runtime (2,5 s)
# e continua muito abaixo de uma mudança operacional longa/indefinida.
F3_TRACKING_INTERMITTENT_SNAPSHOT_MAX_AGE_MS = 2500.0
F3_TRACKING_INTERMITTENT_SNAPSHOT_MAX_FRAME_GAP = 80

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

# Segundo estágio do tracking híbrido: com lock estrutural, três segmentos ON
# identificados pelo próprio ID já bastam para corrigir o encaixe fino. Isso não
# reduz quorum de OK/NG; altera somente a geometria das 28 ROIs.
F3_TRACKING_LUMINOUS_FINE_MIN_ANCHORS = 3
F3_TRACKING_LUMINOUS_FINE_MIN_GAIN_PX = 0.45
F3_TRACKING_LUMINOUS_FINE_ALREADY_ALIGNED_PX = 1.25
F3_TRACKING_LUMINOUS_FINE_SIMILARITY_MIN_SPAN_FRACTION = 0.18
# Rotação/escala fina só são confiáveis quando os anchors cobrem uma porção
# significativa do display nos dois eixos. Um grupo concentrado em um dígito
# pode corrigir translação, mas não recebe autoridade para entortar as 28 ROIs.
F3_TRACKING_LUMINOUS_FINE_SIMILARITY_MIN_X_SPAN_FRACTION = 0.30
F3_TRACKING_LUMINOUS_FINE_SIMILARITY_MIN_Y_SPAN_FRACTION = 0.18
F3_TRACKING_LUMINOUS_FINE_SUPPORT_PADDING_FRACTION = 0.025
F3_TRACKING_LUMINOUS_FINE_SUPPORT_PADDING_MAX_PX = 18
# O padding acima é apenas região de aquisição. Depois do fit, a pose só é
# publicada se a emissão realmente cair dentro do núcleo geométrico exato das
# máscaras reprojetadas, sem dilatação.
F3_TRACKING_LUMINOUS_FINE_MIN_CORE_HOT_PIXELS = 6
F3_TRACKING_LUMINOUS_FINE_MIN_CORE_HOT_FRACTION = 0.08
F3_TRACKING_LUMINOUS_FINE_MIN_CORE_MATCH_RATIO = 0.55
# Quando os anchors não cobrem área suficiente para autorizar rotação/escala,
# somente um consenso de vetores de deslocamento pode mover o grid por
# translação. Isso elimina landmarks vizinhos que apontam em direções
# incompatíveis com o restante do display.
F3_TRACKING_LUMINOUS_FINE_TRANSLATION_CONSENSUS_PX = 15.0
# Reflexo/sujeira no filtro escuro não pode virar landmark geométrico. Em
# 1920x1080 os segmentos reais observados ficam tipicamente abaixo de ~28px de
# erro local antes do refinamento; acima disso a evidência já não pertence à
# máscara projetada com confiança suficiente.
F3_TRACKING_LUMINOUS_FINE_MAX_ANCHOR_ERROR_PX = 30.0
# Mesmo quando um ajuste melhora a pose grosseira, erro residual alto ainda
# significa que o modelo 88:88 não encaixou de verdade. Não publique geometria
# "menos ruim" como se fosse alinhamento válido.
F3_TRACKING_LUMINOUS_FINE_MAX_MEDIAN_ERROR_PX = 12.0
# Muitos componentes brilhantes em relação aos ON esperados caracterizam cena
# contaminada por reflexos/sujeira. Isso pode continuar no DEBUG, mas não prova
# emissão física por si só.
F3_TRACKING_LUMINOUS_MAX_COMPONENT_RATIO_FOR_ENERGY = 3.0

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


def _as_planar_transform(matrix):
    """Normaliza affine 2x3 ou homografia 3x3 sem mudar sua natureza."""
    try:
        value = np.asarray(matrix, dtype=np.float32)
    except Exception:
        return None
    if value.size == 6:
        value = value.reshape(2, 3)
    elif value.size == 9:
        value = value.reshape(3, 3)
    else:
        return None
    if not np.all(np.isfinite(value)):
        return None
    return value


def _planar_to_homography(matrix) -> np.ndarray | None:
    value = _as_planar_transform(matrix)
    if value is None:
        return None
    if value.shape == (3, 3):
        return value.astype(np.float32)
    return np.asarray(
        [
            [value[0, 0], value[0, 1], value[0, 2]],
            [value[1, 0], value[1, 1], value[1, 2]],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )


def _invert_planar_transform(matrix):
    value = _as_planar_transform(matrix)
    if value is None:
        return None
    try:
        if value.shape == (2, 3):
            return cv2.invertAffineTransform(value).astype(np.float32)
        inverse = np.linalg.inv(value).astype(np.float32)
    except Exception:
        return None
    if not np.all(np.isfinite(inverse)):
        return None
    return inverse


def _compose_planar_transform(first, second) -> np.ndarray | None:
    """Compõe FIRST(SECOND(p)); preserva homografia quando qualquer lado é 3x3."""
    first_h = _planar_to_homography(first)
    second_h = _planar_to_homography(second)
    if first_h is None or second_h is None:
        return None
    result = first_h @ second_h
    if not np.all(np.isfinite(result)):
        return None
    if (
        _as_planar_transform(first).shape == (2, 3)
        and _as_planar_transform(second).shape == (2, 3)
    ):
        return result[:2, :].astype(np.float32)
    return result.astype(np.float32)


def transform_points(points, matrix) -> list[list[float]]:
    source = _normalize_points(points, minimum=1)
    if not source:
        return []
    transform = _as_planar_transform(matrix)
    if transform is None:
        return []
    try:
        values = np.asarray(source, dtype=np.float32).reshape(-1, 1, 2)
        if transform.shape == (3, 3):
            transformed = cv2.perspectiveTransform(
                values,
                transform,
            ).reshape(-1, 2)
        else:
            transformed = cv2.transform(
                values,
                transform,
            ).reshape(-1, 2)
        if not np.all(np.isfinite(transformed)):
            return []
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

    transform = _as_planar_transform(matrix)
    if transform is None:
        return None

    if kind == "circle":
        try:
            cx = float(source.get("cx", 0))
            cy = float(source.get("cy", 0))
            radius = max(1.0, float(source.get("radius", 1)))
        except (TypeError, ValueError):
            return None
        probes = transform_points(
            [
                [cx, cy],
                [cx + radius, cy],
                [cx, cy + radius],
            ],
            transform,
        )
        if len(probes) != 3:
            return None
        center = np.asarray(probes[0], dtype=np.float32)
        local_radius = float(
            0.5
            * (
                np.linalg.norm(np.asarray(probes[1]) - center)
                + np.linalg.norm(np.asarray(probes[2]) - center)
            )
        )
        return {
            "id": mask_id,
            "type": "circle",
            "cx": float(center[0]),
            "cy": float(center[1]),
            "radius": max(1.0, local_radius),
        }

    points = pontos_mascara_display(source)
    transformed = transform_points(points, transform)
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


def _projective_filter_pose_from_affine_hint(
    current_board,
    canonical_board,
    hint_matrix,
) -> dict | None:
    """Converte a correspondência já escolhida pela CNN em homografia exata.

    A CNN/affine escolhe QUAL canto corresponde a qual canto. Depois disso os
    quatro cantos físicos do filtro são autoridade geométrica para a perspectiva.
    """
    match = _best_board_correspondence(
        current_board,
        canonical_board,
        hint_matrix=hint_matrix,
    )
    if match is None:
        return None
    _error, current_ordered, canonical_ordered = match
    try:
        current = np.asarray(
            current_ordered,
            dtype=np.float32,
        ).reshape(4, 2)
        canonical = np.asarray(
            canonical_ordered,
            dtype=np.float32,
        ).reshape(4, 2)
        homography = cv2.getPerspectiveTransform(
            current,
            canonical,
        ).astype(np.float32)
        projected = cv2.perspectiveTransform(
            current.reshape(-1, 1, 2),
            homography,
        ).reshape(-1, 2)
    except Exception:
        return None
    if not np.all(np.isfinite(homography)):
        return None
    errors = np.linalg.norm(projected - canonical, axis=1)
    return {
        "homography": homography,
        "current_points": current.tolist(),
        "canonical_points": canonical.tolist(),
        "mean_reprojection_px": float(np.mean(errors)),
        "max_reprojection_px": float(np.max(errors)),
    }


def _affine_approximation_from_projective(
    current_to_canonical,
    canonical_board,
) -> np.ndarray | None:
    """Produz affine apenas para compatibilidade/telemetria.

    Não aplica o gate de reprojeção da pose produtiva: uma homografia válida é
    naturalmente impossível de reproduzir exatamente com similarity 2x3.
    """
    inverse = _invert_planar_transform(current_to_canonical)
    board = _normalize_points(canonical_board, minimum=4)
    if inverse is None or len(board) != 4:
        return None
    current = transform_points(board, inverse)
    if len(current) != 4:
        return None
    try:
        matrix, _inliers = cv2.estimateAffinePartial2D(
            np.asarray(current, dtype=np.float32).reshape(-1, 1, 2),
            np.asarray(board, dtype=np.float32).reshape(-1, 1, 2),
            method=cv2.LMEDS,
            refineIters=20,
        )
    except Exception:
        return None
    if matrix is None:
        return None
    matrix = np.asarray(matrix, dtype=np.float32).reshape(2, 3)
    if not np.all(np.isfinite(matrix)):
        return None
    scale = affine_scale(matrix)
    if not (F3_TRACKING_MIN_SCALE <= scale <= F3_TRACKING_MAX_SCALE):
        return None
    return matrix


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



def _ordered_projective_quad(points) -> list[list[float]]:
    """Ordena um quadrilátero real sem retangularizar sua perspectiva."""
    normalized = _normalize_points(points, minimum=4)
    if len(normalized) != 4:
        return []
    ordered = canonical_pose_anchors(normalized)
    if ordered is None:
        return []
    try:
        contour = np.asarray(
            ordered,
            dtype=np.float32,
        ).reshape(-1, 1, 2)
        if not cv2.isContourConvex(contour):
            return []
        if abs(float(cv2.contourArea(contour))) <= 4.0:
            return []
        points_array = contour.reshape(-1, 2)
        edges = [
            float(
                np.linalg.norm(
                    points_array[(index + 1) % 4] - points_array[index]
                )
            )
            for index in range(4)
        ]
        if min(edges) <= 2.0:
            return []
    except Exception:
        return []
    return [
        [float(point[0]), float(point[1])]
        for point in np.asarray(ordered, dtype=np.float32).reshape(-1, 2)
    ]


def _quad_from_points(points) -> list[list[float]]:
    """Obtém quadrilátero preservando perspectiva quando já há 4 cantos.

    D-071: quatro cantos físicos não podem passar por minAreaRect antes da
    homografia. Contornos com mais vértices continuam usando o retângulo
    orientado apenas como fallback/medida estrutural.
    """
    normalized = _normalize_points(points, minimum=3)
    if len(normalized) < 3:
        return []

    if len(normalized) == 4:
        exact = _ordered_projective_quad(normalized)
        if exact:
            return exact

    try:
        rect = cv2.minAreaRect(
            np.asarray(normalized, dtype=np.float32).reshape(-1, 1, 2)
        )
        box = cv2.boxPoints(rect)
    except Exception:
        return []
    return _ordered_projective_quad(
        np.asarray(box, dtype=np.float32).reshape(-1, 2).tolist()
    )


def _perspective_quad_from_contour(contour) -> list[list[float]]:
    """Extrai os quatro cantos perspectivados do contorno físico do filtro.

    O convex hull remove recortes locais causados por LEDs/reflexos, enquanto
    approxPolyDP preserva as inclinações reais das quatro bordas. Se não
    houver um quadrilátero convexo confiável, o chamador pode usar
    minAreaRect como fallback não-projectivo.
    """
    try:
        data = np.asarray(contour, dtype=np.float32).reshape(-1, 1, 2)
        if len(data) < 4:
            return []
        hull = cv2.convexHull(data)
        perimeter = float(cv2.arcLength(hull, True))
        hull_area = abs(float(cv2.contourArea(hull)))
    except Exception:
        return []
    if perimeter <= 1.0 or hull_area <= 4.0:
        return []

    best = None
    for epsilon_fraction in (
        0.004,
        0.006,
        0.008,
        0.012,
        0.016,
        0.022,
        0.030,
        0.040,
        0.050,
    ):
        try:
            approx = cv2.approxPolyDP(
                hull,
                perimeter * float(epsilon_fraction),
                True,
            )
        except Exception:
            continue
        if len(approx) != 4:
            continue
        ordered = _ordered_projective_quad(
            np.asarray(approx, dtype=np.float32).reshape(-1, 2).tolist()
        )
        if len(ordered) != 4:
            continue
        try:
            quad_area = abs(
                float(
                    cv2.contourArea(
                        np.asarray(
                            ordered,
                            dtype=np.float32,
                        ).reshape(-1, 1, 2)
                    )
                )
            )
        except Exception:
            continue
        coverage = quad_area / max(1.0, hull_area)
        if coverage < F3_TRACKING_FILTER_MIN_RECTANGULARITY:
            continue
        rank = (float(coverage), -float(epsilon_fraction))
        if best is None or rank > best[0]:
            best = (rank, ordered)

    return deepcopy(best[1]) if best is not None else []


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


def _neural_filter_board_matrix_candidates(
    current_board,
    canonical_board,
) -> tuple[list[np.ndarray], str]:
    """Hipóteses de orientação para o snap neural, sem afrouxar o tracking geral.

    O detector do filtro pode devolver um trapézio levemente perspectivado.
    Nessa situação o gerador estrutural estrito pode produzir zero afinidades
    parciais, embora o filtro e a predição neural sejam válidos. Para D-069,
    somente o snap neural recebe um fallback LMEDS mais tolerante; a própria
    distância até os quatro anchors previstos pela CNN continua sendo o gate.
    """
    strict = _filter_board_matrix_candidates(
        current_board,
        canonical_board,
    )
    if strict:
        return strict, "strict_similarity"

    current = _quad_from_points(current_board)
    canonical = _quad_from_points(canonical_board)
    if len(current) != 4 or len(canonical) != 4:
        return [], "invalid_quad"

    cur = np.asarray(current, dtype=np.float32)
    can = np.asarray(canonical, dtype=np.float32)
    matrices: list[np.ndarray] = []
    signatures: set[tuple] = set()

    for reverse in (False, True):
        ordered = cur[::-1].copy() if reverse else cur.copy()
        for shift in range(4):
            candidate = np.roll(ordered, shift, axis=0)
            try:
                matrix, _inliers = cv2.estimateAffinePartial2D(
                    candidate.reshape(-1, 1, 2),
                    can.reshape(-1, 1, 2),
                    method=cv2.LMEDS,
                    refineIters=20,
                )
            except Exception:
                matrix = None
            if matrix is None:
                continue

            matrix = np.asarray(matrix, dtype=np.float32).reshape(2, 3)
            if not np.all(np.isfinite(matrix)):
                continue
            scale = affine_scale(matrix)
            if not (
                F3_TRACKING_REFERENCE_SCALE_MIN
                <= scale
                <= F3_TRACKING_REFERENCE_SCALE_MAX
            ):
                continue

            key = tuple(matrix.round(4).reshape(-1).tolist())
            if key in signatures:
                continue
            signatures.add(key)
            matrices.append(matrix)

    return matrices, (
        "relaxed_similarity_lmeds"
        if matrices
        else "relaxed_similarity_unavailable"
    )


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
        contour_quad = _perspective_quad_from_contour(contour)
        if len(contour_quad) == 4:
            geometry_points = np.asarray(
                contour_quad,
                dtype=np.float32,
            ).reshape(-1, 2)
            corner_source = "contour_quad"
        else:
            geometry_points = np.asarray(
                _quad_from_points(box.tolist()),
                dtype=np.float32,
            ).reshape(-1, 2)
            corner_source = "min_area_rect_fallback"
        if len(geometry_points) != 4:
            continue

        region = np.zeros_like(gray, dtype=np.uint8)
        cv2.fillConvexPoly(
            region,
            np.rint(geometry_points).astype(np.int32),
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
            for point in geometry_points
        ]
        rect_points = [
            [float(point[0]) * inv_scale, float(point[1]) * inv_scale]
            for point in box
        ]
        candidates.append(
            {
                "points": points,
                "rect_points": rect_points,
                "corner_source": corner_source,
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


def experiment_h1_filter_registration(
    reference_frame,
    reference_filter_points,
    current_frame,
    *,
    canonical_resolution=None,
    reference_masks=None,
    expected_on_mask_ids=None,
    current_filter_points=None,
    current_filter_source: str = "",
) -> dict:
    """D-025: avalia homografia + registro H1 sem alterar o runtime produtivo.

    Quando o F3 já possui LOCK estrutural, a geometria do filtro publicada pelo
    proprietário canônico de tracking é reutilizada diretamente. O detector
    escuro permanece apenas como fallback diagnóstico quando essa geometria não
    foi fornecida.
    """
    if not _valid_frame(reference_frame) or not _valid_frame(current_frame):
        return {"available": False, "reason": "invalid_frame"}

    if canonical_resolution is None:
        canonical_resolution = (
            int(reference_frame.shape[1]),
            int(reference_frame.shape[0]),
        )
    resolution = normalizar_resolucao_display(canonical_resolution)
    if resolution is None:
        return {"available": False, "reason": "master_resolution_missing"}

    supplied_filter = _normalize_points(
        current_filter_points,
        minimum=4,
    )
    if len(supplied_filter) >= 4:
        locator_source = str(
            current_filter_source or "tracking_structural_lock"
        )
        candidates = [
            {
                "points": supplied_filter,
                "score": 1.0,
                "source": locator_source,
                "prelocked": True,
            }
        ]
    else:
        locator_source = "dark_filter_detector"
        candidates = _detect_dark_filter_candidates(
            current_frame,
            reference_filter_points,
            resolution,
        )

    if not candidates:
        return {
            "available": False,
            "reason": "filter_not_found",
            "filter_candidate_count": 0,
            "filter_locator_source": locator_source,
            "attempts": [],
        }

    attempts = []
    best = None
    best_score = float("-inf")
    best_filter_source = ""
    for candidate in candidates:
        result = register_h1_with_filter_homography(
            reference_frame,
            reference_filter_points,
            current_frame,
            candidate.get("points") or [],
            reference_masks=reference_masks,
            expected_on_mask_ids=expected_on_mask_ids,
        )
        metrics_after = (
            result.get("metrics_after")
            if isinstance(result.get("metrics_after"), dict)
            else {}
        )
        mask_after = (
            result.get("mask_overlap_after")
            if isinstance(result.get("mask_overlap_after"), dict)
            else {}
        )
        score = (
            float(result.get("ecc_score", 0.0) or 0.0) * 2.0
            + float(metrics_after.get("dice", 0.0) or 0.0)
            + float(metrics_after.get("correlation", 0.0) or 0.0)
            + float(mask_after.get("emission_inside_fraction", 0.0) or 0.0)
        )
        attempts.append(
            {
                "filter_score": round(
                    float(candidate.get("score", 0.0) or 0.0),
                    6,
                ),
                "filter_source": str(
                    candidate.get("source") or "dark_filter_detector"
                ),
                "available": bool(result.get("available")),
                "reason": str(result.get("reason") or ""),
                "quality_ok": bool(result.get("quality_ok")),
                "refinement_applied": bool(
                    result.get("refinement_applied")
                ),
                "refinement_reason": str(
                    result.get("refinement_reason") or ""
                ),
                "selected_alignment_source": str(
                    result.get("selected_alignment_source") or ""
                ),
                "ecc_score": result.get("ecc_score"),
                "rotation_deg": result.get("rotation_deg"),
                "center_shift_px": result.get("center_shift_px"),
                "metrics_before": deepcopy(
                    result.get("metrics_before") or {}
                ),
                "metrics_after": deepcopy(
                    result.get("metrics_after") or {}
                ),
                "mask_overlap_before": deepcopy(
                    result.get("mask_overlap_before") or {}
                ),
                "mask_overlap_after": deepcopy(
                    result.get("mask_overlap_after") or {}
                ),
            }
        )
        if bool(result.get("available")) and score > best_score:
            best = result
            best_score = score
            best_filter_source = str(
                candidate.get("source") or locator_source
            )

    if best is None:
        registration_reason = next(
            (
                str(item.get("reason") or "")
                for item in attempts
                if str(item.get("reason") or "")
            ),
            "h1_registration_not_converged",
        )
        return {
            "available": False,
            "reason": "h1_registration_not_converged",
            "registration_reason": registration_reason,
            "filter_candidate_count": int(len(candidates)),
            "filter_locator_source": locator_source,
            "attempts": attempts,
        }

    registration_reason = str(best.get("reason") or "")
    payload = dict(best)
    payload.update(
        {
            "available": True,
            "reason": "h1_filter_registration_ready",
            "registration_reason": registration_reason,
            "filter_candidate_count": int(len(candidates)),
            "filter_locator_source": str(
                best_filter_source or locator_source
            ),
            "attempts": attempts,
            "experimental": True,
            "production_authority": False,
        }
    )
    return payload


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


def _hot_pixels_inside_projected_mask(
    hot_x,
    hot_y,
    *,
    projected_mask,
    crop_origin,
    crop_shape,
    padding_px: int,
):
    """Retorna quais pixels quentes pertencem à vizinhança da máscara prevista."""
    if not isinstance(projected_mask, dict):
        return None
    try:
        crop_h, crop_w = int(crop_shape[0]), int(crop_shape[1])
        x1, y1 = int(crop_origin[0]), int(crop_origin[1])
    except Exception:
        return None
    if crop_h <= 0 or crop_w <= 0:
        return None

    support = np.zeros((crop_h, crop_w), dtype=np.uint8)
    kind = str(projected_mask.get("type") or "").lower()
    try:
        if kind == "circle":
            cx = int(round(float(projected_mask.get("cx", 0)) - x1))
            cy = int(round(float(projected_mask.get("cy", 0)) - y1))
            radius = max(1, int(round(float(projected_mask.get("radius", 1)))))
            cv2.circle(
                support,
                (cx, cy),
                radius,
                255,
                -1,
                lineType=cv2.LINE_AA,
            )
        else:
            points = pontos_mascara_display(projected_mask)
            if len(points) < 3:
                return None
            polygon = np.rint(
                np.asarray(
                    [
                        [float(px) - x1, float(py) - y1]
                        for px, py in points
                    ],
                    dtype=np.float32,
                )
            ).astype(np.int32)
            cv2.fillPoly(
                support,
                [polygon],
                255,
                lineType=cv2.LINE_AA,
            )
    except Exception:
        return None

    padding = max(0, int(padding_px))
    if padding > 0:
        kernel_size = padding * 2 + 1
        support = cv2.dilate(
            support,
            np.ones((kernel_size, kernel_size), dtype=np.uint8),
            iterations=1,
        )

    try:
        return support[
            np.asarray(hot_y, dtype=np.int32),
            np.asarray(hot_x, dtype=np.int32),
        ] > 0
    except Exception:
        return None


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
        fit_to_current = _invert_planar_transform(current_to_fit)
        if fit_to_current is None:
            raise ValueError("current_to_fit_invalid")
        predicted = np.asarray(
            transform_points(
                [row["center"] for row in expected_rows],
                fit_to_current,
            ),
            dtype=np.float32,
        ).reshape(-1, 2)
        projected_masks = [
            transform_mask(row.get("mask"), fit_to_current)
            if isinstance(row.get("mask"), dict)
            else None
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
    support_padding = min(
        F3_TRACKING_LUMINOUS_FINE_SUPPORT_PADDING_MAX_PX,
        max(
            4,
            int(round(
                filter_diagonal
                * F3_TRACKING_LUMINOUS_FINE_SUPPORT_PADDING_FRACTION
            )),
        ),
    )

    centers: list[list[float]] = []
    details: list[dict] = []
    for expected_index, row in enumerate(expected_rows):
        selected = (
            (nearest_expected == int(expected_index))
            & (nearest_distance <= float(assignment_gate))
        )
        support_used = False
        support_flags = _hot_pixels_inside_projected_mask(
            hot_x,
            hot_y,
            projected_mask=projected_masks[expected_index],
            crop_origin=(x1, y1),
            crop_shape=crop.shape[:2],
            padding_px=support_padding,
        )
        if support_flags is not None:
            shape_selected = selected & support_flags
            if int(np.count_nonzero(shape_selected)) >= (
                F3_TRACKING_LUMINOUS_LOCAL_MIN_HOT_PIXELS
            ):
                selected = shape_selected
                support_used = True

        selected_indices = np.flatnonzero(selected)
        if len(selected_indices) < F3_TRACKING_LUMINOUS_LOCAL_MIN_HOT_PIXELS:
            continue

        # Se existe geometria real da máscara projetada, o landmark precisa
        # nascer dentro dela (com o padding controlado acima). O antigo fallback
        # Voronoi aceitava reflexos distantes e foi a origem de máscaras tortas
        # sobre display desligado.
        projected_mask_available = isinstance(
            projected_masks[expected_index],
            dict,
        )
        if projected_mask_available and not support_used:
            continue

        median_prediction_error = float(
            np.median(nearest_distance[selected_indices])
        )
        if (
            not math.isfinite(median_prediction_error)
            or median_prediction_error
            > F3_TRACKING_LUMINOUS_FINE_MAX_ANCHOR_ERROR_PX
        ):
            continue

        cluster = hot_points[selected_indices]
        # A mediana é deliberadamente usada em vez do centroide do blob:
        # reflexos/blooming nas bordas deslocam menos a posição robusta.
        center = [
            float(np.median(cluster[:, 0])),
            float(np.median(cluster[:, 1])),
        ]
        centers.append(center)
        center_residual_px = float(
            np.linalg.norm(
                np.asarray(center, dtype=np.float32)
                - predicted[expected_index]
            )
        )
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
                "hot_pixel_count": int(len(selected_indices)),
                "center_residual_px": round(center_residual_px, 3),
                "median_prediction_error_px": round(
                    median_prediction_error,
                    3,
                ),
                "projected_mask_support": bool(support_used),
                "support_padding_px": int(support_padding),
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


def _base_core_alignment_residual(
    landmark_details,
    validated_mask_ids,
) -> dict:
    """Separa 'há luz dentro da ROI' de 'a ROI está geometricamente centrada'."""
    validated = {
        str(mask_id)
        for mask_id in (validated_mask_ids or ())
        if str(mask_id)
    }
    errors: list[float] = []
    by_mask: dict[str, float] = {}

    for detail in landmark_details or ():
        if not isinstance(detail, dict):
            continue
        mask_id = str(detail.get("mask_id") or "")
        if not mask_id or mask_id not in validated:
            continue

        error = detail.get("center_residual_px")
        if error is None:
            center = detail.get("center")
            predicted = detail.get("predicted_center")
            if (
                isinstance(center, (list, tuple))
                and len(center) >= 2
                and isinstance(predicted, (list, tuple))
                and len(predicted) >= 2
            ):
                try:
                    error = float(
                        np.linalg.norm(
                            np.asarray(center[:2], dtype=np.float32)
                            - np.asarray(predicted[:2], dtype=np.float32)
                        )
                    )
                except Exception:
                    error = None
        try:
            error = float(error)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(error):
            continue
        errors.append(error)
        by_mask[mask_id] = error

    count = len(errors)
    median_error = (
        float(np.median(np.asarray(errors, dtype=np.float32)))
        if errors
        else float("inf")
    )
    max_error = max(errors) if errors else float("inf")
    limit = float(F3_TRACKING_LUMINOUS_FINE_MAX_MEDIAN_ERROR_PX)
    precise = bool(
        count >= F3_TRACKING_LUMINOUS_FINE_MIN_ANCHORS
        and median_error <= limit
        and max_error <= limit
    )
    return {
        "available": bool(
            count >= F3_TRACKING_LUMINOUS_FINE_MIN_ANCHORS
        ),
        "precise": precise,
        "anchor_count": int(count),
        "required_anchor_count": int(
            F3_TRACKING_LUMINOUS_FINE_MIN_ANCHORS
        ),
        "median_error_px": (
            round(median_error, 3) if math.isfinite(median_error) else None
        ),
        "max_error_px": (
            round(max_error, 3) if math.isfinite(max_error) else None
        ),
        "maximum_allowed_px": limit,
        "errors_by_mask": {
            key: round(float(value), 3)
            for key, value in by_mask.items()
        },
    }


def _validate_luminous_pose_core_support(
    frame,
    expected_rows,
    current_to_fit,
    threshold_v,
) -> dict:
    """Valida a pose candidata contra a área exata das máscaras ON.

    A busca local pode usar padding para encontrar um segmento deslocado em
    relação à pose estrutural. Esse padding nunca vira prova de alinhamento:
    depois do fit, a emissão precisa ocupar o núcleo da própria máscara
    reprojetada. Isso rejeita luz de segmento vizinho e reflexo aceitos apenas
    por proximidade.
    """
    if not _valid_frame(frame):
        return {
            "available": False,
            "enforced": False,
            "reason": "invalid_frame",
            "geometry_count": 0,
            "validated_count": 0,
            "required_count": 0,
            "validated_mask_ids": [],
            "details": [],
        }
    try:
        threshold = float(threshold_v)
        fit_to_current = _invert_planar_transform(current_to_fit)
        if fit_to_current is None:
            raise ValueError("current_to_fit_invalid")
        value = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[:, :, 2]
    except (TypeError, ValueError, cv2.error):
        return {
            "available": False,
            "enforced": False,
            "reason": "core_validation_prepare_failed",
            "geometry_count": 0,
            "validated_count": 0,
            "required_count": 0,
            "validated_mask_ids": [],
            "details": [],
        }
    if not math.isfinite(threshold):
        return {
            "available": False,
            "enforced": False,
            "reason": "core_validation_threshold_invalid",
            "geometry_count": 0,
            "validated_count": 0,
            "required_count": 0,
            "validated_mask_ids": [],
            "details": [],
        }

    frame_h, frame_w = value.shape[:2]
    geometry_count = 0
    validated_ids: list[str] = []
    details: list[dict] = []

    for row in expected_rows or ():
        if not isinstance(row, dict) or not isinstance(row.get("mask"), dict):
            continue
        projected = transform_mask(row.get("mask"), fit_to_current)
        if not isinstance(projected, dict):
            continue
        try:
            bx1, by1, bx2, by2 = bbox_mascara_display(projected)
            x1 = max(0, int(math.floor(float(bx1))) - 1)
            y1 = max(0, int(math.floor(float(by1))) - 1)
            x2 = min(frame_w, int(math.ceil(float(bx2))) + 2)
            y2 = min(frame_h, int(math.ceil(float(by2))) + 2)
        except (TypeError, ValueError):
            continue
        if x2 <= x1 or y2 <= y1:
            continue

        geometry_count += 1
        crop_value = value[y1:y2, x1:x2]
        hot_y, hot_x = np.nonzero(
            crop_value.astype(np.float32) >= threshold
        )
        support_flags = _hot_pixels_inside_projected_mask(
            hot_x,
            hot_y,
            projected_mask=projected,
            crop_origin=(x1, y1),
            crop_shape=crop_value.shape,
            padding_px=0,
        )
        hot_core_count = (
            int(np.count_nonzero(support_flags))
            if support_flags is not None
            else 0
        )

        kind = str(projected.get("type") or "").lower()
        if kind == "circle":
            try:
                radius = max(1.0, float(projected.get("radius", 1.0)))
                core_area = float(math.pi * radius * radius)
            except (TypeError, ValueError):
                core_area = 0.0
        else:
            try:
                polygon = np.asarray(
                    pontos_mascara_display(projected),
                    dtype=np.float32,
                ).reshape(-1, 2)
                core_area = (
                    float(abs(cv2.contourArea(polygon)))
                    if len(polygon) >= 3
                    else 0.0
                )
            except (TypeError, ValueError, cv2.error):
                core_area = 0.0

        hot_fraction = (
            float(hot_core_count) / max(1.0, core_area)
            if core_area > 0.0
            else 0.0
        )
        accepted = bool(
            hot_core_count >= F3_TRACKING_LUMINOUS_FINE_MIN_CORE_HOT_PIXELS
            and hot_fraction
            >= F3_TRACKING_LUMINOUS_FINE_MIN_CORE_HOT_FRACTION
        )
        mask_id = str(row.get("mask_id") or "")
        if accepted and mask_id:
            validated_ids.append(mask_id)
        details.append(
            {
                "mask_id": mask_id,
                "hot_core_count": int(hot_core_count),
                "core_area_px": round(float(core_area), 3),
                "hot_core_fraction": round(float(hot_fraction), 5),
                "accepted": bool(accepted),
            }
        )

    # Chamadores sintéticos/legados podem fornecer somente centros. No runtime
    # produtivo _expected_on_rows() sempre inclui a geometria real da máscara.
    # Sem geometria suficiente, este guard não inventa um veto novo.
    if geometry_count < F3_TRACKING_LUMINOUS_MIN_COMPONENTS:
        return {
            "available": True,
            "enforced": False,
            "reason": "core_geometry_unavailable",
            "geometry_count": int(geometry_count),
            "validated_count": int(len(validated_ids)),
            "required_count": 0,
            "validated_mask_ids": validated_ids,
            "details": details,
        }

    required = max(
        F3_TRACKING_LUMINOUS_MIN_COMPONENTS,
        int(math.ceil(
            geometry_count * F3_TRACKING_LUMINOUS_FINE_MIN_CORE_MATCH_RATIO
        )),
    )
    available = len(validated_ids) >= required
    return {
        "available": bool(available),
        "enforced": True,
        "reason": (
            "fine_core_support_confirmed"
            if available
            else "fine_core_support_insufficient"
        ),
        "geometry_count": int(geometry_count),
        "validated_count": int(len(validated_ids)),
        "required_count": int(required),
        "validated_mask_ids": validated_ids,
        "details": details,
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


def _expected_on_rows(masks, states) -> list[dict]:
    state_map = states if isinstance(states, dict) else {}
    rows: list[dict] = []
    for mask in masks or []:
        if not isinstance(mask, dict):
            continue
        mask_id = str(mask.get("id") or "")
        if state_map.get(mask_id) != DISPLAY_CHECK_STATE_ON:
            continue
        normalized_mask = converter_mascara_legada_para_editor(mask)
        center = _mask_center(normalized_mask)
        if center is None:
            continue
        rows.append(
            {
                "mask_id": mask_id,
                "center": [float(center[0]), float(center[1])],
                "mask": deepcopy(normalized_mask),
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


def _fit_id_anchored_luminous_pose(
    canonical_board,
    expected_rows,
    landmark_details,
    coarse_matrix,
    diagnostics: dict | None = None,
) -> dict | None:
    """Refina a pose grossa usando IDs conhecidos dos segmentos luminosos.

    Com três landmarks já associados ao modelo 88:88, não precisamos exigir que
    metade dos ON do CHECK esteja visível para ajustar geometria. A decisão
    semântica continua fora daqui.
    """
    diag = diagnostics if isinstance(diagnostics, dict) else None
    if diag is not None:
        diag.clear()

    try:
        coarse = np.asarray(coarse_matrix, dtype=np.float32).reshape(2, 3)
    except Exception:
        if diag is not None:
            diag.update({"failure_stage": "coarse_matrix_invalid"})
        return None

    by_id = {
        str(row.get("mask_id") or ""): row
        for row in (expected_rows or ())
        if isinstance(row, dict) and str(row.get("mask_id") or "")
    }
    source_points = []
    target_points = []
    matched_ids = []
    rejected_ids = []
    seen: set[str] = set()
    for detail in landmark_details or ():
        if not isinstance(detail, dict):
            continue
        mask_id = str(detail.get("mask_id") or "")
        row = by_id.get(mask_id)
        center = detail.get("center")
        if (
            not mask_id
            or mask_id in seen
            or row is None
            or not isinstance(center, (list, tuple))
            or len(center) < 2
        ):
            continue

        # Segunda defesa: callers sintéticos/legados podem não declarar esses
        # campos, mas quando o detector real os declara uma evidência explicitamente
        # fora da máscara ou distante demais nunca entra no fit.
        if detail.get("projected_mask_support") is False:
            rejected_ids.append(mask_id)
            continue
        if detail.get("median_prediction_error_px") is not None:
            try:
                anchor_error = float(detail.get("median_prediction_error_px"))
            except (TypeError, ValueError):
                anchor_error = float("inf")
            if (
                not math.isfinite(anchor_error)
                or anchor_error
                > F3_TRACKING_LUMINOUS_FINE_MAX_ANCHOR_ERROR_PX
            ):
                rejected_ids.append(mask_id)
                continue

        try:
            source_points.append([float(center[0]), float(center[1])])
            target = row.get("center") or ()
            target_points.append([float(target[0]), float(target[1])])
        except (TypeError, ValueError, IndexError):
            continue
        seen.add(mask_id)
        matched_ids.append(mask_id)

    anchor_count = len(source_points)
    required = int(F3_TRACKING_LUMINOUS_FINE_MIN_ANCHORS)
    if diag is not None:
        diag.update(
            {
                "expected_on_count": int(len(by_id)),
                "observed_component_count": int(anchor_count),
                "required_match_count": required,
                "best_coarse_match_count": int(anchor_count),
                "best_final_match_count": 0,
                "failure_stage": "not_started",
                "matched_mask_ids": list(matched_ids),
                "rejected_mask_ids": list(rejected_ids),
            }
        )
    if anchor_count < required:
        if diag is not None:
            diag["failure_stage"] = "id_anchors_insufficient"
        return None

    source = np.asarray(source_points, dtype=np.float32).reshape(-1, 2)
    target = np.asarray(target_points, dtype=np.float32).reshape(-1, 2)
    try:
        coarse_projected = cv2.transform(
            source.reshape(-1, 1, 2),
            coarse,
        ).reshape(-1, 2)
    except Exception:
        if diag is not None:
            diag["failure_stage"] = "coarse_projection_failed"
        return None

    coarse_errors = np.linalg.norm(coarse_projected - target, axis=1)
    coarse_median = float(np.median(coarse_errors))
    if coarse_median <= F3_TRACKING_LUMINOUS_FINE_ALREADY_ALIGNED_PX:
        missing_ids = [
            mask_id
            for mask_id in by_id
            if mask_id not in seen
        ]
        match_ratio = anchor_count / max(1, len(by_id))
        score = anchor_count * 4.0 - coarse_median * 0.15
        if diag is not None:
            diag.update(
                {
                    "failure_stage": "",
                    "best_final_match_count": int(anchor_count),
                    "matched_mask_ids": list(matched_ids),
                    "rejected_mask_ids": list(dict.fromkeys(rejected_ids)),
                    "fit_mode": "coarse_verified",
                    "coarse_median_error_px": round(coarse_median, 3),
                    "refined_median_error_px": round(coarse_median, 3),
                    "gain_px": 0.0,
                    "translation_consensus_count": int(anchor_count),
                }
            )
        return {
            "matrix": np.asarray(coarse, dtype=np.float32).reshape(2, 3),
            "matched_mask_ids": list(matched_ids),
            "missing_expected_on_mask_ids": missing_ids,
            "matched_count": int(anchor_count),
            "expected_on_count": int(len(by_id)),
            "match_ratio": float(match_ratio),
            "median_error_px": float(coarse_median),
            "coarse_median_error_px": float(coarse_median),
            "fine_alignment_gain_px": 0.0,
            "fine_fit_mode": "coarse_verified",
            "score": float(score),
        }

    board = np.asarray(
        _quad_from_points(canonical_board),
        dtype=np.float32,
    ).reshape(-1, 2)
    if len(board) != 4:
        if diag is not None:
            diag["failure_stage"] = "invalid_board_geometry"
        return None
    board_diagonal = max(
        1.0,
        float(np.linalg.norm(np.max(board, axis=0) - np.min(board, axis=0))),
    )
    board_extent = np.max(board, axis=0) - np.min(board, axis=0)
    target_extent = np.max(target, axis=0) - np.min(target, axis=0)
    target_span = float(np.linalg.norm(target_extent))
    span_fraction = target_span / board_diagonal
    x_span_fraction = float(target_extent[0]) / max(
        1.0,
        float(board_extent[0]),
    )
    y_span_fraction = float(target_extent[1]) / max(
        1.0,
        float(board_extent[1]),
    )
    similarity_spatially_supported = bool(
        span_fraction
        >= F3_TRACKING_LUMINOUS_FINE_SIMILARITY_MIN_SPAN_FRACTION
        and x_span_fraction
        >= F3_TRACKING_LUMINOUS_FINE_SIMILARITY_MIN_X_SPAN_FRACTION
        and y_span_fraction
        >= F3_TRACKING_LUMINOUS_FINE_SIMILARITY_MIN_Y_SPAN_FRACTION
    )

    fit_mode = "translation"
    translation_consensus_count = int(anchor_count)
    refined = np.asarray(coarse, dtype=np.float32).copy()
    if similarity_spatially_supported:
        similarity = _estimate_affine_partial(source, target)
        if similarity is not None:
            refined = np.asarray(similarity, dtype=np.float32).reshape(2, 3)
            fit_mode = "similarity"

    if fit_mode == "translation":
        residual = target - coarse_projected
        consensus_gate = float(
            F3_TRACKING_LUMINOUS_FINE_TRANSLATION_CONSENSUS_PX
        )
        best_indices: list[int] = []
        best_spread = float("inf")
        for anchor_residual in residual:
            distances = np.linalg.norm(
                residual - anchor_residual,
                axis=1,
            )
            indices = np.flatnonzero(distances <= consensus_gate).tolist()
            if not indices:
                continue
            local_spread = float(
                np.median(distances[np.asarray(indices, dtype=np.int32)])
            )
            if (
                len(indices) > len(best_indices)
                or (
                    len(indices) == len(best_indices)
                    and local_spread < best_spread
                )
            ):
                best_indices = [int(index) for index in indices]
                best_spread = local_spread

        if len(best_indices) < required:
            if diag is not None:
                diag.update(
                    {
                        "failure_stage": "translation_consensus_insufficient",
                        "fit_mode": fit_mode,
                        "translation_consensus_count": int(len(best_indices)),
                        "translation_consensus_required": int(required),
                        "translation_consensus_gate_px": consensus_gate,
                        "coarse_median_error_px": round(coarse_median, 3),
                        "span_fraction": round(span_fraction, 5),
                        "x_span_fraction": round(x_span_fraction, 5),
                        "y_span_fraction": round(y_span_fraction, 5),
                        "similarity_spatially_supported": False,
                    }
                )
            return None

        if len(best_indices) < anchor_count:
            kept = set(best_indices)
            discarded_ids = [
                matched_ids[index]
                for index in range(anchor_count)
                if index not in kept
            ]
            rejected_ids.extend(discarded_ids)
            source = source[best_indices]
            target = target[best_indices]
            coarse_projected = coarse_projected[best_indices]
            coarse_errors = coarse_errors[best_indices]
            matched_ids = [matched_ids[index] for index in best_indices]
            seen = set(matched_ids)
            anchor_count = len(best_indices)
            coarse_median = float(np.median(coarse_errors))
            residual = target - coarse_projected

        translation_consensus_count = int(anchor_count)
        correction = np.median(residual, axis=0)
        refined[0, 2] += float(correction[0])
        refined[1, 2] += float(correction[1])

    allowed, guard = _luminous_refinement_within_coarse_guard(
        refined,
        coarse,
        canonical_board,
    )
    if not allowed:
        if diag is not None:
            diag.update(
                {
                    "failure_stage": "fine_pose_outside_structural_guard",
                    "refinement_guard": deepcopy(guard),
                    "fit_mode": fit_mode,
                }
            )
        return None

    try:
        refined_projected = cv2.transform(
            source.reshape(-1, 1, 2),
            refined,
        ).reshape(-1, 2)
    except Exception:
        if diag is not None:
            diag["failure_stage"] = "refined_projection_failed"
        return None
    refined_errors = np.linalg.norm(refined_projected - target, axis=1)
    refined_median = float(np.median(refined_errors))
    if (
        not math.isfinite(refined_median)
        or refined_median > F3_TRACKING_LUMINOUS_FINE_MAX_MEDIAN_ERROR_PX
    ):
        if diag is not None:
            diag.update(
                {
                    "failure_stage": "fine_residual_too_high",
                    "fit_mode": fit_mode,
                    "coarse_median_error_px": round(coarse_median, 3),
                    "refined_median_error_px": round(refined_median, 3),
                    "maximum_allowed_median_error_px": float(
                        F3_TRACKING_LUMINOUS_FINE_MAX_MEDIAN_ERROR_PX
                    ),
                }
            )
        return None

    gain = coarse_median - refined_median
    minimum_gain = max(
        F3_TRACKING_LUMINOUS_FINE_MIN_GAIN_PX,
        coarse_median * 0.08,
    )
    if gain < minimum_gain:
        if diag is not None:
            diag.update(
                {
                    "failure_stage": "fine_gain_insufficient",
                    "fit_mode": fit_mode,
                    "coarse_median_error_px": round(coarse_median, 3),
                    "refined_median_error_px": round(refined_median, 3),
                    "gain_px": round(gain, 3),
                }
            )
        return None

    missing_ids = [
        mask_id
        for mask_id in by_id
        if mask_id not in seen
    ]
    match_ratio = anchor_count / max(1, len(by_id))
    score = (
        anchor_count * 4.0
        + min(20.0, max(0.0, gain))
        - refined_median * 0.15
    )
    if diag is not None:
        diag.update(
            {
                "failure_stage": "",
                "best_final_match_count": int(anchor_count),
                "matched_mask_ids": list(matched_ids),
                "rejected_mask_ids": list(dict.fromkeys(rejected_ids)),
                "fit_mode": fit_mode,
                "coarse_median_error_px": round(coarse_median, 3),
                "refined_median_error_px": round(refined_median, 3),
                "gain_px": round(gain, 3),
                "span_fraction": round(span_fraction, 5),
                "x_span_fraction": round(x_span_fraction, 5),
                "y_span_fraction": round(y_span_fraction, 5),
                "similarity_spatially_supported": bool(
                    similarity_spatially_supported
                ),
                "translation_consensus_count": int(
                    translation_consensus_count
                ),
                "translation_consensus_gate_px": float(
                    F3_TRACKING_LUMINOUS_FINE_TRANSLATION_CONSENSUS_PX
                ),
                "refinement_guard": deepcopy(guard),
            }
        )

    return {
        "matrix": np.asarray(refined, dtype=np.float32).reshape(2, 3),
        "matched_mask_ids": list(matched_ids),
        "missing_expected_on_mask_ids": missing_ids,
        "matched_count": int(anchor_count),
        "expected_on_count": int(len(by_id)),
        "match_ratio": float(match_ratio),
        "median_error_px": float(refined_median),
        "coarse_median_error_px": float(coarse_median),
        "fine_alignment_gain_px": float(gain),
        "fine_fit_mode": fit_mode,
        "score": float(score),
    }


def _fit_id_anchored_luminous_projective_pose(
    canonical_board,
    expected_rows,
    landmark_details,
    coarse_homography,
    diagnostics: dict | None = None,
) -> dict | None:
    """Refina H_filter com correção residual no espaço canônico.

    A perspectiva vem dos quatro cantos físicos do filtro. Os segmentos
    luminosos aplicam apenas uma correção fina em CANÔNICO, preservando a
    homografia em vez de voltar a aproximar toda a placa por uma affine 2x3.
    """
    diag = diagnostics if isinstance(diagnostics, dict) else None
    if diag is not None:
        diag.clear()

    coarse = _as_planar_transform(coarse_homography)
    if coarse is None or coarse.shape != (3, 3):
        if diag is not None:
            diag["failure_stage"] = "coarse_projective_invalid"
        return None

    by_id = {
        str(row.get("mask_id") or ""): row
        for row in (expected_rows or ())
        if isinstance(row, dict) and str(row.get("mask_id") or "")
    }
    source_points = []
    target_points = []
    matched_ids = []
    rejected_ids = []
    seen: set[str] = set()
    for detail in landmark_details or ():
        if not isinstance(detail, dict):
            continue
        mask_id = str(detail.get("mask_id") or "")
        row = by_id.get(mask_id)
        center = detail.get("center")
        if (
            not mask_id
            or mask_id in seen
            or row is None
            or not isinstance(center, (list, tuple))
            or len(center) < 2
        ):
            continue
        if detail.get("projected_mask_support") is False:
            rejected_ids.append(mask_id)
            continue
        if detail.get("median_prediction_error_px") is not None:
            try:
                anchor_error = float(detail.get("median_prediction_error_px"))
            except (TypeError, ValueError):
                anchor_error = float("inf")
            if (
                not math.isfinite(anchor_error)
                or anchor_error
                > F3_TRACKING_LUMINOUS_FINE_MAX_ANCHOR_ERROR_PX
            ):
                rejected_ids.append(mask_id)
                continue
        try:
            source_points.append([float(center[0]), float(center[1])])
            target = row.get("center") or ()
            target_points.append([float(target[0]), float(target[1])])
        except (TypeError, ValueError, IndexError):
            continue
        seen.add(mask_id)
        matched_ids.append(mask_id)

    required = int(F3_TRACKING_LUMINOUS_FINE_MIN_ANCHORS)
    anchor_count = len(source_points)
    if diag is not None:
        diag.update(
            {
                "expected_on_count": int(len(by_id)),
                "observed_component_count": int(anchor_count),
                "required_match_count": required,
                "best_coarse_match_count": int(anchor_count),
                "best_final_match_count": 0,
                "failure_stage": "not_started",
                "matched_mask_ids": list(matched_ids),
                "rejected_mask_ids": list(rejected_ids),
                "fit_mode": "projective_residual",
            }
        )
    if anchor_count < required:
        if diag is not None:
            diag["failure_stage"] = "id_anchors_insufficient"
        return None

    source = np.asarray(source_points, dtype=np.float32).reshape(-1, 2)
    target = np.asarray(target_points, dtype=np.float32).reshape(-1, 2)
    try:
        coarse_projected = cv2.perspectiveTransform(
            source.reshape(-1, 1, 2),
            coarse,
        ).reshape(-1, 2)
    except Exception:
        if diag is not None:
            diag["failure_stage"] = "coarse_projection_failed"
        return None

    coarse_errors = np.linalg.norm(coarse_projected - target, axis=1)
    coarse_median = float(np.median(coarse_errors))
    if coarse_median <= F3_TRACKING_LUMINOUS_FINE_ALREADY_ALIGNED_PX:
        affine = _affine_approximation_from_projective(
            coarse,
            canonical_board,
        )
        if affine is None:
            if diag is not None:
                diag["failure_stage"] = "projective_affine_compat_failed"
            return None
        if diag is not None:
            diag.update(
                {
                    "failure_stage": "",
                    "best_final_match_count": int(anchor_count),
                    "fit_mode": "projective_coarse_verified",
                    "coarse_median_error_px": round(coarse_median, 3),
                    "refined_median_error_px": round(coarse_median, 3),
                    "gain_px": 0.0,
                }
            )
        return {
            "matrix": affine,
            "projective_matrix": coarse.copy(),
            "matched_mask_ids": list(matched_ids),
            "missing_expected_on_mask_ids": [
                mask_id for mask_id in by_id if mask_id not in seen
            ],
            "matched_count": int(anchor_count),
            "expected_on_count": int(len(by_id)),
            "match_ratio": float(anchor_count / max(1, len(by_id))),
            "median_error_px": coarse_median,
            "coarse_median_error_px": coarse_median,
            "fine_alignment_gain_px": 0.0,
            "fine_fit_mode": "projective_coarse_verified",
            "score": float(anchor_count * 4.0 - coarse_median * 0.15),
        }

    residual = target - coarse_projected
    consensus_gate = float(F3_TRACKING_LUMINOUS_FINE_TRANSLATION_CONSENSUS_PX)
    best_indices: list[int] = []
    best_spread = float("inf")
    for anchor_residual in residual:
        distances = np.linalg.norm(residual - anchor_residual, axis=1)
        indices = np.flatnonzero(distances <= consensus_gate).tolist()
        if not indices:
            continue
        local_spread = float(
            np.median(distances[np.asarray(indices, dtype=np.int32)])
        )
        if (
            len(indices) > len(best_indices)
            or (
                len(indices) == len(best_indices)
                and local_spread < best_spread
            )
        ):
            best_indices = [int(index) for index in indices]
            best_spread = local_spread

    if len(best_indices) < required:
        if diag is not None:
            diag.update(
                {
                    "failure_stage": "translation_consensus_insufficient",
                    "translation_consensus_count": int(len(best_indices)),
                    "translation_consensus_required": required,
                    "coarse_median_error_px": round(coarse_median, 3),
                }
            )
        return None

    if len(best_indices) < anchor_count:
        keep = set(best_indices)
        rejected_ids.extend(
            matched_ids[index]
            for index in range(anchor_count)
            if index not in keep
        )
        source = source[best_indices]
        target = target[best_indices]
        coarse_projected = coarse_projected[best_indices]
        coarse_errors = coarse_errors[best_indices]
        matched_ids = [matched_ids[index] for index in best_indices]
        seen = set(matched_ids)
        anchor_count = len(best_indices)
        coarse_median = float(np.median(coarse_errors))
        residual = target - coarse_projected

    board = np.asarray(
        _quad_from_points(canonical_board),
        dtype=np.float32,
    ).reshape(-1, 2)
    if len(board) != 4:
        if diag is not None:
            diag["failure_stage"] = "invalid_board_geometry"
        return None
    board_diagonal = max(
        1.0,
        float(np.linalg.norm(np.max(board, axis=0) - np.min(board, axis=0))),
    )

    correction_affine = _estimate_affine_partial(
        coarse_projected.tolist(),
        target.tolist(),
    )
    fit_mode = "projective_similarity"
    if correction_affine is None:
        correction = np.median(residual, axis=0)
        correction_affine = np.asarray(
            [
                [1.0, 0.0, float(correction[0])],
                [0.0, 1.0, float(correction[1])],
            ],
            dtype=np.float32,
        )
        fit_mode = "projective_translation"

    correction_scale = affine_scale(correction_affine)
    correction_rotation = abs(affine_rotation_deg(correction_affine))
    correction_shift = math.hypot(
        float(correction_affine[0, 2]),
        float(correction_affine[1, 2]),
    )
    correction_shift_fraction = correction_shift / board_diagonal
    if not (
        correction_rotation <= F3_TRACKING_LUMINOUS_MAX_ROTATION_DELTA_DEG
        and F3_TRACKING_LUMINOUS_MIN_SCALE_RATIO_TO_COARSE
        <= correction_scale
        <= F3_TRACKING_LUMINOUS_MAX_SCALE_RATIO_TO_COARSE
        and correction_shift_fraction
        <= F3_TRACKING_LUMINOUS_MAX_CENTER_SHIFT_FRACTION
    ):
        if diag is not None:
            diag.update(
                {
                    "failure_stage": "fine_pose_outside_structural_guard",
                    "fit_mode": fit_mode,
                    "correction_rotation_deg": round(correction_rotation, 3),
                    "correction_scale": round(correction_scale, 5),
                    "correction_shift_px": round(correction_shift, 3),
                }
            )
        return None

    correction_h = _planar_to_homography(correction_affine)
    refined = (
        correction_h @ coarse
        if correction_h is not None
        else None
    )
    if refined is None or not np.all(np.isfinite(refined)):
        if diag is not None:
            diag["failure_stage"] = "refined_projection_failed"
        return None

    try:
        refined_projected = cv2.perspectiveTransform(
            source.reshape(-1, 1, 2),
            refined.astype(np.float32),
        ).reshape(-1, 2)
    except Exception:
        if diag is not None:
            diag["failure_stage"] = "refined_projection_failed"
        return None

    refined_errors = np.linalg.norm(refined_projected - target, axis=1)
    refined_median = float(np.median(refined_errors))
    if (
        not math.isfinite(refined_median)
        or refined_median > F3_TRACKING_LUMINOUS_FINE_MAX_MEDIAN_ERROR_PX
    ):
        if diag is not None:
            diag.update(
                {
                    "failure_stage": "fine_residual_too_high",
                    "fit_mode": fit_mode,
                    "coarse_median_error_px": round(coarse_median, 3),
                    "refined_median_error_px": round(refined_median, 3),
                }
            )
        return None

    gain = coarse_median - refined_median
    minimum_gain = max(
        F3_TRACKING_LUMINOUS_FINE_MIN_GAIN_PX,
        coarse_median * 0.08,
    )
    if gain < minimum_gain:
        if diag is not None:
            diag.update(
                {
                    "failure_stage": "fine_gain_insufficient",
                    "fit_mode": fit_mode,
                    "coarse_median_error_px": round(coarse_median, 3),
                    "refined_median_error_px": round(refined_median, 3),
                    "gain_px": round(gain, 3),
                }
            )
        return None

    affine = _affine_approximation_from_projective(
        refined,
        canonical_board,
    )
    if affine is None:
        if diag is not None:
            diag["failure_stage"] = "projective_affine_compat_failed"
        return None

    if diag is not None:
        diag.update(
            {
                "failure_stage": "",
                "best_final_match_count": int(anchor_count),
                "matched_mask_ids": list(matched_ids),
                "rejected_mask_ids": list(dict.fromkeys(rejected_ids)),
                "fit_mode": fit_mode,
                "coarse_median_error_px": round(coarse_median, 3),
                "refined_median_error_px": round(refined_median, 3),
                "gain_px": round(gain, 3),
                "translation_consensus_count": int(anchor_count),
            }
        )

    return {
        "matrix": affine,
        "projective_matrix": refined.astype(np.float32),
        "matched_mask_ids": list(matched_ids),
        "missing_expected_on_mask_ids": [
            mask_id for mask_id in by_id if mask_id not in seen
        ],
        "matched_count": int(anchor_count),
        "expected_on_count": int(len(by_id)),
        "match_ratio": float(anchor_count / max(1, len(by_id))),
        "median_error_px": refined_median,
        "coarse_median_error_px": coarse_median,
        "fine_alignment_gain_px": gain,
        "fine_fit_mode": fit_mode,
        "score": float(
            anchor_count * 4.0
            + min(20.0, max(0.0, gain))
            - refined_median * 0.15
        ),
    }


def _fit_luminous_pose(
    canonical_board,
    expected_rows,
    luminous_centers,
    coarse_matrices,
    diagnostics: dict | None = None,
) -> dict | None:
    expected_count = int(len(expected_rows))
    observed_count = int(len(luminous_centers))
    required = max(
        F3_TRACKING_LUMINOUS_MIN_COMPONENTS,
        int(math.ceil(
            expected_count * F3_TRACKING_LUMINOUS_MIN_MATCH_RATIO
        )),
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
    base_projective=None,
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
    base_transform = (
        base_projective
        if base_projective is not None
        else base_matrix
    )
    if base_transform is not None:
        inverse = _invert_planar_transform(base_transform)
        projected = (
            transform_points(canonical_board, inverse)
            if inverse is not None
            else []
        )
        if len(projected) >= 3:
            filter_candidates.append(
                {
                    "points": projected,
                    "score": 100.0,
                    "source": (
                        "tracked_filter_projective"
                        if base_projective is not None
                        else "tracked_filter"
                    ),
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
        normalized_base_projective = None
        if base_matrix is not None:
            try:
                normalized_base_matrix = np.asarray(
                    base_matrix,
                    dtype=np.float32,
                ).reshape(2, 3)
                coarse_matrices.append(normalized_base_matrix)
            except Exception:
                normalized_base_matrix = None
        if base_projective is not None:
            try:
                candidate_h = np.asarray(
                    base_projective,
                    dtype=np.float32,
                ).reshape(3, 3)
                if np.all(np.isfinite(candidate_h)):
                    normalized_base_projective = candidate_h
            except Exception:
                normalized_base_projective = None
        normalized_base_transform = (
            normalized_base_projective
            if normalized_base_projective is not None
            else normalized_base_matrix
        )
        coarse_matrices.extend(
            _filter_board_matrix_candidates(
                filter_points,
                canonical_board,
            )
        )

        fit = None
        global_fit = None
        fit_diagnostics: dict = {}
        fit_landmark_source = "global_connected_components"
        local_landmarks = {
            "available": False,
            "reason": "structural_base_matrix_missing",
            "centers": [],
        }

        if bool(luminous.get("available")):
            global_fit = _fit_luminous_pose(
                canonical_board,
                expected_rows,
                luminous.get("centers") or [],
                coarse_matrices,
                diagnostics=fit_diagnostics,
            )
            # Sem lock estrutural, o grid global ainda pode reacquirir a pose.
            # Com lock estrutural, ele é apenas diagnóstico: não conhece IDs e
            # pode casar um segmento vizinho com a máscara errada.
            if normalized_base_transform is None:
                fit = global_fit
        elif normalized_base_transform is None:
            attempt["fit_diagnostics"] = {}
            attempt["fit"] = False
            attempts.append(attempt)
            continue

        # Com lock estrutural, o segundo estágio rastreia os segmentos luminosos
        # individualmente. A associação local preserva o ID do 88:88 e permite
        # que três landmarks confirmados corrijam a pose fina de TODAS as 28 ROIs.
        # Isso roda mesmo quando o fit global já encontrou uma pose, porque o
        # objetivo aqui é remover o erro residual do contorno.
        #
        # Antes de exigir movimento, validamos também a pose estrutural atual
        # contra o núcleo EXATO das máscaras ON. Se a luz já cai dentro das ROIs
        # corretas, não existe razão para rejeitar a pose apenas porque um ajuste
        # adicional teve ganho pequeno. Nesse caso publicamos a MESMA matriz como
        # lock luminoso atual, sem deslocar/rotacionar o grid.
        base_core_validation: dict = {}
        if (
            normalized_base_transform is not None
            and luminous.get("threshold_v") is not None
        ):
            base_core_validation = _validate_luminous_pose_core_support(
                frame,
                expected_rows,
                normalized_base_transform,
                luminous.get("threshold_v"),
            )
            attempt["base_core_validation"] = deepcopy(
                base_core_validation
            )

            local_landmarks = _detect_expected_on_luminous_landmarks(
                frame,
                filter_points,
                expected_rows,
                normalized_base_transform,
                luminous.get("threshold_v"),
            )
            attempt["global_fit_diagnostics"] = deepcopy(fit_diagnostics)
            attempt["global_fit_candidate_available"] = bool(
                global_fit is not None
            )
            if bool(local_landmarks.get("available")):
                fine_fit_diagnostics: dict = {}
                if normalized_base_projective is not None:
                    fine_fit = _fit_id_anchored_luminous_projective_pose(
                        canonical_board,
                        expected_rows,
                        local_landmarks.get("details") or [],
                        normalized_base_projective,
                        diagnostics=fine_fit_diagnostics,
                    )
                else:
                    fine_fit = _fit_id_anchored_luminous_pose(
                        canonical_board,
                        expected_rows,
                        local_landmarks.get("details") or [],
                        normalized_base_matrix,
                        diagnostics=fine_fit_diagnostics,
                    )
                attempt["fine_fit_diagnostics"] = deepcopy(
                    fine_fit_diagnostics
                )
                if fine_fit is not None:
                    core_validation = _validate_luminous_pose_core_support(
                        frame,
                        expected_rows,
                        (
                            fine_fit.get("projective_matrix")
                            if fine_fit.get("projective_matrix") is not None
                            else fine_fit.get("matrix")
                        ),
                        luminous.get("threshold_v"),
                    )
                    attempt["fine_core_validation"] = deepcopy(
                        core_validation
                    )
                    if (
                        bool(core_validation.get("enforced"))
                        and not bool(core_validation.get("available"))
                    ):
                        fine_fit_diagnostics.update(
                            {
                                "failure_stage": (
                                    "fine_core_support_insufficient"
                                ),
                                "core_validation": deepcopy(
                                    core_validation
                                ),
                            }
                        )
                        fine_fit = None
                    else:
                        fine_fit["core_validated_mask_ids"] = list(
                            core_validation.get("validated_mask_ids") or []
                        )
                        fine_fit["core_validated_count"] = int(
                            core_validation.get("validated_count", 0) or 0
                        )
                        fine_fit["core_required_count"] = int(
                            core_validation.get("required_count", 0) or 0
                        )

                if fine_fit is not None:
                    fit = fine_fit
                    fit_diagnostics = fine_fit_diagnostics
                    fit_landmark_source = "expected_on_id_anchored_fine"
                else:
                    fit = None
                    fit_diagnostics = fine_fit_diagnostics
                    fit_landmark_source = "expected_on_id_anchored_fine"

            if (
                fit is None
                and bool(base_core_validation.get("enforced"))
                and bool(base_core_validation.get("available"))
            ):
                validated_ids = [
                    str(mask_id)
                    for mask_id in (
                        base_core_validation.get("validated_mask_ids") or ()
                    )
                    if str(mask_id)
                ]
                validated_set = set(validated_ids)
                validated_count = int(
                    base_core_validation.get("validated_count", 0) or 0
                )
                expected_count = int(len(expected_rows))
                previous_failure = str(
                    fit_diagnostics.get("failure_stage") or ""
                )
                required_count = int(
                    base_core_validation.get("required_count", 0) or 0
                )
                alignment_residual = _base_core_alignment_residual(
                    local_landmarks.get("details") or (),
                    validated_ids,
                )

                # D-069: núcleo luminoso prova emissão, não centralização.
                # Só reutilizamos a matriz estrutural como alinhamento pronto
                # quando os centros luminosos também confirmam precisão
                # geométrica dentro do MESMO limite residual já existente.
                if bool(alignment_residual.get("precise")):
                    median_error = float(
                        alignment_residual.get("median_error_px", 0.0)
                        or 0.0
                    )
                    fit_diagnostics = {
                        "expected_on_count": expected_count,
                        "observed_component_count": int(
                            len(local_landmarks.get("centers") or [])
                        ),
                        "required_match_count": required_count,
                        "best_coarse_match_count": validated_count,
                        "best_final_match_count": validated_count,
                        "failure_stage": "",
                        "refinement_failure_stage": previous_failure,
                        "fit_mode": "base_core_verified",
                        "matched_mask_ids": list(validated_ids),
                        "base_core_validation": deepcopy(
                            base_core_validation
                        ),
                        "base_alignment_residual": deepcopy(
                            alignment_residual
                        ),
                    }
                    compatibility_affine = (
                        normalized_base_matrix.copy()
                        if normalized_base_matrix is not None
                        else _affine_approximation_from_projective(
                            normalized_base_projective,
                            canonical_board,
                        )
                    )
                    if compatibility_affine is None:
                        fit = None
                    else:
                        fit = {
                            "matrix": compatibility_affine,
                            "projective_matrix": (
                                normalized_base_projective.copy()
                                if normalized_base_projective is not None
                                else None
                            ),
                        "matched_mask_ids": list(validated_ids),
                        "missing_expected_on_mask_ids": [
                            str(row.get("mask_id") or "")
                            for row in expected_rows
                            if str(row.get("mask_id") or "")
                            and str(row.get("mask_id") or "")
                            not in validated_set
                        ],
                        "matched_count": validated_count,
                        "expected_on_count": expected_count,
                        "match_ratio": (
                            validated_count / max(1, expected_count)
                        ),
                        "median_error_px": median_error,
                        "coarse_median_error_px": median_error,
                        "fine_alignment_gain_px": 0.0,
                        "fine_fit_mode": "base_core_verified",
                        "score": (
                            validated_count * 4.0
                            - median_error * 0.15
                        ),
                        "core_validated_mask_ids": list(validated_ids),
                        "core_validated_count": validated_count,
                            "core_required_count": required_count,
                        }
                    if fit is not None:
                        fit_landmark_source = "expected_on_core_validated_base"
                else:
                    fit = None
                    fit_landmark_source = (
                        "expected_on_core_emission_only"
                    )
                    fit_diagnostics = {
                        **deepcopy(fit_diagnostics),
                        "expected_on_count": expected_count,
                        "observed_component_count": int(
                            len(local_landmarks.get("centers") or [])
                        ),
                        "required_match_count": required_count,
                        "best_coarse_match_count": validated_count,
                        "best_final_match_count": 0,
                        "failure_stage": (
                            "base_core_alignment_residual_too_high"
                            if bool(alignment_residual.get("available"))
                            else "base_core_alignment_landmarks_insufficient"
                        ),
                        "refinement_failure_stage": previous_failure,
                        "fit_mode": "base_core_emission_only",
                        "matched_mask_ids": list(validated_ids),
                        "base_core_validation": deepcopy(
                            base_core_validation
                        ),
                        "base_alignment_residual": deepcopy(
                            alignment_residual
                        ),
                        "base_core_emission_only": True,
                    }

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
        attempt["fine_fit_mode"] = str(
            (fit or {}).get("fine_fit_mode") or ""
        )
        attempt["fine_alignment_gain_px"] = (
            round(float((fit or {}).get("fine_alignment_gain_px")), 3)
            if (fit or {}).get("fine_alignment_gain_px") is not None
            else None
        )
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
            "fine_fit_mode": str(fit.get("fine_fit_mode") or ""),
            "fine_alignment_gain_px": fit.get("fine_alignment_gain_px"),
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


def _luminous_tracking_power_veto(
    app,
    *,
    project_name: str,
    check_id: str,
    frame_token=None,
) -> tuple[bool, str]:
    """OFF só veta o refinamento quando pertence à mesma captura e pose válida.

    A autoridade de energia é publicada depois do tracking. Portanto um OFF de
    frame anterior nunca pode bloquear a descoberta de uma transição física
    para ligado. Da mesma forma, OFF calculado sobre ROIs ainda sustentadas
    apenas pelo lock estrutural não pode vetar o mecanismo que corrige essas
    próprias ROIs. Isso preserva D-022 sem reabrir autoridade para reflexos.
    """
    status = getattr(app, "_display_f3_power_authority_status", None)
    energy = status.get("energy") if isinstance(status, dict) else None
    if not isinstance(energy, dict):
        return False, ""

    energy_project = str(energy.get("project_name") or "")
    energy_check = str(energy.get("check_id") or "")
    if energy_project and energy_project != str(project_name or ""):
        return False, ""
    if energy_check and energy_check != str(check_id or ""):
        return False, ""

    energy_frame_token = energy.get("frame_token")
    same_frame = bool(
        frame_token is not None
        and energy_frame_token is not None
        and energy_frame_token == frame_token
    )
    spatially_authoritative = bool(
        energy.get("spatial_alignment_ready") is True
    )
    explicit_off = bool(
        energy.get("off_confirmed") is True
        and energy.get("powered_confirmed") is not True
        and str(energy.get("energy_state") or "").strip().lower()
        in {"", "off"}
    )
    if explicit_off and same_frame and spatially_authoritative:
        return True, "power_off_confirmed_blocks_luminous_tracking"
    return False, ""


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

    power_vetoed, power_veto_reason = _luminous_tracking_power_veto(
        app,
        project_name=str(project_name or ""),
        check_id=check_id,
        frame_token=frame_token,
    )
    if power_vetoed:
        app._display_f3_luminous_tracking_debug = {
            "available": False,
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
            "luminous_emission_detected": False,
            "alignment_required": True,
            "alignment_ready": False,
            "matched_mask_ids": [],
            "matched_count": 0,
            "validated_luminous_anchor_count": 0,
            "reason": power_veto_reason,
            "power_vetoed": True,
        }
        return None

    fit_board = (
        getattr(runtime, "canonical_board", None)
        or canonical_board_points(project, runtime.store)
    )
    fit_masks = _canonical_check_masks_for_luminous_tracking(
        runtime,
        project,
        check,
    )
    fit_space = "canonical"

    expected_rows = _expected_on_rows(
        fit_masks,
        check.get("mask_states", {}),
    )

    base_matrix = None
    base_projective = None
    if (
        base_result is not None
        and bool(getattr(base_result, "locked", False))
    ):
        if getattr(base_result, "current_to_canonical", None) is not None:
            try:
                base_matrix = np.asarray(
                    base_result.current_to_canonical,
                    dtype=np.float32,
                ).reshape(2, 3)
            except Exception:
                base_matrix = None
        if getattr(
            base_result,
            "current_to_canonical_homography",
            None,
        ) is not None:
            try:
                candidate_h = np.asarray(
                    base_result.current_to_canonical_homography,
                    dtype=np.float32,
                ).reshape(3, 3)
                if np.all(np.isfinite(candidate_h)):
                    base_projective = candidate_h
            except Exception:
                base_projective = None

    pose = _find_luminous_segment_pose(
        frame,
        fit_board,
        expected_rows,
        (int(runtime.width), int(runtime.height)),
        base_matrix=base_matrix,
        base_projective=base_projective,
    )
    attempts = [
        item for item in (pose.get("attempts") or ())
        if isinstance(item, dict)
    ]
    alignment_required = bool(
        len(expected_rows) >= F3_TRACKING_LUMINOUS_MIN_COMPONENTS
    )
    alignment_ready = bool(
        pose.get("available")
        and (
            pose.get("projective_matrix") is not None
            or pose.get("matrix") is not None
        )
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
    validated_luminous_anchor_count = max(
        (
            len(
                [
                    detail
                    for detail in (item.get("local_luminous_details") or ())
                    if isinstance(detail, dict)
                    and detail.get("projected_mask_support") is not False
                    and (
                        detail.get("median_prediction_error_px") is None
                        or float(detail.get("median_prediction_error_px"))
                        <= F3_TRACKING_LUMINOUS_FINE_MAX_ANCHOR_ERROR_PX
                    )
                ]
            )
            for item in attempts
        ),
        default=0,
    )
    maximum_components_for_energy = max(
        F3_TRACKING_LUMINOUS_MIN_COMPONENTS,
        int(
            math.ceil(
                max(1, len(expected_rows))
                * F3_TRACKING_LUMINOUS_MAX_COMPONENT_RATIO_FOR_ENERGY
            )
        ),
    )
    luminous_scene_noisy = bool(
        luminous_component_count > maximum_components_for_energy
    )
    luminous_emission_detected = bool(
        alignment_ready
        or (
            (base_projective is not None or base_matrix is not None)
            and validated_luminous_anchor_count
            >= F3_TRACKING_LUMINOUS_MIN_COMPONENTS
            and not luminous_scene_noisy
        )
    )

    telemetry = {
        key: (
            value.tolist()
            if isinstance(value, np.ndarray)
            else deepcopy(value)
        )
        for key, value in pose.items()
        if key not in {"matrix", "projective_matrix"}
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
            "fit_composed_to_canonical": bool(fit_space != "canonical"),
            "expected_on_count": int(len(expected_rows)),
            "luminous_component_count": luminous_component_count,
            "validated_luminous_anchor_count": int(
                validated_luminous_anchor_count
            ),
            "maximum_components_for_energy": int(
                maximum_components_for_energy
            ),
            "luminous_scene_noisy": bool(luminous_scene_noisy),
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

    projective_matrix = None
    if pose.get("projective_matrix") is not None:
        try:
            candidate_h = np.asarray(
                pose.get("projective_matrix"),
                dtype=np.float32,
            ).reshape(3, 3)
            if np.all(np.isfinite(candidate_h)):
                projective_matrix = candidate_h
        except Exception:
            projective_matrix = None

    try:
        fit_matrix = np.asarray(
            pose.get("matrix"), dtype=np.float32
        ).reshape(2, 3)
    except Exception:
        fit_matrix = None
    if fit_matrix is None and projective_matrix is not None:
        fit_matrix = _affine_approximation_from_projective(
            projective_matrix,
            fit_board,
        )
    if fit_matrix is None or not np.all(np.isfinite(fit_matrix)):
        return None

    matrix = np.asarray(fit_matrix, dtype=np.float32).reshape(2, 3)

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
        if projective_matrix is not None:
            aligned = cv2.warpPerspective(
                frame,
                projective_matrix,
                (int(runtime.width), int(runtime.height)),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT101,
            )
        else:
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
    runtime.last_homography = (
        projective_matrix.copy()
        if projective_matrix is not None
        else None
    )
    runtime._force_absolute_reacquire = False
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
        if (base_projective is not None or base_matrix is not None)
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
        current_to_canonical_homography=(
            projective_matrix.copy()
            if projective_matrix is not None
            else None
        ),
        source_type="luminous_segment_grid",
        evidence_current=True,
        luminous_validated_mask_ids=tuple(
            str(mask_id)
            for mask_id in (
                pose.get("core_validated_mask_ids")
                or pose.get("matched_mask_ids")
                or ()
            )
            if str(mask_id)
        ),
        luminous_alignment_mode=str(
            pose.get("fine_fit_mode")
            or pose.get("fit_landmark_source")
            or ""
        ),
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
    current_to_canonical_homography: object | None = None
    source_type: str = ""
    evidence_current: bool = False
    luminous_validated_mask_ids: tuple[str, ...] = ()
    luminous_alignment_mode: str = ""


class F3DisplayObjectTracker:
    """ORB/RANSAC independente, sempre produz CURRENT -> CANÔNICO."""

    def __init__(self, repository: DisplayProjectRepository) -> None:
        self.repository = repository
        self.store = F3TrackingConfigStore(repository)
        self.check_store = DisplayCheckPresenceReferenceStore(repository)
        self.project_presence_store = DisplayProjectPresenceReferenceStore(repository)
        self.mask_reference_store = DisplayMaskEditorReferenceStore(repository)
        self.neural_pose_detector = F3NeuralPoseDetector(repository)
        self.reset()

    def reset(self) -> None:
        """Invalida configuração + banco de referências + pose corrente."""
        self.project = ""
        self.signature = None
        self.width = 0
        self.height = 0
        self.references: dict[str, dict] = {}
        self.reference_specs: dict[str, dict] = {}
        self.reference_materialization_failures: set[str] = set()
        self.ready = False
        self.reason = "not_configured"
        self.canonical_board: list[list[float]] = []
        self.canonical_masks: list[dict] = []
        self.reset_pose()

    def reset_pose(self) -> None:
        """Descarta somente a pose da placa; preserva calibração já preparada.

        Rearme físico entre duas placas precisa procurar a nova posição do zero,
        mas não precisa reler as mesmas fotos nem recalcular o banco estrutural.
        """
        self.last_matrix: np.ndarray | None = None
        self.last_homography: np.ndarray | None = None
        self._force_absolute_reacquire = False
        self.last_compute_s = 0.0
        self.last_result: F3TrackingResult | None = None
        self.last_frame_id = None
        self._last_reference = ""
        self.last_gray = None
        self.last_verified_s = 0.0
        self.last_verified_rotation_deg: float | None = None
        self._last_rotation_jump_rejections: list[dict] = []
        self._last_neural_pose_debug: dict = {}
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

    def _signature(
        self,
        project: dict,
        board,
        *,
        reference_specs: list[dict] | None = None,
    ) -> tuple:
        reference_specs = (
            self._calibrated_reference_specs(project)
            if reference_specs is None
            else reference_specs
        )
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

    def _available_reference_keys(self) -> tuple[str, ...]:
        keys = list(self.reference_specs)
        for key in self.references:
            if key not in self.reference_specs:
                keys.append(key)
        return tuple(str(key) for key in keys if str(key))

    def has_reference(self, key: str) -> bool:
        name = str(key or "")
        return bool(
            name
            and (
                name in self.references
                or (
                    name in self.reference_specs
                    and name not in self.reference_materialization_failures
                )
            )
        )

    def _ensure_reference(self, key: str) -> bool:
        """Materializa uma referência estrutural somente quando ela é usada."""
        name = str(key or "")
        if not name:
            return False
        if name in self.references:
            return True
        if name in self.reference_materialization_failures:
            return False

        spec = self.reference_specs.get(name)
        if not isinstance(spec, dict):
            return False

        path = str(spec.get("path") or "")
        image = cv2.imread(path, cv2.IMREAD_COLOR)
        if not _valid_frame(image) or image.shape[:2] != (self.height, self.width):
            self.reference_materialization_failures.add(name)
            return False

        tracking_mask = build_tracking_mask(
            self.width,
            self.height,
            spec.get("board", []),
            spec.get("masks", []),
        )
        if tracking_mask is None:
            self.reference_materialization_failures.add(name)
            return False

        self._add_reference(
            self.references,
            key=name,
            image=image,
            tracking_mask=tracking_mask,
            reference_to_canonical=spec.get("reference_to_canonical"),
            angle=float(spec.get("angle", 0.0) or 0.0),
            source_type=str(spec.get("source_type") or "reference"),
            board_points=spec.get("board", []),
        )
        if name not in self.references:
            self.reference_materialization_failures.add(name)
            return False
        return True

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

        # AKAZE é fallback absoluto e é sensivelmente mais caro. Não pagamos
        # esse custo para TODAS as fotos durante o primeiro "IDENTIFICANDO".
        # Guardamos somente a imagem cinza+mask já preparadas e materializamos
        # descritores AKAZE na primeira reacquisition que realmente precisar.
        akaze_descriptors = None
        akaze_canonical_points = np.empty((0, 2), dtype=np.float32)
        akaze_lazy_gray = gray.copy()
        akaze_lazy_tracking_mask = (
            tracking_mask.copy()
            if isinstance(tracking_mask, np.ndarray)
            else None
        )

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

        # Uma referência pode ser útil mesmo com pouco ORB/template porque
        # AKAZE será materializado somente se o caminho nominal falhar.
        if (
            descriptors is None
            and template_edges is None
            and akaze_lazy_gray is None
        ):
            return

        refs[key] = {
            "descriptors": descriptors,
            "canonical_points": canonical_points,
            "akaze_descriptors": akaze_descriptors,
            "akaze_canonical_points": akaze_canonical_points,
            "akaze_ready": False,
            "_akaze_lazy_gray": akaze_lazy_gray,
            "_akaze_lazy_tracking_mask": akaze_lazy_tracking_mask,
            "angle_deg": float(angle),
            "source_type": str(source_type or "reference"),
            "reference_to_canonical": reference_to_canonical,
            "template_edges": template_edges,
            "template_origin": template_origin,
            "template_support_mask": template_support_mask,
        }

    def _ensure_akaze_reference(self, key: str) -> bool:
        """Materializa AKAZE de UMA referência somente no fallback real."""
        if not self._ensure_reference(str(key or "")):
            return False
        ref = self.references.get(str(key or ""))
        if not isinstance(ref, dict):
            return False
        if bool(ref.get("akaze_ready")):
            return ref.get("akaze_descriptors") is not None

        # Marca antes do compute: falha também é cacheada e não vira retry por
        # frame durante uma cena difícil.
        ref["akaze_ready"] = True
        gray = ref.pop("_akaze_lazy_gray", None)
        tracking_mask = ref.pop("_akaze_lazy_tracking_mask", None)
        if not isinstance(gray, np.ndarray) or gray.size == 0:
            return False

        try:
            akaze = cv2.AKAZE_create(
                threshold=F3_TRACKING_AKAZE_THRESHOLD,
                nOctaves=4,
                nOctaveLayers=4,
            )
            keypoints, detected = akaze.detectAndCompute(
                gray,
                tracking_mask,
            )
        except Exception:
            keypoints, detected = [], None

        if (
            detected is None
            or len(keypoints) < F3_TRACKING_AKAZE_MIN_MATCHES
        ):
            ref["akaze_descriptors"] = None
            ref["akaze_canonical_points"] = np.empty(
                (0, 2),
                dtype=np.float32,
            )
            return False

        points = np.asarray(
            [kp.pt for kp in keypoints],
            dtype=np.float32,
        ).reshape(-1, 1, 2)
        try:
            canonical = cv2.transform(
                points,
                np.asarray(
                    ref.get("reference_to_canonical"),
                    dtype=np.float32,
                ).reshape(2, 3),
            ).reshape(-1, 2)
        except Exception:
            ref["akaze_descriptors"] = None
            ref["akaze_canonical_points"] = np.empty(
                (0, 2),
                dtype=np.float32,
            )
            return False

        ref["akaze_descriptors"] = detected
        ref["akaze_canonical_points"] = canonical
        return True


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
        current_to_canonical = (
            self.last_homography
            if self.last_homography is not None
            else self.last_matrix
        )
        canonical_to_previous = _invert_planar_transform(
            current_to_canonical
        )
        if canonical_to_previous is None:
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
        homography = (
            _compose_planar_transform(self.last_homography, motion)
            if self.last_homography is not None
            else None
        )
        return {
            "reference": self._last_reference,
            "matrix": matrix.astype(np.float32),
            "homography": (
                np.asarray(homography, dtype=np.float32).reshape(3, 3)
                if homography is not None
                else None
            ),
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

        if self.last_homography is not None:
            aligned = cv2.warpPerspective(
                frame,
                self.last_homography,
                (self.width, self.height),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT101,
            )
        else:
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
            current_to_canonical_homography=(
                self.last_homography.copy()
                if self.last_homography is not None
                else None
            ),
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
        reference_specs = self._calibrated_reference_specs(project)
        signature = self._signature(
            project,
            board,
            reference_specs=reference_specs,
        )
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

        # Configuração agora indexa o banco multivista sem decodificar todas as
        # imagens Full HD nem calcular ORB de todas elas. A referência necessária
        # é materializada no primeiro uso e então permanece em cache na sessão.
        self.reference_specs = {
            str(spec.get("key") or ""): deepcopy(spec)
            for spec in reference_specs
            if isinstance(spec, dict) and str(spec.get("key") or "")
        }
        if not self.reference_specs:
            self.reason = "reference_features_insufficient"
            return False

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

    def _neural_filter_pose_candidate(self, frame) -> dict | None:
        """Aquisição rápida: CNN dá orientação; filtro escuro fixa a geometria.

        A rede nunca vira autoridade semântica e sua regressão não é usada como
        pose final diretamente. Ela apenas escolhe, entre as correspondências
        geométricas possíveis do quadrilátero detectado, aquela compatível com
        a orientação aprendida das referências configuradas do projeto.
        """
        detector = getattr(self, "neural_pose_detector", None)
        if detector is None or not self.project or not self.canonical_board:
            self._last_neural_pose_debug = {
                "available": False,
                "reason": "neural_pose_detector_unavailable",
            }
            return None

        prediction = detector.predict(
            frame,
            project_name=self.project,
            canonical_board=self.canonical_board,
        )
        debug = {
            "available": bool(prediction.get("ready")),
            "reason": str(prediction.get("reason") or ""),
            "inference_ms": prediction.get("inference_ms"),
            "anchor_fit_mean_px": prediction.get("anchor_fit_mean_px"),
            "anchor_fit_max_px": prediction.get("anchor_fit_max_px"),
            "model_validation_mean_px": prediction.get(
                "model_validation_mean_px"
            ),
            "model_validation_p95_px": prediction.get(
                "model_validation_p95_px"
            ),
        }
        if not bool(prediction.get("ready")):
            self._last_neural_pose_debug = debug
            return None

        neural_anchors = prediction.get("current_anchors")
        canonical_anchors = canonical_pose_anchors(self.canonical_board)
        if (
            not isinstance(neural_anchors, np.ndarray)
            or canonical_anchors is None
        ):
            debug["available"] = False
            debug["reason"] = "neural_pose_anchors_invalid"
            self._last_neural_pose_debug = debug
            return None

        filter_candidates = _detect_dark_filter_candidates(
            frame,
            self.canonical_board,
            (self.width, self.height),
        )
        debug["filter_candidate_count"] = int(len(filter_candidates))
        if not filter_candidates:
            debug["available"] = False
            debug["reason"] = "neural_pose_filter_not_found"
            self._last_neural_pose_debug = debug
            return None

        validation = (
            prediction.get("validation")
            if isinstance(prediction.get("validation"), dict)
            else {}
        )
        try:
            max_snap_error = float(
                validation.get("runtime_max_snap_error_px", 140.0)
            )
        except (TypeError, ValueError):
            max_snap_error = 140.0
        max_snap_error = min(220.0, max(60.0, max_snap_error))

        best = None
        best_error = float("inf")
        attempts = []
        canonical_list = canonical_anchors.astype(
            np.float32
        ).reshape(-1, 2).tolist()

        for filter_candidate in filter_candidates:
            points = filter_candidate.get("points") or []
            matrices, candidate_mode = (
                _neural_filter_board_matrix_candidates(
                    points,
                    canonical_list,
                )
            )
            local_best = None
            local_error = float("inf")
            for matrix in matrices:
                try:
                    inverse = cv2.invertAffineTransform(
                        np.asarray(matrix, dtype=np.float32).reshape(2, 3)
                    )
                    projected_current = np.asarray(
                        transform_points(canonical_list, inverse),
                        dtype=np.float32,
                    ).reshape(-1, 2)
                except Exception:
                    continue
                if projected_current.shape != neural_anchors.shape:
                    continue
                errors = np.linalg.norm(
                    projected_current
                    - np.asarray(neural_anchors, dtype=np.float32),
                    axis=1,
                )
                mean_error = float(np.mean(errors))
                if mean_error < local_error:
                    local_error = mean_error
                    local_best = np.asarray(
                        matrix,
                        dtype=np.float32,
                    ).reshape(2, 3)

            corner_source = str(
                filter_candidate.get("corner_source")
                or "provided_quad"
            )
            attempts.append(
                {
                    "filter_source": str(
                        filter_candidate.get("source") or ""
                    ),
                    "filter_corner_source": corner_source,
                    "filter_score": round(
                        float(filter_candidate.get("score", 0.0) or 0.0),
                        4,
                    ),
                    "snap_error_px": (
                        round(local_error, 3)
                        if math.isfinite(local_error)
                        else None
                    ),
                    "pose_candidates": int(len(matrices)),
                    "candidate_mode": str(candidate_mode or ""),
                }
            )
            if local_best is not None and local_error < best_error:
                # D-071: minAreaRect continua útil como fallback estrutural,
                # mas seus quatro cantos retangulares não representam a
                # perspectiva física real exigida por uma homografia.
                projective = (
                    _projective_filter_pose_from_affine_hint(
                        points,
                        canonical_list,
                        local_best,
                    )
                    if corner_source != "min_area_rect_fallback"
                    else None
                )
                best_error = local_error
                best = {
                    "matrix": local_best,
                    "filter": filter_candidate,
                    "projective": projective,
                }

        debug["attempts"] = attempts
        debug["max_snap_error_px"] = round(max_snap_error, 3)
        debug["selected_snap_error_px"] = (
            round(best_error, 3)
            if math.isfinite(best_error)
            else None
        )
        if best is None or best_error > max_snap_error:
            debug["available"] = False
            debug["reason"] = "neural_pose_filter_snap_rejected"
            self._last_neural_pose_debug = debug
            return None

        matrix = np.asarray(
            best["matrix"],
            dtype=np.float32,
        ).reshape(2, 3)
        scale = affine_scale(matrix)
        rotation = affine_rotation_deg(matrix)
        if not (F3_TRACKING_MIN_SCALE <= scale <= F3_TRACKING_MAX_SCALE):
            debug["available"] = False
            debug["reason"] = "neural_pose_scale_rejected"
            self._last_neural_pose_debug = debug
            return None
        if abs(float(matrix[0, 2])) > (
            self.width * F3_TRACKING_MAX_TRANSLATION_FRACTION
        ):
            debug["available"] = False
            debug["reason"] = "neural_pose_translation_x_rejected"
            self._last_neural_pose_debug = debug
            return None
        if abs(float(matrix[1, 2])) > (
            self.height * F3_TRACKING_MAX_TRANSLATION_FRACTION
        ):
            debug["available"] = False
            debug["reason"] = "neural_pose_translation_y_rejected"
            self._last_neural_pose_debug = debug
            return None

        confidence = max(
            0.0,
            min(1.0, 1.0 - (best_error / max(1.0, max_snap_error))),
        )
        projective = (
            best.get("projective")
            if isinstance(best, dict)
            and isinstance(best.get("projective"), dict)
            else None
        )
        projective_h = (
            np.asarray(
                projective.get("homography"),
                dtype=np.float32,
            ).reshape(3, 3)
            if isinstance(projective, dict)
            and projective.get("homography") is not None
            else None
        )
        selected_filter = (
            best.get("filter")
            if isinstance(best, dict)
            and isinstance(best.get("filter"), dict)
            else {}
        )
        selected_points = _normalize_points(
            selected_filter.get("points"),
            minimum=4,
        )
        ordered_projective_points = (
            _normalize_points(
                projective.get("current_points"),
                minimum=4,
            )
            if isinstance(projective, dict)
            else []
        )
        corner_errors_to_neural = []
        if len(ordered_projective_points) == 4:
            try:
                corner_errors_to_neural = np.linalg.norm(
                    np.asarray(
                        ordered_projective_points,
                        dtype=np.float32,
                    ).reshape(-1, 2)
                    - np.asarray(
                        neural_anchors,
                        dtype=np.float32,
                    ).reshape(-1, 2),
                    axis=1,
                ).tolist()
            except Exception:
                corner_errors_to_neural = []

        debug.update(
            {
                "available": True,
                "reason": "neural_filter_pose_ready",
                "rotation_deg": round(float(rotation), 3),
                "scale": round(float(scale), 5),
                "confidence": round(float(confidence), 4),
                "filter_corner_source": str(
                    selected_filter.get("corner_source")
                    or "provided_quad"
                ),
                "filter_points": [
                    [round(float(point[0]), 3), round(float(point[1]), 3)]
                    for point in selected_points
                ],
                "neural_anchor_points": [
                    [round(float(point[0]), 3), round(float(point[1]), 3)]
                    for point in np.asarray(
                        neural_anchors,
                        dtype=np.float32,
                    ).reshape(-1, 2)
                ],
                "filter_corner_errors_to_neural_px": [
                    round(float(value), 3)
                    for value in corner_errors_to_neural
                ],
                "filter_corner_error_mean_px": (
                    round(float(np.mean(corner_errors_to_neural)), 3)
                    if corner_errors_to_neural
                    else None
                ),
                "filter_corner_error_max_px": (
                    round(float(np.max(corner_errors_to_neural)), 3)
                    if corner_errors_to_neural
                    else None
                ),
                "projective_pose_ready": bool(projective_h is not None),
                "projective_reprojection_mean_px": (
                    round(
                        float(projective.get("mean_reprojection_px", 0.0)),
                        4,
                    )
                    if isinstance(projective, dict)
                    else None
                ),
                "projective_reprojection_max_px": (
                    round(
                        float(projective.get("max_reprojection_px", 0.0)),
                        4,
                    )
                    if isinstance(projective, dict)
                    else None
                ),
            }
        )
        self._last_neural_pose_debug = debug
        return {
            "reference": f"neural_pose:{self.project}",
            "matrix": matrix,
            "matches": 4,
            "inliers": 4,
            "ratio": confidence,
            "rotation_deg": float(rotation),
            "scale": float(scale),
            "score": 40.0 + confidence * 10.0,
            "source_type": "neural_filter_pose",
            "fallback": "neural_filter_pose",
            "neural_snap_error_px": float(best_error),
            "homography": (
                projective_h.copy()
                if projective_h is not None
                else None
            ),
            "filter_points": deepcopy(
                selected_filter.get("points") or []
            ),
            "filter_corner_source": str(
                selected_filter.get("corner_source")
                or "provided_quad"
            ),
        }

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
            or not self.has_reference(str(key or ""))
        ):
            return None
        if not self._ensure_reference(str(key or "")):
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
            self._ensure_akaze_reference(str(key))
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

    def align(
        self,
        frame,
        frame_id=None,
        *,
        preferred_reference_keys=None,
    ) -> F3TrackingResult:
        if not _valid_frame(frame):
            return F3TrackingResult(False, frame, reason="invalid_frame")
        if not self.ready:
            return F3TrackingResult(False, frame, reason=self.reason)
        if frame.shape[:2] != (self.height, self.width):
            return F3TrackingResult(False, frame, reason="resolution_mismatch")
        if (
            frame_id is not None
            and frame_id == self.last_frame_id
            and self.last_result is not None
        ):
            return self.last_result

        now = time.monotonic()
        force_absolute_reacquire = bool(
            getattr(self, "_force_absolute_reacquire", False)
        )
        if (
            not force_absolute_reacquire
            and self.last_matrix is not None
            and self.last_result is not None
            and self.last_result.locked
            and now - self.last_compute_s < F3_TRACKING_REFRESH_S
        ):
            if self.last_homography is not None:
                aligned = cv2.warpPerspective(
                    frame,
                    self.last_homography,
                    (self.width, self.height),
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_REFLECT101,
                )
            else:
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
                current_to_canonical_homography=(
                    self.last_homography.copy()
                    if self.last_homography is not None
                    else None
                ),
                source_type=self.last_result.source_type,
                evidence_current=bool(self.last_result.evidence_current),
            )
            self.last_result = result
            self.last_frame_id = frame_id
            return result

        self._last_rotation_jump_rejections = []
        candidates = []
        gray = None
        orb_available = False
        akaze_available = False

        # Depois do primeiro LOCK, continuidade óptica é o caminho nominal mais
        # barato. Não faz sentido pagar ORB full-HD antes de tentar acompanhar a
        # pose que já foi confirmada no frame anterior.
        if self.last_matrix is not None and not force_absolute_reacquire:
            gray = self._gray(frame)
            if gray is not None:
                temporal = self._temporal_candidate(gray)
                if temporal is not None:
                    candidates.append(temporal)

        # D-067: aquisição/reacquisition começa pelo prior neural de GEOMETRIA.
        # A CNN só desambigua a pose; o quadrilátero final vem do filtro
        # estrutural detectado no frame. Se o modelo não existir/falhar, o
        # pipeline legado abaixo permanece integralmente disponível.
        if not candidates:
            neural = self._neural_filter_pose_candidate(frame)
            if neural is not None:
                neural_candidates = self._filter_abrupt_rotation_candidates(
                    [neural],
                    source="neural_filter_pose",
                )
                if neural_candidates:
                    candidates = neural_candidates

        all_reference_keys = list(self._available_reference_keys())
        preferred_keys = []
        for key in preferred_reference_keys or ():
            name = str(key or "")
            if (
                name
                and name in all_reference_keys
                and name not in preferred_keys
            ):
                preferred_keys.append(name)
        remaining_keys = [
            key for key in all_reference_keys if key not in preferred_keys
        ]
        reference_groups = (
            [
                *[[key] for key in preferred_keys],
                *([remaining_keys] if remaining_keys else []),
            ]
            if preferred_keys
            else [all_reference_keys]
        )

        # Fallback absoluto legado. O grayscale/CLAHE full-HD só é calculado se
        # temporal + neural não resolverem a pose.
        if not candidates:
            if gray is None:
                gray = self._gray(frame)
            if gray is None:
                self.consecutive_misses += 1
                held = self._held_lock_result(frame, now)
                if held is not None:
                    self.last_result = held
                    self.last_frame_id = frame_id
                    self.last_compute_s = now
                    return held
                self.last_matrix = None
                self.last_homography = None
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
            try:
                current_kp, current_desc = orb.detectAndCompute(gray, None)
            except Exception:
                current_kp, current_desc = [], None
            orb_available = bool(
                current_desc is not None
                and len(current_kp) >= F3_TRACKING_MIN_MATCHES
            )

            if orb_available:
                for group in reference_groups:
                    if not group:
                        continue
                    group_candidates = []
                    for key in group:
                        if not self._ensure_reference(key):
                            continue
                        candidate = self._candidate(
                            current_kp,
                            current_desc,
                            key,
                        )
                        if candidate is not None:
                            group_candidates.append(candidate)
                    group_candidates = self._filter_abrupt_rotation_candidates(
                        group_candidates,
                        source="orb",
                    )
                    if group_candidates:
                        candidates = group_candidates
                        break

        # Reacquisition absoluta mais cara somente quando os caminhos rápidos
        # não produziram pose.
        if not candidates:
            if gray is None:
                gray = self._gray(frame)
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
                for group in reference_groups:
                    if not group:
                        continue
                    group_candidates = []
                    for key in group:
                        if not self._ensure_akaze_reference(key):
                            continue
                        candidate = self._akaze_candidate(
                            akaze_kp,
                            akaze_desc,
                            key,
                        )
                        if candidate is not None:
                            group_candidates.append(candidate)
                    group_candidates = self._filter_abrupt_rotation_candidates(
                        group_candidates,
                        source="akaze",
                    )
                    if group_candidates:
                        candidates = group_candidates
                        break

        if not candidates:
            if gray is None:
                gray = self._gray(frame)
            try:
                current_edges = cv2.Canny(gray, 45, 135)
            except Exception:
                current_edges = None
            for group in reference_groups:
                if not group:
                    continue
                group_candidates = []
                for key in group:
                    if not self._ensure_reference(key):
                        continue
                    candidate = self._template_candidate(
                        current_edges,
                        key,
                    )
                    if candidate is not None:
                        group_candidates.append(candidate)
                group_candidates = self._filter_abrupt_rotation_candidates(
                    group_candidates,
                    source="edge_template",
                )
                if group_candidates:
                    candidates = group_candidates
                    break

        if not candidates:
            self.consecutive_misses += 1
            held = self._held_lock_result(frame, now)
            if held is not None:
                self.last_result = held
                self.last_frame_id = frame_id
                self.last_compute_s = now
                return held

            self.last_matrix = None
            self.last_homography = None
            self.last_gray = None
            self.last_verified_s = 0.0
            self.consecutive_misses = 0
            self._last_reference = ""
            neural_reason = str(
                (self._last_neural_pose_debug or {}).get("reason") or ""
            )
            result = F3TrackingResult(
                False,
                frame,
                reason=(
                    "current_features_insufficient"
                    if not orb_available and not akaze_available
                    else (
                        neural_reason
                        if neural_reason
                        and neural_reason
                        not in {
                            "neural_tracking_model_missing",
                            "neural_tracking_model_not_validated",
                        }
                        else "object_not_locked"
                    )
                ),
                evidence_current=False,
            )
            self.last_result = result
            self.last_frame_id = frame_id
            self.last_compute_s = now
            return result

        best = max(candidates, key=self._candidate_rank)
        matrix = np.asarray(
            best["matrix"],
            dtype=np.float32,
        ).reshape(2, 3)
        homography = None
        if best.get("homography") is not None:
            try:
                candidate_h = np.asarray(
                    best.get("homography"),
                    dtype=np.float32,
                ).reshape(3, 3)
                if np.all(np.isfinite(candidate_h)):
                    homography = candidate_h
            except Exception:
                homography = None
        continuous, _closeness = self._matrix_continuity(matrix)
        if self.last_matrix is not None and continuous:
            fallback = str(best.get("fallback") or "")
            alpha = (
                0.72
                if fallback == "temporal_flow"
                else (
                    0.82
                    if fallback == "neural_filter_pose"
                    else 0.54
                )
            )
            matrix = (
                (1.0 - alpha) * self.last_matrix.astype(np.float32)
                + alpha * matrix.astype(np.float32)
            ).astype(np.float32)

        # O próximo frame pode usar LK; calcule a mesma representação somente
        # depois de a aquisição neural ter evitado ORB/AKAZE neste frame.
        if gray is None:
            gray = self._gray(frame)

        self.last_matrix = matrix
        self.last_homography = (
            homography.copy()
            if homography is not None
            else None
        )
        self.last_verified_rotation_deg = float(
            affine_rotation_deg(matrix)
        )
        self._last_reference = str(best["reference"])
        self.last_compute_s = now
        self.last_frame_id = frame_id
        self.last_gray = (
            gray.copy()
            if isinstance(gray, np.ndarray)
            else None
        )
        self.last_verified_s = now
        self.consecutive_misses = 0

        if homography is not None:
            aligned = cv2.warpPerspective(
                frame,
                homography,
                (self.width, self.height),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT101,
            )
        else:
            aligned = cv2.warpAffine(
                frame,
                matrix,
                (self.width, self.height),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT101,
            )
        fallback = str(best.get("fallback") or "")
        if fallback == "neural_filter_pose":
            lock_reason = "locked_neural_filter_pose"
        elif fallback == "edge_template":
            lock_reason = "locked_template"
        elif fallback == "adaptive_edge_template":
            lock_reason = "locked_adaptive_template"
        elif fallback == "akaze_reacquire":
            lock_reason = "locked_akaze"
        elif fallback == "temporal_flow":
            lock_reason = "locked_temporal"
        else:
            lock_reason = "locked"

        result = F3TrackingResult(
            True,
            aligned,
            reference=str(best["reference"]),
            matches=int(best["matches"]),
            inliers=int(best["inliers"]),
            inlier_ratio=float(best["ratio"]),
            rotation_deg=float(affine_rotation_deg(matrix)),
            scale=float(affine_scale(matrix)),
            reason=lock_reason,
            current_to_canonical=matrix.copy(),
            current_to_canonical_homography=(
                homography.copy()
                if homography is not None
                else None
            ),
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


def _hybrid_semantic_authority_active(app) -> bool:
    """Indica que tracking fornece geometria, mas não possui decisão semântica.

    A autoridade híbrida D-065 deve decidir ON/OFF/INCERTO e CHECK OK/NG da
    mesma forma com tracking OFF ou ON. O tracking pode exigir LOCK/frescor para
    saber onde estão placa e máscaras, mas não instala uma segunda regra de
    aprovação, reprovação ou avanço da sequência.
    """
    analysis = getattr(app, "_display_auto_last_analysis", None)
    if isinstance(analysis, dict) and (
        analysis.get("hybrid_visual_authority") is True
        or str(analysis.get("semantic_authority") or "")
        == "f3_hybrid_same_mask_neural_authority"
    ):
        return True

    owner = getattr(app, "_display_f3_check_analyzer_authority", None)
    analyzer = getattr(owner, "analyzer", None)
    if analyzer is None:
        analyzer = getattr(app, "_display_auto_analyzer", None)
    semantic = getattr(analyzer, "semantic", None)
    if semantic is not None and semantic.__class__.__name__ == "F3HybridCheckAnalyzer":
        return True
    return bool(
        analyzer is not None
        and analyzer.__class__.__name__ == "F3HybridCheckAnalyzer"
    )


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


def _clear_tracking_runtime_transients(
    app,
    *,
    reason: str,
    resync_enabled: bool,
) -> None:
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
    app._display_f3_tracking_queued_frame_token = None
    app._display_f3_semantic_pipeline_status = None
    app._display_f3_tracking_prefetch_submissions = 0
    app._display_f3_tracking_prefetch_replacements = 0
    app._display_auto_precomputed_payload = None
    app._display_auto_analysis_frame_override = None
    app._display_f3_tracking_raw_preview_frame = None
    app._display_f3_tracking_result = None
    app._display_f3_tracking_live_geometry = None
    app._display_f3_tracking_analysis_frame = None
    app._display_f3_tracking_analysis_pending = False
    app._display_f3_tracking_pending_raw_frame = None

    enabled = bool(
        tracking_enabled(app)
        if resync_enabled
        else getattr(app, "_display_f3_object_tracking_enabled", False)
    )
    app._display_f3_object_tracking_last_status = {
        "enabled": enabled,
        "locked": False,
        "reason": str(reason or "reset"),
    }


def reset_tracking_runtime(app) -> None:
    """Reset completo usado quando configuração/projeto pode ter mudado."""
    runtime = get_tracking_runtime(app)
    if runtime is not None:
        runtime.reset()
    _clear_tracking_runtime_transients(
        app,
        reason="reset",
        resync_enabled=True,
    )


def reset_tracking_cycle(app) -> None:
    """Nova placa: perde toda pose, mas preserva referências da mesma sessão."""
    runtime = get_tracking_runtime(app)
    if runtime is not None:
        runtime.reset_pose()
    _clear_tracking_runtime_transients(
        app,
        reason="cycle_pose_reset",
        resync_enabled=False,
    )


def _runtime_reference_available(runtime, key: str) -> bool:
    """Consulta referência sem exigir materialização prévia.

    O tracker real expõe has_reference() para o banco lazy. O fallback por
    references preserva compatibilidade com adapters/test doubles estruturais.
    """
    checker = getattr(runtime, "has_reference", None)
    if callable(checker):
        return bool(checker(key))
    references = getattr(runtime, "references", None)
    return bool(isinstance(references, dict) and str(key or "") in references)


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
        if key in seen or not _runtime_reference_available(runtime, key):
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
        current = _current_check(app)
        current_check_id = (
            str(current.get("id") or "")
            if isinstance(current, dict)
            else ""
        )
        preferred_reference_keys = []
        if current_check_id:
            preferred_reference_keys.append(f"check:{current_check_id}")
        preferred_reference_keys.append("board_off")

        result = runtime.align(
            frame,
            frame_id=analysis_frame_id,
            preferred_reference_keys=preferred_reference_keys,
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
        "neural_pose": deepcopy(
            getattr(runtime, "_last_neural_pose_debug", {})
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
    """Retorna CURRENT -> espaço de análise preservando perspectiva D-070."""
    if result is None or not result.locked:
        return None, "canonical"

    current_to_canonical = (
        result.current_to_canonical_homography
        if result.current_to_canonical_homography is not None
        else result.current_to_canonical
    )
    if current_to_canonical is None:
        return None, "canonical"

    runtime = get_tracking_runtime(app)
    current = _current_check(app)
    if runtime is None or not isinstance(current, dict):
        return current_to_canonical, "canonical"

    check_id = str(current.get("id") or "")
    reference_key = f"check:{check_id}"
    reference = runtime.references.get(reference_key)
    if not isinstance(reference, dict):
        reference = runtime.reference_specs.get(reference_key)
    mapping = (
        reference.get("reference_to_canonical")
        if isinstance(reference, dict)
        else None
    )
    if mapping is None:
        return current_to_canonical, "canonical"

    canonical_to_check = _invert_planar_transform(mapping)
    if canonical_to_check is None:
        return current_to_canonical, "canonical"

    current_to_check = _compose_planar_transform(
        canonical_to_check,
        current_to_canonical,
    )
    if current_to_check is None:
        return current_to_canonical, "canonical"
    return current_to_check, f"check:{check_id}"


def _analysis_alignment_for_current_check(
    app,
    raw_frame,
    result: F3TrackingResult | None,
):
    """Gera frame normalizado usando affine ou homografia conforme a pose."""
    if not _valid_frame(raw_frame):
        return None, None

    matrix, _space = _analysis_transform_for_current_check(app, result)
    transform = _as_planar_transform(matrix)
    if transform is None:
        return None, None

    runtime = get_tracking_runtime(app)
    if runtime is None:
        return None, None

    try:
        if transform.shape == (3, 3):
            aligned = cv2.warpPerspective(
                raw_frame,
                transform,
                (int(runtime.width), int(runtime.height)),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT101,
            )
        else:
            aligned = cv2.warpAffine(
                raw_frame,
                transform,
                (int(runtime.width), int(runtime.height)),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT101,
            )
    except Exception:
        return None, None
    return aligned, transform


def _update_tracking_live_geometry(
    app,
    raw_frame,
    result: F3TrackingResult | None,
) -> None:
    """Projeta contorno+28 ROIs no RAW; D-070 preserva perspectiva do filtro."""
    if (
        result is None
        or not result.locked
        or (
            result.current_to_canonical is None
            and result.current_to_canonical_homography is None
        )
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

    current_to_canonical = (
        result.current_to_canonical_homography
        if result.current_to_canonical_homography is not None
        else result.current_to_canonical
    )
    source_to_current = _invert_planar_transform(current_to_canonical)
    if source_to_current is None:
        app._display_f3_tracking_live_geometry = None
        return

    projective_geometry = bool(
        _as_planar_transform(current_to_canonical) is not None
        and _as_planar_transform(current_to_canonical).shape == (3, 3)
    )
    geometry_space = "canonical_projective" if projective_geometry else "canonical"

    current = _current_check(app)
    current_check_id = (
        str(current.get("id") or "")
        if isinstance(current, dict)
        else ""
    )
    current_mask_states = (
        current.get("mask_states", {})
        if isinstance(current, dict)
        and isinstance(current.get("mask_states"), dict)
        else {}
    )
    if not current_mask_states and current_check_id:
        for configured_check in project.get("checks", []) or []:
            if (
                isinstance(configured_check, dict)
                and str(configured_check.get("id") or "")
                == current_check_id
            ):
                states = configured_check.get("mask_states")
                if isinstance(states, dict):
                    current_mask_states = states
                break
    if not current_mask_states and current_check_id:
        try:
            configured_check = repository.carregar_check(
                project_name,
                current_check_id,
            )
        except Exception:
            configured_check = None
        states = (
            configured_check.get("mask_states")
            if isinstance(configured_check, dict)
            else None
        )
        if isinstance(states, dict):
            current_mask_states = states

    expected_on_count = sum(
        1
        for state in current_mask_states.values()
        if str(state or "").strip().lower() == "on"
    )
    alignment_required = bool(
        expected_on_count >= F3_TRACKING_LUMINOUS_MIN_COMPONENTS
    )
    spatial_alignment_ready = bool(
        not alignment_required
        or str(result.source_type or "") == "luminous_segment_grid"
    )
    spatial_alignment_source = (
        "luminous_segment_grid"
        if spatial_alignment_ready and alignment_required
        else (
            "projective_filter_structural"
            if alignment_required and projective_geometry
            else (
                "structural_only"
                if alignment_required
                else "not_required"
            )
        )
    )

    # D-070: LK/cached transform pode manter a visualização somente depois que
    # o alinhamento fino foi provado. Enquanto ainda estamos ALINHANDO, o próximo
    # job volta a tentar aquisição absoluta CNN+filtro em vez de perpetuar pose.
    runtime._force_absolute_reacquire = bool(
        alignment_required and not spatial_alignment_ready
    )

    board_current = transform_points(source_board, source_to_current)
    masks_current = []
    for mask in source_masks:
        transformed = transform_mask(mask, source_to_current)
        if transformed is None:
            continue
        masks_current.append(
            sincronizar_formato_mascara_display(mask, transformed)
        )

    h, w = raw_frame.shape[:2]
    app._display_f3_tracking_live_geometry = {
        "locked": True,
        "reference": str(result.reference or ""),
        "source_type": str(result.source_type or ""),
        "geometry_space": geometry_space,
        "geometry_transform_type": (
            "homography_3x3"
            if projective_geometry
            else "affine_2x3"
        ),
        "absolute_reacquire_required": bool(
            runtime._force_absolute_reacquire
        ),
        "check_id": current_check_id,
        "expected_on_count": int(expected_on_count),
        "alignment_required": bool(alignment_required),
        "spatial_alignment_ready": bool(spatial_alignment_ready),
        "spatial_alignment_source": spatial_alignment_source,
        "luminous_core_validated_mask_ids": list(
            getattr(result, "luminous_validated_mask_ids", ()) or ()
        ),
        "luminous_alignment_mode": str(
            getattr(result, "luminous_alignment_mode", "") or ""
        ),
        "luminous_evidence_current": bool(
            str(result.source_type or "") == "luminous_segment_grid"
            and bool(result.evidence_current)
        ),
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
    """Executa tracking/warp no executor pesado e mede cada estágio."""
    started = time.perf_counter()

    align_started = time.perf_counter()
    aligned, result = align_frame_for_f3(
        app,
        raw_frame,
        frame_token=frame_token,
    )
    align_elapsed_ms = max(
        0.0,
        (time.perf_counter() - align_started) * 1000.0,
    )

    geometry = None
    analysis_frame = None
    geometry_elapsed_ms = 0.0
    analysis_warp_elapsed_ms = 0.0
    if result is not None and bool(result.locked):
        # A geometria usa apenas matrizes; o único warp adicional cria o frame
        # de análise do CHECK atual e também fica fora do Tk.
        geometry_started = time.perf_counter()
        previous_geometry = getattr(app, "_display_f3_tracking_live_geometry", None)
        try:
            _update_tracking_live_geometry(app, raw_frame, result)
            geometry = deepcopy(
                getattr(app, "_display_f3_tracking_live_geometry", None)
            )
        finally:
            app._display_f3_tracking_live_geometry = previous_geometry
        geometry_elapsed_ms = max(
            0.0,
            (time.perf_counter() - geometry_started) * 1000.0,
        )

        warp_started = time.perf_counter()
        analysis_frame, _matrix = _analysis_alignment_for_current_check(
            app,
            raw_frame,
            result,
        )
        if not _valid_frame(analysis_frame):
            analysis_frame = aligned
        analysis_warp_elapsed_ms = max(
            0.0,
            (time.perf_counter() - warp_started) * 1000.0,
        )
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
        "stage_elapsed_ms": {
            "align": round(align_elapsed_ms, 2),
            "geometry_projection": round(geometry_elapsed_ms, 2),
            "analysis_warp": round(analysis_warp_elapsed_ms, 2),
        },
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
    app._display_f3_tracking_queued_frame_token = deepcopy(frame_token)
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
    finished_at = time.perf_counter()
    elapsed_ms = max(
        0.0,
        (finished_at - started) * 1000.0,
    )
    queue_age_ms = max(
        0.0,
        (finished_at - float(submitted_at_s)) * 1000.0,
    )
    queue_wait_ms = max(0.0, queue_age_ms - elapsed_ms)
    source_age_ms = max(0.0, float(source_age_ms))
    return {
        "generation": int(generation),
        "frame_token": frame_token,
        # Idade operacional completa do snapshot: tracking que o produziu +
        # espera na fila única + compute semântico.
        "age_ms": round(source_age_ms + queue_age_ms, 2),
        "source_age_ms": round(source_age_ms, 2),
        "semantic_elapsed_ms": round(elapsed_ms, 2),
        "queue_age_ms": round(queue_age_ms, 2),
        "queue_wait_ms": round(queue_wait_ms, 2),
        "analysis_frame": analysis_frame,
        # D-072: o frame RAW e a geometria abaixo pertencem exatamente ao
        # mesmo snapshot usado pelo analyzer. Eles seguem juntos até um
        # eventual freeze de NG; nunca são reconstruídos a partir do estado
        # live depois que a decisão foi tomada.
        "raw_frame": raw_frame,
        "tracking_geometry": deepcopy(tracking_geometry),
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


def _camera_frame_gap(source_token, current_token) -> int | None:
    if (
        isinstance(source_token, tuple)
        and isinstance(current_token, tuple)
        and len(source_token) >= 2
        and len(current_token) >= 2
        and source_token[0] == "camera"
        and current_token[0] == "camera"
    ):
        try:
            return abs(int(current_token[1]) - int(source_token[1]))
        except (TypeError, ValueError):
            return None
    return None


def _queue_latest_tracking_behind_semantic(
    app,
    raw_frame,
    *,
    heavy_due: bool,
) -> bool:
    """Mantém exatamente um tracking latest-frame-wins atrás da semântica.

    Não cria worker. Enquanto o único executor está ocupado com a semântica,
    deixa um único tracking HIGH pendente. Frames novos substituem esse job
    pendente pela mesma chave. Assim que a semântica termina, o executor já
    recebe o frame mais recente sem esperar outro ciclo Tk.
    """
    if not bool(heavy_due) or not _valid_frame(raw_frame):
        return False

    semantic_future = getattr(app, "_display_f3_semantic_future", None)
    if semantic_future is None or semantic_future.done():
        return False

    token_fn = getattr(app, "_display_auto_frame_token", None)
    try:
        current_token = (
            token_fn(raw_frame)
            if callable(token_fn)
            else ("object", id(raw_frame))
        )
    except Exception:
        current_token = ("object", id(raw_frame))

    tracking_future = getattr(app, "_display_f3_tracking_future", None)
    queued_token = getattr(
        app,
        "_display_f3_tracking_queued_frame_token",
        None,
    )

    replacing_pending = bool(
        tracking_future is not None
        and not tracking_future.done()
        and not tracking_future.running()
    )
    if tracking_future is not None:
        if tracking_future.running():
            return False
        if not tracking_future.done() and queued_token == current_token:
            return False

    future = _submit_live_tracking_job(app, raw_frame)
    if future is None:
        return False

    app._display_f3_tracking_prefetch_submissions = int(
        getattr(app, "_display_f3_tracking_prefetch_submissions", 0) or 0
    ) + 1
    if replacing_pending:
        app._display_f3_tracking_prefetch_replacements = int(
            getattr(app, "_display_f3_tracking_prefetch_replacements", 0) or 0
        ) + 1
    return True


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


def _analysis_has_positive_on_evidence(analysis: dict | None) -> bool:
    """Indica que o snapshot contém emissão positiva do CHECK atual."""
    if not isinstance(analysis, dict) or not bool(analysis.get("ready")):
        return False
    try:
        if int(analysis.get("positive_on_matched_count", 0) or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    if analysis.get("luminous_core_confirmed_mask_ids"):
        return True
    for item in analysis.get("mask_results") or ():
        if not isinstance(item, dict):
            continue
        if (
            str(item.get("expected") or "").strip().lower() == "on"
            and str(item.get("classified") or "").strip().lower() == "on"
            and item.get("matched") is not False
        ):
            return True
    return False


def _intermittent_snapshot_acceptable(
    payload: dict | None,
    current_context: dict | None,
    current_token,
) -> bool:
    """Aceita por pouco tempo o frame ON congelado de um CHECK intermitente.

    O frame da câmera continua latest-frame-wins. Esta exceção vale somente para
    o snapshot de análise/tracking: quando o BLUE pisca, o worker pode terminar
    depois que a câmera já entrou na fase OFF. Se o snapshot pertence ao mesmo
    CHECK e contém emissão positiva coerente, ele continua analisável durante a
    janela temporal do pisca.
    """
    if not isinstance(payload, dict) or not isinstance(current_context, dict):
        return False
    if not bool(current_context.get("intermittent", False)):
        return False

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
    if not (
        0.0
        <= age_ms
        <= F3_TRACKING_INTERMITTENT_SNAPSHOT_MAX_AGE_MS
    ):
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
        if gap > F3_TRACKING_INTERMITTENT_SNAPSHOT_MAX_FRAME_GAP:
            return False

    project_name = str(current_context.get("project_name") or "")
    check_id = str(current_context.get("check_id") or "")

    payload_context = payload.get("context")
    if isinstance(payload_context, dict):
        if (
            str(payload_context.get("project_name") or "") != project_name
            or str(payload_context.get("check_id") or "") != check_id
        ):
            return False

    analysis = payload.get("analysis")
    if isinstance(analysis, dict):
        if (
            str(analysis.get("project_name") or project_name) != project_name
            or str(analysis.get("check_id") or check_id) != check_id
        ):
            return False
        if not bool(analysis.get("tracking_snapshot_explicit")):
            return False
        return _analysis_has_positive_on_evidence(analysis)

    geometry = payload.get("geometry")
    if isinstance(geometry, dict):
        geometry_check_id = str(geometry.get("check_id") or "")
        if geometry_check_id and geometry_check_id != check_id:
            return False
        if (
            bool(geometry.get("locked"))
            and str(geometry.get("source_type") or "")
            == "luminous_segment_grid"
            and bool(geometry.get("luminous_evidence_current"))
            and bool(geometry.get("luminous_core_validated_mask_ids"))
        ):
            return True

    result = payload.get("result")
    if result is not None:
        if (
            bool(getattr(result, "locked", False))
            and bool(getattr(result, "evidence_current", False))
            and str(getattr(result, "source_type", "") or "")
            == "luminous_segment_grid"
            and bool(
                getattr(result, "luminous_validated_mask_ids", ()) or ()
            )
        ):
            return True

    return False


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
                normal_fresh = _tracking_result_operationally_fresh(
                    payload,
                    current_token,
                )
                intermittent_snapshot = _intermittent_snapshot_acceptable(
                    payload,
                    current_context,
                    current_token,
                )
                semantic_pipeline = {
                    "frame_token": deepcopy(payload.get("frame_token")),
                    "camera_frame_token": deepcopy(current_token),
                    "frame_gap": _camera_frame_gap(
                        payload.get("frame_token"),
                        current_token,
                    ),
                    "source_age_ms": round(
                        float(payload.get("source_age_ms", 0.0) or 0.0),
                        2,
                    ),
                    "queue_wait_ms": round(
                        float(payload.get("queue_wait_ms", 0.0) or 0.0),
                        2,
                    ),
                    "semantic_elapsed_ms": round(
                        float(payload.get("semantic_elapsed_ms", 0.0) or 0.0),
                        2,
                    ),
                    "queue_age_ms": round(
                        float(payload.get("queue_age_ms", 0.0) or 0.0),
                        2,
                    ),
                    "total_age_ms": round(
                        float(payload.get("age_ms", 0.0) or 0.0),
                        2,
                    ),
                    "same_context": bool(same_context),
                    "normal_fresh": bool(normal_fresh),
                    "intermittent_snapshot": bool(intermittent_snapshot),
                    "accepted_for_runtime": bool(
                        same_context
                        and (normal_fresh or intermittent_snapshot)
                        and isinstance(payload.get("analysis"), dict)
                        and _valid_frame(payload.get("analysis_frame"))
                    ),
                }
                self._display_f3_semantic_pipeline_status = semantic_pipeline
                tracking_status = getattr(
                    self,
                    "_display_f3_object_tracking_last_status",
                    None,
                )
                if isinstance(tracking_status, dict):
                    tracking_status = dict(tracking_status)
                    tracking_status["semantic_pipeline"] = deepcopy(
                        semantic_pipeline
                    )
                    executor = getattr(
                        self,
                        "_display_f3_heavy_executor",
                        None,
                    )
                    if executor is not None:
                        try:
                            tracking_status["heavy_executor"] = executor.stats()
                        except Exception:
                            pass
                    self._display_f3_object_tracking_last_status = tracking_status

                if (
                    same_context
                    and (normal_fresh or intermittent_snapshot)
                    and isinstance(payload.get("analysis"), dict)
                    and _valid_frame(payload.get("analysis_frame"))
                ):
                    if intermittent_snapshot and not normal_fresh:
                        analysis = deepcopy(payload.get("analysis") or {})
                        analysis.update(
                            intermittent_snapshot_capture=True,
                            intermittent_snapshot_frame_token=deepcopy(
                                payload.get("frame_token")
                            ),
                            intermittent_snapshot_age_ms=float(
                                payload.get("age_ms", 0.0) or 0.0
                            ),
                            intermittent_snapshot_policy=(
                                "positive_on_frozen_snapshot"
                            ),
                        )
                        payload = dict(payload)
                        payload["analysis"] = analysis
                    ready_semantic = payload

        if isinstance(ready_semantic, dict):
            self._display_auto_precomputed_payload = {
                "frame_token": ready_semantic.get("frame_token"),
                "raw_frame": ready_semantic.get("raw_frame"),
                "tracking_geometry": deepcopy(
                    ready_semantic.get("tracking_geometry")
                ),
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
                    self._display_f3_tracking_queued_frame_token = None
                    compute_ms = float(payload.get("elapsed_ms", 0.0) or 0.0)
                    self._display_f3_tracking_last_compute_ms = compute_ms
                    status = getattr(
                        self,
                        "_display_f3_object_tracking_last_status",
                        None,
                    )
                    if isinstance(status, dict):
                        status = dict(status)
                        status["worker_elapsed_ms"] = round(
                            compute_ms,
                            2,
                        )
                        status["worker_age_ms"] = round(
                            float(payload.get("age_ms", 0.0) or 0.0),
                            2,
                        )
                        status["worker_frame_token"] = deepcopy(
                            payload.get("frame_token")
                        )
                        status["worker_stage_elapsed_ms"] = deepcopy(
                            payload.get("stage_elapsed_ms") or {}
                        )
                        semantic_pipeline = getattr(
                            self,
                            "_display_f3_semantic_pipeline_status",
                            None,
                        )
                        if isinstance(semantic_pipeline, dict):
                            status["semantic_pipeline"] = deepcopy(
                                semantic_pipeline
                            )
                        status["pipeline_prefetch"] = {
                            "submissions": int(
                                getattr(
                                    self,
                                    "_display_f3_tracking_prefetch_submissions",
                                    0,
                                )
                                or 0
                            ),
                            "replacements": int(
                                getattr(
                                    self,
                                    "_display_f3_tracking_prefetch_replacements",
                                    0,
                                )
                                or 0
                            ),
                            "queued_frame_token": deepcopy(
                                getattr(
                                    self,
                                    "_display_f3_tracking_queued_frame_token",
                                    None,
                                )
                            ),
                        }
                        executor = getattr(
                            self,
                            "_display_f3_heavy_executor",
                            None,
                        )
                        if executor is not None:
                            try:
                                status["heavy_executor"] = executor.stats()
                            except Exception:
                                pass
                        self._display_f3_object_tracking_last_status = status

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
                    current_context = None
                    context_fn = getattr(
                        self,
                        "_display_auto_current_context",
                        None,
                    )
                    if callable(context_fn):
                        try:
                            current_context = context_fn()
                        except Exception:
                            current_context = None
                    intermittent_snapshot = _intermittent_snapshot_acceptable(
                        payload,
                        current_context,
                        current_token,
                    )

                    if (
                        (operational_fresh or intermittent_snapshot)
                        and _valid_frame(analysis_frame)
                    ):
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

            # D-068: enquanto a semântica ocupa o único worker, mantenha UM
            # tracking pendente com o frame mais recente. O executor substitui
            # o pendente anterior pela mesma chave; nunca há fila histórica.
            if (
                semantic_future is not None
                and not semantic_future.done()
            ):
                _queue_latest_tracking_behind_semantic(
                    self,
                    raw_latest,
                    heavy_due=heavy_due,
                )
                tracking_future = getattr(
                    self,
                    "_display_f3_tracking_future",
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
            tracking_is_enabled = bool(tracking_enabled(app))
            rotation = int(visual_rotation or 0) % 360
            mirror_debug = {
                "hook_active": True,
                "tracking_enabled": tracking_is_enabled,
                "frame_id": getattr(app, "camera_ultimo_frame_id", None),
                "visual_rotation": rotation,
                "stage": "entry",
                "render_path": "",
                "error_type": "",
                "error": "",
            }
            app._display_f3_live_visual_mirror_debug = mirror_debug

            # Nunca renderize o frame que entrou em worker. O argumento recebido
            # é o camera_frame_atual e é a autoridade visual latest-frame.
            source = frame
            if not _valid_frame(source):
                mirror_debug["stage"] = "invalid_frame"
                mirror_debug["render_path"] = "previous_window_update"
                return previous_window_update(
                    frame,
                    visual_rotation=visual_rotation,
                )

            try:
                mirror_debug["frame_shape"] = tuple(
                    int(value) for value in source.shape[:3]
                )
            except Exception:
                mirror_debug["frame_shape"] = None

            if not tracking_is_enabled:
                # D-035: tracking OFF muda SOMENTE a origem geométrica. O
                # proprietário final da preview não delega antes do espelho
                # visual, porque isso era exatamente o bypass observado no
                # equipamento (stage=tracking_disabled/previous_window_update).
                mirror_debug["stage"] = "fixed_context_build"
                try:
                    from src.platform.display_f3_preview_clarity_fix import (
                        F3_PREVIEW_CLEAR_LEGEND,
                        preparar_contexto_espelho_visual_f3,
                        renderizar_preview_claro_display_f3,
                    )
                    from src.platform.display_visual_rotation import (
                        preparar_frame_visual_display,
                    )

                    visual = preparar_frame_visual_display(source, rotation)
                    visual = _fit_live_preview_before_overlay(
                        visual,
                        self_window,
                    )

                    token_fn = getattr(app, "_display_auto_frame_token", None)
                    try:
                        live_frame_token = (
                            token_fn(source)
                            if callable(token_fn)
                            else ("object", id(source))
                        )
                    except Exception:
                        live_frame_token = ("object", id(source))

                    semantic_context = preparar_contexto_espelho_visual_f3(
                        self_window,
                        visual,
                        rotation,
                        frame_token=live_frame_token,
                        geometry_token=("fixed", rotation),
                    )
                    mirror_debug["context_ready"] = isinstance(
                        semantic_context,
                        dict,
                    )

                    if isinstance(semantic_context, dict):
                        mirror_debug.update(
                            {
                                "stage": "fixed_visual_sample_ready",
                                "render_path": "fixed_latest_frame_live_visual",
                                "project_name": str(
                                    semantic_context.get("project_name") or ""
                                ),
                                "check_id": str(
                                    semantic_context.get("check_id") or ""
                                ),
                                "context_mask_count": len(
                                    tuple(semantic_context.get("masks") or ())
                                ),
                                "readout_mask_id_count": len(
                                    tuple(
                                        semantic_context.get(
                                            "readout_mask_ids"
                                        )
                                        or ()
                                    )
                                ),
                                "readout_slot_count": len(
                                    tuple(
                                        semantic_context.get(
                                            "readout_slot_mask_ids"
                                        )
                                        or ()
                                    )
                                ),
                                "live_visual_sample_ready": bool(
                                    semantic_context.get(
                                        "live_visual_sample_ready"
                                    )
                                ),
                                "live_visual_sample_reason": str(
                                    semantic_context.get(
                                        "live_visual_sample_reason"
                                    )
                                    or ""
                                ),
                                "live_visual_sampled_mask_count": int(
                                    semantic_context.get(
                                        "live_visual_sampled_mask_count",
                                        0,
                                    )
                                    or 0
                                ),
                                "live_visual_mask_ids": tuple(
                                    str(mask_id)
                                    for mask_id in (
                                        semantic_context.get(
                                            "live_visual_mask_ids"
                                        )
                                        or ()
                                    )
                                    if str(mask_id)
                                ),
                                "live_visual_classification_count": len(
                                    dict(
                                        semantic_context.get(
                                            "live_visual_classifications"
                                        )
                                        or {}
                                    )
                                ),
                                "live_visual_frame_token": repr(
                                    semantic_context.get(
                                        "live_visual_frame_token"
                                    )
                                ),
                            }
                        )

                        self_window.set_display_readout_context(
                            semantic_context
                        )
                        readout_context = getattr(
                            self_window,
                            "_display_readout_context",
                            None,
                        )
                        mirror_debug.update(
                            {
                                "readout_context_ready": isinstance(
                                    readout_context,
                                    dict,
                                ),
                                "readout_mask_slot_count": (
                                    len(
                                        tuple(
                                            readout_context.get(
                                                "mask_slots"
                                            )
                                            or ()
                                        )
                                    )
                                    if isinstance(readout_context, dict)
                                    else 0
                                ),
                                "readout_live_visual_mask_ids": (
                                    tuple(
                                        sorted(
                                            str(mask_id)
                                            for mask_id in (
                                                readout_context.get(
                                                    "live_visual_mask_ids"
                                                )
                                                or ()
                                            )
                                            if str(mask_id)
                                        )
                                    )
                                    if isinstance(readout_context, dict)
                                    else ()
                                ),
                            }
                        )
                        decorated = renderizar_preview_claro_display_f3(
                            visual,
                            semantic_context,
                        )
                    else:
                        mirror_debug["stage"] = "fixed_context_unavailable"
                        mirror_debug["render_path"] = "fixed_raw_preview"
                        try:
                            self_window.set_display_readout_context(None)
                        except Exception:
                            pass
                        decorated = visual

                    try:
                        self_window.preview_legend.configure(
                            text=F3_PREVIEW_CLEAR_LEGEND,
                            fg=self_window.PREVIEW_MUTED,
                        )
                    except Exception:
                        pass

                    preview_h, preview_w = decorated.shape[:2]
                    mirror_debug["decorated_shape"] = (
                        int(preview_h),
                        int(preview_w),
                    )
                    rendered = self_window.update_preview(decorated, leds=())
                    mirror_debug["update_preview_rendered"] = bool(rendered)
                    if rendered:
                        raw_h, raw_w = source.shape[:2]
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
                    return rendered
                except Exception as exc:
                    mirror_debug.update(
                        {
                            "stage": "fixed_render_exception",
                            "render_path": "previous_window_update",
                            "error_type": type(exc).__name__,
                            "error": str(exc)[:240],
                        }
                    )
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
            mirror_debug.update(
                {
                    "geometry_present": isinstance(geometry, dict),
                    "geometry_locked": locked,
                    "geometry_check_id": (
                        str(geometry.get("check_id") or "")
                        if isinstance(geometry, dict)
                        else ""
                    ),
                    "geometry_mask_count": (
                        len(tuple(geometry.get("masks") or ()))
                        if isinstance(geometry, dict)
                        else 0
                    ),
                    "geometry_source_type": (
                        str(geometry.get("source_type") or "")
                        if isinstance(geometry, dict)
                        else ""
                    ),
                }
            )

            # Sem LOCK não existem ROIs móveis válidas. Nesse estado de startup,
            # renderize somente o frame real reduzido: não recarregue projeto,
            # máscaras e contexto semântico a cada repaint enquanto o worker
            # ainda procura a placa.
            if not locked:
                mirror_debug["stage"] = "tracking_not_locked"
                mirror_debug["render_path"] = "raw_without_moving_rois"
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
                mirror_debug["stage"] = "locked_context_build"
                try:
                    from src.platform.display_f3_preview_clarity_fix import (
                        _effective_phase_mask_ids_for_current_check,
                        _mask_snapshot_for_current_check,
                        preparar_contexto_espelho_visual_f3,
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
                    token_fn = getattr(app, "_display_auto_frame_token", None)
                    try:
                        live_frame_token = (
                            token_fn(source)
                            if callable(token_fn)
                            else ("object", id(source))
                        )
                    except Exception:
                        live_frame_token = ("object", id(source))

                    semantic_context = preparar_contexto_espelho_visual_f3(
                        self_window,
                        visual,
                        int(visual_rotation or 0) % 360,
                        frame_token=live_frame_token,
                        geometry_token=id(geometry),
                    )
                    mirror_debug["context_ready"] = isinstance(
                        semantic_context,
                        dict,
                    )
                    if isinstance(semantic_context, dict):
                        mirror_debug.update(
                            {
                                "stage": "visual_sampling",
                                "project_name": str(
                                    semantic_context.get("project_name") or ""
                                ),
                                "check_id": str(
                                    semantic_context.get("check_id") or ""
                                ),
                                "context_mask_count": len(
                                    tuple(semantic_context.get("masks") or ())
                                ),
                                "readout_mask_id_count": len(
                                    tuple(
                                        semantic_context.get(
                                            "readout_mask_ids"
                                        )
                                        or ()
                                    )
                                ),
                                "readout_slot_count": len(
                                    tuple(
                                        semantic_context.get(
                                            "readout_slot_mask_ids"
                                        )
                                        or ()
                                    )
                                ),
                            }
                        )
                        mirror_debug.update(
                            {
                                "stage": "visual_sample_ready",
                                "live_visual_sample_ready": bool(
                                    isinstance(semantic_context, dict)
                                    and semantic_context.get(
                                        "live_visual_sample_ready"
                                    )
                                ),
                                "live_visual_sample_reason": (
                                    str(
                                        semantic_context.get(
                                            "live_visual_sample_reason"
                                        )
                                        or ""
                                    )
                                    if isinstance(semantic_context, dict)
                                    else ""
                                ),
                                "live_visual_sampled_mask_count": (
                                    int(
                                        semantic_context.get(
                                            "live_visual_sampled_mask_count",
                                            0,
                                        )
                                        or 0
                                    )
                                    if isinstance(semantic_context, dict)
                                    else 0
                                ),
                                "live_visual_mask_ids": (
                                    tuple(
                                        str(mask_id)
                                        for mask_id in (
                                            semantic_context.get(
                                                "live_visual_mask_ids"
                                            )
                                            or ()
                                        )
                                        if str(mask_id)
                                    )
                                    if isinstance(semantic_context, dict)
                                    else ()
                                ),
                                "live_visual_frame_token": (
                                    repr(
                                        semantic_context.get(
                                            "live_visual_frame_token"
                                        )
                                    )
                                    if isinstance(semantic_context, dict)
                                    else ""
                                ),
                            }
                        )

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
                        mirror_debug["stage"] = "readout_update"
                        try:
                            self_window.set_display_readout_context(
                                semantic_context
                            )
                            readout_context = getattr(
                                self_window,
                                "_display_readout_context",
                                None,
                            )
                            mirror_debug.update(
                                {
                                    "readout_context_ready": isinstance(
                                        readout_context,
                                        dict,
                                    ),
                                    "readout_live_visual_mask_ids": (
                                        tuple(
                                            sorted(
                                                str(mask_id)
                                                for mask_id in (
                                                    readout_context.get(
                                                        "live_visual_mask_ids"
                                                    )
                                                    or ()
                                                )
                                                if str(mask_id)
                                            )
                                        )
                                        if isinstance(readout_context, dict)
                                        else ()
                                    ),
                                    "readout_mask_slot_count": (
                                        len(
                                            tuple(
                                                readout_context.get(
                                                    "mask_slots"
                                                )
                                                or ()
                                            )
                                        )
                                        if isinstance(readout_context, dict)
                                        else 0
                                    ),
                                }
                            )
                        except Exception as exc:
                            mirror_debug.update(
                                {
                                    "readout_context_ready": False,
                                    "readout_error_type": type(exc).__name__,
                                    "readout_error": str(exc)[:240],
                                }
                            )

                        mirror_debug["stage"] = "camera_overlay_render"
                        decorated = renderizar_preview_claro_display_f3(
                            visual,
                            semantic_context,
                        )
                        mirror_debug["stage"] = "rendered_live_mirror"
                        mirror_debug["render_path"] = (
                            "latest_frame_live_visual"
                        )
                    else:
                        mirror_debug["stage"] = "context_unavailable"
                        mirror_debug["render_path"] = (
                            "tracking_geometry_fallback"
                        )
                        try:
                            self_window.set_display_readout_context(None)
                        except Exception as exc:
                            mirror_debug.update(
                                {
                                    "readout_error_type": type(exc).__name__,
                                    "readout_error": str(exc)[:240],
                                }
                            )
                        decorated = _draw_tracking_geometry_visual(
                            source,
                            geometry,
                            visual_rotation,
                        )
                except Exception as exc:
                    mirror_debug.update(
                        {
                            "stage": "render_exception",
                            "render_path": "tracking_geometry_fallback",
                            "error_type": type(exc).__name__,
                            "error": str(exc)[:240],
                        }
                    )
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
                alignment_required = bool(
                    isinstance(geometry, dict)
                    and geometry.get("alignment_required") is True
                )
                alignment_ready = bool(
                    isinstance(geometry, dict)
                    and geometry.get("spatial_alignment_ready") is True
                )
                if (
                    bool(status.get("evidence_current", False))
                    and alignment_required
                    and not alignment_ready
                ):
                    legend = (
                        "LOCK ESTRUTURAL • ALINHANDO SEGMENTOS • "
                        "MÁSCARA CLÁSSICA"
                    )
                    color = "#FDE68A"
                elif bool(status.get("evidence_current", False)):
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
            mirror_debug["decorated_shape"] = (
                int(preview_h),
                int(preview_w),
            )
            rendered = self_window.update_preview(decorated, leds=())
            mirror_debug["update_preview_rendered"] = bool(rendered)
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
            if (
                not tracking_enabled(app)
                or _hybrid_semantic_authority_active(app)
            ):
                # D-066: com a autoridade híbrida ativa, tracking localiza e
                # projeta a geometria. A decisão/registro usa exatamente a mesma
                # state machine do caminho tracking OFF.
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
            tracking_owns_only_geometry = _hybrid_semantic_authority_active(self)
            if (
                tracking_enabled(self)
                and automatic
                and not tracking_owns_only_geometry
            ):
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
