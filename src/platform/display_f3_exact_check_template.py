from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

import src.platform.display_auto_check_runtime as runtime_module
import src.platform.display_f3_live_runtime_fix as live_runtime_module
import src.platform.display_f3_operational_status as operational_module
import src.platform.display_f3_physical_learning_policy as physical_policy_module
import src.platform.display_reference_roi as reference_roi_module
from src.core.roi_geometry import criar_mascaras_roi
from src.platform.display_auto_check_analyzer import (
    DISPLAY_AUTO_CLASS_LABELS,
    display_mask_to_analysis_selection,
)
from src.platform.display_check_presence_reference import (
    DisplayCheckPresenceReferenceStore,
    _prepare_bgr,
    avaliar_referencia_presenca_display,
    calcular_similaridade_presenca_display,
)
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_IGNORE,
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
    mascaras_geometria_check_display,
    normalizar_resolucao_display,
)
from src.platform.display_visual_reference_status import (
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
    DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
    DISPLAY_PROJECT_REFERENCE_TYPES,
    DisplayVisualReferenceMatcher,
)
from src.platform.display_visual_rotation import preparar_check_visual_display


F3_EXACT_TEMPLATE_SOURCE = "f3_current_check_exact_photo"
F3_EXACT_MASK_MIN_SIMILARITY = 0.82
F3_EXACT_MASK_AMBIGUOUS_BAND = 0.015
F3_EXACT_PHYSICAL_MIN_MARGIN = 0.010


def _valid_image(image) -> bool:
    return image is not None and getattr(image, "size", 0) > 0


def _read_reference_full(metadata: dict | None):
    if not isinstance(metadata, dict):
        return None
    path = Path(str(metadata.get("image_path") or ""))
    if not path.is_file():
        return None
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    return image if _valid_image(image) else None


def _score_reference_full_roi(frame, metadata: dict | None) -> float | None:
    """Recorta a ROI na resolução original antes de reduzir para comparação.

    Este é o ponto central da correção. O fluxo anterior reduzia o frame completo
    de 1920 px para 220 px e somente depois recortava o display. Segmentos de
    sete segmentos viravam poucos pixels e OFF/H1 ficavam artificialmente iguais.
    """
    reference = _read_reference_full(metadata)
    if reference is None or not _valid_image(frame):
        return None

    current = _prepare_bgr(frame, (reference.shape[1], reference.shape[0]))
    if current is None:
        return None

    roi = reference_roi_module.normalizar_roi_referencia(
        (metadata or {}).get("roi")
    )
    if roi is not None:
        reference = reference_roi_module.recortar_roi_referencia(reference, roi)
        current = reference_roi_module.recortar_roi_referencia(current, roi)

    if not _valid_image(reference) or not _valid_image(current):
        return None
    return float(calcular_similaridade_presenca_display(reference, current))


def _physical_candidates(matcher, project_name: str) -> list[dict]:
    candidates: list[dict] = []
    project_references = matcher.project_store.get_all(project_name)

    empty = project_references.get(DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT)
    if isinstance(empty, dict):
        candidates.append(
            {
                "key": "empty",
                "kind": "empty",
                "name": "PLACA FORA DO SUPORTE",
                "metadata": empty,
            }
        )

    off = project_references.get(DISPLAY_PROJECT_REFERENCE_BOARD_OFF)
    if isinstance(off, dict):
        candidates.append(
            {
                "key": "off",
                "kind": "off",
                "name": "PLACA NO SUPORTE • DESLIGADA",
                "metadata": off,
            }
        )

    for check in matcher.repository.listar_checks(project_name):
        check_id = str(check.get("id") or "")
        if not check_id:
            continue
        metadata = matcher.check_store.get(project_name, check_id)
        if not isinstance(metadata, dict):
            continue
        candidates.append(
            {
                "key": f"check:{check_id}",
                "kind": "check",
                "name": str(check.get("name") or check_id).strip().upper(),
                "check_id": check_id,
                "metadata": metadata,
            }
        )
    return candidates


