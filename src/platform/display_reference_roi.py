from __future__ import annotations

"""Regiões de comparação das referências visuais do Display F3.

A câmera e a placa do dispositivo ficam mecanicamente fixas. Por isso as regiões
mais específicas para comparar uma referência não são mais um recorte retangular
manual: são exatamente as máscaras desenhadas em "Seleção, ajuste e máscara".

Este módulo mantém apenas os helpers antigos de ROI retangular por compatibilidade
com imports históricos. O instalador produtivo NÃO cria seletor de recorte, NÃO
persiste ROI retangular e NÃO usa ``metadata['roi']`` como autoridade.
"""

from copy import deepcopy
from pathlib import Path

import cv2
import numpy as np

import src.platform.display_check_presence_reference as check_module
import src.platform.display_visual_reference_status as visual_module
from src.core.roi_geometry import criar_mascara_roi_global, criar_mascaras_roi
from src.platform.display_auto_check_analyzer import display_mask_to_analysis_selection
from src.platform.display_project_repository import normalizar_resolucao_display


DISPLAY_REFERENCE_ROI_MIN_FRACTION = 0.015
DISPLAY_REFERENCE_ROI_COLOR = "#38BDF8"
DISPLAY_REFERENCE_MASK_COMPARE_MODE = "project_mask_regions_full_resolution"
DISPLAY_REFERENCE_MASK_PREVIEW_COLOR_BGR = (248, 189, 56)  # #38BDF8
DISPLAY_REFERENCE_MASK_PREVIEW_FILL_ALPHA = 0.10

# Mantidos somente porque módulos/testes antigos podem importar estes nomes.
# O fluxo F3 atual não abre mais diálogo de recorte nem usa estes valores na UI.
DISPLAY_REFERENCE_ROI_VERTICAL_UI_RESERVE = 320
DISPLAY_REFERENCE_ROI_MIN_DRAW_HEIGHT = 220


def normalizar_roi_referencia(roi) -> dict | None:
    """Compatibilidade com metadados antigos; não participa mais do F3 atual."""
    if not isinstance(roi, dict):
        return None
    try:
        x = float(roi.get("x", 0.0))
        y = float(roi.get("y", 0.0))
        width = float(roi.get("width", roi.get("w", 0.0)))
        height = float(roi.get("height", roi.get("h", 0.0)))
    except (TypeError, ValueError):
        return None

    x1 = max(0.0, min(1.0, x))
    y1 = max(0.0, min(1.0, y))
    x2 = max(0.0, min(1.0, x + width))
    y2 = max(0.0, min(1.0, y + height))
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    width = x2 - x1
    height = y2 - y1
    if (
        width < DISPLAY_REFERENCE_ROI_MIN_FRACTION
        or height < DISPLAY_REFERENCE_ROI_MIN_FRACTION
    ):
        return None
    if (
        x1 <= 0.000001
        and y1 <= 0.000001
        and x2 >= 0.999999
        and y2 >= 0.999999
    ):
        return None
    return {
        "x": round(x1, 6),
        "y": round(y1, 6),
        "width": round(width, 6),
        "height": round(height, 6),
    }


def recortar_roi_referencia(image, roi):
    """Compatibilidade legada. O comparador atual não chama este helper."""
    normalized = normalizar_roi_referencia(roi)
    if image is None or getattr(image, "size", 0) == 0 or normalized is None:
        return image
    image_height, image_width = image.shape[:2]
    x1 = max(0, min(image_width - 1, int(round(normalized["x"] * image_width))))
    y1 = max(0, min(image_height - 1, int(round(normalized["y"] * image_height))))
    x2 = max(
        x1 + 1,
        min(
            image_width,
            int(round((normalized["x"] + normalized["width"]) * image_width)),
        ),
    )
    y2 = max(
        y1 + 1,
        min(
            image_height,
            int(round((normalized["y"] + normalized["height"]) * image_height)),
        ),
    )
    return image[y1:y2, x1:x2]


def descricao_roi_referencia(metadata: dict | None) -> str:
    del metadata
    return "MÁSCARAS DO PROJETO"


def _valid_image(image) -> bool:
    return image is not None and getattr(image, "size", 0) > 0


