from __future__ import annotations

"""Identidade física de CHECK pelo contorno rastreado do Display F3.

O projeto já possui toda a geometria necessária: contorno canônico da placa,
contorno/máscaras de cada foto de CHECK e a transformação referência->canônico.
Este módulo usa esses dados como autoridade de IDENTIDADE ("qual função está
fisicamente na tela?") sem confundir isso com CONFORMIDADE ("há defeito?").

Também fornece ao classificador semântico as máscaras projetadas diretamente no
frame RAW. O frame continua bruto; quem se move são contorno e ROIs. Isso evita
erros de poucos pixels introduzidos por warp/interpolação antes da leitura.
"""

from copy import deepcopy
from pathlib import Path
from types import MethodType
import time

import cv2
import numpy as np

import src.platform.display_f3_operational_status as operational_module
from src.platform.display_f3_object_tracking import (
    F3TrackingResult,
    _update_tracking_live_geometry,
    build_tracking_mask,
    get_tracking_runtime,
    tracking_enabled,
)
from src.platform.display_f3_same_mask_reference_fix import (
    F3SameMaskReferenceAnalyzer,
)


F3_CONTOUR_CHECK_IDENTITY_SOURCE = "f3_board_contour_check_identity"
F3_CONTOUR_IDENTITY_MIN_SCORE = 0.52
F3_CONTOUR_IDENTITY_MIN_MARGIN = 0.025
F3_CONTOUR_DISPLAY_WEIGHT = 0.78
F3_CONTOUR_STRUCTURE_WEIGHT = 0.22
# Identidade/refino são mais caros que a leitura das 28 máscaras e não precisam
# acompanhar cada repaint. Mudança de CHECK força atualização imediata.
F3_CONTOUR_IDENTITY_REFRESH_S = 0.18
F3_DIRECT_REFINEMENT_REFRESH_S = 0.26


def _valid_frame(frame) -> bool:
    return frame is not None and getattr(frame, "size", 0) > 0


def _raw_frame(app, fallback=None):
    for name in (
        "_display_f3_tracking_raw_authority_frame",
        "_display_f3_tracking_raw_preview_frame",
    ):
        value = getattr(app, name, None)
        if _valid_frame(value):
            return value
    if _valid_frame(fallback):
        return fallback
    value = getattr(app, "camera_frame_atual", None)
    return value if _valid_frame(value) else None


def _polygon_mask(width: int, height: int, points) -> np.ndarray:
    result = np.zeros((int(height), int(width)), dtype=np.uint8)
    normalized = []
    for point in points or ():
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            normalized.append((float(point[0]), float(point[1])))
        except (TypeError, ValueError):
            continue
    if len(normalized) < 3:
        return result
    polygon = np.rint(np.asarray(normalized, dtype=np.float32)).astype(np.int32)
    cv2.fillPoly(result, [polygon], 255, lineType=cv2.LINE_AA)
    return result


def _segment_union_mask(width: int, height: int, masks) -> np.ndarray:
    result = np.zeros((int(height), int(width)), dtype=np.uint8)
    for item in masks or ():
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "").strip().lower()
        try:
            if kind == "circle":
                center = (
                    int(round(float(item.get("cx", 0)))),
                    int(round(float(item.get("cy", 0)))),
                )
                radius = max(1, int(round(float(item.get("radius", 1)))))
                cv2.circle(result, center, radius, 255, -1, cv2.LINE_AA)
            else:
                points = item.get("points") or ()
                polygon = []
                for point in points:
                    if isinstance(point, (list, tuple)) and len(point) >= 2:
                        polygon.append((float(point[0]), float(point[1])))
                if len(polygon) >= 3:
                    data = np.rint(np.asarray(polygon, dtype=np.float32)).astype(np.int32)
                    cv2.fillPoly(result, [data], 255, lineType=cv2.LINE_AA)
        except (TypeError, ValueError, cv2.error):
            continue
    if int(cv2.countNonZero(result)) > 0:
        result = cv2.dilate(result, np.ones((5, 5), dtype=np.uint8), iterations=1)
    return result


