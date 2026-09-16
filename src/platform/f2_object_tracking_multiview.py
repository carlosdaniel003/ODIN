from __future__ import annotations

"""Reaquisição multivista do rastreamento opt-in da placa no F2.

Não treina um modelo nem exige novas fotos do operador. A partir das referências
já salvas (placa ligada/desligada), cria em memória vistas rotacionadas da própria
placa e extrai descritores ORB dessas vistas. O banco só é consultado quando o
pipeline normal ORB + ECC + histerese não conseguiu manter/reencontrar a placa.

Os keypoints das vistas sintéticas são reprojetados para o sistema canônico da
referência. Assim a matriz encontrada continua sendo CURRENT->REFERÊNCIA e todo o
restante do F2 (overlay móvel, alinhamento e OperationEngine) permanece igual.
"""

import math
import time

import cv2
import numpy as np

from src.core.roi_geometry import TIPO_ROI_SEGMENTO, normalizar_tipo_roi, pontos_segmento
from src.platform.f2_board_presence_references import (
    F2_BOARD_REF_BOARD_OFF,
    F2_BOARD_REF_BOARD_ON,
)
from src.platform.f2_board_shape_editor import carregar_contorno_placa_leds
from src.platform.f2_object_tracking import (
    F2BoardObjectTracker,
    F2TrackingResult,
    F2_TRACKING_MAX_SCALE,
    F2_TRACKING_MIN_INLIER_RATIO,
    F2_TRACKING_MIN_INLIERS,
    F2_TRACKING_MIN_MATCHES,
    F2_TRACKING_MIN_SCALE,
    F2_TRACKING_RANSAC_THRESHOLD_PX,
    F2_TRACKING_RATIO_TEST,
    construir_mascara_rastreamento_f2,
)
from src.platform.f2_object_tracking_runtime_fix import (
    F2_TRACKING_WIDE_ROTATION_DEG,
    F2_TRACKING_WIDE_TRANSLATION_FRACTION,
    _pose_matriz_rastreamento,
    _registrar_lock_confiavel,
)


# ORB já tolera variações menores de orientação. O banco cobre os grandes saltos
# que fazem a aquisição inicial falhar, sem multiplicar descritores em todo frame.
F2_MULTIVIEW_ANGLES_DEG = (
    -150.0,
    -120.0,
    -90.0,
    -60.0,
    -30.0,
    30.0,
    60.0,
    90.0,
    120.0,
    150.0,
    180.0,
)
F2_MULTIVIEW_FEATURES_PER_VIEW = 280
F2_MULTIVIEW_RETRY_INTERVAL_S = 0.16
F2_MULTIVIEW_MIN_SPREAD_FRACTION = 0.10
F2_MULTIVIEW_STRONG_INLIERS = 18
F2_MULTIVIEW_STRONG_RATIO = 0.52

_PATCH_INSTALADO = False


def _limpar_multiview(tracker) -> None:
    tracker._f2_multiview_signature = None
    tracker._f2_multiview_bank = {}
    tracker._f2_multiview_ready = False
    tracker._f2_multiview_last_compute_s = 0.0
    tracker._f2_multiview_last_angle = None


def _centro_mascara(mask: np.ndarray) -> tuple[float, float]:
    try:
        moments = cv2.moments(mask, binaryImage=True)
        if float(moments.get("m00", 0.0)) > 1.0:
            return (
                float(moments["m10"] / moments["m00"]),
                float(moments["m01"] / moments["m00"]),
            )
    except Exception:
        pass
    height, width = mask.shape[:2]
    return float(width) / 2.0, float(height) / 2.0


def _mapear_keypoints_para_canonico(keypoints, rotated_from_canonical):
    """Mantém o descritor da vista rotacionada, mas devolve o ponto canônico."""
    if not keypoints:
        return []
    inverse = cv2.invertAffineTransform(
        np.asarray(rotated_from_canonical, dtype=np.float32).reshape(2, 3)
    )
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