def _project_mask_context(repository, project_name: str) -> tuple[tuple[int, int] | None, list[dict]]:
    if repository is None:
        return None, []
    try:
        project = repository.carregar_projeto(project_name)
    except Exception:
        project = None
    if not isinstance(project, dict):
        return None, []
    resolution = normalizar_resolucao_display(project.get("master_resolution"))
    masks = [
        deepcopy(mask)
        for mask in (project.get("masks", []) or [])
        if isinstance(mask, dict) and mask.get("id") is not None
    ]
    return resolution, masks


def _metadata_with_project_masks(repository, project_name: str, metadata: dict | None):
    if not isinstance(metadata, dict):
        return metadata
    resolution, masks = _project_mask_context(repository, project_name)
    result = deepcopy(metadata)
    # ROI retangular antiga deixa de ser consumida, mesmo que ainda exista em
    # algum JSON criado por uma versão anterior do sistema.
    result.pop("roi", None)
    result["_display_project_name"] = str(project_name or "")
    result["_display_master_resolution"] = (
        tuple(resolution) if resolution is not None else None
    )
    result["_display_mask_regions"] = masks
    result["mask_region_count"] = len(masks)
    result["comparison_mode"] = DISPLAY_REFERENCE_MASK_COMPARE_MODE
    return result


def _metadata_masks(metadata: dict | None) -> tuple[tuple[int, int] | None, list[dict]]:
    data = metadata if isinstance(metadata, dict) else {}
    resolution = normalizar_resolucao_display(data.get("_display_master_resolution"))
    masks = [
        deepcopy(mask)
        for mask in (data.get("_display_mask_regions", []) or [])
        if isinstance(mask, dict) and mask.get("id") is not None
    ]
    return resolution, masks


def _mask_selection(mask: dict):
    try:
        return display_mask_to_analysis_selection(mask)
    except (TypeError, ValueError):
        return None


def construir_mascara_uniao_referencias_display(
    masks: list[dict],
    width: int,
    height: int,
) -> np.ndarray:
    """Cria a união binária das ROIs desenhadas no Projeto Display."""
    width = max(1, int(width))
    height = max(1, int(height))
    union = np.zeros((height, width), dtype=np.uint8)
    for mask in masks or []:
        if not isinstance(mask, dict):
            continue
        selection = _mask_selection(mask)
        if selection is None:
            continue
        try:
            region = criar_mascara_roi_global(selection, width, height)
        except Exception:
            continue
        if region is None or region.shape[:2] != union.shape[:2]:
            continue
        union = cv2.bitwise_or(union, region.astype(np.uint8))
    return union


def _masked_ssim(reference_roi, current_roi, mask) -> float | None:
    if not _valid_image(reference_roi) or not _valid_image(current_roi):
        return None
    if mask is None:
        return None
    selected = np.asarray(mask) > 0
    if selected.shape[:2] != reference_roi.shape[:2] or not np.any(selected):
        return None

    ref_gray = cv2.cvtColor(reference_roi, cv2.COLOR_BGR2GRAY).astype(np.float32)
    cur_gray = cv2.cvtColor(current_roi, cv2.COLOR_BGR2GRAY).astype(np.float32)
    if cur_gray.shape != ref_gray.shape:
        cur_gray = cv2.resize(
            cur_gray,
            (ref_gray.shape[1], ref_gray.shape[0]),
            interpolation=cv2.INTER_AREA,
        )

    smallest = min(ref_gray.shape[:2])
    if smallest >= 5:
        kernel = (5, 5)
        sigma = 1.0
    elif smallest >= 3:
        kernel = (3, 3)
        sigma = 0.8
    else:
        kernel = None
        sigma = 0.0

    if kernel is not None:
        mu_ref = cv2.GaussianBlur(ref_gray, kernel, sigma)
        mu_cur = cv2.GaussianBlur(cur_gray, kernel, sigma)
        mu_ref_sq = mu_ref * mu_ref
        mu_cur_sq = mu_cur * mu_cur
        mu_ref_cur = mu_ref * mu_cur
        sigma_ref_sq = (
            cv2.GaussianBlur(ref_gray * ref_gray, kernel, sigma) - mu_ref_sq
        )
        sigma_cur_sq = (
            cv2.GaussianBlur(cur_gray * cur_gray, kernel, sigma) - mu_cur_sq
        )
        sigma_ref_cur = (
            cv2.GaussianBlur(ref_gray * cur_gray, kernel, sigma) - mu_ref_cur
        )
        c1 = (0.01 * 255.0) ** 2
        c2 = (0.03 * 255.0) ** 2
        numerator = (2.0 * mu_ref_cur + c1) * (2.0 * sigma_ref_cur + c2)
        denominator = (mu_ref_sq + mu_cur_sq + c1) * (
            sigma_ref_sq + sigma_cur_sq + c2
        )
        ssim_map = numerator / np.maximum(denominator, 1e-9)
        structural = float(np.mean(ssim_map[selected]))
    else:
        structural = 1.0

    ref_pixels = reference_roi[selected].astype(np.float32)
    cur_pixels = current_roi[selected].astype(np.float32)
    pixel_mae = float(np.mean(np.abs(ref_pixels - cur_pixels)) / 255.0)
    pixel_similarity = 1.0 - max(0.0, min(1.0, pixel_mae))

    # SSIM mantém tolerância a pequenas oscilações da câmera; o termo de pixel
    # impede que um segmento claramente aceso/apagado seja diluído pela estrutura.
    score = (0.78 * structural) + (0.22 * pixel_similarity)
    return max(0.0, min(1.0, float(score)))


