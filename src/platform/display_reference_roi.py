from __future__ import annotations

"""Região visual das referências do Display F3 baseada nas máscaras do projeto.

Esta camada é deliberadamente pequena: o runtime produtivo do F3 permanece o
mesmo que existia antes da troca do recorte retangular. A única mudança é a
região considerada pelas fotos de presença/referência: em vez de ``metadata.roi``
retangular, usa-se a união das máscaras já desenhadas em "Seleção, ajuste e
máscara".

Não altera o loop de preview, não cria timers, não executa uma segunda análise e
não interfere no F2.
"""

import json
from copy import deepcopy
from pathlib import Path

import cv2
import numpy as np

import src.platform.display_check_presence_reference as check_module
import src.platform.display_visual_reference_status as visual_module
from src.core.roi_geometry import criar_mascara_roi_global
from src.platform.display_auto_check_analyzer import display_mask_to_analysis_selection
from src.platform.display_project_repository import normalizar_resolucao_display


DISPLAY_REFERENCE_ROI_MIN_FRACTION = 0.015
DISPLAY_REFERENCE_ROI_COLOR = "#38BDF8"
DISPLAY_REFERENCE_ROI_VERTICAL_UI_RESERVE = 320
DISPLAY_REFERENCE_ROI_MIN_DRAW_HEIGHT = 220
DISPLAY_REFERENCE_MASK_COMPARE_MODE = "project_mask_union"
DISPLAY_REFERENCE_MASK_PREVIEW_BGR = (248, 189, 56)
DISPLAY_REFERENCE_MASK_PREVIEW_ALPHA = 0.12
DISPLAY_REFERENCE_COMPARE_WIDTH = 360

_UNION_CACHE: dict[tuple, np.ndarray] = {}


def normalizar_roi_referencia(roi) -> dict | None:
    """Compatibilidade para imports históricos; o F3 não usa mais esta ROI."""
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
    if width < DISPLAY_REFERENCE_ROI_MIN_FRACTION or height < DISPLAY_REFERENCE_ROI_MIN_FRACTION:
        return None
    return {
        "x": round(x1, 6),
        "y": round(y1, 6),
        "width": round(width, 6),
        "height": round(height, 6),
    }


def recortar_roi_referencia(image, roi):
    """Compatibilidade legada. O instalador produtivo não chama este helper."""
    normalized = normalizar_roi_referencia(roi)
    if image is None or getattr(image, "size", 0) == 0 or normalized is None:
        return image
    image_height, image_width = image.shape[:2]
    x1 = max(0, min(image_width - 1, int(round(normalized["x"] * image_width))))
    y1 = max(0, min(image_height - 1, int(round(normalized["y"] * image_height))))
    x2 = max(x1 + 1, min(image_width, int(round((normalized["x"] + normalized["width"]) * image_width))))
    y2 = max(y1 + 1, min(image_height, int(round((normalized["y"] + normalized["height"]) * image_height))))
    return image[y1:y2, x1:x2]


def descricao_roi_referencia(_metadata: dict | None) -> str:
    return "MÁSCARAS DO PROJETO"


class DisplayReferenceRoiDialog:
    """Compatibilidade de import. O seletor retangular foi aposentado da UI."""

    def __init__(self, *_args, **_kwargs) -> None:
        self.window = None


def _project_mask_context(repository, project_name: str):
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


def _mask_signature(masks: list[dict]) -> str:
    try:
        return json.dumps(masks, sort_keys=True, separators=(",", ":"), default=str)
    except Exception:
        return repr(masks)


def _decorate_metadata(repository, project_name: str, metadata: dict | None):
    if not isinstance(metadata, dict):
        return metadata
    resolution, masks = _project_mask_context(repository, project_name)
    result = deepcopy(metadata)
    result.pop("roi", None)
    result["_display_master_resolution"] = tuple(resolution) if resolution else None
    result["_display_mask_regions"] = masks
    result["_display_mask_signature"] = _mask_signature(masks)
    result["mask_region_count"] = len(masks)
    result["comparison_mode"] = DISPLAY_REFERENCE_MASK_COMPARE_MODE
    return result


