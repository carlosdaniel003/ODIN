from __future__ import annotations

"""Reforço de reacquisição do rastreamento F2 em 90° e 180°.

O banco multivista original já possuía ângulos grandes, porém duas propriedades
prejudicavam placas retangulares quando ficavam de lado ou invertidas:

1. as vistas sintéticas eram rotacionadas dentro do frame inteiro original, o que
   podia recortar parte da placa/contorno e reduzir bastante os descritores úteis;
2. a validação de distribuição dos inliers era feita nos eixos X/Y da câmera.
   Uma placa longa e estreita girada 90° naturalmente fica estreita em X e podia
   ser rejeitada mesmo com uma correspondência geométrica correta.

Esta camada mantém o recurso completamente opt-in pelo mesmo setting de tracking.
Ela apenas substitui a construção e a validação das vistas do fallback multivista.
Nenhuma referência, ROI ou imagem do projeto é persistida/modificada.
"""

import math

import cv2
import numpy as np

import src.platform.f2_object_tracking_multiview as multiview
from src.platform.f2_object_tracking import (
    F2_TRACKING_MAX_SCALE,
    F2_TRACKING_MIN_INLIER_RATIO,
    F2_TRACKING_MIN_INLIERS,
    F2_TRACKING_MIN_MATCHES,
    F2_TRACKING_MIN_SCALE,
    F2_TRACKING_RANSAC_THRESHOLD_PX,
    F2_TRACKING_RATIO_TEST,
)
from src.platform.f2_object_tracking_runtime_fix import (
    F2_TRACKING_WIDE_ROTATION_DEG,
    F2_TRACKING_WIDE_TRANSLATION_FRACTION,
    _pose_matriz_rastreamento,
)


# Mais descritores são calculados somente na preparação do projeto, não em cada
# frame. O aumento é pequeno o suficiente para o Raspberry Pi 3 e melhora bastante
# a reacquisição da placa invertida.
F2_CARDINAL_FEATURES_PER_VIEW = 520
F2_CARDINAL_EDGE_THRESHOLD = 12
F2_CARDINAL_FAST_THRESHOLD = 7
F2_CARDINAL_CANVAS_MARGIN_PX = 18
F2_CARDINAL_CROP_PADDING_PX = 22

# Nos ângulos cardinais aceitamos um pouco mais de ambiguidade no descriptor ORB,
# mas continuamos exigindo RANSAC, escala, translação e dispersão geométrica.
F2_CARDINAL_RATIO_TEST = max(0.82, float(F2_TRACKING_RATIO_TEST))
F2_CARDINAL_MIN_MATCHES = max(10, int(F2_TRACKING_MIN_MATCHES) - 4)
F2_CARDINAL_MIN_INLIERS = max(7, int(F2_TRACKING_MIN_INLIERS) - 3)
F2_CARDINAL_MIN_INLIER_RATIO = min(0.30, float(F2_TRACKING_MIN_INLIER_RATIO))
F2_CARDINAL_RANSAC_THRESHOLD_PX = max(
    4.5,
    float(F2_TRACKING_RANSAC_THRESHOLD_PX),
)

# A validação abaixo usa eixos principais (PCA/SVD), portanto é invariável à
# rotação. Ela substitui o antigo requisito X/Y baseado na resolução da câmera.
F2_CARDINAL_MAJOR_SPREAD_FRACTION = 0.14
F2_CARDINAL_MINOR_SPREAD_FRACTION = 0.08
F2_MULTIVIEW_MAJOR_SPREAD_FRACTION = 0.16
F2_MULTIVIEW_MINOR_SPREAD_FRACTION = 0.10

_CARDINAL_ANGLES = (-90.0, 90.0, 180.0)
_PATCH_INSTALADO = False


def _eh_angulo_cardinal(angle: float) -> bool:
    value = ((float(angle) + 180.0) % 360.0) - 180.0
    if abs(value + 180.0) < 0.5:
        value = 180.0
    return any(abs(value - expected) < 0.5 for expected in _CARDINAL_ANGLES)