def calcular_similaridade_referencia_por_mascaras(
    reference_image,
    current_image,
    metadata: dict | None,
) -> dict:
    """Compara somente os pixels pertencentes às máscaras do Projeto Display.

    Cada máscara recebe um score próprio e todas têm o mesmo peso no score final.
    Assim uma máscara pequena não desaparece dentro de uma ROI retangular grande.
    """
    resolution, masks = _metadata_masks(metadata)
    if not masks or not _valid_image(reference_image) or not _valid_image(current_image):
        return {
            "score": None,
            "mask_region_count": len(masks),
            "valid_mask_region_count": 0,
            "mask_scores": {},
            "comparison_mode": DISPLAY_REFERENCE_MASK_COMPARE_MODE,
        }

    if resolution is None:
        resolution = (
            int(reference_image.shape[1]),
            int(reference_image.shape[0]),
        )
    reference = check_module._prepare_bgr(reference_image, resolution)
    current = check_module._prepare_bgr(current_image, resolution)
    if not _valid_image(reference) or not _valid_image(current):
        return {
            "score": None,
            "mask_region_count": len(masks),
            "valid_mask_region_count": 0,
            "mask_scores": {},
            "comparison_mode": DISPLAY_REFERENCE_MASK_COMPARE_MODE,
        }

    height, width = reference.shape[:2]
    scores: dict[str, float] = {}
    for index, mask in enumerate(masks, start=1):
        selection = _mask_selection(mask)
        if selection is None:
            continue
        try:
            prepared = criar_mascaras_roi(selection, width, height)
        except Exception:
            prepared = None
        if prepared is None:
            continue
        x1, y1, x2, y2, local_mask, _inner, _ring = prepared
        reference_roi = reference[y1:y2, x1:x2]
        current_roi = current[y1:y2, x1:x2]
        score = _masked_ssim(reference_roi, current_roi, local_mask)
        if score is None:
            continue
        mask_id = str(mask.get("id") or f"MASK_{index:03d}")
        scores[mask_id] = round(float(score), 4)

    final_score = (
        float(sum(scores.values()) / len(scores))
        if scores
        else None
    )
    return {
        "score": None if final_score is None else round(final_score, 4),
        "mask_region_count": len(masks),
        "valid_mask_region_count": len(scores),
        "mask_scores": scores,
        "comparison_mode": DISPLAY_REFERENCE_MASK_COMPARE_MODE,
    }


def _reference_image(metadata: dict | None):
    path = Path(str((metadata or {}).get("image_path") or ""))
    if not path.is_file():
        return None, path
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    return (image if _valid_image(image) else None), path


def _threshold(metadata: dict | None) -> float:
    try:
        value = float(
            (metadata or {}).get(
                "threshold",
                check_module.DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD,
            )
        )
    except (TypeError, ValueError):
        value = check_module.DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD
    return max(0.10, min(0.99, value))