def classificar_estado_fisico_por_gabaritos_f3(
    matcher,
    frame,
    project_name: str,
) -> dict:
    """Escolhe a referência visual mais parecida usando a ROI em alta resolução."""
    project_references = matcher.project_store.get_all(project_name)
    board_complete = all(
        kind in project_references for kind in DISPLAY_PROJECT_REFERENCE_TYPES
    )
    if not _valid_image(frame):
        return {
            "kind": "unknown",
            "text": "AGUARDANDO CÂMERA",
            "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"],
            "allow_auto": False,
            "board_references_complete": board_complete,
        }

    scored: list[dict] = []
    for candidate in _physical_candidates(matcher, project_name):
        score = _score_reference_full_roi(frame, candidate.get("metadata"))
        if score is None:
            continue
        item = dict(candidate)
        item["score"] = float(score)
        item["threshold"] = float(matcher._threshold(candidate.get("metadata")))
        scored.append(item)

    if not scored:
        return {
            "kind": "unavailable",
            "text": "REFERÊNCIAS VISUAIS NÃO CONFIGURADAS",
            "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["unavailable"],
            "allow_auto": False,
            "board_references_complete": board_complete,
            "configured_count": 0,
        }

    passing = [
        item
        for item in scored
        if float(item["score"]) >= float(item["threshold"])
    ]
    scored.sort(key=lambda item: float(item["score"]), reverse=True)
    passing.sort(key=lambda item: float(item["score"]), reverse=True)

    if not passing:
        best = scored[0]
        return {
            "kind": "unknown",
            "text": "IDENTIFICANDO...",
            "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"],
            "allow_auto": False,
            "board_references_complete": board_complete,
            "configured_count": len(scored),
            "best_score": float(best["score"]),
            "reference_scores": {
                str(item["key"]): round(float(item["score"]), 4)
                for item in scored
            },
        }

    winner = passing[0]
    if len(passing) >= 2:
        margin = float(winner["score"]) - float(passing[1]["score"])
        if margin < F3_EXACT_PHYSICAL_MIN_MARGIN:
            return {
                "kind": "unknown",
                "text": "IDENTIFICANDO...",
                "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"],
                "allow_auto": False,
                "board_references_complete": board_complete,
                "configured_count": len(scored),
                "ambiguous": True,
                "best_score": float(winner["score"]),
                "second_score": float(passing[1]["score"]),
                "reference_scores": {
                    str(item["key"]): round(float(item["score"]), 4)
                    for item in scored
                },
            }

    kind = str(winner.get("kind") or "unknown")
    state = {
        "kind": kind,
        "allow_auto": False,
        "board_references_complete": board_complete,
        "configured_count": len(scored),
        "physical_state_key": str(winner.get("key") or kind),
        "score": float(winner["score"]),
        "reference_scores": {
            str(item["key"]): round(float(item["score"]), 4)
            for item in scored
        },
        "comparison_mode": "full_resolution_roi_first",
    }
    if kind == "empty":
        state.update(
            text="PLACA FORA DO SUPORTE",
            color=operational_module.F3_OPERATIONAL_STATUS_COLORS["empty"],
        )
    elif kind == "off":
        state.update(
            text="PLACA NO SUPORTE • DESLIGADA",
            color=operational_module.F3_OPERATIONAL_STATUS_COLORS["off"],
        )
    else:
        name = str(winner.get("name") or "CHECK").strip().upper()
        state.update(
            text=f"DISPLAY EM {name}",
            color=operational_module.F3_OPERATIONAL_STATUS_COLORS["check"],
            check_id=str(winner.get("check_id") or ""),
            check_name=name,
        )
    return state


