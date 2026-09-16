from __future__ import annotations

"""Correção de runtime para o rastreamento automático da placa no F2.

O rastreador original usa ORB + RANSAC. Em placas reais, especialmente quando a
PCB tem pouca textura útil depois de excluir os LEDs, o ORB pode não produzir
correspondências suficientes. Nesse caso a Produção F2 continuava exibindo as
ROIs canônicas fixas porque nunca existia um ``tracking_locked`` verdadeiro.

Esta camada mantém ORB como primeira autoridade e acrescenta um fallback ECC
(Euclidean: X/Y + rotação) usando as mesmas referências ligada/desligada e a
mesma máscara física da placa. Também publica um status explícito na câmera ao
vivo para diferenciar TRAVADO de PROCURANDO, sem alterar o comportamento quando
o recurso está desativado.
"""

import math
import time

import cv2
import numpy as np

from src.platform.f2_board_presence_references import (
    F2_BOARD_REF_BOARD_OFF,
    F2_BOARD_REF_BOARD_ON,
)
from src.platform.f2_board_shape_editor import carregar_contorno_placa_leds
from src.platform.f2_object_tracking import (
    F2BoardObjectTracker,
    F2ObjectTrackingMixin,
    F2TrackingResult,
    F2_TRACKING_MAX_ROTATION_DEG,
    F2_TRACKING_MAX_TRANSLATION_FRACTION,
    F2_TRACKING_SMOOTH_ALPHA,
    construir_mascara_rastreamento_f2,
)


F2_ECC_SCALE = 0.50
F2_ECC_MAX_ITERATIONS = 45
F2_ECC_EPSILON = 1e-4
F2_ECC_GAUSS_SIZE = 5
F2_ECC_MIN_SCORE = 0.58
F2_ECC_RETRY_INTERVAL_S = 0.12

_PATCH_INSTALADO = False


def _limpar_estado_ecc(tracker) -> None:
    tracker._f2_ecc_signature = None
    tracker._f2_ecc_references = {}
    tracker._f2_ecc_ready = False
    tracker._f2_ecc_last_score = 0.0
    tracker._f2_ecc_last_compute_s = 0.0
    tracker._f2_tracking_last_method = ""


def _preparar_imagem_ecc(tracker, image):
    gray = tracker._prepare_gray(image)
    if gray is None:
        return None
    try:
        return cv2.GaussianBlur(gray, (5, 5), 0)
    except Exception:
        return gray


def _preparar_referencia_ecc(tracker, image, mask):
    gray = _preparar_imagem_ecc(tracker, image)
    if gray is None:
        return None
    try:
        valid = mask > 0
        if not np.any(valid):
            return None
        baseline = int(np.median(gray[valid]))
        isolated = np.full_like(gray, baseline)
        isolated[valid] = gray[valid]
        return cv2.resize(
            isolated,
            None,
            fx=F2_ECC_SCALE,
            fy=F2_ECC_SCALE,
            interpolation=cv2.INTER_AREA,
        )
    except Exception:
        return None


def _preparar_frame_ecc(tracker, frame):
    gray = _preparar_imagem_ecc(tracker, frame)
    if gray is None:
        return None
    try:
        return cv2.resize(
            gray,
            None,
            fx=F2_ECC_SCALE,
            fy=F2_ECC_SCALE,
            interpolation=cv2.INTER_AREA,
        )
    except Exception:
        return None


def _matriz_inicial_ref_para_atual(last_matrix):
    """Converte CURRENT->REF anterior em REF->CURRENT no espaço reduzido."""
    if last_matrix is None:
        return np.eye(2, 3, dtype=np.float32)
    try:
        full = cv2.invertAffineTransform(
            np.asarray(last_matrix, dtype=np.float32).reshape(2, 3)
        ).astype(np.float32)
        small = full.copy()
        small[0, 2] *= float(F2_ECC_SCALE)
        small[1, 2] *= float(F2_ECC_SCALE)
        return small
    except Exception:
        return np.eye(2, 3, dtype=np.float32)


def _matriz_ecc_para_current_to_reference(warp_ref_to_current_small):
    try:
        full = np.asarray(
            warp_ref_to_current_small,
            dtype=np.float32,
        ).reshape(2, 3).copy()
        full[0, 2] /= float(F2_ECC_SCALE)
        full[1, 2] /= float(F2_ECC_SCALE)
        return cv2.invertAffineTransform(full).astype(np.float32)
    except Exception:
        return None


def _validar_matriz_ecc(tracker, matrix) -> bool:
    if matrix is None:
        return False
    try:
        affine = np.asarray(matrix, dtype=np.float32).reshape(2, 3)
        a = float(affine[0, 0])
        b = float(affine[0, 1])
        rotation_deg = math.degrees(math.atan2(float(affine[1, 0]), a))
        scale = math.sqrt(max(1e-12, a * a + b * b))
        dx = float(affine[0, 2])
        dy = float(affine[1, 2])
        if not (0.96 <= scale <= 1.04):
            return False
        if abs(rotation_deg) > float(F2_TRACKING_MAX_ROTATION_DEG):
            return False
        if abs(dx) > int(tracker.width) * float(F2_TRACKING_MAX_TRANSLATION_FRACTION):
            return False
        if abs(dy) > int(tracker.height) * float(F2_TRACKING_MAX_TRANSLATION_FRACTION):
            return False
        return True
    except Exception:
        return False


