from __future__ import annotations

"""Integra as referências reais 90°/180°/270° ao rastreador F2.

As fotos reais são convertidas para o mesmo sistema canônico usado pelo projeto.
Os descritores ORB são extraídos da imagem real, porém cada keypoint é reprojetado
pela matriz calibrada REFERÊNCIA -> CANÔNICO antes de entrar no RANSAC. Assim o
resultado final continua sendo uma matriz CURRENT -> CANÔNICO e todo o restante
do pipeline (contorno móvel, ROIs móveis e análise) permanece inalterado.
"""

import cv2
import numpy as np

import src.platform.f2_object_tracking_multiview as multiview
from src.core.roi_geometry import bbox_roi
from src.platform.f2_board_shape_editor import carregar_contorno_placa_leds
from src.platform.f2_object_tracking import (
    F2BoardObjectTracker,
    F2_TRACKING_MIN_MATCHES,
    construir_mascara_rastreamento_f2,
)
from src.platform.f2_object_tracking_visual_overlay import (
    transformar_rois_para_frame_atual_f2,
)
from src.platform.f2_tracking_orientation_references import (
    F2_ORIENTATION_ANGLE,
    F2_ORIENTATION_SLOTS,
    matriz_orientacao_np,
    obter_referencias_orientacao_projeto,
    referencia_orientacao_calibrada,
)


F2_REAL_ORIENTATION_ORB_FEATURES = 1500
F2_REAL_ORIENTATION_EDGE_THRESHOLD = 12
F2_REAL_ORIENTATION_FAST_THRESHOLD = 7
F2_REAL_ORIENTATION_SCORE_BONUS = 6.0

_PATCH_INSTALADO = False


def _limpar_estado_real(tracker) -> None:
    tracker._f2_real_orientation_signature = None
    tracker._f2_real_orientation_slots = set()
    tracker._f2_real_orientation_views = {}


def _shape_stamp(controller, project: str) -> str | None:
    repository = getattr(controller.app, "config_repository", None)
    if repository is None:
        return None
    try:
        config = repository.carregar_configuracao_existente_sem_alerta()
        project_data = config.get("led_projects", {}).get(project, {})
        shape = project_data.get("f2_board_shape", {}) if isinstance(project_data, dict) else {}
        return shape.get("updated_at") if isinstance(shape, dict) else None
    except Exception:
        return None


def _mapear_keypoints_para_canonico(keypoints, canonical_to_reference):
    try:
        inverse = cv2.invertAffineTransform(
            np.asarray(canonical_to_reference, dtype=np.float32).reshape(2, 3)
        )
    except Exception:
        return []

    mapped = []
    for keypoint in tuple(keypoints or ()):
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


def _dimensoes_contorno(shape) -> tuple[float, float]:
    if not shape:
        return 1.0, 1.0
    try:
        x1, y1, x2, y2 = bbox_roi(shape[0])
        width = max(1.0, float(x2 - x1))
        height = max(1.0, float(y2 - y1))
        return max(width, height), min(width, height)
    except Exception:
        return 1.0, 1.0


def _assinatura(entries: dict, shape_stamp: str | None) -> tuple:
    return (
        shape_stamp,
        tuple(
            (
                slot,
                entries.get(slot, {}).get("image_path"),
                entries.get(slot, {}).get("updated_at"),
                entries.get(slot, {}).get("base_shape_updated_at"),
                bool(entries.get(slot, {}).get("calibrated")),
                repr(entries.get(slot, {}).get("canonical_to_reference")),
            )
            for slot in F2_ORIENTATION_SLOTS
        ),
    )