def _avaliar_referencia_por_mascaras(frame, metadata: dict | None) -> dict:
    if not isinstance(metadata, dict):
        return {
            "configured": False,
            "available": False,
            "matched": True,
            "score": None,
            "threshold": check_module.DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD,
            "comparison_mode": DISPLAY_REFERENCE_MASK_COMPARE_MODE,
            "mask_region_count": 0,
        }

    threshold = _threshold(metadata)
    reference, path = _reference_image(metadata)
    if reference is None or not _valid_image(frame):
        return {
            "configured": True,
            "available": False,
            "matched": False,
            "score": None,
            "threshold": round(threshold, 4),
            "image_path": str(path),
            "comparison_mode": DISPLAY_REFERENCE_MASK_COMPARE_MODE,
            "mask_region_count": int(metadata.get("mask_region_count", 0) or 0),
        }

    comparison = calcular_similaridade_referencia_por_mascaras(
        reference,
        frame,
        metadata,
    )
    score = comparison.get("score")
    available = score is not None and int(comparison.get("valid_mask_region_count", 0)) > 0
    return {
        "configured": True,
        "available": bool(available),
        "matched": bool(available and float(score) >= threshold),
        "score": score,
        "threshold": round(threshold, 4),
        "image_path": str(path),
        "comparison_mode": DISPLAY_REFERENCE_MASK_COMPARE_MODE,
        "mask_region_count": int(comparison.get("mask_region_count", 0) or 0),
        "valid_mask_region_count": int(
            comparison.get("valid_mask_region_count", 0) or 0
        ),
        "mask_scores": dict(comparison.get("mask_scores") or {}),
        "reason": None if available else "mascaras_projeto_indisponiveis",
    }


def _install_reference_store_mask_context() -> None:
    check_cls = check_module.DisplayCheckPresenceReferenceStore
    if not bool(getattr(check_cls, "_display_mask_regions_installed", False)):
        original_get = check_cls.get

        def get(self, project_name: str, check_id: str):
            metadata = original_get(self, project_name, check_id)
            return _metadata_with_project_masks(self.repository, project_name, metadata)

        check_cls.get = get
        check_cls._display_mask_regions_installed = True

    project_cls = visual_module.DisplayProjectPresenceReferenceStore
    if not bool(getattr(project_cls, "_display_mask_regions_installed", False)):
        original_get = project_cls.get
        original_get_all = project_cls.get_all

        def get(self, project_name: str, kind: str):
            metadata = original_get(self, project_name, kind)
            return _metadata_with_project_masks(self.repository, project_name, metadata)

        def get_all(self, project_name: str):
            values = original_get_all(self, project_name)
            return {
                str(kind): _metadata_with_project_masks(
                    self.repository,
                    project_name,
                    metadata,
                )
                for kind, metadata in (values or {}).items()
                if isinstance(metadata, dict)
            }

        project_cls.get = get
        project_cls.get_all = get_all
        project_cls._display_mask_regions_installed = True


def _install_mask_matchers() -> None:
    check_module.avaliar_referencia_presenca_display = _avaliar_referencia_por_mascaras

    matcher_cls = visual_module.DisplayVisualReferenceMatcher
    if not bool(getattr(matcher_cls, "_display_mask_regions_matcher_installed", False)):
        def score(self, current_frame, metadata):
            reference, _path = _reference_image(metadata)
            if reference is None or not _valid_image(current_frame):
                return None
            return calcular_similaridade_referencia_por_mascaras(
                reference,
                current_frame,
                metadata,
            ).get("score")

        def identify_check_state(self, frame, project_name: str):
            checks = self.repository.listar_checks(project_name)
            candidates = []
            for check in checks:
                check_id = str(check.get("id") or "")
                metadata = self.check_store.get(project_name, check_id)
                if metadata is None:
                    continue
                candidates.append(
                    {
                        "kind": "check",
                        "check_id": check_id,
                        "name": str(check.get("name") or check_id),
                        "score": self._score(frame, metadata),
                        "threshold": self._threshold(metadata),
                        "comparison_mode": DISPLAY_REFERENCE_MASK_COMPARE_MODE,
                        "mask_region_count": int(
                            metadata.get("mask_region_count", 0) or 0
                        ),
                    }
                )
            result = self._choose(candidates)
            result["configured_count"] = len(candidates)
            result["camera"] = _valid_image(frame)
            result["comparison_mode"] = DISPLAY_REFERENCE_MASK_COMPARE_MODE
            return result

        def identify_board_presence(self, frame, project_name: str):
            references = self.project_store.get_all(project_name)
            configured_count = sum(
                1
                for kind in visual_module.DISPLAY_PROJECT_REFERENCE_TYPES
                if kind in references
            )
            candidates = []
            for kind in visual_module.DISPLAY_PROJECT_REFERENCE_TYPES:
                metadata = references.get(kind)
                if metadata is None:
                    continue
                candidates.append(
                    {
                        "kind": kind,
                        "name": visual_module.DISPLAY_PROJECT_REFERENCE_LABELS[kind],
                        "score": self._score(frame, metadata),
                        "threshold": self._threshold(metadata),
                        "comparison_mode": DISPLAY_REFERENCE_MASK_COMPARE_MODE,
                        "mask_region_count": int(
                            metadata.get("mask_region_count", 0) or 0
                        ),
                    }
                )
            result = self._choose(candidates)
            result["configured_count"] = configured_count
            result["required_count"] = len(visual_module.DISPLAY_PROJECT_REFERENCE_TYPES)
            result["camera"] = _valid_image(frame)
            result["comparison_mode"] = DISPLAY_REFERENCE_MASK_COMPARE_MODE
            if configured_count < len(visual_module.DISPLAY_PROJECT_REFERENCE_TYPES):
                result["matched"] = False
                result["incomplete"] = True
            return result

        matcher_cls._score = score
        matcher_cls.identify_check_state = identify_check_state
        matcher_cls.identify_board_presence = identify_board_presence
        matcher_cls._display_mask_regions_matcher_installed = True

    # Estes módulos importaram a função de presença por nome antes da instalação.
    # Atualizamos as cópias locais para que nenhum caminho F3 volte ao frame inteiro.
    try:
        import src.platform.display_f3_same_mask_reference_fix as same_mask_module

        same_mask_module.avaliar_referencia_presenca_display = (
            _avaliar_referencia_por_mascaras
        )
    except Exception:
        pass