def _install_store_masks() -> None:
    check_cls = check_module.DisplayCheckPresenceReferenceStore
    if not bool(getattr(check_cls, "_display_mask_regions_installed", False)):
        original_get = check_cls.get
        original_capture = check_cls.capture

        def get(self, project_name: str, check_id: str):
            return _decorate_metadata(
                self.repository,
                project_name,
                original_get(self, project_name, check_id),
            )

        def capture(self, project_name, check_id, frame, master_resolution):
            result = original_capture(self, project_name, check_id, frame, master_resolution)
            return _decorate_metadata(self.repository, project_name, result)

        check_cls.get = get
        check_cls.capture = capture
        check_cls._display_mask_regions_installed = True

    project_cls = visual_module.DisplayProjectPresenceReferenceStore
    if not bool(getattr(project_cls, "_display_mask_regions_installed", False)):
        original_get = project_cls.get
        original_get_all = project_cls.get_all
        original_capture = project_cls.capture

        def get(self, project_name: str, kind: str):
            return _decorate_metadata(
                self.repository,
                project_name,
                original_get(self, project_name, kind),
            )

        def get_all(self, project_name: str):
            values = original_get_all(self, project_name)
            return {
                key: _decorate_metadata(self.repository, project_name, value)
                for key, value in values.items()
            }

        def capture(self, project_name, kind, frame, master_resolution):
            result = original_capture(self, project_name, kind, frame, master_resolution)
            return _decorate_metadata(self.repository, project_name, result)

        project_cls.get = get
        project_cls.get_all = get_all
        project_cls.capture = capture
        project_cls._display_mask_regions_installed = True


def _union_mask(metadata: dict | None, width: int, height: int) -> np.ndarray | None:
    data = metadata if isinstance(metadata, dict) else {}
    masks = [m for m in (data.get("_display_mask_regions", []) or []) if isinstance(m, dict)]
    if not masks:
        return None

    master = normalizar_resolucao_display(data.get("_display_master_resolution"))
    if master is None:
        master = (int(width), int(height))
    master_w, master_h = int(master[0]), int(master[1])
    signature = str(data.get("_display_mask_signature") or _mask_signature(masks))
    key = (master_w, master_h, int(width), int(height), signature)
    cached = _UNION_CACHE.get(key)
    if cached is not None:
        return cached

    union = np.zeros((master_h, master_w), dtype=np.uint8)
    for mask in masks:
        try:
            selection = display_mask_to_analysis_selection(mask)
            region = criar_mascara_roi_global(selection, master_w, master_h)
        except Exception:
            continue
        if region is None or region.shape[:2] != union.shape[:2]:
            continue
        union = cv2.bitwise_or(union, region.astype(np.uint8))

    if not np.any(union):
        return None
    if (master_w, master_h) != (int(width), int(height)):
        union = cv2.resize(
            union,
            (int(width), int(height)),
            interpolation=cv2.INTER_NEAREST,
        )
    if len(_UNION_CACHE) > 12:
        _UNION_CACHE.clear()
    _UNION_CACHE[key] = union
    return union


def _resize_for_compare(reference, current, metadata):
    if reference is None or current is None:
        return None, None, None
    if getattr(reference, "size", 0) == 0 or getattr(current, "size", 0) == 0:
        return None, None, None
    current = check_module._prepare_bgr(
        current,
        (int(reference.shape[1]), int(reference.shape[0])),
    )
    if current is None:
        return None, None, None

    height, width = reference.shape[:2]
    if width > DISPLAY_REFERENCE_COMPARE_WIDTH:
        target_w = DISPLAY_REFERENCE_COMPARE_WIDTH
        target_h = max(1, int(round(height * target_w / float(width))))
        reference = cv2.resize(reference, (target_w, target_h), interpolation=cv2.INTER_AREA)
        current = cv2.resize(current, (target_w, target_h), interpolation=cv2.INTER_AREA)
        width, height = target_w, target_h

    union = _union_mask(metadata, width, height)
    return reference, current, union


