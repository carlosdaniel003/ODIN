from __future__ import annotations

"""Referências visuais do F3 usando as máscaras já desenhadas do projeto.

O runtime produtivo do F3 permanece inalterado. Esta camada troca somente a
região das fotos de presença/referência: o antigo recorte retangular perde a
autoridade e a comparação passa a considerar a união das máscaras persistidas em
"Seleção, ajuste e máscara".

Também garante que as telas de configuração recebam um frame válido da câmera e
que as previews de referência desenhem as mesmas máscaras do projeto.
"""

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

import src.platform.display_check_presence_reference as check_module
import src.platform.display_visual_reference_status as visual_module
from src.platform.display_mask_geometry import (
    converter_mascara_legada_para_editor,
    pontos_mascara_display,
)
from src.platform.display_project_repository import (
    normalizar_nome_projeto_display,
    normalizar_resolucao_display,
)


DISPLAY_REFERENCE_ROI_MIN_FRACTION = 0.015
DISPLAY_REFERENCE_ROI_COLOR = "#38BDF8"
DISPLAY_REFERENCE_ROI_VERTICAL_UI_RESERVE = 320
DISPLAY_REFERENCE_ROI_MIN_DRAW_HEIGHT = 220
DISPLAY_REFERENCE_MASK_COMPARE_MODE = "project_mask_union"
DISPLAY_REFERENCE_MASK_PREVIEW_BGR = (248, 189, 56)
DISPLAY_REFERENCE_MASK_PREVIEW_ALPHA = 0.12
DISPLAY_REFERENCE_COMPARE_WIDTH = 360

_PROJECT_MASK_CACHE: dict[tuple, tuple] = {}
_UNION_CACHE: dict[tuple, np.ndarray] = {}


def _valid_frame(frame) -> bool:
    return frame is not None and getattr(frame, "size", 0) > 0


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


def _mask_signature(masks: list[dict]) -> str:
    try:
        return json.dumps(masks, sort_keys=True, separators=(",", ":"), default=str)
    except Exception:
        return repr(masks)


def _repository_signature(repository) -> tuple[int, int]:
    try:
        stat = Path(repository.config_file).stat()
        return int(stat.st_mtime_ns), int(stat.st_size)
    except Exception:
        return 0, 0


def _project_mask_context(repository, project_name: str):
    key = (
        id(repository),
        str(project_name or ""),
        _repository_signature(repository),
    )
    cached = _PROJECT_MASK_CACHE.get(key)
    if cached is not None:
        resolution, masks, signature = cached
        return resolution, list(masks), signature

    try:
        project = repository.carregar_projeto(project_name)
    except Exception:
        project = None
    if not isinstance(project, dict):
        return None, [], ""

    resolution = normalizar_resolucao_display(project.get("master_resolution"))
    masks = tuple(
        deepcopy(mask)
        for mask in (project.get("masks", []) or [])
        if isinstance(mask, dict) and mask.get("id") is not None
    )
    signature = _mask_signature(list(masks))
    if len(_PROJECT_MASK_CACHE) > 8:
        _PROJECT_MASK_CACHE.clear()
    _PROJECT_MASK_CACHE[key] = (resolution, masks, signature)
    return resolution, list(masks), signature


def _decorate_metadata(repository, project_name: str, metadata: dict | None):
    if not isinstance(metadata, dict):
        return metadata
    resolution, masks, signature = _project_mask_context(repository, project_name)
    result = deepcopy(metadata)
    result.pop("roi", None)
    if "masks_reference" in result:
        masks = normalizar_mascaras_display(
            deepcopy(result.get("masks_reference", []))
        )
        signature = _mask_signature(masks)
    else:
        overrides = (
            result.get("mask_overrides_reference", {})
            if isinstance(result.get("mask_overrides_reference"), dict)
            else {}
        )
        if overrides:
            masks = [
                deepcopy(overrides.get(str(mask.get("id") or "")))
                if isinstance(overrides.get(str(mask.get("id") or "")), dict)
                else deepcopy(mask)
                for mask in masks
                if isinstance(mask, dict)
            ]
            signature = _mask_signature(masks)
    result["_display_master_resolution"] = tuple(resolution) if resolution else None
    result["_display_mask_regions"] = masks
    result["_display_mask_signature"] = signature
    result["mask_region_count"] = len(masks)
    result["comparison_mode"] = DISPLAY_REFERENCE_MASK_COMPARE_MODE
    return result