def _score_exact_reference_by_masks(frame, metadata: dict | None) -> float | None:
    reference, _path = _reference_image(metadata)
    if reference is None or not _valid_image(frame):
        return None
    return calcular_similaridade_referencia_por_mascaras(
        reference,
        frame,
        metadata,
    ).get("score")


def _install_exact_reference_mask_score() -> None:
    try:
        import src.platform.display_f3_exact_check_template as exact_module
    except Exception:
        return

    if not bool(getattr(exact_module, "_display_mask_regions_score_installed", False)):
        original_classifier = exact_module.classificar_estado_fisico_por_gabaritos_f3
        exact_module._score_reference_full_roi = _score_exact_reference_by_masks
        exact_module._score_reference_full_masks = _score_exact_reference_by_masks
        exact_module.avaliar_referencia_presenca_display = (
            _avaliar_referencia_por_mascaras
        )

        def classify(matcher, frame, project_name: str):
            state = original_classifier(matcher, frame, project_name)
            if isinstance(state, dict):
                state["comparison_mode"] = DISPLAY_REFERENCE_MASK_COMPARE_MODE
                try:
                    _resolution, masks = _project_mask_context(
                        matcher.repository,
                        project_name,
                    )
                except Exception:
                    masks = []
                state["mask_region_count"] = len(masks)
                state.pop("roi", None)
            return state

        exact_module.classificar_estado_fisico_por_gabaritos_f3 = classify
        exact_module._display_mask_regions_score_installed = True