def calcular_similaridade_referencia_por_mascaras(reference, current, metadata) -> float | None:
    """Um único SSIM pequeno, calculado somente dentro da união das máscaras."""
    reference, current, union = _resize_for_compare(reference, current, metadata)
    if reference is None or current is None or union is None:
        return None
    selected = union > 0
    if not np.any(selected):
        return None

    ref_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY).astype(np.float32)
    cur_gray = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY).astype(np.float32)
    c1 = (0.01 * 255.0) ** 2
    c2 = (0.03 * 255.0) ** 2
    mu_ref = cv2.GaussianBlur(ref_gray, (11, 11), 1.5)
    mu_cur = cv2.GaussianBlur(cur_gray, (11, 11), 1.5)
    mu_ref_sq = mu_ref * mu_ref
    mu_cur_sq = mu_cur * mu_cur
    mu_ref_cur = mu_ref * mu_cur
    sigma_ref_sq = cv2.GaussianBlur(ref_gray * ref_gray, (11, 11), 1.5) - mu_ref_sq
    sigma_cur_sq = cv2.GaussianBlur(cur_gray * cur_gray, (11, 11), 1.5) - mu_cur_sq
    sigma_ref_cur = cv2.GaussianBlur(ref_gray * cur_gray, (11, 11), 1.5) - mu_ref_cur
    numerator = (2.0 * mu_ref_cur + c1) * (2.0 * sigma_ref_cur + c2)
    denominator = (mu_ref_sq + mu_cur_sq + c1) * (sigma_ref_sq + sigma_cur_sq + c2)
    score_map = numerator / np.maximum(denominator, 1e-9)
    score = float(np.mean(score_map[selected]))
    return round(max(0.0, min(1.0, score)), 4)


def _read_reference(metadata: dict | None):
    path = Path(str((metadata or {}).get("image_path") or ""))
    if not path.is_file():
        return None, path
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    return image, path


def _install_matchers_masks() -> None:
    if not bool(getattr(check_module, "_display_mask_union_matcher_installed", False)):
        original_check_eval = check_module.avaliar_referencia_presenca_display

        def avaliar(frame, metadata):
            if not isinstance(metadata, dict) or not metadata.get("_display_mask_regions"):
                return original_check_eval(frame, metadata)
            reference, path = _read_reference(metadata)
            if reference is None or frame is None or getattr(frame, "size", 0) == 0:
                return original_check_eval(frame, metadata)
            score = calcular_similaridade_referencia_por_mascaras(reference, frame, metadata)
            if score is None:
                return original_check_eval(frame, metadata)
            try:
                threshold = float(metadata.get("threshold", check_module.DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD))
            except (TypeError, ValueError):
                threshold = check_module.DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD
            return {
                "configured": True,
                "available": True,
                "matched": bool(score >= threshold),
                "score": score,
                "threshold": round(threshold, 4),
                "image_path": str(path),
                "comparison_mode": DISPLAY_REFERENCE_MASK_COMPARE_MODE,
                "mask_region_count": int(metadata.get("mask_region_count", 0) or 0),
            }

        check_module.avaliar_referencia_presenca_display = avaliar
        check_module._display_mask_union_matcher_installed = True

    matcher_cls = visual_module.DisplayVisualReferenceMatcher
    if not bool(getattr(matcher_cls, "_display_mask_union_matcher_installed", False)):
        original_score = matcher_cls._score

        def score(self, current_small, metadata):
            if not isinstance(metadata, dict) or not metadata.get("_display_mask_regions"):
                return original_score(self, current_small, metadata)
            reference_small = self._reference_image(metadata)
            if reference_small is None or current_small is None:
                return None
            return calcular_similaridade_referencia_por_mascaras(
                reference_small,
                current_small,
                metadata,
            )

        matcher_cls._score = score
        matcher_cls._display_mask_union_matcher_installed = True

    try:
        import src.platform.display_f3_exact_check_template as exact_module

        def score_exact(frame, metadata):
            reference, _path = _read_reference(metadata)
            if reference is None or frame is None or getattr(frame, "size", 0) == 0:
                return None
            return calcular_similaridade_referencia_por_mascaras(
                reference,
                frame,
                metadata,
            )

        exact_module._score_reference_full_roi = score_exact
    except Exception:
        pass