def _bbox_mascara(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    try:
        points = cv2.findNonZero(mask)
        if points is None:
            return None
        x, y, width, height = cv2.boundingRect(points)
        if width <= 0 or height <= 0:
            return None
        return int(x), int(y), int(width), int(height)
    except Exception:
        return None


def _matriz_homogenea(affine) -> np.ndarray:
    value = np.asarray(affine, dtype=np.float32).reshape(2, 3)
    return np.asarray(
        [
            [value[0, 0], value[0, 1], value[0, 2]],
            [value[1, 0], value[1, 1], value[1, 2]],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )


def _preparar_canvas_rotacao(
    gray: np.ndarray,
    mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, float] | None:
    """Recorta a região da placa e a centraliza num canvas quadrado sem clipping.

    Retorna ``(gray_canvas, mask_canvas, canonical_to_canvas, board_major,
    board_minor)``. O lado do canvas usa a diagonal do recorte, então 90°, 180°
    e também os ângulos intermediários cabem sem cortar a placa.
    """
    if gray is None or mask is None or gray.shape[:2] != mask.shape[:2]:
        return None

    bbox = _bbox_mascara(mask)
    if bbox is None:
        return None
    x, y, width, height = bbox
    image_height, image_width = gray.shape[:2]

    pad = int(F2_CARDINAL_CROP_PADDING_PX)
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(int(image_width), x + width + pad)
    y2 = min(int(image_height), y + height + pad)
    if x2 <= x1 or y2 <= y1:
        return None

    crop_gray = gray[y1:y2, x1:x2]
    crop_mask = mask[y1:y2, x1:x2]
    crop_h, crop_w = crop_gray.shape[:2]
    diagonal = int(math.ceil(math.hypot(float(crop_w), float(crop_h))))
    side = max(crop_w, crop_h, diagonal) + 2 * int(F2_CARDINAL_CANVAS_MARGIN_PX)
    side = max(64, int(side))

    valid = crop_mask > 0
    if np.any(valid):
        fill_value = int(np.median(crop_gray[valid]))
    else:
        fill_value = int(np.median(crop_gray)) if crop_gray.size else 0

    gray_canvas = np.full((side, side), fill_value, dtype=np.uint8)
    mask_canvas = np.zeros((side, side), dtype=np.uint8)
    offset_x = (side - crop_w) // 2
    offset_y = (side - crop_h) // 2
    gray_canvas[offset_y:offset_y + crop_h, offset_x:offset_x + crop_w] = crop_gray
    mask_canvas[offset_y:offset_y + crop_h, offset_x:offset_x + crop_w] = crop_mask

    canonical_to_canvas = np.asarray(
        [
            [1.0, 0.0, float(offset_x - x1)],
            [0.0, 1.0, float(offset_y - y1)],
        ],
        dtype=np.float32,
    )
    board_major = float(max(width, height))
    board_minor = float(min(width, height))
    return (
        gray_canvas,
        mask_canvas,
        canonical_to_canvas,
        board_major,
        board_minor,
    )


def _mapear_keypoints_para_canonico(keypoints, canonical_to_view):
    if not keypoints:
        return []
    try:
        inverse = cv2.invertAffineTransform(
            np.asarray(canonical_to_view, dtype=np.float32).reshape(2, 3)
        )
    except Exception:
        return []

    mapped = []
    for keypoint in keypoints:
        try:
            x, y = keypoint.pt
            canonical = inverse @ np.asarray([x, y, 1.0], dtype=np.float32)
            mapped.append(
                cv2.KeyPoint(
                    float(canonical[0]),
                    float(canonical[1]),
                    float(keypoint.size),
                    float(keypoint.angle),
                    float(keypoint.response),
                    int(keypoint.octave),
                    int(keypoint.class_id),
                )
            )
        except Exception:
            continue
    return mapped


def _criar_vistas_referencia_sem_clipping(gray, mask) -> list[dict]:
    prepared = _preparar_canvas_rotacao(gray, mask)
    if prepared is None:
        return []
    (
        gray_canvas,
        mask_canvas,
        canonical_to_canvas,
        board_major,
        board_minor,
    ) = prepared

    side = int(gray_canvas.shape[0])
    center = ((side - 1) / 2.0, (side - 1) / 2.0)
    orb = cv2.ORB_create(
        nfeatures=int(F2_CARDINAL_FEATURES_PER_VIEW),
        scaleFactor=1.2,
        nlevels=8,
        edgeThreshold=int(F2_CARDINAL_EDGE_THRESHOLD),
        fastThreshold=int(F2_CARDINAL_FAST_THRESHOLD),
    )

    canvas_transform = _matriz_homogenea(canonical_to_canvas)
    views = []
    for angle in tuple(multiview.F2_MULTIVIEW_ANGLES_DEG):
        rotation = cv2.getRotationMatrix2D(center, float(angle), 1.0).astype(np.float32)
        rotated_gray = cv2.warpAffine(
            gray_canvas,
            rotation,
            (side, side),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
        rotated_mask = cv2.warpAffine(
            mask_canvas,
            rotation,
            (side, side),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )

        keypoints, descriptors = orb.detectAndCompute(rotated_gray, rotated_mask)
        if descriptors is None or not keypoints:
            continue

        rotation_transform = _matriz_homogenea(rotation)
        canonical_to_view = (rotation_transform @ canvas_transform)[:2, :]
        mapped = _mapear_keypoints_para_canonico(keypoints, canonical_to_view)
        if len(mapped) != len(keypoints):
            continue

        cardinal = _eh_angulo_cardinal(float(angle))
        minimum = (
            int(F2_CARDINAL_MIN_MATCHES)
            if cardinal
            else int(F2_TRACKING_MIN_MATCHES)
        )
        if len(mapped) < minimum:
            continue

        views.append(
            {
                "angle": float(angle),
                "keypoints": mapped,
                "descriptors": descriptors,
                "cardinal": bool(cardinal),
                "board_major": float(board_major),
                "board_minor": float(board_minor),
            }
        )
    return views


def _spans_principais(points) -> tuple[float, float]:
    """Retorna extensão maior/menor dos pontos em eixos próprios, não X/Y."""
    values = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    if len(values) < 3:
        return 0.0, 0.0
    centered = values - np.mean(values, axis=0, keepdims=True)
    try:
        _u, _s, vh = np.linalg.svd(centered, full_matrices=False)
        projected = centered @ vh.T
        spans = np.ptp(projected, axis=0)
        if len(spans) < 2:
            return 0.0, 0.0
        major = float(max(spans[0], spans[1]))
        minor = float(min(spans[0], spans[1]))
        return major, minor
    except Exception:
        return 0.0, 0.0


def _dispersao_inliers_valida(points, view: dict) -> bool:
    major, minor = _spans_principais(points)
    board_major = max(1.0, float(view.get("board_major", 1.0) or 1.0))
    board_minor = max(1.0, float(view.get("board_minor", 1.0) or 1.0))
    cardinal = bool(view.get("cardinal", False))

    major_fraction = (
        F2_CARDINAL_MAJOR_SPREAD_FRACTION
        if cardinal
        else F2_MULTIVIEW_MAJOR_SPREAD_FRACTION
    )
    minor_fraction = (
        F2_CARDINAL_MINOR_SPREAD_FRACTION
        if cardinal
        else F2_MULTIVIEW_MINOR_SPREAD_FRACTION
    )
    return bool(
        major >= board_major * float(major_fraction)
        and minor >= board_minor * float(minor_fraction)
    )


def _candidato_vista_rotacao_robusta(
    tracker,
    current_kp,
    current_desc,
    slot: str,
    view: dict,
):
    ref_kp = list(view.get("keypoints", ()) or ())
    ref_desc = view.get("descriptors")
    if ref_desc is None or not ref_kp:
        return None

    cardinal = bool(view.get("cardinal", False))
    ratio_test = (
        float(F2_CARDINAL_RATIO_TEST)
        if cardinal
        else float(F2_TRACKING_RATIO_TEST)
    )
    min_matches = (
        int(F2_CARDINAL_MIN_MATCHES)
        if cardinal
        else int(F2_TRACKING_MIN_MATCHES)
    )
    min_inliers = (
        int(F2_CARDINAL_MIN_INLIERS)
        if cardinal
        else int(F2_TRACKING_MIN_INLIERS)
    )
    min_ratio = (
        float(F2_CARDINAL_MIN_INLIER_RATIO)
        if cardinal
        else float(F2_TRACKING_MIN_INLIER_RATIO)
    )
    ransac_threshold = (
        float(F2_CARDINAL_RANSAC_THRESHOLD_PX)
        if cardinal
        else float(F2_TRACKING_RANSAC_THRESHOLD_PX)
    )

    if len(ref_kp) < min_matches:
        return None

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    try:
        pairs = matcher.knnMatch(ref_desc, current_desc, k=2)
    except Exception:
        return None

    good = []
    for pair in pairs:
        if len(pair) < 2:
            continue
        first, second = pair[0], pair[1]
        if first.distance < ratio_test * second.distance:
            good.append(first)
    if len(good) < min_matches:
        return None

    current_points = np.float32(
        [current_kp[item.trainIdx].pt for item in good]
    ).reshape(-1, 1, 2)
    reference_points = np.float32(
        [ref_kp[item.queryIdx].pt for item in good]
    ).reshape(-1, 1, 2)
    matrix, inlier_mask = cv2.estimateAffinePartial2D(
        current_points,
        reference_points,
        method=cv2.RANSAC,
        ransacReprojThreshold=ransac_threshold,
        maxIters=3600 if cardinal else 2800,
        confidence=0.997 if cardinal else 0.995,
        refineIters=15,
    )
    if matrix is None or inlier_mask is None:
        return None

    flags = np.asarray(inlier_mask).reshape(-1).astype(bool)
    inliers = int(np.count_nonzero(flags))
    ratio = float(inliers / max(1, len(good)))
    if inliers < min_inliers or ratio < min_ratio:
        return None

    inlier_points = current_points.reshape(-1, 2)[flags]
    if not _dispersao_inliers_valida(inlier_points, view):
        return None

    try:
        scale, rotation_deg, dx, dy = _pose_matriz_rastreamento(
            tracker,
            matrix,
            slot,
        )
    except Exception:
        return None

    if not (float(F2_TRACKING_MIN_SCALE) <= scale <= float(F2_TRACKING_MAX_SCALE)):
        return None
    # Pequena tolerância numérica no limite de ±180°.
    if abs(rotation_deg) > float(F2_TRACKING_WIDE_ROTATION_DEG) + 0.75:
        return None
    if abs(dx) > float(tracker.width) * float(F2_TRACKING_WIDE_TRANSLATION_FRACTION):
        return None
    if abs(dy) > float(tracker.height) * float(F2_TRACKING_WIDE_TRANSLATION_FRACTION):
        return None

    score = float(inliers) + ratio * 10.0
    if cardinal:
        # Bônus pequeno: serve apenas para desempatar candidatos praticamente
        # equivalentes; RANSAC e a geometria continuam sendo autoritativos.
        score += 0.75

    return {
        "slot": str(slot),
        "angle": float(view.get("angle", 0.0) or 0.0),
        "matrix": np.asarray(matrix, dtype=np.float32),
        "matches": len(good),
        "inliers": inliers,
        "ratio": ratio,
        "dx": float(dx),
        "dy": float(dy),
        "rotation_deg": float(rotation_deg),
        "scale": float(scale),
        "score": float(score),
    }


def instalar_correcao_rotacao_cardinal_rastreamento_f2() -> None:
    """Torna o fallback multivista robusto a placa de lado e invertida."""
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return

    # A configuração do tracker chama essas funções por lookup no módulo em tempo
    # de execução. O instalador é executado antes de RaspberryPi3ProductionApp ser
    # criado, então o banco do projeto já nasce com as vistas corrigidas.
    multiview._criar_vistas_referencia = _criar_vistas_referencia_sem_clipping
    multiview._candidato_vista = _candidato_vista_rotacao_robusta
    multiview.F2_MULTIVIEW_FEATURES_PER_VIEW = int(F2_CARDINAL_FEATURES_PER_VIEW)

    _PATCH_INSTALADO = True