def _criar_vistas_referencia(gray, mask) -> list[dict]:
    if gray is None or mask is None:
        return []
    height, width = gray.shape[:2]
    if width <= 0 or height <= 0 or mask.shape[:2] != gray.shape[:2]:
        return []

    center = _centro_mascara(mask)
    orb = cv2.ORB_create(
        nfeatures=int(F2_MULTIVIEW_FEATURES_PER_VIEW),
        scaleFactor=1.2,
        nlevels=7,
        edgeThreshold=15,
        fastThreshold=9,
    )
    views = []
    for angle in F2_MULTIVIEW_ANGLES_DEG:
        rotation = cv2.getRotationMatrix2D(center, float(angle), 1.0).astype(np.float32)
        rotated_gray = cv2.warpAffine(
            gray,
            rotation,
            (int(width), int(height)),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        rotated_mask = cv2.warpAffine(
            mask,
            rotation,
            (int(width), int(height)),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        keypoints, descriptors = orb.detectAndCompute(rotated_gray, rotated_mask)
        if descriptors is None or len(keypoints) < int(F2_TRACKING_MIN_MATCHES):
            continue
        mapped = _mapear_keypoints_para_canonico(keypoints, rotation)
        if len(mapped) != len(keypoints):
            continue
        views.append(
            {
                "angle": float(angle),
                "keypoints": mapped,
                "descriptors": descriptors,
            }
        )
    return views


def _configurar_multiview(tracker, controller) -> bool:
    signature = getattr(tracker, "signature", None)
    if (
        signature is not None
        and getattr(tracker, "_f2_multiview_signature", None) == signature
        and bool(getattr(tracker, "_f2_multiview_ready", False))
    ):
        return True

    tracker._f2_multiview_signature = signature
    tracker._f2_multiview_bank = {}
    tracker._f2_multiview_ready = False

    if controller is None:
        return False
    project = str(controller.project_name() or "").strip()
    resolution = controller.master_resolution(project) if project else None
    entries = controller._entries(project) if project else {}
    if not project or not resolution:
        return False

    width, height = int(resolution[0]), int(resolution[1])
    shape = carregar_contorno_placa_leds(controller, project, width, height)
    if not shape:
        return False
    leds = tracker._load_leds(controller, project)
    tracking_mask = construir_mascara_rastreamento_f2(
        shape,
        leds,
        width,
        height,
    )
    if tracking_mask is None:
        return False

    bank = {}
    for slot in (F2_BOARD_REF_BOARD_ON, F2_BOARD_REF_BOARD_OFF):
        path = str(entries.get(slot, {}).get("image_path") or "").strip()
        image = cv2.imread(path) if path else None
        if image is None or getattr(image, "size", 0) == 0:
            continue
        if image.shape[1] != width or image.shape[0] != height:
            continue
        gray = tracker._prepare_gray(image)
        if gray is None:
            continue
        views = _criar_vistas_referencia(gray, tracking_mask)
        if views:
            bank[str(slot)] = views

    tracker._f2_multiview_bank = bank
    tracker._f2_multiview_ready = bool(bank)
    return bool(bank)


def _candidato_vista(tracker, current_kp, current_desc, slot: str, view: dict):
    ref_kp = list(view.get("keypoints", ()) or ())
    ref_desc = view.get("descriptors")
    if ref_desc is None or len(ref_kp) < int(F2_TRACKING_MIN_MATCHES):
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
        if first.distance < float(F2_TRACKING_RATIO_TEST) * second.distance:
            good.append(first)
    if len(good) < int(F2_TRACKING_MIN_MATCHES):
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
        ransacReprojThreshold=float(F2_TRACKING_RANSAC_THRESHOLD_PX),
        maxIters=2600,
        confidence=0.995,
        refineIters=12,
    )
    if matrix is None or inlier_mask is None:
        return None

    inlier_flags = np.asarray(inlier_mask).reshape(-1).astype(bool)
    inliers = int(np.count_nonzero(inlier_flags))
    ratio = float(inliers / max(1, len(good)))
    if inliers < int(F2_TRACKING_MIN_INLIERS) or ratio < float(
        F2_TRACKING_MIN_INLIER_RATIO
    ):
        return None

    # Evita que uma pequena textura do suporte gere lock falso: os inliers precisam
    # ocupar uma região razoável da placa/frame, não apenas um agrupamento local.
    try:
        spread_points = current_points.reshape(-1, 2)[inlier_flags]
        spread_x = float(np.ptp(spread_points[:, 0])) if len(spread_points) else 0.0
        spread_y = float(np.ptp(spread_points[:, 1])) if len(spread_points) else 0.0
        if spread_x < float(tracker.width) * F2_MULTIVIEW_MIN_SPREAD_FRACTION:
            return None
        if spread_y < float(tracker.height) * F2_MULTIVIEW_MIN_SPREAD_FRACTION:
            return None
    except Exception:
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
    if abs(rotation_deg) > float(F2_TRACKING_WIDE_ROTATION_DEG):
        return None
    if abs(dx) > float(tracker.width) * float(F2_TRACKING_WIDE_TRANSLATION_FRACTION):
        return None
    if abs(dy) > float(tracker.height) * float(F2_TRACKING_WIDE_TRANSLATION_FRACTION):
        return None

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
        "score": float(inliers) + ratio * 10.0,
    }