def _decorate_reference_image(image, metadata):
    if image is None or getattr(image, "size", 0) == 0:
        return image
    union = _union_mask(metadata, int(image.shape[1]), int(image.shape[0]))
    if union is None:
        return image
    result = image.copy()
    tint = result.copy()
    tint[union > 0] = DISPLAY_REFERENCE_MASK_PREVIEW_BGR
    result = cv2.addWeighted(
        tint,
        DISPLAY_REFERENCE_MASK_PREVIEW_ALPHA,
        result,
        1.0 - DISPLAY_REFERENCE_MASK_PREVIEW_ALPHA,
        0.0,
    )
    contours, _ = cv2.findContours(union, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        cv2.drawContours(result, contours, -1, DISPLAY_REFERENCE_MASK_PREVIEW_BGR, 2, cv2.LINE_AA)
    return result


def _install_preview_masks() -> None:
    check_cls = check_module.DisplayCheckManagerPresenceWindow
    if not bool(getattr(check_cls, "_display_mask_preview_installed", False)):
        original_update = check_cls._update_presence_detail

        def update(self):
            original_update(self)
            store = getattr(self, "_presence_store", None)
            canvas = getattr(self, "reference_canvas", None)
            check_id = self._selected_id()
            if store is None or canvas is None or not check_id:
                return
            metadata = store.get(self.project_name, check_id)
            if not isinstance(metadata, dict):
                return
            image, _path = _read_reference(metadata)
            if image is None:
                return
            decorated = _decorate_reference_image(image, metadata)
            photo = self._photo_from_image(decorated, 326, 88)
            if photo is None:
                return
            self._presence_photo = photo
            canvas.delete("all")
            canvas.create_image(165, 46, image=photo, anchor="center")

        check_cls._update_presence_detail = update
        check_cls._display_mask_preview_installed = True

    project_cls = visual_module.DisplayProjectConfigPresenceWindow
    if not bool(getattr(project_cls, "_display_mask_preview_installed", False)):
        original_update = project_cls._update_project_presence_detail

        def update(self):
            original_update(self)
            store = getattr(self, "_project_presence_store", None)
            project_name = self._selected_name()
            if store is None or not project_name:
                return
            for kind in visual_module.DISPLAY_PROJECT_REFERENCE_TYPES:
                canvas = self._project_presence_canvases.get(kind)
                metadata = store.get(project_name, kind)
                if canvas is None or not isinstance(metadata, dict):
                    continue
                image, _path = _read_reference(metadata)
                if image is None:
                    continue
                decorated = _decorate_reference_image(image, metadata)
                photo = visual_module._photo_from_image(decorated, 170, 78)
                if photo is None:
                    continue
                self._project_presence_photos[kind] = photo
                canvas.delete("all")
                canvas.create_image(87, 41, image=photo, anchor="center")

        project_cls._update_project_presence_detail = update
        project_cls._display_mask_preview_installed = True


def instalar_roi_referencias_display_f3() -> None:
    """Troca apenas a região das referências; não altera o loop produtivo F3."""
    _install_store_masks()
    _install_matchers_masks()
    _install_preview_masks()