def _normalize_gray(image, board_mask: np.ndarray):
    if not _valid_frame(image):
        return None
    try:
        gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    except cv2.error:
        return None
    valid = gray[board_mask > 0]
    if valid.size < 32:
        return None
    lo = float(np.percentile(valid, 3.0))
    hi = float(np.percentile(valid, 97.0))
    if hi - lo < 8.0:
        lo = float(np.min(valid))
        hi = float(np.max(valid))
    scale = max(8.0, hi - lo)
    normalized = np.clip((gray.astype(np.float32) - lo) * (255.0 / scale), 0.0, 255.0)
    return normalized.astype(np.uint8)


def _masked_similarity(left: np.ndarray, right: np.ndarray, mask: np.ndarray) -> float:
    valid = mask > 0
    if int(np.count_nonzero(valid)) < 16:
        return 0.0
    diff = np.abs(left.astype(np.float32) - right.astype(np.float32))
    error = float(np.mean(diff[valid]))
    return max(0.0, min(1.0, 1.0 - (error / 255.0)))


def _edge_similarity(left: np.ndarray, right: np.ndarray, mask: np.ndarray) -> float:
    try:
        left_edge = cv2.Canny(left, 45, 135)
        right_edge = cv2.Canny(right, 45, 135)
    except cv2.error:
        return 0.0
    kernel = np.ones((3, 3), dtype=np.uint8)
    left_d = cv2.dilate(left_edge, kernel, iterations=1)
    right_d = cv2.dilate(right_edge, kernel, iterations=1)
    valid = mask > 0
    left_on = (left_edge > 0) & valid
    right_on = (right_edge > 0) & valid
    denominator = int(np.count_nonzero(left_on)) + int(np.count_nonzero(right_on))
    if denominator <= 0:
        return 1.0
    overlap_left = left_on & (right_d > 0)
    overlap_right = right_on & (left_d > 0)
    overlap = int(np.count_nonzero(overlap_left)) + int(np.count_nonzero(overlap_right))
    return max(0.0, min(1.0, float(overlap) / float(denominator)))


def _crop_to_board_bbox(
    current,
    reference,
    board_mask: np.ndarray,
    display_mask: np.ndarray,
    padding: int = 8,
):
    """Recorta o trabalho óptico para a área real da placa.

    Em 1920x1080 o display ocupa apenas uma fração do frame. Executar grayscale,
    normalização e Canny na imagem inteira para cada CHECK desperdiçava CPU e
    deixava a interface F3 pesada sem acrescentar informação à decisão.
    """
    if (
        not _valid_frame(current)
        or not _valid_frame(reference)
        or board_mask is None
        or getattr(board_mask, "size", 0) == 0
    ):
        return current, reference, board_mask, display_mask
    try:
        points = cv2.findNonZero((board_mask > 0).astype(np.uint8))
        if points is None:
            return current, reference, board_mask, display_mask
        x, y, width, height = cv2.boundingRect(points)
        pad = max(0, int(padding))
        x1 = max(0, int(x) - pad)
        y1 = max(0, int(y) - pad)
        x2 = min(int(board_mask.shape[1]), int(x + width) + pad)
        y2 = min(int(board_mask.shape[0]), int(y + height) + pad)
        if x2 - x1 < 8 or y2 - y1 < 8:
            return current, reference, board_mask, display_mask
        return (
            current[y1:y2, x1:x2],
            reference[y1:y2, x1:x2],
            board_mask[y1:y2, x1:x2],
            display_mask[y1:y2, x1:x2],
        )
    except Exception:
        return current, reference, board_mask, display_mask