def _encode_jpeg_to_path(path: Path, image) -> bool:
    try:
        ok, encoded = cv2.imencode(
            ".jpg",
            image,
            [cv2.IMWRITE_JPEG_QUALITY, 92],
        )
        if not ok:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded.tobytes())
        return True
    except Exception:
        return False


def _capture_check_reference_fallback(
    store,
    project_name: str,
    check_id: str,
    frame,
    master_resolution,
):
    resolution = normalizar_resolucao_display(master_resolution)
    if resolution is None or not _valid_frame(frame):
        return None
    image = check_module._prepare_bgr(frame, resolution)
    if not _valid_frame(image):
        return None

    project = normalizar_nome_projeto_display(project_name)
    check = check_module._normalizar_check_id(check_id)
    if not project or not check:
        return None

    path = store.image_dir / f"{check_module._slug(project)}_{check_module._slug(check)}.jpg"
    if not _encode_jpeg_to_path(path, image):
        return None

    metadata = {
        "image_path": str(path),
        "threshold": check_module.DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD,
        "width": int(resolution[0]),
        "height": int(resolution[1]),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        data = store._load()
        data["references"][check_module._reference_key(project, check)] = metadata
        store._write(data)
    except Exception:
        return None
    return deepcopy(metadata)


def _capture_project_reference_fallback(
    store,
    project_name: str,
    kind: str,
    frame,
    master_resolution,
):
    project = normalizar_nome_projeto_display(project_name)
    ref_kind = str(kind or "").strip().lower()
    resolution = normalizar_resolucao_display(master_resolution)
    if (
        not project
        or ref_kind not in visual_module.DISPLAY_PROJECT_REFERENCE_TYPES
        or resolution is None
        or not _valid_frame(frame)
    ):
        return None

    image = visual_module._prepare_bgr(frame, resolution)
    if not _valid_frame(image):
        return None
    path = store.image_dir / f"{visual_module._slug(project)}_{ref_kind}.jpg"
    if not _encode_jpeg_to_path(path, image):
        return None

    try:
        data = store._load()
    except Exception:
        return None
    previous = (
        data.get("projects", {}).get(project, {}).get(ref_kind, {})
        if isinstance(data, dict)
        else {}
    )
    metadata = {
        "image_path": str(path),
        "threshold": check_module.DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD,
        "width": int(resolution[0]),
        "height": int(resolution[1]),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    if isinstance(previous, dict):
        for key in ("board_points_reference", "mask_overrides_reference"):
            if previous.get(key):
                metadata[key] = deepcopy(previous[key])
        if "masks_reference" in previous:
            metadata["masks_reference"] = deepcopy(
                previous.get("masks_reference", [])
            )
    try:
        data["projects"].setdefault(project, {})[ref_kind] = metadata
        store._write(data)
    except Exception:
        return None
    return deepcopy(metadata)


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
            if result is None:
                result = _capture_check_reference_fallback(
                    self,
                    project_name,
                    check_id,
                    frame,
                    master_resolution,
                )
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
            if result is None:
                result = _capture_project_reference_fallback(
                    self,
                    project_name,
                    kind,
                    frame,
                    master_resolution,
                )
            return _decorate_metadata(self.repository, project_name, result)

        project_cls.get = get
        project_cls.get_all = get_all
        project_cls.capture = capture
        project_cls._display_mask_regions_installed = True


def _rasterize_single_mask(mask: dict, width: int, height: int) -> np.ndarray | None:
    if not isinstance(mask, dict) or width < 1 or height < 1:
        return None
    item = converter_mascara_legada_para_editor(deepcopy(mask))
    kind = str(item.get("type", "")).lower()
    region = np.zeros((int(height), int(width)), dtype=np.uint8)

    try:
        if kind == "circle":
            cv2.circle(
                region,
                (int(round(item.get("cx", 0))), int(round(item.get("cy", 0)))),
                max(1, int(round(item.get("radius", 1)))),
                255,
                -1,
                cv2.LINE_AA,
            )
            return region if np.any(region) else None

        points = pontos_mascara_display(item)
        if len(points) < 3:
            return None
        polygon = np.asarray(
            [[int(round(x)), int(round(y))] for x, y in points],
            dtype=np.int32,
        )
        cv2.fillPoly(region, [polygon], 255, lineType=cv2.LINE_AA)
        return region if np.any(region) else None
    except Exception:
        return None


def _union_mask(metadata: dict | None, width: int, height: int) -> np.ndarray | None:
    data = metadata if isinstance(metadata, dict) else {}
    masks = [
        mask
        for mask in (data.get("_display_mask_regions", []) or [])
        if isinstance(mask, dict)
    ]
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
        region = _rasterize_single_mask(mask, master_w, master_h)
        if region is not None:
            union = cv2.bitwise_or(union, region)

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
            if reference is None or not _valid_frame(frame):
                return original_check_eval(frame, metadata)
            score = calcular_similaridade_referencia_por_mascaras(reference, frame, metadata)
            if score is None:
                return original_check_eval(frame, metadata)
            try:
                threshold = float(
                    metadata.get(
                        "threshold",
                        check_module.DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD,
                    )
                )
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
            if reference is None or not _valid_frame(frame):
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
    """Desenha cada ROI/máscara individual sobre a foto de referência."""
    if not _valid_frame(image):
        return image
    data = metadata if isinstance(metadata, dict) else {}
    masks = [
        mask
        for mask in (data.get("_display_mask_regions", []) or [])
        if isinstance(mask, dict)
    ]
    if not masks:
        return image

    master = normalizar_resolucao_display(data.get("_display_master_resolution"))
    if master is None:
        master = (int(image.shape[1]), int(image.shape[0]))
    master_w, master_h = int(master[0]), int(master[1])
    image_h, image_w = image.shape[:2]

    result = image.copy()
    union = np.zeros((image_h, image_w), dtype=np.uint8)
    regions: list[np.ndarray] = []
    for mask in masks:
        region = _rasterize_single_mask(mask, master_w, master_h)
        if region is None:
            continue
        if (master_w, master_h) != (image_w, image_h):
            region = cv2.resize(
                region,
                (image_w, image_h),
                interpolation=cv2.INTER_NEAREST,
            )
        if not np.any(region):
            continue
        regions.append(region)
        union = cv2.bitwise_or(union, region)

    if not regions:
        return image

    tint = result.copy()
    tint[union > 0] = DISPLAY_REFERENCE_MASK_PREVIEW_BGR
    result = cv2.addWeighted(
        tint,
        DISPLAY_REFERENCE_MASK_PREVIEW_ALPHA,
        result,
        1.0 - DISPLAY_REFERENCE_MASK_PREVIEW_ALPHA,
        0.0,
    )

    # Contorno por máscara, não apenas o contorno externo da união. Assim cada
    # segmento continua visível mesmo quando duas ROIs se encostam.
    for region in regions:
        contours, _ = cv2.findContours(
            region,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        if contours:
            cv2.drawContours(
                result,
                contours,
                -1,
                DISPLAY_REFERENCE_MASK_PREVIEW_BGR,
                2,
                cv2.LINE_AA,
            )
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


def _install_config_frame_provider() -> None:
    """Entrega ao editor/captura um frame real sem tocar no loop de produção."""
    try:
        import src.platform.display_production_f3 as production_module
    except Exception:
        return

    cls = production_module.DisplayProductionF3Mixin
    if bool(getattr(cls, "_display_f3_config_frame_fallback_installed", False)):
        return
    original_get = cls._obter_frame_para_configuracao_display

    def get_frame(self):
        candidates = (
            getattr(self, "camera_frame_atual", None),
            getattr(self, "imagem_original", None),
            getattr(self, "_display_f3_last_config_frame", None),
        )
        for frame in candidates:
            if not _valid_frame(frame):
                continue
            try:
                copied = frame.copy()
            except Exception:
                copied = frame
            self._display_f3_last_config_frame = copied
            try:
                return copied.copy()
            except Exception:
                return copied

        # Último recurso: solicita um snapshot atual diretamente ao serviço.
        # Isto só ocorre quando o usuário abre/captura uma configuração; não é
        # executado no callback contínuo do preview F3.
        service = getattr(self, "camera_service", None)
        if service is not None:
            try:
                snapshot = service.obter_snapshot(-1)
                frame = getattr(snapshot, "frame", None)
            except Exception:
                frame = None
            if _valid_frame(frame):
                try:
                    copied = frame.copy()
                except Exception:
                    copied = frame
                self._display_f3_last_config_frame = copied
                try:
                    return copied.copy()
                except Exception:
                    return copied

        try:
            frame = original_get(self)
        except Exception:
            frame = None
        if _valid_frame(frame):
            try:
                self._display_f3_last_config_frame = frame.copy()
            except Exception:
                self._display_f3_last_config_frame = frame
        return frame

    cls._obter_frame_para_configuracao_display = get_frame
    cls._display_f3_config_frame_fallback_installed = True


def instalar_roi_referencias_display_f3() -> None:
    """Troca somente a ROI das referências e corrige previews de configuração."""
    _install_config_frame_provider()
    _install_store_masks()
    _install_matchers_masks()
    _install_preview_masks()
