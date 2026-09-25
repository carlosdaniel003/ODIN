from __future__ import annotations

"""Serviço de previews da configuração do Display F3.

Responsabilidade única:
- executar OpenCV e leitura/decodificação de imagens fora do thread do Tk;
- manter somente o pedido mais recente por tipo de preview;
- devolver para a UI somente dados já preparados para PhotoImage.

O serviço não cria nem manipula widgets Tkinter.
"""

import base64
import queue
from concurrent.futures import CancelledError
from dataclasses import dataclass
from pathlib import Path

import cv2

from src.platform.display_f3_heavy_executor import F3HeavyWorkPriority


F3_CONFIG_PREVIEW_CACHE_LIMIT = 32
F3_CONFIG_PREVIEW_RESULT_LIMIT = 8


@dataclass(frozen=True)
class DisplayF3ConfigPreviewResult:
    key: str
    generation: int
    kind: str
    payload: dict
    error: str = ""


def _valid_image(image) -> bool:
    return image is not None and getattr(image, "size", 0) > 0


def _file_signature(path) -> tuple[int, int]:
    try:
        stat = Path(path).stat()
        return int(stat.st_mtime_ns), int(stat.st_size)
    except (OSError, TypeError, ValueError):
        return 0, 0


def _photo_data(image) -> str | None:
    if not _valid_image(image):
        return None
    ok, buffer = cv2.imencode(
        ".png",
        image,
        [cv2.IMWRITE_PNG_COMPRESSION, 1],
    )
    if not ok:
        return None
    return base64.b64encode(buffer).decode("ascii")


def _fit_image(image, width: int, height: int):
    if not _valid_image(image):
        return None
    source_h, source_w = image.shape[:2]
    target_w = max(1, int(width))
    target_h = max(1, int(height))
    scale = min(
        target_w / max(1.0, float(source_w)),
        target_h / max(1.0, float(source_h)),
    )
    rendered_w = max(1, int(round(source_w * scale)))
    rendered_h = max(1, int(round(source_h * scale)))
    return cv2.resize(
        image,
        (rendered_w, rendered_h),
        interpolation=cv2.INTER_AREA,
    )


