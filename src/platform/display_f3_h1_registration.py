from __future__ import annotations

"""Experimento geométrico D-025: homografia do filtro + registro visual do H1.

Este módulo contém apenas compute de visão. Ele não decide energia, OK/NG,
sequência de CHECKS, presença nem apresentação. O runtime produtivo ainda não
consome esta implementação enquanto D-025 permanecer Proposed.

Contrato experimental:
    frame -> filtro -> homografia -> ROI retificada
          -> mapa de emissão -> phase correlation + ECC
          -> imagem atual alinhada ao H1 de referência
          -> máscaras fixas no espaço retificado da referência
"""

import math

import cv2
import numpy as np

from src.platform.display_mask_geometry import (
    converter_mascara_legada_para_editor,
    pontos_mascara_display,
)


F3_H1_REGISTRATION_MIN_FILTER_SIDE_PX = 24
F3_H1_REGISTRATION_MIN_DYNAMIC_RANGE = 18.0
F3_H1_REGISTRATION_BINARY_THRESHOLD = 0.45
F3_H1_REGISTRATION_ECC_QUALITY_SCORE = 0.45
F3_H1_REGISTRATION_MAX_ROTATION_DEG = 8.0
F3_H1_REGISTRATION_MAX_CENTER_SHIFT_FRACTION = 0.24
F3_H1_REGISTRATION_ECC_MAX_ITERATIONS = 120
F3_H1_REGISTRATION_ECC_EPSILON = 1e-6


def _valid_image(image) -> bool:
    return image is not None and getattr(image, "size", 0) > 0


def order_filter_quad(points) -> np.ndarray | None:
    """Normaliza um contorno em TL, TR, BR, BL.

    O editor normalmente fornece quatro pontos. Para contornos com mais pontos,
    o experimento reduz somente a geometria do filtro ao retângulo orientado;
    nenhum estado produtivo é alterado.
    """
    try:
        values = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    except (TypeError, ValueError):
        return None
    if len(values) < 4 or not np.all(np.isfinite(values)):
        return None
    if len(values) != 4:
        try:
            rect = cv2.minAreaRect(values.reshape(-1, 1, 2))
            values = cv2.boxPoints(rect).astype(np.float32)
        except cv2.error:
            return None

    center = np.mean(values, axis=0)
    angles = np.arctan2(
        values[:, 1] - center[1],
        values[:, 0] - center[0],
    )
    ordered = values[np.argsort(angles)]
    start = int(np.argmin(np.sum(ordered, axis=1)))
    ordered = np.roll(ordered, -start, axis=0)

    # Em coordenadas de imagem, TL -> TR -> BR -> BL deve percorrer o contorno
    # no sentido horário visual. Se os dois pontos intermediários vierem
    # invertidos por uma geometria degenerada, corrija pelo eixo horizontal.
    if float(ordered[1][0]) < float(ordered[3][0]):
        ordered = ordered[[0, 3, 2, 1]]
    return np.asarray(ordered, dtype=np.float32).reshape(4, 2)


def rectified_filter_size(points) -> tuple[int, int] | None:
    quad = order_filter_quad(points)
    if quad is None:
        return None
    top = float(np.linalg.norm(quad[1] - quad[0]))
    bottom = float(np.linalg.norm(quad[2] - quad[3]))
    left = float(np.linalg.norm(quad[3] - quad[0]))
    right = float(np.linalg.norm(quad[2] - quad[1]))
    width = int(round((top + bottom) * 0.5))
    height = int(round((left + right) * 0.5))
    if (
        width < F3_H1_REGISTRATION_MIN_FILTER_SIDE_PX
        or height < F3_H1_REGISTRATION_MIN_FILTER_SIDE_PX
    ):
        return None
    return width, height