def _carregar_referencias_reais(tracker, controller) -> bool:
    if controller is None:
        return False
    project = str(controller.project_name() or "").strip()
    resolution = controller.master_resolution(project) if project else None
    if not project or not resolution:
        return False

    width, height = int(resolution[0]), int(resolution[1])
    repository = getattr(controller.app, "config_repository", None)
    if repository is None:
        return False
    try:
        config = repository.carregar_configuracao_existente_sem_alerta()
    except Exception:
        config = {}
    entries = obter_referencias_orientacao_projeto(config, project)
    stamp = _shape_stamp(controller, project)
    signature = _assinatura(entries, stamp)

    if (
        getattr(tracker, "_f2_real_orientation_signature", None) == signature
        and bool(getattr(tracker, "_f2_real_orientation_slots", set()))
    ):
        return True

    # Remove somente dados reais de uma configuração anterior. Referências base e
    # vistas sintéticas continuam pertencendo aos módulos históricos.
    previous_slots = set(getattr(tracker, "_f2_real_orientation_slots", set()) or set())
    for slot in previous_slots:
        try:
            tracker.references.pop(slot, None)
        except Exception:
            pass
        try:
            tracker._f2_multiview_bank.pop(slot, None)
        except Exception:
            pass

    tracker._f2_real_orientation_signature = signature
    tracker._f2_real_orientation_slots = set()
    tracker._f2_real_orientation_views = {}

    shape = carregar_contorno_placa_leds(controller, project, width, height)
    if not shape:
        return False
    leds = tracker._load_leds(controller, project)
    board_major, board_minor = _dimensoes_contorno(shape)

    orb = cv2.ORB_create(
        nfeatures=int(F2_REAL_ORIENTATION_ORB_FEATURES),
        scaleFactor=1.2,
        nlevels=8,
        edgeThreshold=int(F2_REAL_ORIENTATION_EDGE_THRESHOLD),
        fastThreshold=int(F2_REAL_ORIENTATION_FAST_THRESHOLD),
    )

    loaded = 0
    for slot in F2_ORIENTATION_SLOTS:
        entry = entries.get(slot, {})
        if not referencia_orientacao_calibrada(entry, stamp):
            continue
        path = str(entry.get("image_path") or "").strip()
        image = cv2.imread(path) if path else None
        if image is None or getattr(image, "size", 0) == 0:
            continue
        if image.shape[1] != width or image.shape[0] != height:
            continue

        matrix = matriz_orientacao_np(entry)
        if matrix is None:
            continue
        transformed_shape = transformar_rois_para_frame_atual_f2(
            shape,
            matrix,
            width,
            height,
        )
        transformed_leds = transformar_rois_para_frame_atual_f2(
            leds,
            matrix,
            width,
            height,
        )
        if len(transformed_shape) != len(shape):
            continue
        if leds and len(transformed_leds) != len(leds):
            continue

        mask = construir_mascara_rastreamento_f2(
            transformed_shape,
            transformed_leds,
            width,
            height,
        )
        if mask is None:
            continue
        gray = tracker._prepare_gray(image)
        if gray is None:
            continue
        keypoints, descriptors = orb.detectAndCompute(gray, mask)
        if descriptors is None or len(keypoints) < int(F2_TRACKING_MIN_MATCHES):
            continue
        mapped = _mapear_keypoints_para_canonico(keypoints, matrix)
        if len(mapped) != len(keypoints) or len(mapped) < int(F2_TRACKING_MIN_MATCHES):
            continue

        # Referência direta: o ORB principal já pode adquirir a placa por esta
        # orientação antes de cair em ECC/HOLD/fallbacks.
        tracker.references[slot] = (mapped, descriptors)
        tracker._f2_real_orientation_slots.add(slot)

        # Também entra no banco multivista para recuperação quando a aquisição
        # direta não alcançar o limiar naquele frame.
        view = {
            "angle": float(F2_ORIENTATION_ANGLE[slot]),
            "keypoints": mapped,
            "descriptors": descriptors,
            "cardinal": True,
            "board_major": float(board_major),
            "board_minor": float(board_minor),
            "real_orientation": True,
            "orientation_slot": slot,
        }
        bank = getattr(tracker, "_f2_multiview_bank", None)
        if not isinstance(bank, dict):
            bank = {}
            tracker._f2_multiview_bank = bank
        bank[slot] = [view]
        tracker._f2_real_orientation_views[slot] = view
        loaded += 1

    return loaded > 0