def _decorate_reference_image(image, masks: list[dict], resolution):
    if not _valid_image(image):
        return image
    target_resolution = normalizar_resolucao_display(resolution)
    if target_resolution is None:
        target_resolution = (int(image.shape[1]), int(image.shape[0]))
    result = check_module._prepare_bgr(image, target_resolution)
    if not _valid_image(result):
        return image

    height, width = result.shape[:2]
    tint = result.copy()
    contours_to_draw = []
    for mask in masks or []:
        selection = _mask_selection(mask)
        if selection is None:
            continue
        try:
            region = criar_mascara_roi_global(selection, width, height)
        except Exception:
            continue
        if region is None or not np.any(region):
            continue
        contours, _hierarchy = cv2.findContours(
            region.astype(np.uint8),
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        if not contours:
            continue
        tint[region > 0] = DISPLAY_REFERENCE_MASK_PREVIEW_COLOR_BGR
        contours_to_draw.extend(contours)

    if not contours_to_draw:
        return result
    cv2.addWeighted(
        tint,
        DISPLAY_REFERENCE_MASK_PREVIEW_FILL_ALPHA,
        result,
        1.0 - DISPLAY_REFERENCE_MASK_PREVIEW_FILL_ALPHA,
        0.0,
        dst=result,
    )
    thickness = max(1, int(round(min(width, height) / 420.0)))
    cv2.drawContours(
        result,
        contours_to_draw,
        -1,
        DISPLAY_REFERENCE_MASK_PREVIEW_COLOR_BGR,
        thickness,
        lineType=cv2.LINE_AA,
    )
    return result


def _install_check_reference_preview_masks() -> None:
    cls = check_module.DisplayCheckManagerPresenceWindow
    if bool(getattr(cls, "_display_mask_regions_preview_installed", False)):
        return
    original_update = cls._update_presence_detail

    def update_detail(self):
        original_update(self)
        canvas = getattr(self, "reference_canvas", None)
        store = getattr(self, "_presence_store", None)
        check_id = self._selected_id() if hasattr(self, "_selected_id") else ""
        if canvas is None or store is None or not check_id:
            return
        metadata = store.get(self.project_name, check_id)
        if not isinstance(metadata, dict):
            return
        path = Path(str(metadata.get("image_path") or ""))
        image = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.is_file() else None
        resolution, masks = _metadata_masks(metadata)
        if image is None or not masks:
            return
        decorated = _decorate_reference_image(image, masks, resolution)
        photo = self._photo_from_image(decorated, 326, 88)
        if photo is None:
            return
        self._presence_photo = photo
        canvas.delete("all")
        canvas.create_image(165, 46, image=photo, anchor="center")
        status = getattr(self, "reference_status", None)
        if status is not None:
            threshold = _threshold(metadata)
            status.configure(
                text=(
                    f"Referência ativa • {len(masks)} ROIs de máscara • "
                    f"mínimo {threshold * 100:.0f}%"
                ),
                fg="#86EFAC",
            )

    cls._update_presence_detail = update_detail
    cls._display_mask_regions_preview_installed = True


def _install_project_reference_preview_masks() -> None:
    cls = visual_module.DisplayProjectConfigPresenceWindow
    if bool(getattr(cls, "_display_mask_regions_preview_installed", False)):
        return
    original_update = cls._update_project_presence_detail

    def update_detail(self):
        original_update(self)
        store = getattr(self, "_project_presence_store", None)
        project_name = self._selected_name() if hasattr(self, "_selected_name") else ""
        if store is None or not project_name:
            return
        for kind in visual_module.DISPLAY_PROJECT_REFERENCE_TYPES:
            canvas = getattr(self, "_project_presence_canvases", {}).get(kind)
            status = getattr(self, "_project_presence_status", {}).get(kind)
            metadata = store.get(project_name, kind)
            if canvas is None or not isinstance(metadata, dict):
                continue
            path = Path(str(metadata.get("image_path") or ""))
            image = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.is_file() else None
            resolution, masks = _metadata_masks(metadata)
            if image is None or not masks:
                continue
            decorated = _decorate_reference_image(image, masks, resolution)
            photo = visual_module._photo_from_image(decorated, 170, 78)
            if photo is None:
                continue
            self._project_presence_photos[kind] = photo
            canvas.delete("all")
            canvas.create_image(87, 41, image=photo, anchor="center")
            if status is not None:
                status.configure(
                    text=f"ATIVA • {len(masks)} ROIs DE MÁSCARA",
                    fg="#86EFAC",
                )

    cls._update_project_presence_detail = update_detail
    cls._display_mask_regions_preview_installed = True


def _install_visual_analysis_contract() -> None:
    """Atualiza diagnóstico/status para declarar corretamente a nova base visual."""
    try:
        import src.platform.display_f3_visual_analysis_relative_fallback as fallback_module
    except Exception:
        fallback_module = None

    if fallback_module is not None and not bool(
        getattr(fallback_module, "_display_mask_regions_contract_installed", False)
    ):
        original_collect = fallback_module._collect_visual_candidates
        original_build = fallback_module._build_visual_analysis_state
        original_extend = fallback_module._extend_debug_snapshot

        def collect(matcher, frame, project_name: str, score_overrides=None):
            result = original_collect(
                matcher,
                frame,
                project_name,
                score_overrides=score_overrides,
            )
            _resolution, masks = _project_mask_context(
                matcher.repository,
                project_name,
            )
            for item in result.values():
                if not isinstance(item, dict):
                    continue
                item["roi"] = None
                item["mask_region_count"] = len(masks)
                item["comparison_mode"] = DISPLAY_REFERENCE_MASK_COMPARE_MODE
            return result

        def build(self, frame, project_name: str):
            state = original_build(self, frame, project_name)
            if isinstance(state, dict):
                state["uses_masks"] = True
                state["uses_mask_geometry"] = True
                state["uses_check_state"] = False
                state["comparison_basis"] = DISPLAY_REFERENCE_MASK_COMPARE_MODE
                try:
                    repository = getattr(self, "display_project_repository", None)
                    _resolution, masks = _project_mask_context(repository, project_name)
                except Exception:
                    masks = []
                state["mask_region_count"] = len(masks)
            return state

        def extend_debug(original):
            extended = original_extend(original)

            def build_debug(app, frame, project_name: str):
                snapshot = extended(app, frame, project_name)
                if isinstance(snapshot, dict):
                    snapshot["uses_masks"] = True
                    snapshot["uses_mask_geometry"] = True
                    snapshot["uses_check_state"] = False
                    snapshot["comparison_basis"] = DISPLAY_REFERENCE_MASK_COMPARE_MODE
                    repository = getattr(app, "display_project_repository", None)
                    _resolution, masks = _project_mask_context(repository, project_name)
                    snapshot["mask_region_count"] = len(masks)
                return snapshot

            return build_debug

        fallback_module._collect_visual_candidates = collect
        fallback_module._build_visual_analysis_state = build
        fallback_module._extend_debug_snapshot = extend_debug
        fallback_module._display_mask_regions_contract_installed = True

    try:
        import src.platform.display_f3_manual_snapshot_debug as manual_module
    except Exception:
        manual_module = None
    if manual_module is not None and not bool(
        getattr(manual_module, "_display_mask_regions_debug_installed", False)
    ):
        original_rows = manual_module._reference_rows

        def reference_rows(matcher, frame, project_name: str):
            rows = original_rows(matcher, frame, project_name)
            _resolution, masks = _project_mask_context(
                matcher.repository,
                project_name,
            )
            for row in rows:
                if not isinstance(row, dict):
                    continue
                row["roi"] = None
                row["mask_region_count"] = len(masks)
                row["comparison_mode"] = DISPLAY_REFERENCE_MASK_COMPARE_MODE
            return rows

        manual_module._reference_rows = reference_rows
        manual_module._display_mask_regions_debug_installed = True

    try:
        import src.platform.display_f3_snapshot_debug_lightweight_ui as debug_ui
    except Exception:
        debug_ui = None
    if debug_ui is not None and not bool(
        getattr(debug_ui, "_display_mask_regions_debug_installed", False)
    ):
        original_build = debug_ui._build_visual_analysis_snapshot
        original_report_block = debug_ui._visual_report_block

        def build_snapshot(app, frame, project_name: str):
            snapshot = original_build(app, frame, project_name)
            if isinstance(snapshot, dict):
                snapshot["uses_masks"] = True
                snapshot["uses_mask_geometry"] = True
                snapshot["uses_check_state"] = False
                snapshot["comparison_basis"] = DISPLAY_REFERENCE_MASK_COMPARE_MODE
                repository = getattr(app, "display_project_repository", None)
                _resolution, masks = _project_mask_context(repository, project_name)
                snapshot["mask_region_count"] = len(masks)
            return snapshot

        def report_block(snapshot: dict):
            text = original_report_block(snapshot)
            return (
                str(text)
                .replace(
                    "Esta leitura usa somente as referências visuais do projeto e a ROI configurada.",
                    "Esta leitura usa as referências visuais somente dentro das máscaras do Projeto Display.",
                )
                .replace(
                    "Ela NÃO participa de OK/NG, CHECK, máscaras, avanço de fluxo ou rearmamento.",
                    "Ela usa somente a geometria das máscaras como região visual; não usa o estado lógico do CHECK e não altera OK/NG, avanço ou rearmamento.",
                )
            )

        debug_ui._build_visual_analysis_snapshot = build_snapshot
        debug_ui._visual_report_block = report_block
        debug_ui._display_mask_regions_debug_installed = True


def instalar_roi_referencias_display_f3() -> None:
    """Instala ROIs por máscara e aposenta o seletor retangular no F3.

    O nome público é preservado para não quebrar o bootstrap existente, mas a
    implementação agora é exclusivamente baseada nas máscaras do projeto.
    """
    _install_reference_store_mask_context()
    _install_mask_matchers()
    _install_exact_reference_mask_score()
    _install_check_reference_preview_masks()
    _install_project_reference_preview_masks()
    _install_visual_analysis_contract()