class DisplayF3ConfigPreviewService:
    """Previews de configuração submetidas ao executor pesado canônico."""

    def __init__(self, executor) -> None:
        if executor is None:
            raise ValueError("DisplayF3ConfigPreviewService requer heavy executor.")
        self._executor = executor
        self._result_queue: queue.Queue = queue.Queue(
            maxsize=F3_CONFIG_PREVIEW_RESULT_LIMIT
        )
        self._stopped = False
        self._owner = f"f3-config-preview:{id(self)}"
        self._cache: dict[tuple, dict] = {}

    @staticmethod
    def _build_result(request: dict) -> DisplayF3ConfigPreviewResult:
        error = ""
        payload = {}
        try:
            payload = request["renderer"](request["payload"])
            if not isinstance(payload, dict):
                payload = {}
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        return DisplayF3ConfigPreviewResult(
            key=str(request["key"]),
            generation=int(request["generation"]),
            kind=str(request["kind"]),
            payload=payload,
            error=error,
        )

    def _publish_result(self, result: DisplayF3ConfigPreviewResult) -> None:
        if self._stopped:
            return
        try:
            self._result_queue.put_nowait(result)
            return
        except queue.Full:
            pass
        try:
            self._result_queue.get_nowait()
        except queue.Empty:
            return
        try:
            self._result_queue.put_nowait(result)
        except queue.Full:
            return

    def _submit(
        self,
        *,
        key: str,
        generation: int,
        kind: str,
        renderer,
        payload: dict,
    ) -> None:
        if self._stopped:
            return
        request = {
            "key": str(key),
            "generation": int(generation),
            "kind": str(kind),
            "renderer": renderer,
            "payload": payload,
        }
        future = self._executor.submit(
            lambda current=request: self._build_result(current),
            priority=F3HeavyWorkPriority.LOW,
            name=f"config-preview:{kind}",
            owner=self._owner,
            key=str(key),
            replace_pending=True,
        )

        def completed(done) -> None:
            if done.cancelled() or self._stopped:
                return
            try:
                result = done.result()
            except CancelledError:
                return
            except Exception as exc:
                result = DisplayF3ConfigPreviewResult(
                    key=str(key),
                    generation=int(generation),
                    kind=str(kind),
                    payload={},
                    error=f"{type(exc).__name__}: {exc}",
                )
            self._publish_result(result)

        future.add_done_callback(completed)

    def submit_mask_reference_preview(
        self,
        *,
        generation: int,
        repository,
        project_name: str,
        project: dict,
        visual_rotation: int,
        target_width: int,
        target_height: int,
    ) -> str:
        key = "mask_reference"
        self._submit(
            key=key,
            generation=generation,
            kind="mask_reference_preview",
            renderer=self._render_mask_reference_preview,
            payload={
                "repository": repository,
                "project_name": str(project_name or ""),
                "project": project,
                "visual_rotation": int(visual_rotation or 0),
                "target_width": int(target_width),
                "target_height": int(target_height),
            },
        )
        return key

    def submit_presence_reference_preview(
        self,
        *,
        generation: int,
        project_name: str,
        reference_kind: str,
        metadata: dict,
        target_width: int = 170,
        target_height: int = 78,
    ) -> str:
        key = f"presence_reference:{reference_kind}"
        self._submit(
            key=key,
            generation=generation,
            kind="presence_reference_preview",
            renderer=self._render_presence_reference_preview,
            payload={
                "project_name": str(project_name or ""),
                "reference_kind": str(reference_kind or ""),
                "metadata": dict(metadata or {}),
                "target_width": int(target_width),
                "target_height": int(target_height),
            },
        )
        return key

    def poll_results(self, max_items: int = 16) -> list[DisplayF3ConfigPreviewResult]:
        results = []
        for _ in range(max(1, int(max_items))):
            try:
                results.append(self._result_queue.get_nowait())
            except queue.Empty:
                break
        return results

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._executor.cancel_owner(self._owner)

    def _cache_get(self, key: tuple) -> dict | None:
        value = self._cache.get(key)
        return dict(value) if isinstance(value, dict) else None

    def _cache_put(self, key: tuple, value: dict) -> None:
        self._cache[key] = dict(value)
        while len(self._cache) > F3_CONFIG_PREVIEW_CACHE_LIMIT:
            try:
                oldest = next(iter(self._cache))
            except StopIteration:
                break
            self._cache.pop(oldest, None)

    def _render_presence_reference_preview(self, request: dict) -> dict:
        metadata = request.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        path = Path(str(metadata.get("image_path") or ""))
        if not path.is_file():
            return {
                "available": False,
                "reason": "file_missing",
                "project_name": str(request.get("project_name") or ""),
                "reference_kind": str(request.get("reference_kind") or ""),
            }

        target_width = max(1, int(request.get("target_width", 170) or 170))
        target_height = max(1, int(request.get("target_height", 78) or 78))
        cache_key = (
            "presence",
            str(path),
            _file_signature(path),
            target_width,
            target_height,
        )
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if not _valid_image(image):
            return {
                "available": False,
                "reason": "image_invalid",
                "project_name": str(request.get("project_name") or ""),
                "reference_kind": str(request.get("reference_kind") or ""),
            }
        resized = _fit_image(image, target_width, target_height)
        photo_data = _photo_data(resized)
        if not photo_data:
            raise ValueError("presence preview encode failed")

        result = {
            "available": True,
            "project_name": str(request.get("project_name") or ""),
            "reference_kind": str(request.get("reference_kind") or ""),
            "photo_data": photo_data,
            "width": int(metadata.get("width", image.shape[1]) or image.shape[1]),
            "height": int(metadata.get("height", image.shape[0]) or image.shape[0]),
            "rendered_width": int(resized.shape[1]),
            "rendered_height": int(resized.shape[0]),
        }
        self._cache_put(cache_key, result)
        return result

    def _render_mask_reference_preview(self, request: dict) -> dict:
        from src.platform.display_f3_mask_editor_reference import (
            DisplayMaskEditorReferenceStore,
        )
        from src.platform.display_f3_object_tracking import (
            F3TrackingConfigStore,
            canonical_board_points,
            draw_reference_geometry,
            transform_mask,
            transform_points,
        )
        from src.platform.display_project_repository import (
            normalizar_resolucao_display,
        )
        from src.platform.display_visual_rotation import (
            preparar_check_visual_display,
            preparar_pontos_visuais_display,
        )

        repository = request.get("repository")
        project_name = str(request.get("project_name") or "")
        project = request.get("project")
        project = project if isinstance(project, dict) else {}
        metadata = DisplayMaskEditorReferenceStore(repository).get(project_name)
        if not isinstance(metadata, dict):
            return {
                "available": False,
                "reason": "no_reference",
                "project_name": project_name,
            }

        path = Path(str(metadata.get("image_path") or ""))
        if not path.is_file():
            return {
                "available": False,
                "reason": "file_missing",
                "project_name": project_name,
            }

        master_resolution = normalizar_resolucao_display(
            project.get("master_resolution")
        )
        if master_resolution is None:
            return {
                "available": False,
                "reason": "invalid_master_resolution",
                "project_name": project_name,
            }

        visual_rotation = int(request.get("visual_rotation", 0) or 0) % 360
        target_width = max(120, int(request.get("target_width", 360) or 360))
        target_height = max(90, int(request.get("target_height", 150) or 150))
        tracking_store = F3TrackingConfigStore(repository)
        tracking_signature = _file_signature(
            getattr(tracking_store, "config_file", "")
        )
        cache_key = (
            "mask",
            project_name,
            str(path),
            _file_signature(path),
            str(project.get("updated_at") or ""),
            tracking_signature,
            visual_rotation,
            target_width,
            target_height,
        )
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if not _valid_image(frame):
            return {
                "available": False,
                "reason": "image_invalid",
                "project_name": project_name,
            }

        frame_visual, visual_resolution, masks_visual = preparar_check_visual_display(
            frame,
            master_resolution,
            project.get("masks", []),
            visual_rotation,
        )
        board_master = canonical_board_points(project, tracking_store)
        board_visual = preparar_pontos_visuais_display(
            board_master,
            master_resolution[0],
            master_resolution[1],
            visual_rotation,
        )

        source_h, source_w = frame_visual.shape[:2]
        scale = min(
            max(1, target_width - 12) / max(1.0, float(source_w)),
            max(1, target_height - 12) / max(1.0, float(source_h)),
        )
        rendered_w = max(1, int(round(source_w * scale)))
        rendered_h = max(1, int(round(source_h * scale)))
        thumbnail = cv2.resize(
            frame_visual,
            (rendered_w, rendered_h),
            interpolation=cv2.INTER_AREA,
        )
        matrix = (
            (scale, 0.0, 0.0),
            (0.0, scale, 0.0),
        )
        board_preview = transform_points(board_visual, matrix)
        masks_preview = [
            transform_mask(mask, matrix)
            for mask in (masks_visual or [])
            if isinstance(mask, dict)
        ]
        thumbnail = draw_reference_geometry(
            thumbnail,
            board_preview,
            [mask for mask in masks_preview if mask is not None],
            alpha=0.74,
        )
        photo_data = _photo_data(thumbnail)
        if not photo_data:
            raise ValueError("mask preview encode failed")

        result = {
            "available": True,
            "project_name": project_name,
            "photo_data": photo_data,
            "source_width": int(source_w),
            "source_height": int(source_h),
            "rendered_width": int(rendered_w),
            "rendered_height": int(rendered_h),
            "mask_count": len(project.get("masks", []) or []),
            "visual_rotation": visual_rotation,
        }
        self._cache_put(cache_key, result)
        return result