def instalar_banco_referencias_reais_orientacao_f2() -> None:
    """Instala as fotos reais como referências prioritárias do tracker F2."""
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return

    reset_atual = F2BoardObjectTracker.reset
    if not bool(getattr(reset_atual, "_odin_f2_real_orientation_reset", False)):
        reset_anterior = reset_atual

        def reset_com_reais(self):
            reset_anterior(self)
            _limpar_estado_real(self)

        reset_com_reais._odin_f2_real_orientation_reset = True
        F2BoardObjectTracker.reset = reset_com_reais

    configure_atual = F2BoardObjectTracker.configure
    if not bool(getattr(configure_atual, "_odin_f2_real_orientation_configure", False)):
        configure_anterior = configure_atual

        def configure_com_reais(self, controller):
            ready = False
            try:
                ready = bool(configure_anterior(self, controller))
            except Exception:
                ready = False
            real_ready = False
            try:
                real_ready = bool(_carregar_referencias_reais(self, controller))
            except Exception:
                real_ready = False
            if real_ready and not ready:
                self.ready = True
                self.reason = "ready_real_orientation"
            return bool(ready or real_ready)

        configure_com_reais._odin_f2_real_orientation_configure = True
        configure_com_reais._odin_f2_real_orientation_configure_base = configure_anterior
        F2BoardObjectTracker.configure = configure_com_reais

    # Bônus pequeno para a foto real competir acima de uma vista sintética com
    # quantidade de inliers praticamente igual. RANSAC e os limites geométricos
    # continuam autoritativos; o bônus não transforma candidato inválido em válido.
    candidate_atual = F2BoardObjectTracker._candidate
    if not bool(getattr(candidate_atual, "_odin_f2_real_orientation_score", False)):
        candidate_anterior = candidate_atual

        def candidate_com_prioridade_real(self, current_gray, current_kp, current_desc, slot):
            result = candidate_anterior(self, current_gray, current_kp, current_desc, slot)
            if result is not None and slot in set(
                getattr(self, "_f2_real_orientation_slots", set()) or set()
            ):
                result = dict(result)
                result["score"] = float(result.get("score", 0.0)) + float(
                    F2_REAL_ORIENTATION_SCORE_BONUS
                )
                result["real_orientation"] = True
            return result

        candidate_com_prioridade_real._odin_f2_real_orientation_score = True
        candidate_com_prioridade_real._odin_f2_real_orientation_score_base = candidate_anterior
        F2BoardObjectTracker._candidate = candidate_com_prioridade_real

    multiview_candidate_atual = multiview._candidato_vista
    if not bool(
        getattr(multiview_candidate_atual, "_odin_f2_real_orientation_score", False)
    ):
        multiview_candidate_anterior = multiview_candidate_atual

        def candidato_multivista_com_prioridade_real(
            tracker,
            current_kp,
            current_desc,
            slot,
            view,
        ):
            result = multiview_candidate_anterior(
                tracker,
                current_kp,
                current_desc,
                slot,
                view,
            )
            if result is not None and bool(view.get("real_orientation", False)):
                result = dict(result)
                result["score"] = float(result.get("score", 0.0)) + float(
                    F2_REAL_ORIENTATION_SCORE_BONUS
                )
                result["real_orientation"] = True
            return result

        candidato_multivista_com_prioridade_real._odin_f2_real_orientation_score = True
        candidato_multivista_com_prioridade_real._odin_f2_real_orientation_score_base = (
            multiview_candidate_anterior
        )
        multiview._candidato_vista = candidato_multivista_com_prioridade_real

    _PATCH_INSTALADO = True