def calcular_similaridade_contorno_check_f3(
    current_canonical,
    reference_canonical,
    board_mask: np.ndarray,
    display_mask: np.ndarray,
) -> dict:
    """Compara somente a placa; o padrão dos segmentos recebe maior peso."""
    (
        current_canonical,
        reference_canonical,
        board_mask,
        display_mask,
    ) = _crop_to_board_bbox(
        current_canonical,
        reference_canonical,
        board_mask,
        display_mask,
    )
    current_gray = _normalize_gray(current_canonical, board_mask)
    reference_gray = _normalize_gray(reference_canonical, board_mask)
    if current_gray is None or reference_gray is None:
        return {"available": False, "score": 0.0}

    board_core = cv2.erode(
        board_mask,
        np.ones((3, 3), dtype=np.uint8),
        iterations=1,
    )
    display = cv2.bitwise_and(display_mask, board_core)
    if int(cv2.countNonZero(display)) < 16:
        display = board_core

    structure = cv2.bitwise_and(
        board_core,
        cv2.bitwise_not(display),
    )
    if int(cv2.countNonZero(structure)) < 32:
        structure = board_core

    display_pixel = _masked_similarity(
        current_gray,
        reference_gray,
        display,
    )
    display_edge = _edge_similarity(
        current_gray,
        reference_gray,
        display,
    )
    display_score = (0.72 * display_pixel) + (0.28 * display_edge)

    structure_score = _masked_similarity(
        current_gray,
        reference_gray,
        structure,
    )
    score = (
        F3_CONTOUR_DISPLAY_WEIGHT * display_score
        + F3_CONTOUR_STRUCTURE_WEIGHT * structure_score
    )
    return {
        "available": True,
        "score": round(float(score), 4),
        "display_score": round(float(display_score), 4),
        "display_pixel_similarity": round(float(display_pixel), 4),
        "display_edge_similarity": round(float(display_edge), 4),
        "structure_score": round(float(structure_score), 4),
        "board_pixels": int(cv2.countNonZero(board_core)),
        "display_pixels": int(cv2.countNonZero(display)),
        "comparison_width": int(board_mask.shape[1]),
        "comparison_height": int(board_mask.shape[0]),
    }