def _build_exact_physical_operational_state(
    self,
    frame,
    project_name: str,
    context: dict | None,
) -> dict:
    repository = getattr(self, "display_project_repository", None)
    if repository is None:
        return {
            "kind": "unavailable",
            "text": "PROJETO DISPLAY NÃO DISPONÍVEL",
            "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["unavailable"],
            "allow_auto": False,
        }

    matcher = getattr(self, "_display_f3_operational_matcher", None)
    if matcher is None or getattr(matcher, "repository", None) is not repository:
        matcher = DisplayVisualReferenceMatcher(repository)
        self._display_f3_operational_matcher = matcher

    raw_state = classificar_estado_fisico_por_gabaritos_f3(
        matcher,
        frame,
        project_name,
    )

    # Mantém somente o debounce temporal já existente; a decisão visual vem dos
    # gabaritos exatos acima.
    import src.platform.display_f3_check_transition_guard as transition_module
    import src.platform.display_f3_live_runtime_fix as live_gate_module

    state = transition_module._estado_fisico_estavel(self, raw_state)
    current_check_id = str((context or {}).get("check_id") or "")
    state = physical_policy_module.aplicar_contexto_ao_estado_fisico_f3(
        state,
        current_check_id=current_check_id,
    )
    metadata = (
        matcher.check_store.get(project_name, current_check_id)
        if current_check_id
        else None
    )
    state["current_check_reference_configured"] = isinstance(metadata, dict)
    return live_gate_module.aplicar_gate_rearme_ciclo_f3(self, state)


def _resize_visual_frame(frame, visual_resolution):
    if not _valid_image(frame):
        return None
    width = max(1, int(visual_resolution[0]))
    height = max(1, int(visual_resolution[1]))
    if frame.shape[:2] == (height, width):
        return frame
    interpolation = (
        cv2.INTER_AREA
        if frame.shape[1] > width or frame.shape[0] > height
        else cv2.INTER_LINEAR
    )
    return cv2.resize(frame, (width, height), interpolation=interpolation)


def comparar_mascara_com_gabarito_f3(current_frame, reference_frame, selection) -> dict | None:
    """Compara somente os pixels pertencentes à mesma máscara física."""
    if not _valid_image(current_frame) or not _valid_image(reference_frame):
        return None
    height, width = reference_frame.shape[:2]
    if current_frame.shape[:2] != (height, width):
        current_frame = cv2.resize(
            current_frame,
            (width, height),
            interpolation=cv2.INTER_AREA,
        )

    prepared = criar_mascaras_roi(selection, width, height)
    if prepared is None:
        return None
    x1, y1, x2, y2, mask, _inner, _ring = prepared
    reference_roi = reference_frame[y1:y2, x1:x2]
    current_roi = current_frame[y1:y2, x1:x2]
    if (
        not _valid_image(reference_roi)
        or not _valid_image(current_roi)
        or mask is None
        or int(np.count_nonzero(mask)) <= 0
    ):
        return None

    # Um blur mínimo remove ruído de sensor/JPEG sem apagar a diferença física
    # entre um segmento aceso e o mesmo segmento apagado.
    reference_blur = cv2.GaussianBlur(reference_roi, (3, 3), 0)
    current_blur = cv2.GaussianBlur(current_roi, (3, 3), 0)

    reference_hsv = cv2.cvtColor(reference_blur, cv2.COLOR_BGR2HSV)
    current_hsv = cv2.cvtColor(current_blur, cv2.COLOR_BGR2HSV)

    ref_bgr = reference_blur[mask].astype(np.float32)
    cur_bgr = current_blur[mask].astype(np.float32)
    ref_s = reference_hsv[:, :, 1][mask].astype(np.float32)
    cur_s = current_hsv[:, :, 1][mask].astype(np.float32)
    ref_v = reference_hsv[:, :, 2][mask].astype(np.float32)
    cur_v = current_hsv[:, :, 2][mask].astype(np.float32)

    bgr_mae = float(np.mean(np.abs(cur_bgr - ref_bgr)) / 255.0)
    s_mae = float(np.mean(np.abs(cur_s - ref_s)) / 255.0)
    v_mae = float(np.mean(np.abs(cur_v - ref_v)) / 255.0)

    pixel_similarity = 1.0 - (
        (0.30 * bgr_mae)
        + (0.20 * s_mae)
        + (0.50 * v_mae)
    )
    reference_v_mean = float(np.mean(ref_v))
    current_v_mean = float(np.mean(cur_v))
    energy_similarity = 1.0 - min(
        1.0,
        abs(current_v_mean - reference_v_mean) / 255.0,
    )

    similarity = (
        (0.75 * pixel_similarity)
        + (0.25 * energy_similarity)
    )
    similarity = max(0.0, min(1.0, float(similarity)))
    return {
        "similarity": round(similarity, 4),
        "pixel_similarity": round(float(pixel_similarity), 4),
        "energy_similarity": round(float(energy_similarity), 4),
        "reference_v_mean": round(reference_v_mean, 4),
        "current_v_mean": round(current_v_mean, 4),
    }