def rectify_filter_homography(
    image,
    filter_points,
    *,
    output_size: tuple[int, int] | None = None,
) -> dict:
    """Retifica o filtro para um retângulo canônico por homografia."""
    if not _valid_image(image):
        return {"available": False, "reason": "invalid_image"}
    source = order_filter_quad(filter_points)
    if source is None:
        return {"available": False, "reason": "invalid_filter_quad"}

    size = output_size or rectified_filter_size(source)
    if (
        not isinstance(size, (tuple, list))
        or len(size) < 2
        or int(size[0]) < F3_H1_REGISTRATION_MIN_FILTER_SIDE_PX
        or int(size[1]) < F3_H1_REGISTRATION_MIN_FILTER_SIDE_PX
    ):
        return {"available": False, "reason": "invalid_rectified_size"}
    width, height = int(size[0]), int(size[1])
    target = np.asarray(
        [
            [0.0, 0.0],
            [float(width - 1), 0.0],
            [float(width - 1), float(height - 1)],
            [0.0, float(height - 1)],
        ],
        dtype=np.float32,
    )

    try:
        image_to_rectified = cv2.getPerspectiveTransform(source, target)
        rectified_to_image = cv2.getPerspectiveTransform(target, source)
        rectified = cv2.warpPerspective(
            image,
            image_to_rectified,
            (width, height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
    except cv2.error:
        return {"available": False, "reason": "homography_failed"}

    if not _valid_image(rectified):
        return {"available": False, "reason": "rectification_failed"}
    return {
        "available": True,
        "reason": "filter_rectified",
        "image": rectified,
        "size": (width, height),
        "filter_points": source.tolist(),
        "image_to_rectified": np.asarray(
            image_to_rectified,
            dtype=np.float32,
        ).reshape(3, 3),
        "rectified_to_image": np.asarray(
            rectified_to_image,
            dtype=np.float32,
        ).reshape(3, 3),
    }


def build_h1_emission_map(image) -> dict:
    """Reduz a ROI a uma representação contínua de emissão luminosa."""
    if not _valid_image(image):
        return {
            "available": False,
            "reason": "invalid_image",
            "map": None,
        }
    try:
        if image.ndim == 2:
            value = image.astype(np.float32)
        else:
            value = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)[:, :, 2].astype(
                np.float32
            )
    except (cv2.error, TypeError, ValueError):
        return {
            "available": False,
            "reason": "emission_prepare_failed",
            "map": None,
        }

    if value.size < 64:
        return {
            "available": False,
            "reason": "emission_samples_insufficient",
            "map": None,
        }

    median_v = float(np.percentile(value, 50.0))
    p995_v = float(np.percentile(value, 99.5))
    dynamic_range = float(p995_v - median_v)
    if dynamic_range < F3_H1_REGISTRATION_MIN_DYNAMIC_RANGE:
        return {
            "available": False,
            "reason": "emission_dynamic_range_insufficient",
            "map": None,
            "median_v": round(median_v, 3),
            "p995_v": round(p995_v, 3),
            "dynamic_range": round(dynamic_range, 3),
        }

    normalized = np.clip(
        (value - median_v) / max(1.0, dynamic_range),
        0.0,
        1.0,
    )
    # Remove variação de fundo e mantém uma borda suave para o ECC trabalhar
    # com informação contínua em vez de um threshold binário rígido.
    normalized = np.clip((normalized - 0.15) / 0.85, 0.0, 1.0)
    normalized = cv2.GaussianBlur(
        normalized.astype(np.float32),
        (3, 3),
        0,
    )

    # Borda do filtro não deve dominar o registro fino dos segmentos.
    h, w = normalized.shape[:2]
    margin_x = max(1, int(round(w * 0.025)))
    margin_y = max(1, int(round(h * 0.05)))
    normalized[:margin_y, :] = 0.0
    normalized[max(0, h - margin_y):, :] = 0.0
    normalized[:, :margin_x] = 0.0
    normalized[:, max(0, w - margin_x):] = 0.0

    return {
        "available": True,
        "reason": "emission_map_ready",
        "map": normalized,
        "median_v": round(median_v, 3),
        "p995_v": round(p995_v, 3),
        "dynamic_range": round(dynamic_range, 3),
    }


def _normalized_correlation(first, second) -> float:
    try:
        a = np.asarray(first, dtype=np.float32)
        b = np.asarray(second, dtype=np.float32)
        if a.shape != b.shape or a.size == 0:
            return 0.0
        a = a - float(np.mean(a))
        b = b - float(np.mean(b))
        denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
        if denominator <= 1e-9:
            return 0.0
        return float(np.sum(a * b) / denominator)
    except (TypeError, ValueError):
        return 0.0


def emission_alignment_metrics(reference_map, observed_map) -> dict:
    """Métricas objetivas de coincidência da emissão no mesmo espaço."""
    try:
        reference = np.asarray(reference_map, dtype=np.float32)
        observed = np.asarray(observed_map, dtype=np.float32)
    except (TypeError, ValueError):
        return {"available": False, "reason": "invalid_maps"}
    if reference.shape != observed.shape or reference.size == 0:
        return {"available": False, "reason": "map_shape_mismatch"}

    threshold = float(F3_H1_REGISTRATION_BINARY_THRESHOLD)
    ref_binary = reference >= threshold
    obs_binary = observed >= threshold
    ref_count = int(np.count_nonzero(ref_binary))
    obs_count = int(np.count_nonzero(obs_binary))
    if ref_count <= 0 or obs_count <= 0:
        return {
            "available": False,
            "reason": "emission_binary_empty",
            "reference_hot_pixels": ref_count,
            "observed_hot_pixels": obs_count,
        }

    intersection = int(np.count_nonzero(ref_binary & obs_binary))
    union = int(np.count_nonzero(ref_binary | obs_binary))
    dice = (2.0 * intersection) / max(1, ref_count + obs_count)
    iou = intersection / max(1, union)

    ref_distance = cv2.distanceTransform(
        (~ref_binary).astype(np.uint8),
        cv2.DIST_L2,
        3,
    )
    obs_distance = cv2.distanceTransform(
        (~obs_binary).astype(np.uint8),
        cv2.DIST_L2,
        3,
    )
    obs_to_ref = ref_distance[obs_binary]
    ref_to_obs = obs_distance[ref_binary]
    distances = np.concatenate((obs_to_ref, ref_to_obs))
    mean_error = float(np.mean(distances)) if distances.size else float("inf")
    p95_error = (
        float(np.percentile(distances, 95.0))
        if distances.size
        else float("inf")
    )

    return {
        "available": True,
        "reason": "metrics_ready",
        "correlation": round(
            _normalized_correlation(reference, observed),
            6,
        ),
        "dice": round(float(dice), 6),
        "iou": round(float(iou), 6),
        "mean_error_px": round(mean_error, 4),
        "p95_error_px": round(p95_error, 4),
        "reference_hot_pixels": ref_count,
        "observed_hot_pixels": obs_count,
        "intersection_hot_pixels": intersection,
    }


def _ecc_refinement_decision(
    before: dict,
    candidate: dict,
    ecc_score: float,
) -> tuple[bool, str]:
    """Aceita ECC somente quando ele melhora sem piorar métricas-chave."""
    if float(ecc_score) < F3_H1_REGISTRATION_ECC_QUALITY_SCORE:
        return False, "ecc_score_below_quality_threshold"
    if not bool(candidate.get("available")):
        return False, "ecc_candidate_metrics_unavailable"
    if not bool(before.get("available")):
        return True, "ecc_candidate_metrics_available_without_base_metrics"

    higher_is_better = ("dice", "correlation")
    lower_is_better = ("mean_error_px", "p95_error_px")
    worsened = []
    improved = []

    for key in higher_is_better:
        base_value = float(before.get(key, 0.0) or 0.0)
        candidate_value = float(candidate.get(key, 0.0) or 0.0)
        if candidate_value < base_value:
            worsened.append(key)
        elif candidate_value > base_value:
            improved.append(key)

    for key in lower_is_better:
        try:
            base_value = float(before.get(key))
            candidate_value = float(candidate.get(key))
        except (TypeError, ValueError):
            continue
        if candidate_value > base_value:
            worsened.append(key)
        elif candidate_value < base_value:
            improved.append(key)

    if worsened:
        return False, "ecc_candidate_worsened:" + ",".join(worsened)
    if not improved:
        return False, "ecc_candidate_no_measurable_gain"
    return True, "ecc_candidate_improved_alignment"


def _mask_overlap_refinement_decision(
    before: dict,
    candidate: dict,
) -> tuple[bool, str]:
    """Veta refinamento que afaste emissão das máscaras ON fixas."""
    if not bool(before.get("available")) or not bool(candidate.get("available")):
        return True, "mask_overlap_guard_unavailable"

    higher_is_better = (
        "emission_inside_fraction",
        "mask_hot_fraction",
    )
    worsened = []
    for key in higher_is_better:
        base_value = float(before.get(key, 0.0) or 0.0)
        candidate_value = float(candidate.get(key, 0.0) or 0.0)
        if candidate_value < base_value:
            worsened.append(key)

    if worsened:
        return False, "ecc_candidate_worsened_mask_overlap:" + ",".join(
            worsened
        )
    return True, "mask_overlap_preserved"


def _identity_affine() -> np.ndarray:
    return np.asarray(
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        dtype=np.float32,
    )


def _base_registration_result(
    reference_map,
    current_map,
    current_rectified,
    metrics_before: dict,
    *,
    reason: str,
    refinement_reason: str,
    phase_shift=(0.0, 0.0),
    phase_response: float = 0.0,
    ecc_score=None,
    rotation_deg=None,
    center_shift_px=None,
    center_shift_fraction=None,
    error: str = "",
) -> dict:
    """Mantém a homografia retificada quando o refinamento ECC não é utilizável."""
    identity = _identity_affine()
    result = {
        "available": True,
        "reason": str(reason),
        "quality_ok": False,
        "refinement_applied": False,
        "refinement_reason": str(refinement_reason),
        "selected_alignment_source": "filter_homography_base",
        "phase_shift": (
            round(float(phase_shift[0]), 4),
            round(float(phase_shift[1]), 4),
        ),
        "phase_response": round(float(phase_response), 6),
        "reference_to_current_affine": identity.copy(),
        "current_to_reference_affine": identity.copy(),
        "reference_emission_map": np.asarray(reference_map, dtype=np.float32),
        "current_emission_map": np.asarray(current_map, dtype=np.float32),
        "aligned_emission_map": np.asarray(current_map, dtype=np.float32),
        "aligned_current": current_rectified.copy(),
        "metrics_before": dict(metrics_before or {}),
        "metrics_after": dict(metrics_before or {}),
        "ecc_candidate_metrics": {},
    }
    if ecc_score is not None:
        result["ecc_score"] = round(float(ecc_score), 6)
    if rotation_deg is not None:
        result["rotation_deg"] = round(float(rotation_deg), 4)
    if center_shift_px is not None:
        result["center_shift_px"] = round(float(center_shift_px), 4)
    if center_shift_fraction is not None:
        result["center_shift_fraction"] = round(float(center_shift_fraction), 6)
    if error:
        result["error"] = str(error)
    return result


def _preserve_homography_base(
    registration: dict,
    current_rectified,
    reason: str,
) -> dict:
    """Descarta apenas o ajuste ECC e mantém a homografia já retificada."""
    result = dict(registration)
    identity = _identity_affine()
    result.update(
        {
            "quality_ok": False,
            "refinement_applied": False,
            "refinement_reason": str(reason),
            "selected_alignment_source": "filter_homography_base",
            "reference_to_current_affine": identity.copy(),
            "current_to_reference_affine": identity.copy(),
            "aligned_emission_map": np.asarray(
                result["current_emission_map"],
                dtype=np.float32,
            ),
            "aligned_current": current_rectified.copy(),
            "metrics_after": dict(result.get("metrics_before") or {}),
        }
    )
    return result


def register_rectified_h1(
    reference_rectified,
    current_rectified,
) -> dict:
    """Registra o H1 atual inteiro contra o H1 de referência.

    phaseCorrelate fornece a translação inicial. ECC em MOTION_EUCLIDEAN pode
    ajustar somente translação + pequena rotação; não existe escala livre nesta
    etapa experimental.
    """
    if not _valid_image(reference_rectified) or not _valid_image(
        current_rectified
    ):
        return {"available": False, "reason": "invalid_rectified_image"}
    if reference_rectified.shape[:2] != current_rectified.shape[:2]:
        return {"available": False, "reason": "rectified_shape_mismatch"}

    reference_emission = build_h1_emission_map(reference_rectified)
    current_emission = build_h1_emission_map(current_rectified)
    if not bool(reference_emission.get("available")):
        return {
            "available": False,
            "reason": "reference_" + str(reference_emission.get("reason") or ""),
            "reference_emission": reference_emission,
        }
    if not bool(current_emission.get("available")):
        return {
            "available": False,
            "reason": "current_" + str(current_emission.get("reason") or ""),
            "current_emission": current_emission,
        }

    reference_map = np.asarray(
        reference_emission["map"],
        dtype=np.float32,
    )
    current_map = np.asarray(
        current_emission["map"],
        dtype=np.float32,
    )
    h, w = reference_map.shape[:2]

    before = emission_alignment_metrics(reference_map, current_map)

    try:
        window = cv2.createHanningWindow((int(w), int(h)), cv2.CV_32F)
        phase_shift, phase_response = cv2.phaseCorrelate(
            reference_map,
            current_map,
            window,
        )
    except cv2.error:
        phase_shift = (0.0, 0.0)
        phase_response = 0.0

    warp_reference_to_current = np.asarray(
        [
            [1.0, 0.0, float(phase_shift[0])],
            [0.0, 1.0, float(phase_shift[1])],
        ],
        dtype=np.float32,
    )
    criteria = (
        cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
        int(F3_H1_REGISTRATION_ECC_MAX_ITERATIONS),
        float(F3_H1_REGISTRATION_ECC_EPSILON),
    )

    try:
        ecc_score, warp_reference_to_current = cv2.findTransformECC(
            reference_map,
            current_map,
            warp_reference_to_current,
            cv2.MOTION_EUCLIDEAN,
            criteria,
            None,
            5,
        )
    except cv2.error as exc:
        return _base_registration_result(
            reference_map,
            current_map,
            current_rectified,
            before,
            reason="ecc_failed_base_preserved",
            refinement_reason="ecc_failed_base_preserved",
            phase_shift=phase_shift,
            phase_response=phase_response,
            error=type(exc).__name__,
        )

    warp_reference_to_current = np.asarray(
        warp_reference_to_current,
        dtype=np.float32,
    ).reshape(2, 3)
    warp_current_to_reference = cv2.invertAffineTransform(
        warp_reference_to_current
    )

    rotation_deg = math.degrees(
        math.atan2(
            float(warp_reference_to_current[0, 1]),
            float(warp_reference_to_current[0, 0]),
        )
    )
    center = np.asarray(
        [float(w - 1) * 0.5, float(h - 1) * 0.5, 1.0],
        dtype=np.float32,
    )
    mapped_center = warp_reference_to_current @ center
    center_shift = float(
        np.linalg.norm(mapped_center - center[:2])
    )
    diagonal = max(1.0, math.hypot(float(w), float(h)))
    center_shift_fraction = center_shift / diagonal

    guard_ok = bool(
        abs(rotation_deg) <= F3_H1_REGISTRATION_MAX_ROTATION_DEG
        and center_shift_fraction
        <= F3_H1_REGISTRATION_MAX_CENTER_SHIFT_FRACTION
    )
    if not guard_ok:
        return _base_registration_result(
            reference_map,
            current_map,
            current_rectified,
            before,
            reason="registration_outside_guard_base_preserved",
            refinement_reason="registration_outside_guard_base_preserved",
            phase_shift=phase_shift,
            phase_response=phase_response,
            ecc_score=ecc_score,
            rotation_deg=rotation_deg,
            center_shift_px=center_shift,
            center_shift_fraction=center_shift_fraction,
        )

    candidate_map = cv2.warpAffine(
        current_map,
        warp_reference_to_current,
        (int(w), int(h)),
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    candidate_image = cv2.warpAffine(
        current_rectified,
        warp_reference_to_current,
        (int(w), int(h)),
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_REPLICATE,
    )
    candidate_metrics = emission_alignment_metrics(
        reference_map,
        candidate_map,
    )
    refinement_applied, refinement_reason = _ecc_refinement_decision(
        before,
        candidate_metrics,
        float(ecc_score),
    )

    if refinement_applied:
        selected_reference_to_current = warp_reference_to_current
        selected_current_to_reference = np.asarray(
            warp_current_to_reference,
            dtype=np.float32,
        ).reshape(2, 3)
        selected_map = candidate_map
        selected_image = candidate_image
        selected_metrics = candidate_metrics
        selected_source = "ecc_refined"
    else:
        selected_reference_to_current = _identity_affine()
        selected_current_to_reference = _identity_affine()
        selected_map = current_map
        selected_image = current_rectified.copy()
        selected_metrics = before
        selected_source = "filter_homography_base"

    return {
        "available": True,
        "reason": (
            "h1_registered"
            if refinement_applied
            else "h1_registration_base_preserved"
        ),
        "quality_ok": bool(refinement_applied),
        "refinement_applied": bool(refinement_applied),
        "refinement_reason": str(refinement_reason),
        "selected_alignment_source": selected_source,
        "phase_shift": (
            round(float(phase_shift[0]), 4),
            round(float(phase_shift[1]), 4),
        ),
        "phase_response": round(float(phase_response), 6),
        "ecc_score": round(float(ecc_score), 6),
        "rotation_deg": round(float(rotation_deg), 4),
        "center_shift_px": round(center_shift, 4),
        "center_shift_fraction": round(center_shift_fraction, 6),
        "reference_to_current_affine": np.asarray(
            selected_reference_to_current,
            dtype=np.float32,
        ).reshape(2, 3),
        "current_to_reference_affine": np.asarray(
            selected_current_to_reference,
            dtype=np.float32,
        ).reshape(2, 3),
        "ecc_candidate_reference_to_current_affine": np.asarray(
            warp_reference_to_current,
            dtype=np.float32,
        ).reshape(2, 3),
        "ecc_candidate_current_to_reference_affine": np.asarray(
            warp_current_to_reference,
            dtype=np.float32,
        ).reshape(2, 3),
        "reference_emission_map": reference_map,
        "current_emission_map": current_map,
        "aligned_emission_map": selected_map,
        "aligned_current": selected_image,
        "ecc_candidate_emission_map": candidate_map,
        "ecc_candidate_aligned_current": candidate_image,
        "metrics_before": before,
        "metrics_after": selected_metrics,
        "ecc_candidate_metrics": candidate_metrics,
    }


def project_masks_to_rectified_space(masks, image_to_rectified) -> list[dict]:
    """Projeta máscaras ensinadas para a ROI fixa da referência.

    O resultado é somente geométrico/experimental e não é persistido. Círculos
    são amostrados como polígonos porque uma homografia pode transformá-los em
    elipses.
    """
    try:
        homography = np.asarray(
            image_to_rectified,
            dtype=np.float32,
        ).reshape(3, 3)
    except (TypeError, ValueError):
        return []

    projected: list[dict] = []
    for raw in masks or ():
        if not isinstance(raw, dict):
            continue
        mask = converter_mascara_legada_para_editor(raw)
        mask_id = str(mask.get("id") or "")
        if not mask_id:
            continue
        kind = str(mask.get("type") or "").lower()
        points = []
        if kind == "circle":
            try:
                cx = float(mask.get("cx", 0.0))
                cy = float(mask.get("cy", 0.0))
                radius = max(1.0, float(mask.get("radius", 1.0)))
            except (TypeError, ValueError):
                continue
            for index in range(24):
                angle = 2.0 * math.pi * index / 24.0
                points.append(
                    [
                        cx + radius * math.cos(angle),
                        cy + radius * math.sin(angle),
                    ]
                )
        else:
            points = [
                [float(point[0]), float(point[1])]
                for point in pontos_mascara_display(mask)
            ]
        if len(points) < 3:
            continue
        try:
            values = np.asarray(
                points,
                dtype=np.float32,
            ).reshape(-1, 1, 2)
            transformed = cv2.perspectiveTransform(
                values,
                homography,
            ).reshape(-1, 2)
        except (cv2.error, TypeError, ValueError):
            continue
        if not np.all(np.isfinite(transformed)):
            continue
        projected.append(
            {
                "id": mask_id,
                "type": "polygon",
                "points": [
                    [float(point[0]), float(point[1])]
                    for point in transformed
                ],
            }
        )
    return projected


def emission_overlap_with_masks(
    emission_map,
    masks,
    *,
    mask_ids=None,
) -> dict:
    """Mede quanto da emissão cai dentro das máscaras fixas selecionadas."""
    try:
        emission = np.asarray(emission_map, dtype=np.float32)
    except (TypeError, ValueError):
        return {"available": False, "reason": "invalid_emission_map"}
    if emission.ndim != 2 or emission.size == 0:
        return {"available": False, "reason": "invalid_emission_map"}

    selected_ids = (
        {str(value) for value in mask_ids}
        if mask_ids is not None
        else None
    )
    mask_union = np.zeros(emission.shape, dtype=np.uint8)
    selected_count = 0
    for mask in masks or ():
        if not isinstance(mask, dict):
            continue
        mask_id = str(mask.get("id") or "")
        if selected_ids is not None and mask_id not in selected_ids:
            continue
        points = mask.get("points")
        try:
            polygon = np.rint(
                np.asarray(points, dtype=np.float32)
            ).astype(np.int32).reshape(-1, 2)
        except (TypeError, ValueError):
            continue
        if len(polygon) < 3:
            continue
        cv2.fillPoly(
            mask_union,
            [polygon],
            255,
            lineType=cv2.LINE_AA,
        )
        selected_count += 1

    mask_pixels = int(cv2.countNonZero(mask_union))
    hot = emission >= float(F3_H1_REGISTRATION_BINARY_THRESHOLD)
    hot_count = int(np.count_nonzero(hot))
    if selected_count <= 0 or mask_pixels <= 0 or hot_count <= 0:
        return {
            "available": False,
            "reason": "mask_or_emission_empty",
            "selected_mask_count": selected_count,
            "mask_pixels": mask_pixels,
            "hot_pixels": hot_count,
        }
    inside = int(np.count_nonzero(hot & (mask_union > 0)))
    return {
        "available": True,
        "reason": "mask_overlap_ready",
        "selected_mask_count": int(selected_count),
        "mask_pixels": mask_pixels,
        "hot_pixels": hot_count,
        "hot_inside_mask_pixels": inside,
        "emission_inside_fraction": round(
            inside / max(1, hot_count),
            6,
        ),
        "mask_hot_fraction": round(
            inside / max(1, mask_pixels),
            6,
        ),
    }


def register_h1_with_filter_homography(
    reference_frame,
    reference_filter_points,
    current_frame,
    current_filter_points,
    *,
    reference_masks=None,
    expected_on_mask_ids=None,
) -> dict:
    """Executa o experimento completo para um par referência/atual conhecido."""
    reference_rectification = rectify_filter_homography(
        reference_frame,
        reference_filter_points,
    )
    if not bool(reference_rectification.get("available")):
        return {
            "available": False,
            "reason": "reference_" + str(
                reference_rectification.get("reason") or ""
            ),
        }

    current_rectification = rectify_filter_homography(
        current_frame,
        current_filter_points,
        output_size=reference_rectification.get("size"),
    )
    if not bool(current_rectification.get("available")):
        return {
            "available": False,
            "reason": "current_" + str(
                current_rectification.get("reason") or ""
            ),
        }

    registration = register_rectified_h1(
        reference_rectification["image"],
        current_rectification["image"],
    )
    if not bool(registration.get("available")):
        result = dict(registration)
        result["reference_rectification"] = reference_rectification
        result["current_rectification"] = current_rectification
        return result

    fixed_masks = project_masks_to_rectified_space(
        reference_masks or (),
        reference_rectification["image_to_rectified"],
    )
    mask_overlap_before = {}
    mask_overlap_candidate = {}
    if fixed_masks:
        mask_overlap_before = emission_overlap_with_masks(
            registration["current_emission_map"],
            fixed_masks,
            mask_ids=expected_on_mask_ids,
        )
        mask_overlap_candidate = emission_overlap_with_masks(
            registration.get(
                "ecc_candidate_emission_map",
                registration["aligned_emission_map"],
            ),
            fixed_masks,
            mask_ids=expected_on_mask_ids,
        )

    selected_registration = dict(registration)
    if bool(selected_registration.get("refinement_applied")) and fixed_masks:
        overlap_ok, overlap_reason = _mask_overlap_refinement_decision(
            mask_overlap_before,
            mask_overlap_candidate,
        )
        if not overlap_ok:
            selected_registration = _preserve_homography_base(
                selected_registration,
                current_rectification["image"],
                overlap_reason,
            )

    mask_overlap_after = {}
    if fixed_masks:
        mask_overlap_after = emission_overlap_with_masks(
            selected_registration["aligned_emission_map"],
            fixed_masks,
            mask_ids=expected_on_mask_ids,
        )

    current_to_reference_affine = np.eye(3, dtype=np.float32)
    current_to_reference_affine[:2, :] = np.asarray(
        selected_registration["current_to_reference_affine"],
        dtype=np.float32,
    ).reshape(2, 3)
    current_frame_to_reference_rectified = (
        current_to_reference_affine
        @ np.asarray(
            current_rectification["image_to_rectified"],
            dtype=np.float32,
        ).reshape(3, 3)
    )

    result = dict(selected_registration)
    result.update(
        {
            "source": "d025_homography_h1_registration_experiment",
            "expected_on_mask_ids": sorted(
                str(value)
                for value in (expected_on_mask_ids or ())
                if str(value)
            ),
            "reference_rectified": reference_rectification["image"],
            "current_rectified": current_rectification["image"],
            "rectified_size": tuple(reference_rectification["size"]),
            "reference_filter_points": reference_rectification[
                "filter_points"
            ],
            "current_filter_points": current_rectification[
                "filter_points"
            ],
            "reference_image_to_rectified": np.asarray(
                reference_rectification["image_to_rectified"],
                dtype=np.float32,
            ).reshape(3, 3),
            "current_image_to_rectified": np.asarray(
                current_rectification["image_to_rectified"],
                dtype=np.float32,
            ).reshape(3, 3),
            "current_frame_to_reference_rectified": np.asarray(
                current_frame_to_reference_rectified,
                dtype=np.float32,
            ).reshape(3, 3),
            "fixed_masks_rectified": fixed_masks,
            "mask_overlap_before": mask_overlap_before,
            "mask_overlap_after": mask_overlap_after,
            "ecc_candidate_mask_overlap": mask_overlap_candidate,
        }
    )
    return result



def summarize_h1_registration(result: dict | None) -> dict:
    """Remove imagens/matrizes pesadas e mantém somente telemetria copiável."""
    data = result if isinstance(result, dict) else {}
    return {
        "available": bool(data.get("available")),
        "reason": str(data.get("reason") or ""),
        "registration_reason": str(
            data.get("registration_reason")
            or data.get("reason")
            or ""
        ),
        "quality_ok": bool(data.get("quality_ok")),
        "refinement_applied": bool(data.get("refinement_applied")),
        "refinement_reason": str(data.get("refinement_reason") or ""),
        "selected_alignment_source": str(
            data.get("selected_alignment_source") or ""
        ),
        "experimental": bool(data.get("experimental", True)),
        "production_authority": bool(data.get("production_authority", False)),
        "filter_candidate_count": int(data.get("filter_candidate_count", 0) or 0),
        "filter_locator_source": str(
            data.get("filter_locator_source") or ""
        ),
        "rectified_size": list(data.get("rectified_size") or ()),
        "phase_shift": list(data.get("phase_shift") or ()),
        "phase_response": data.get("phase_response"),
        "ecc_score": data.get("ecc_score"),
        "rotation_deg": data.get("rotation_deg"),
        "center_shift_px": data.get("center_shift_px"),
        "center_shift_fraction": data.get("center_shift_fraction"),
        "expected_on_mask_ids": list(data.get("expected_on_mask_ids") or ()),
        "metrics_before": dict(data.get("metrics_before") or {}),
        "metrics_after": dict(data.get("metrics_after") or {}),
        "ecc_candidate_metrics": dict(
            data.get("ecc_candidate_metrics") or {}
        ),
        "mask_overlap_before": dict(data.get("mask_overlap_before") or {}),
        "mask_overlap_after": dict(data.get("mask_overlap_after") or {}),
        "ecc_candidate_mask_overlap": dict(
            data.get("ecc_candidate_mask_overlap") or {}
        ),
        "attempts": [
            {
                "filter_score": item.get("filter_score"),
                "filter_source": item.get("filter_source"),
                "available": bool(item.get("available")),
                "reason": str(item.get("reason") or ""),
                "quality_ok": bool(item.get("quality_ok")),
                "refinement_applied": bool(item.get("refinement_applied")),
                "refinement_reason": str(item.get("refinement_reason") or ""),
                "selected_alignment_source": str(
                    item.get("selected_alignment_source") or ""
                ),
                "ecc_score": item.get("ecc_score"),
                "rotation_deg": item.get("rotation_deg"),
                "center_shift_px": item.get("center_shift_px"),
                "metrics_after": dict(item.get("metrics_after") or {}),
                "mask_overlap_after": dict(
                    item.get("mask_overlap_after") or {}
                ),
            }
            for item in (data.get("attempts") or ())
            if isinstance(item, dict)
        ],
    }


def _draw_fixed_mask_overlay(
    image,
    masks,
    *,
    expected_on_mask_ids=None,
):
    if not _valid_image(image):
        return None
    output = image.copy()
    expected = {
        str(value)
        for value in (expected_on_mask_ids or ())
        if str(value)
    }
    for mask in masks or ():
        if not isinstance(mask, dict):
            continue
        mask_id = str(mask.get("id") or "")
        try:
            polygon = np.rint(
                np.asarray(mask.get("points"), dtype=np.float32)
            ).astype(np.int32).reshape(-1, 2)
        except (TypeError, ValueError):
            continue
        if len(polygon) < 3:
            continue
        color = (70, 220, 90) if mask_id in expected else (230, 190, 45)
        cv2.polylines(
            output,
            [polygon],
            True,
            color,
            2 if mask_id in expected else 1,
            cv2.LINE_AA,
        )
    return output


def _diagnostic_panel(image, title: str, masks, expected_on_ids) -> np.ndarray:
    visual = _draw_fixed_mask_overlay(
        image,
        masks,
        expected_on_mask_ids=expected_on_ids,
    )
    if visual is None:
        visual = np.zeros((120, 320, 3), dtype=np.uint8)
    panel = cv2.copyMakeBorder(
        visual,
        28,
        0,
        0,
        0,
        cv2.BORDER_CONSTANT,
        value=(12, 20, 34),
    )
    cv2.putText(
        panel,
        str(title),
        (9, 19),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (232, 238, 246),
        1,
        cv2.LINE_AA,
    )
    return panel


def render_h1_registration_diagnostic(result: dict | None):
    """Monta REFERÊNCIA | RETIFICADO | REGISTRADO com máscaras fixas."""
    data = result if isinstance(result, dict) else {}
    reference = data.get("reference_rectified")
    current = data.get("current_rectified")
    aligned = data.get("aligned_current")
    if not all(_valid_image(image) for image in (reference, current, aligned)):
        return None

    masks = [
        mask
        for mask in (data.get("fixed_masks_rectified") or ())
        if isinstance(mask, dict)
    ]
    expected = list(data.get("expected_on_mask_ids") or ())
    refinement_applied = bool(data.get("refinement_applied"))
    selected_title = (
        "H1 REGISTRADO - ECC ACEITO"
        if refinement_applied
        else "BASE PRESERVADA - ECC REJEITADO"
    )
    panels = [
        _diagnostic_panel(reference, "REFERENCIA H1", masks, expected),
        _diagnostic_panel(current, "FILTRO RETIFICADO", masks, expected),
        _diagnostic_panel(aligned, selected_title, masks, expected),
    ]
    height = min(panel.shape[0] for panel in panels)
    normalized = []
    for panel in panels:
        if panel.shape[0] != height:
            width = max(
                1,
                int(round(panel.shape[1] * height / float(panel.shape[0]))),
            )
            panel = cv2.resize(
                panel,
                (width, height),
                interpolation=cv2.INTER_AREA,
            )
        normalized.append(panel)

    composite = np.hstack(normalized)
    before = data.get("metrics_before") or {}
    after = data.get("metrics_after") or {}
    overlap_before = data.get("mask_overlap_before") or {}
    overlap_after = data.get("mask_overlap_after") or {}
    composite = cv2.copyMakeBorder(
        composite,
        0,
        34,
        0,
        0,
        cv2.BORDER_CONSTANT,
        value=(7, 17, 31),
    )
    candidate = data.get("ecc_candidate_metrics") or {}
    candidate_overlap = data.get("ecc_candidate_mask_overlap") or {}
    if refinement_applied:
        decision_text = "ECC ACEITO"
    else:
        decision_text = "ECC REJEITADO / BASE PRESERVADA"
    summary = (
        f"{decision_text} | ECC {float(data.get('ecc_score', 0.0) or 0.0):.3f} | "
        f"DICE base {float(before.get('dice', 0.0) or 0.0):.3f}"
        f" / cand {float(candidate.get('dice', 0.0) or 0.0):.3f}"
        f" / sel {float(after.get('dice', 0.0) or 0.0):.3f} | "
        f"erro base {float(before.get('mean_error_px', 0.0) or 0.0):.2f}"
        f" / cand {float(candidate.get('mean_error_px', 0.0) or 0.0):.2f}"
        f" / sel {float(after.get('mean_error_px', 0.0) or 0.0):.2f}px | "
        f"mascaras base "
        f"{float(overlap_before.get('emission_inside_fraction', 0.0) or 0.0):.2f}"
        f" / cand "
        f"{float(candidate_overlap.get('emission_inside_fraction', 0.0) or 0.0):.2f}"
        f" / sel "
        f"{float(overlap_after.get('emission_inside_fraction', 0.0) or 0.0):.2f}"
    )
    cv2.putText(
        composite,
        summary,
        (9, composite.shape[0] - 11),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.43,
        (202, 213, 226),
        1,
        cv2.LINE_AA,
    )
    return composite


def encode_h1_registration_diagnostic_png(result: dict | None) -> bytes:
    """PNG pronto no worker; a UI apenas apresenta os bytes precomputados."""
    visual = render_h1_registration_diagnostic(result)
    if not _valid_image(visual):
        return b""
    ok, buffer = cv2.imencode(".png", visual)
    return bytes(buffer) if ok else b""