def _configurar_ecc(tracker, controller) -> bool:
    project = str(controller.project_name() or "").strip()
    resolution = controller.master_resolution(project) if project else None
    entries = controller._entries(project) if project else {}
    if not project or not resolution:
        tracker._f2_ecc_ready = False
        return False

    width, height = int(resolution[0]), int(resolution[1])
    signature = getattr(tracker, "signature", None)
    if (
        getattr(tracker, "_f2_ecc_signature", None) == signature
        and bool(getattr(tracker, "_f2_ecc_ready", False))
    ):
        return True

    tracker._f2_ecc_signature = signature
    tracker._f2_ecc_references = {}
    tracker._f2_ecc_ready = False

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

    refs = {}
    for slot in (F2_BOARD_REF_BOARD_ON, F2_BOARD_REF_BOARD_OFF):
        path = str(entries.get(slot, {}).get("image_path") or "").strip()
        image = cv2.imread(path) if path else None
        if image is None or getattr(image, "size", 0) == 0:
            continue
        if image.shape[1] != width or image.shape[0] != height:
            continue
        prepared = _preparar_referencia_ecc(tracker, image, tracking_mask)
        if prepared is not None and getattr(prepared, "size", 0):
            refs[slot] = prepared

    tracker._f2_ecc_references = refs
    tracker._f2_ecc_ready = bool(refs)
    return bool(refs)


def _tentar_ecc(tracker, frame, previous_matrix=None):
    if not bool(getattr(tracker, "_f2_ecc_ready", False)):
        return None

    now = time.monotonic()
    last_compute = float(getattr(tracker, "_f2_ecc_last_compute_s", 0.0) or 0.0)
    if now - last_compute < F2_ECC_RETRY_INTERVAL_S:
        return None
    tracker._f2_ecc_last_compute_s = now

    current = _preparar_frame_ecc(tracker, frame)
    if current is None:
        return None

    criteria = (
        cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
        int(F2_ECC_MAX_ITERATIONS),
        float(F2_ECC_EPSILON),
    )
    candidates = []
    for slot, reference in dict(getattr(tracker, "_f2_ecc_references", {})).items():
        if reference.shape != current.shape:
            continue
        warp = _matriz_inicial_ref_para_atual(previous_matrix)
        try:
            score, warp_ref_to_current = cv2.findTransformECC(
                reference,
                current,
                warp,
                cv2.MOTION_EUCLIDEAN,
                criteria,
                None,
                int(F2_ECC_GAUSS_SIZE),
            )
        except cv2.error:
            continue
        except Exception:
            continue

        score = float(score)
        matrix = _matriz_ecc_para_current_to_reference(warp_ref_to_current)
        if score < float(F2_ECC_MIN_SCORE) or not _validar_matriz_ecc(tracker, matrix):
            continue
        candidates.append((score, str(slot), matrix))

    if not candidates:
        tracker._f2_ecc_last_score = 0.0
        return None

    score, slot, matrix = max(candidates, key=lambda item: item[0])
    tracker._f2_ecc_last_score = float(score)

    if previous_matrix is not None:
        try:
            alpha = float(F2_TRACKING_SMOOTH_ALPHA)
            matrix = (
                (1.0 - alpha) * np.asarray(previous_matrix, dtype=np.float32)
                + alpha * np.asarray(matrix, dtype=np.float32)
            ).astype(np.float32)
        except Exception:
            pass

    aligned = cv2.warpAffine(
        frame,
        matrix,
        (int(tracker.width), int(tracker.height)),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT101,
    )
    a = float(matrix[0, 0])
    b = float(matrix[0, 1])
    scale = math.sqrt(max(1e-12, a * a + b * b))
    rotation_deg = math.degrees(math.atan2(float(matrix[1, 0]), a))
    return F2TrackingResult(
        True,
        aligned,
        reference=slot,
        matches=0,
        inliers=0,
        inlier_ratio=0.0,
        dx=float(matrix[0, 2]),
        dy=float(matrix[1, 2]),
        rotation_deg=float(rotation_deg),
        scale=float(scale),
        reason="locked_ecc",
    ), matrix, float(score)