class F3ExactCheckTemplateAnalyzer:
    """O próprio CHECK configurado é o gabarito de produção daquele CHECK."""

    def __init__(self, repository) -> None:
        self.repository = repository
        self.presence_store = DisplayCheckPresenceReferenceStore(repository)

    def invalidate_learning_cache(self) -> None:
        return None

    @staticmethod
    def _not_ready(reason: str, **extra) -> dict:
        return {
            "ready": False,
            "approved": None,
            "reason": str(reason),
            "mask_results": [],
            "reference_authority": F3_EXACT_TEMPLATE_SOURCE,
            **extra,
        }

    def _reference_visual_context(
        self,
        project_name: str,
        check_id: str,
        project: dict,
        masks: list[dict],
        visual_rotation: int,
    ):
        metadata = self.presence_store.get(project_name, check_id)
        if not isinstance(metadata, dict):
            return None, {}, None
        reference = _read_reference_full(metadata)
        if reference is None:
            return None, {}, metadata
        master_resolution = normalizar_resolucao_display(
            project.get("master_resolution")
        )
        if master_resolution is None:
            return None, {}, metadata
        frame, resolution, visual_masks = preparar_check_visual_display(
            reference,
            master_resolution,
            masks,
            visual_rotation,
        )
        frame = _resize_visual_frame(frame, resolution)
        mask_by_id = {
            str(mask.get("id")): mask
            for mask in visual_masks
            if isinstance(mask, dict) and mask.get("id") is not None
        }
        return frame, mask_by_id, metadata

    def analyze(
        self,
        frame,
        project_name: str,
        check_id: str,
        visual_rotation: int = 0,
    ) -> dict:
        if not _valid_image(frame):
            return self._not_ready("camera_sem_frame")

        project = self.repository.carregar_projeto(project_name)
        if project is None:
            return self._not_ready("projeto_display_inexistente")
        check = self.repository.carregar_check(project_name, check_id)
        if check is None:
            return self._not_ready("check_display_inexistente")

        master_resolution = normalizar_resolucao_display(
            project.get("master_resolution")
        )
        if master_resolution is None:
            return self._not_ready("resolucao_mestra_ausente")

        masks = mascaras_geometria_check_display(project, check)
        states = (
            check.get("mask_states", {})
            if isinstance(check.get("mask_states"), dict)
            else {}
        )
        active_masks = [
            mask
            for mask in masks
            if states.get(str(mask.get("id")))
            in (DISPLAY_CHECK_STATE_ON, DISPLAY_CHECK_STATE_OFF)
        ]
        if not active_masks:
            return self._not_ready("check_sem_mascaras_ativas")

        reference_frame, reference_masks, metadata = self._reference_visual_context(
            project_name,
            check_id,
            project,
            masks,
            visual_rotation,
        )
        if reference_frame is None:
            return self._not_ready(
                "referencia_visual_check_indisponivel",
                check_id=str(check_id),
            )

        visual_frame, visual_resolution, visual_masks = preparar_check_visual_display(
            frame,
            master_resolution,
            masks,
            visual_rotation,
        )
        visual_frame = _resize_visual_frame(visual_frame, visual_resolution)
        if visual_frame is None:
            return self._not_ready("camera_sem_frame_visual")

        current_masks = {
            str(mask.get("id")): mask
            for mask in visual_masks
            if isinstance(mask, dict) and mask.get("id") is not None
        }

        results = []
        for original_mask in active_masks:
            mask_id = str(original_mask.get("id") or "")
            expected = str(states.get(mask_id) or "")
            visual_mask = current_masks.get(mask_id)
            reference_mask = reference_masks.get(mask_id)
            if visual_mask is None or reference_mask is None:
                return self._not_ready(
                    "mascara_visual_nao_encontrada",
                    mask_id=mask_id,
                )

            try:
                # Geometria é a mesma nos dois frames; usamos a máscara do frame
                # atual e a foto salva apenas como gabarito de pixels.
                selection = display_mask_to_analysis_selection(visual_mask)
            except (TypeError, ValueError):
                return self._not_ready("mascara_invalida", mask_id=mask_id)

            comparison = comparar_mascara_com_gabarito_f3(
                visual_frame,
                reference_frame,
                selection,
            )
            if comparison is None:
                return self._not_ready("mascara_fora_do_frame", mask_id=mask_id)

            similarity = float(comparison["similarity"])
            matched = similarity >= F3_EXACT_MASK_MIN_SIMILARITY
            opposite = (
                DISPLAY_CHECK_STATE_OFF
                if expected == DISPLAY_CHECK_STATE_ON
                else DISPLAY_CHECK_STATE_ON
            )
            classified = expected if matched else opposite

            distance_to_threshold = abs(
                similarity - F3_EXACT_MASK_MIN_SIMILARITY
            )
            confidence = (
                0.49
                if distance_to_threshold < F3_EXACT_MASK_AMBIGUOUS_BAND
                else min(0.99, 0.70 + (distance_to_threshold * 1.8))
            )

            results.append(
                {
                    "mask_id": mask_id,
                    "expected": expected,
                    "expected_label": DISPLAY_AUTO_CLASS_LABELS[expected],
                    "classified": classified,
                    "classified_label": DISPLAY_AUTO_CLASS_LABELS[classified],
                    "matched": bool(matched),
                    "confidence": round(float(confidence), 4),
                    "template_similarity": round(similarity, 4),
                    "template_threshold": F3_EXACT_MASK_MIN_SIMILARITY,
                    "pixel_similarity": comparison["pixel_similarity"],
                    "energy_similarity": comparison["energy_similarity"],
                    "reference_v_mean": comparison["reference_v_mean"],
                    "current_v_mean": comparison["current_v_mean"],
                    "reference_source": F3_EXACT_TEMPLATE_SOURCE,
                    "reference_checks": {
                        expected: {
                            "check_id": str(check_id),
                            "check_name": str(check.get("name") or check_id),
                            "mask_id": mask_id,
                            "state": expected,
                        }
                    },
                }
            )

        approved = all(bool(item.get("matched")) for item in results)
        presence = avaliar_referencia_presenca_display(frame, metadata)
        presence["decision_authority"] = False
        presence["role"] = "exact_check_photo_diagnostic"

        return {
            "ready": True,
            "approved": bool(approved),
            "reason": (
                "check_conforme_gabarito_exato"
                if approved
                else "check_diverge_gabarito_exato"
            ),
            "project_name": str(project_name),
            "check_id": str(check_id),
            "check_name": str(check.get("name") or check_id),
            "mask_results": results,
            "active_mask_count": len(results),
            "matched_mask_count": sum(
                1 for item in results if bool(item.get("matched"))
            ),
            "ignored_mask_count": sum(
                1
                for mask in masks
                if states.get(str(mask.get("id"))) == DISPLAY_CHECK_STATE_IGNORE
            ),
            "reference_authority": F3_EXACT_TEMPLATE_SOURCE,
            "presence_reference": presence,
        }


_INSTALLED = False


def instalar_gabarito_exato_checks_display_f3() -> None:
    """Instala a autoridade final do F3 sem tocar em qualquer módulo F2."""
    global _INSTALLED
    if _INSTALLED:
        return

    # O gate físico instalado anteriormente referencia esta função global em
    # tempo de execução, então a substituição passa a valer sem criar outro loop.
    physical_policy_module._build_physical_operational_state = (
        _build_exact_physical_operational_state
    )
    operational_module._build_operational_state = (
        _build_exact_physical_operational_state
    )

    # O runtime passa a comparar cada máscara diretamente com a mesma máscara da
    # foto do CHECK atual. Não há dependência do bloco manual de aprendizado nem
    # de pools de outros CHECKS para aceitar o gabarito atual.
    runtime_module.DisplayAutomaticCheckAnalyzer = F3ExactCheckTemplateAnalyzer
    live_runtime_module.DisplayAutomaticCheckAnalyzer = F3ExactCheckTemplateAnalyzer

    _INSTALLED = True