def selecionar_identidade_check_f3(rows: list[dict]) -> dict:
    valid = [
        deepcopy(item)
        for item in rows or ()
        if isinstance(item, dict) and item.get("available") and item.get("score") is not None
    ]
    valid.sort(key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
    if not valid:
        return {
            "available": False,
            "confirmed": False,
            "reason": "checks_sem_comparacao_por_contorno",
            "rows": [],
        }

    best = valid[0]
    second = valid[1] if len(valid) > 1 else None
    best_score = float(best.get("score", 0.0) or 0.0)
    second_score = float((second or {}).get("score", 0.0) or 0.0)
    margin = best_score - second_score if second is not None else best_score
    confirmed = bool(
        best_score >= F3_CONTOUR_IDENTITY_MIN_SCORE
        and (
            second is None
            or margin >= F3_CONTOUR_IDENTITY_MIN_MARGIN
        )
    )
    return {
        "available": True,
        "confirmed": confirmed,
        "reason": (
            "check_identificado_por_contorno_e_display"
            if confirmed
            else "identidade_check_ambigua_no_contorno"
        ),
        "best_check_id": str(best.get("check_id") or ""),
        "best_check_name": str(best.get("check_name") or best.get("check_id") or "").strip().upper(),
        "best_score": round(best_score, 4),
        "second_check_id": str((second or {}).get("check_id") or ""),
        "second_score": round(second_score, 4) if second is not None else None,
        "margin": round(float(margin), 4),
        "rows": valid,
    }


def _reference_cache(app, runtime, project_name: str):
    signature = (
        str(project_name or ""),
        repr(getattr(runtime, "signature", None)),
    )
    cached = getattr(app, "_display_f3_contour_identity_reference_cache", None)
    if isinstance(cached, dict) and cached.get("signature") == signature:
        return cached.get("rows") or []

    width = int(getattr(runtime, "width", 0) or 0)
    height = int(getattr(runtime, "height", 0) or 0)
    rows = []
    if width < 1 or height < 1:
        return rows

    try:
        checks = runtime.repository.listar_checks(project_name)
    except Exception:
        checks = []

    for check in checks or ():
        if not isinstance(check, dict):
            continue
        check_id = str(check.get("id") or "")
        if not check_id:
            continue
        ref = runtime.references.get(f"check:{check_id}")
        mapping = ref.get("reference_to_canonical") if isinstance(ref, dict) else None
        metadata = runtime.check_store.get(project_name, check_id)
        path = Path(str((metadata or {}).get("image_path") or ""))
        if mapping is None or not path.exists():
            continue
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if not _valid_frame(image):
            continue
        try:
            canonical = cv2.warpAffine(
                image,
                np.asarray(mapping, dtype=np.float32).reshape(2, 3),
                (width, height),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT101,
            )
        except (ValueError, cv2.error):
            continue
        rows.append(
            {
                "check_id": check_id,
                "check_name": str(check.get("name") or check_id),
                "canonical": canonical,
            }
        )

    app._display_f3_contour_identity_reference_cache = {
        "signature": signature,
        "rows": rows,
    }
    return rows


def avaliar_identidade_visual_checks_por_contorno_f3(
    app,
    frame=None,
    project_name: str | None = None,
) -> dict:
    """Ranqueia H1/BLUE/USB/AUX no espaço canônico do contorno da placa."""
    if not tracking_enabled(app):
        return {
            "source": F3_CONTOUR_CHECK_IDENTITY_SOURCE,
            "available": False,
            "confirmed": False,
            "reason": "rastreamento_desativado",
        }

    runtime = get_tracking_runtime(app)
    if runtime is None:
        return {
            "source": F3_CONTOUR_CHECK_IDENTITY_SOURCE,
            "available": False,
            "confirmed": False,
            "reason": "tracker_indisponivel",
        }

    result = getattr(app, "_display_f3_tracking_result", None)
    if result is None:
        result = getattr(runtime, "last_result", None)
    if (
        result is None
        or not bool(getattr(result, "locked", False))
        or not bool(getattr(result, "evidence_current", False))
        or getattr(result, "current_to_canonical", None) is None
    ):
        return {
            "source": F3_CONTOUR_CHECK_IDENTITY_SOURCE,
            "available": False,
            "confirmed": False,
            "reason": "rastreamento_sem_evidencia_atual",
        }

    raw = _raw_frame(app, frame)
    if not _valid_frame(raw):
        return {
            "source": F3_CONTOUR_CHECK_IDENTITY_SOURCE,
            "available": False,
            "confirmed": False,
            "reason": "frame_raw_ausente",
        }

    repository = getattr(app, "display_project_repository", None)
    if repository is None:
        return {
            "source": F3_CONTOUR_CHECK_IDENTITY_SOURCE,
            "available": False,
            "confirmed": False,
            "reason": "repositorio_ausente",
        }
    name = str(project_name or repository.obter_projeto_ativo() or "")
    if not name:
        return {
            "source": F3_CONTOUR_CHECK_IDENTITY_SOURCE,
            "available": False,
            "confirmed": False,
            "reason": "projeto_ausente",
        }

    width = int(getattr(runtime, "width", 0) or 0)
    height = int(getattr(runtime, "height", 0) or 0)
    if width < 1 or height < 1:
        return {
            "source": F3_CONTOUR_CHECK_IDENTITY_SOURCE,
            "available": False,
            "confirmed": False,
            "reason": "resolucao_tracker_invalida",
        }

    try:
        current_canonical = cv2.warpAffine(
            raw,
            np.asarray(result.current_to_canonical, dtype=np.float32).reshape(2, 3),
            (width, height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT101,
        )
    except (ValueError, cv2.error):
        return {
            "source": F3_CONTOUR_CHECK_IDENTITY_SOURCE,
            "available": False,
            "confirmed": False,
            "reason": "falha_alinhar_frame_ao_contorno",
        }

    board_mask = _polygon_mask(
        width,
        height,
        getattr(runtime, "canonical_board", None),
    )
    if int(cv2.countNonZero(board_mask)) < 128:
        return {
            "source": F3_CONTOUR_CHECK_IDENTITY_SOURCE,
            "available": False,
            "confirmed": False,
            "reason": "contorno_placa_ausente",
        }
    display_mask = _segment_union_mask(
        width,
        height,
        getattr(runtime, "canonical_masks", None),
    )

    rows = []
    for reference in _reference_cache(app, runtime, name):
        comparison = calcular_similaridade_contorno_check_f3(
            current_canonical,
            reference.get("canonical"),
            board_mask,
            display_mask,
        )
        rows.append(
            {
                "check_id": str(reference.get("check_id") or ""),
                "check_name": str(reference.get("check_name") or ""),
                **comparison,
            }
        )

    identity = selecionar_identidade_check_f3(rows)
    identity.update(
        {
            "source": F3_CONTOUR_CHECK_IDENTITY_SOURCE,
            "project_name": name,
            "tracking_reference": str(getattr(result, "reference", "") or ""),
            "tracking_source_type": str(getattr(result, "source_type", "") or ""),
            "tracking_matches": int(getattr(result, "matches", 0) or 0),
            "tracking_inliers": int(getattr(result, "inliers", 0) or 0),
            "tracking_inlier_ratio": round(float(getattr(result, "inlier_ratio", 0.0) or 0.0), 4),
            "contour_point_count": len(getattr(runtime, "canonical_board", None) or ()),
            "comparison_space": "canonical_board_contour",
            "uses_saved_check_images": True,
            "uses_saved_board_contour": True,
            "uses_saved_masks": True,
        }
    )
    return identity


def _refinement_shift_px(runtime, base_matrix, refined_matrix) -> float | None:
    """Deslocamento mediano das ROIs no frame causado pelo refinamento."""
    if base_matrix is None or refined_matrix is None:
        return None
    masks = getattr(runtime, "canonical_masks", None) or ()
    centers = []
    for item in masks:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "").strip().lower()
        try:
            if kind == "circle":
                centers.append(
                    [float(item.get("cx", 0.0)), float(item.get("cy", 0.0))]
                )
            else:
                points = [
                    [float(p[0]), float(p[1])]
                    for p in (item.get("points") or ())
                    if isinstance(p, (list, tuple)) and len(p) >= 2
                ]
                if points:
                    centers.append(np.mean(np.asarray(points, dtype=np.float32), axis=0).tolist())
        except (TypeError, ValueError):
            continue
    if not centers:
        return None
    try:
        base_inverse = cv2.invertAffineTransform(
            np.asarray(base_matrix, dtype=np.float32).reshape(2, 3)
        )
        refined_inverse = cv2.invertAffineTransform(
            np.asarray(refined_matrix, dtype=np.float32).reshape(2, 3)
        )
        source = np.asarray(centers, dtype=np.float32).reshape(-1, 1, 2)
        base_points = cv2.transform(source, base_inverse).reshape(-1, 2)
        refined_points = cv2.transform(source, refined_inverse).reshape(-1, 2)
        distances = np.linalg.norm(refined_points - base_points, axis=1)
        if not distances.size:
            return None
        return round(float(np.median(distances)), 3)
    except Exception:
        return None


def refinar_geometria_check_identificado_f3(
    app,
    raw_frame,
    identity: dict | None,
) -> dict:
    """Refina as ROIs diretamente contra a foto do CHECK já identificado.

    A identidade por contorno responde QUAL função está presente. Somente quando
    ela coincide com o CHECK lógico atual tentamos uma transformação direta
    FOTO_DO_CHECK -> FRAME_ATUAL. O lock global não é alterado.
    """
    telemetry = {
        "source": "f3_identified_check_direct_geometry_refinement",
        "available": False,
        "applied": False,
        "reason": "identidade_check_indisponivel",
    }
    if not isinstance(identity, dict) or not bool(identity.get("confirmed")):
        return telemetry
    if not _valid_frame(raw_frame):
        telemetry["reason"] = "frame_raw_ausente"
        return telemetry

    identified_id = str(identity.get("best_check_id") or "")
    identified_name = str(identity.get("best_check_name") or identified_id).strip().upper()
    telemetry["identified_check_id"] = identified_id
    telemetry["identified_check_name"] = identified_name

    try:
        context = app._display_auto_current_context()
    except Exception:
        context = None
    expected_id = str((context or {}).get("check_id") or "")
    expected_name = str(
        (context or {}).get("check_name") or expected_id
    ).strip().upper()
    telemetry["expected_check_id"] = expected_id
    telemetry["expected_check_name"] = expected_name

    if not identified_id or identified_id != expected_id:
        telemetry["reason"] = "check_identificado_diferente_do_check_logico"
        return telemetry

    runtime = get_tracking_runtime(app)
    if runtime is None:
        telemetry["reason"] = "tracker_indisponivel"
        return telemetry

    base_result = getattr(app, "_display_f3_tracking_result", None)
    if base_result is None:
        base_result = getattr(runtime, "last_result", None)
    base_matrix = getattr(base_result, "current_to_canonical", None)
    if base_matrix is None:
        telemetry["reason"] = "pose_global_indisponivel"
        return telemetry

    geometry = getattr(app, "_display_f3_tracking_live_geometry", None)
    current_tracking_mask = None
    if isinstance(geometry, dict):
        try:
            h, w = raw_frame.shape[:2]
            current_tracking_mask = build_tracking_mask(
                int(w),
                int(h),
                geometry.get("board_points") or (),
                geometry.get("masks") or (),
            )
        except Exception:
            current_tracking_mask = None

    key = f"check:{identified_id}"
    try:
        candidate = runtime.candidate_for_reference(
            raw_frame,
            key,
            current_tracking_mask=current_tracking_mask,
        )
    except Exception:
        candidate = None
    if not isinstance(candidate, dict) or candidate.get("matrix") is None:
        telemetry["reason"] = "referencia_direta_check_sem_match"
        telemetry["direct_reference"] = key
        return telemetry

    refined_matrix = candidate.get("matrix")
    try:
        compatible, closeness = runtime._matrix_continuity(refined_matrix)
    except Exception:
        compatible, closeness = False, 0.0
    if not compatible:
        telemetry.update(
            {
                "available": True,
                "reason": "pose_direta_incompativel_com_lock_global",
                "direct_reference": key,
                "continuity_closeness": round(float(closeness), 4),
            }
        )
        return telemetry

    refined = F3TrackingResult(
        True,
        raw_frame,
        reference=key,
        matches=int(candidate.get("matches", 0) or 0),
        inliers=int(candidate.get("inliers", 0) or 0),
        inlier_ratio=float(candidate.get("ratio", 0.0) or 0.0),
        rotation_deg=float(candidate.get("rotation_deg", 0.0) or 0.0),
        scale=float(candidate.get("scale", 1.0) or 1.0),
        reason="identified_check_direct_refinement",
        current_to_canonical=np.asarray(
            refined_matrix,
            dtype=np.float32,
        ).reshape(2, 3),
        source_type="check_direct_refinement",
        evidence_current=True,
    )
    _update_tracking_live_geometry(app, raw_frame, refined)

    refined_geometry = getattr(app, "_display_f3_tracking_live_geometry", None)
    applied = bool(
        isinstance(refined_geometry, dict)
        and refined_geometry.get("locked")
        and str(refined_geometry.get("reference") or "") == key
        and str(refined_geometry.get("geometry_space") or "") == key
    )
    telemetry.update(
        {
            "available": True,
            "applied": applied,
            "reason": (
                "geometria_refinada_diretamente_pelo_check"
                if applied
                else "refinamento_nao_publicou_geometria_do_check"
            ),
            "base_reference": str(getattr(base_result, "reference", "") or ""),
            "direct_reference": key,
            "matches": int(candidate.get("matches", 0) or 0),
            "inliers": int(candidate.get("inliers", 0) or 0),
            "inlier_ratio": round(float(candidate.get("ratio", 0.0) or 0.0), 4),
            "fallback": str(candidate.get("fallback") or ""),
            "current_masked_for_segments": bool(
                candidate.get("current_masked_for_segments", False)
            ),
            "continuity_closeness": round(float(closeness), 4),
            "median_roi_shift_px": _refinement_shift_px(
                runtime,
                base_matrix,
                refined_matrix,
            ),
            "geometry_space_after": (
                str(refined_geometry.get("geometry_space") or "")
                if isinstance(refined_geometry, dict)
                else ""
            ),
        }
    )
    return telemetry


class F3TrackedRawCheckAnalyzer:
    """Classifica segmentos no frame RAW usando ROIs móveis do contorno."""

    def __init__(self, repository, app) -> None:
        self.repository = repository
        self.app = app
        self.semantic = F3SameMaskReferenceAnalyzer(repository)

    def invalidate_learning_cache(self) -> None:
        try:
            self.semantic.invalidate_learning_cache()
        except Exception:
            pass

    def analyze(
        self,
        frame,
        project_name: str,
        check_id: str,
        visual_rotation: int = 0,
    ) -> dict:
        geometry = getattr(self.app, "_display_f3_tracking_live_geometry", None)
        raw = _raw_frame(self.app, frame)
        if (
            isinstance(geometry, dict)
            and bool(geometry.get("locked"))
            and _valid_frame(raw)
            and geometry.get("masks")
        ):
            result = self.semantic.analyze(
                frame=raw,
                project_name=project_name,
                check_id=check_id,
                visual_rotation=visual_rotation,
                mask_geometry_override=geometry.get("masks"),
                mask_geometry_resolution=geometry.get("resolution"),
                mask_geometry_source=str(geometry.get("geometry_space") or "tracking_live"),
            )
            if isinstance(result, dict):
                result["analysis_frame_source"] = "tracking_raw_with_live_geometry"
                result["tracking_geometry_reference"] = str(geometry.get("reference") or "")
                result["tracking_geometry_space"] = str(geometry.get("geometry_space") or "")
                result["tracking_geometry_refinement"] = deepcopy(
                    getattr(
                        self.app,
                        "_display_f3_check_geometry_refinement",
                        None,
                    )
                )
            return result

        result = self.semantic.analyze(
            frame=frame,
            project_name=project_name,
            check_id=check_id,
            visual_rotation=visual_rotation,
        )
        if isinstance(result, dict):
            result["analysis_frame_source"] = "legacy_aligned_or_pipeline_frame"
        return result


def _publish_identity_status(app, identity: dict | None) -> None:
    if not isinstance(identity, dict) or not bool(identity.get("confirmed")):
        return
    power = getattr(app, "_display_f3_power_authority_status", None)
    energy = power.get("energy") if isinstance(power, dict) else None
    if not (
        isinstance(power, dict)
        and power.get("board_present") is True
        and isinstance(energy, dict)
        and energy.get("powered_confirmed") is True
    ):
        return

    name = str(identity.get("best_check_name") or identity.get("best_check_id") or "CHECK").strip().upper()
    score = float(identity.get("best_score", 0.0) or 0.0)
    margin = float(identity.get("margin", 0.0) or 0.0)
    text = (
        f"ANÁLISE VISUAL: DISPLAY EM {name} • contorno {score * 100:.0f}% "
        f"• margem {margin * 100:.0f}%"
    )
    window = getattr(app, "display_f3_window", None)
    if window is not None:
        try:
            window.set_visual_analysis_status(
                text,
                operational_module.F3_OPERATIONAL_STATUS_COLORS["check"],
            )
        except Exception:
            pass


def instalar_identidade_visual_contorno_checks_f3(app) -> None:
    """Instala identidade por contorno e análise RAW móvel na instância real."""
    if bool(getattr(app, "_display_f3_contour_check_identity_installed", False)):
        return

    repository = getattr(app, "display_project_repository", None)
    if repository is not None:
        app._display_auto_analyzer = F3TrackedRawCheckAnalyzer(repository, app)

    previous_rebuild = app._rebuild_display_auto_analyzer

    def rebuild(self):
        result = previous_rebuild()
        repo = getattr(self, "display_project_repository", None)
        if repo is not None:
            self._display_auto_analyzer = F3TrackedRawCheckAnalyzer(repo, self)
        return result

    app._rebuild_display_auto_analyzer = MethodType(rebuild, app)

    previous_process = app._process_display_auto_check

    def process(self):
        raw = _raw_frame(self, getattr(self, "camera_frame_atual", None))
        now = time.monotonic()
        try:
            context = self._display_auto_current_context()
        except Exception:
            context = None
        logical_check_id = str((context or {}).get("check_id") or "")
        previous_check_id = str(
            getattr(self, "_display_f3_contour_perf_check_id", "") or ""
        )
        check_changed = logical_check_id != previous_check_id

        identity = getattr(self, "_display_f3_check_identity_status", None)
        last_identity_s = float(
            getattr(self, "_display_f3_contour_identity_last_s", 0.0) or 0.0
        )
        identity_due = bool(
            check_changed
            or not isinstance(identity, dict)
            or (now - last_identity_s) >= F3_CONTOUR_IDENTITY_REFRESH_S
        )
        if identity_due:
            identity = avaliar_identidade_visual_checks_por_contorno_f3(
                self,
                raw,
            )
            self._display_f3_check_identity_status = deepcopy(identity)
            self._display_f3_contour_identity_last_s = now

        refinement = getattr(
            self,
            "_display_f3_check_geometry_refinement",
            None,
        )
        last_refinement_s = float(
            getattr(self, "_display_f3_contour_refinement_last_s", 0.0) or 0.0
        )
        refinement_due = bool(
            check_changed
            or not isinstance(refinement, dict)
            or (now - last_refinement_s) >= F3_DIRECT_REFINEMENT_REFRESH_S
        )
        if refinement_due:
            refinement = refinar_geometria_check_identificado_f3(
                self,
                raw,
                identity,
            )
            self._display_f3_check_geometry_refinement = deepcopy(refinement)
            self._display_f3_contour_refinement_last_s = now

        self._display_f3_contour_perf_check_id = logical_check_id
        self._display_f3_live_performance = {
            "preview_interval_ms": int(
                getattr(self, "DISPLAY_F3_PREVIEW_INTERVAL_MS", 0) or 0
            ),
            "analysis_interval_ms": int(
                getattr(self, "DISPLAY_F3_ANALYSIS_INTERVAL_MS", 0) or 0
            ),
            "identity_refresh_ms": int(F3_CONTOUR_IDENTITY_REFRESH_S * 1000.0),
            "refinement_refresh_ms": int(F3_DIRECT_REFINEMENT_REFRESH_S * 1000.0),
            "identity_recomputed": bool(identity_due),
            "refinement_recomputed": bool(refinement_due),
            "logical_check_id": logical_check_id,
        }

        result = previous_process()
        _publish_identity_status(self, identity)
        return result

    app._process_display_auto_check = MethodType(process, app)
    app._display_f3_contour_check_identity_installed = True