def _texto_motivo(reason: str) -> str:
    mapping = {
        "reset": "inicializando",
        "not_configured": "não configurado",
        "presence_controller_missing": "referências indisponíveis",
        "project_or_resolution_missing": "projeto/resolução ausente",
        "board_shape_missing": "contorno da placa ausente",
        "board_shape_mask_invalid": "contorno da placa inválido",
        "reference_features_insufficient": "referência visual insuficiente",
        "resolution_mismatch": "resolução incompatível",
        "current_features_insufficient": "poucos detalhes visuais",
        "object_not_locked": "procurando placa",
        "gray_prepare_failed": "frame inválido",
    }
    return mapping.get(str(reason or ""), str(reason or "procurando placa"))


def instalar_correcao_runtime_rastreamento_f2() -> None:
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return

    # 1) Reset também limpa o estado auxiliar do fallback.
    reset_atual = F2BoardObjectTracker.reset
    if not bool(getattr(reset_atual, "_odin_f2_ecc_reset", False)):
        reset_anterior = reset_atual

        def reset_com_ecc(self):
            reset_anterior(self)
            _limpar_estado_ecc(self)

        reset_com_ecc._odin_f2_ecc_reset = True
        F2BoardObjectTracker.reset = reset_com_ecc

    # 2) ORB continua sendo configurado primeiro; ECC garante uma segunda via.
    configure_atual = F2BoardObjectTracker.configure
    if not bool(getattr(configure_atual, "_odin_f2_ecc_configure", False)):
        configure_anterior = configure_atual

        def configure_com_ecc(self, controller):
            orb_ready = False
            try:
                orb_ready = bool(configure_anterior(self, controller))
            except Exception:
                orb_ready = False
            try:
                ecc_ready = bool(_configurar_ecc(self, controller))
            except Exception:
                ecc_ready = False
            if ecc_ready and not orb_ready:
                self.ready = True
                self.reason = "ready_ecc_fallback"
            return bool(orb_ready or ecc_ready)

        configure_com_ecc._odin_f2_ecc_configure = True
        F2BoardObjectTracker.configure = configure_com_ecc

    # 3) Só cai no ECC quando ORB/RANSAC não conseguiu travar o objeto.
    align_atual = F2BoardObjectTracker.align
    if not bool(getattr(align_atual, "_odin_f2_ecc_align", False)):
        align_anterior = align_atual

        def align_com_ecc(self, frame, frame_id=None):
            previous_matrix = None
            if getattr(self, "last_matrix", None) is not None:
                try:
                    previous_matrix = self.last_matrix.copy()
                except Exception:
                    previous_matrix = self.last_matrix

            result = align_anterior(self, frame, frame_id=frame_id)
            if bool(getattr(result, "locked", False)):
                if str(getattr(result, "reason", "")) != "cached_transform":
                    self._f2_tracking_last_method = "ORB"
                return result

            fallback = _tentar_ecc(self, frame, previous_matrix=previous_matrix)
            if fallback is None:
                self._f2_tracking_last_method = ""
                return result

            ecc_result, matrix, score = fallback
            self.last_matrix = matrix
            self.last_compute_s = time.monotonic()
            self.last_result = ecc_result
            self.last_frame_id = frame_id
            self._f2_tracking_last_method = "ECC"
            self._f2_ecc_last_score = float(score)
            return ecc_result

        align_com_ecc._odin_f2_ecc_align = True
        F2BoardObjectTracker.align = align_com_ecc

    # 4) Status da própria câmera: deixa explícito se a geometria está seguindo.
    preview_atual = F2ObjectTrackingMixin._atualizar_preview_operacao
    if not bool(getattr(preview_atual, "_odin_f2_tracking_status", False)):
        preview_anterior = preview_atual

        def preview_com_status_tracking(self):
            result = preview_anterior(self)
            if not bool(getattr(self, "_f2_tracking_enabled", lambda: False)()):
                return result

            window = getattr(self, "operacao_window", None)
            setter = getattr(window, "set_preview_status", None)
            if not callable(setter):
                return result

            status = getattr(self, "_f2_object_tracking_last_status", {})
            if not isinstance(status, dict):
                status = {}
            locked = bool(status.get("locked"))
            tracker = getattr(self, "_f2_object_tracker", None)
            if locked:
                method = str(getattr(tracker, "_f2_tracking_last_method", "") or "TRACK")
                dx = float(status.get("dx", 0.0) or 0.0)
                dy = float(status.get("dy", 0.0) or 0.0)
                rotation = float(status.get("rotation_deg", 0.0) or 0.0)
                try:
                    setter(
                        f"RASTREAMENTO ATIVO • TRAVADO ({method}) • X {dx:+.1f}  Y {dy:+.1f}  R {rotation:+.1f}°",
                        "#86EFAC",
                    )
                except Exception:
                    pass
            else:
                reason = _texto_motivo(str(status.get("reason", "")))
                try:
                    setter(
                        f"RASTREAMENTO ATIVO • PROCURANDO • {reason}",
                        "#FBBF24",
                    )
                except Exception:
                    pass
            return result

        preview_com_status_tracking._odin_f2_tracking_status = True
        F2ObjectTrackingMixin._atualizar_preview_operacao = preview_com_status_tracking

    _PATCH_INSTALADO = True