def _tentar_multiview(tracker, frame, frame_id=None):
    if not bool(getattr(tracker, "_f2_multiview_ready", False)):
        return None
    if frame is None or getattr(frame, "size", 0) == 0:
        return None

    now = time.monotonic()
    last_compute = float(getattr(tracker, "_f2_multiview_last_compute_s", 0.0) or 0.0)
    if now - last_compute < float(F2_MULTIVIEW_RETRY_INTERVAL_S):
        return None
    tracker._f2_multiview_last_compute_s = now

    current_gray = tracker._prepare_gray(frame)
    if current_gray is None:
        return None
    orb = cv2.ORB_create(
        nfeatures=1200,
        scaleFactor=1.2,
        nlevels=8,
        edgeThreshold=15,
        fastThreshold=9,
    )
    current_kp, current_desc = orb.detectAndCompute(current_gray, None)
    if current_desc is None or len(current_kp) < int(F2_TRACKING_MIN_MATCHES):
        return None

    best = None
    for slot, views in dict(getattr(tracker, "_f2_multiview_bank", {})).items():
        for view in tuple(views or ()):
            candidate = _candidato_vista(
                tracker,
                current_kp,
                current_desc,
                str(slot),
                view,
            )
            if candidate is None:
                continue
            if best is None or float(candidate["score"]) > float(best["score"]):
                best = candidate
            if (
                int(candidate["inliers"]) >= int(F2_MULTIVIEW_STRONG_INLIERS)
                and float(candidate["ratio"]) >= float(F2_MULTIVIEW_STRONG_RATIO)
            ):
                break

    if best is None:
        return None

    matrix = np.asarray(best["matrix"], dtype=np.float32).reshape(2, 3)
    aligned = cv2.warpAffine(
        frame,
        matrix,
        (int(tracker.width), int(tracker.height)),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT101,
    )
    result = F2TrackingResult(
        True,
        aligned,
        reference=str(best["slot"]),
        matches=int(best["matches"]),
        inliers=int(best["inliers"]),
        inlier_ratio=float(best["ratio"]),
        dx=float(best["dx"]),
        dy=float(best["dy"]),
        rotation_deg=float(best["rotation_deg"]),
        scale=float(best["scale"]),
        reason="locked_multiview",
    )
    tracker.last_matrix = matrix
    tracker.last_compute_s = time.monotonic()
    tracker.last_result = result
    tracker.last_frame_id = frame_id
    tracker._f2_tracking_last_method = "ORB-MV"
    tracker._f2_multiview_last_angle = float(best["angle"])
    _registrar_lock_confiavel(tracker, result)
    return result


def instalar_banco_multivista_rastreamento_f2() -> None:
    """Instala aquisição multivista depois das correções ORB/ECC já existentes."""
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return

    reset_atual = F2BoardObjectTracker.reset
    if not bool(getattr(reset_atual, "_odin_f2_multiview_reset", False)):
        reset_anterior = reset_atual

        def reset_com_multiview(self):
            reset_anterior(self)
            _limpar_multiview(self)

        reset_com_multiview._odin_f2_multiview_reset = True
        F2BoardObjectTracker.reset = reset_com_multiview

    configure_atual = F2BoardObjectTracker.configure
    if not bool(getattr(configure_atual, "_odin_f2_multiview_configure", False)):
        configure_anterior = configure_atual

        def configure_com_multiview(self, controller):
            ready = False
            try:
                ready = bool(configure_anterior(self, controller))
            except Exception:
                ready = False
            try:
                multiview_ready = bool(_configurar_multiview(self, controller))
            except Exception:
                multiview_ready = False
            if multiview_ready and not ready:
                self.ready = True
                self.reason = "ready_multiview_fallback"
            return bool(ready or multiview_ready)

        configure_com_multiview._odin_f2_multiview_configure = True
        F2BoardObjectTracker.configure = configure_com_multiview

    align_atual = F2BoardObjectTracker.align
    if not bool(getattr(align_atual, "_odin_f2_multiview_align", False)):
        align_anterior = align_atual

        def align_com_multiview(self, frame, frame_id=None):
            result = align_anterior(self, frame, frame_id=frame_id)
            if bool(getattr(result, "locked", False)):
                return result
            multiview = _tentar_multiview(self, frame, frame_id=frame_id)
            if multiview is not None:
                return multiview
            return result

        align_com_multiview._odin_f2_multiview_align = True
        F2BoardObjectTracker.align = align_com_multiview

    _PATCH_INSTALADO = True
