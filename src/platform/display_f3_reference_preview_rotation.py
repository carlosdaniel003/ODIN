from __future__ import annotations

"""Preview rotacionada das referências físicas do Display F3.

As imagens persistidas continuam no referencial original da câmera. Na UI,
foto e máscaras do Projeto Display são convertidas juntas para a orientação
visual atual e as mesmas máscaras já desenhadas em "Seleção, ajuste e máscara"
são sobrepostas às miniaturas de presença/referência.

Esta camada não altera captura, classificação, loop produtivo ou F2.
"""

from copy import deepcopy
from pathlib import Path

import cv2
import tkinter as tk

import src.platform.display_check_presence_reference as check_module
import src.platform.display_reference_roi as roi_module
import src.platform.display_visual_reference_status as visual_module
from src.platform.display_project_repository import normalizar_resolucao_display
from src.platform.display_visual_rotation import (
    obter_rotacao_visual_do_frame_provider,
    preparar_check_visual_display,
    preparar_frame_visual_display,
    preparar_pontos_visuais_display,
)
from src.ui.main_window_parts.image.rotacao_visual_principal import (
    normalizar_rotacao_visual,
)


F3_REFERENCE_ROI_COLOR = roi_module.DISPLAY_REFERENCE_ROI_COLOR


def transformar_roi_referencia_visual_f3(roi, rotacao: int) -> dict | None:
    """Compatibilidade histórica para metadados antigos com ROI retangular."""
    normalized = roi_module.normalizar_roi_referencia(roi)
    if normalized is None:
        return None
    angle = normalizar_rotacao_visual(rotacao)
    x = float(normalized["x"])
    y = float(normalized["y"])
    width = float(normalized["width"])
    height = float(normalized["height"])

    if angle == 90:
        value = {
            "x": 1.0 - (y + height),
            "y": x,
            "width": height,
            "height": width,
        }
    elif angle == 180:
        value = {
            "x": 1.0 - (x + width),
            "y": 1.0 - (y + height),
            "width": width,
            "height": height,
        }
    elif angle == 270:
        value = {
            "x": y,
            "y": 1.0 - (x + width),
            "width": height,
            "height": width,
        }
    else:
        value = normalized
    return roi_module.normalizar_roi_referencia(value)


def restaurar_roi_referencia_original_f3(roi_visual, rotacao: int) -> dict | None:
    angle = normalizar_rotacao_visual(rotacao)
    return transformar_roi_referencia_visual_f3(
        roi_visual,
        (360 - angle) % 360,
    )


def _rotation(owner) -> int:
    provider = getattr(owner, "frame_provider", None)
    if provider is None:
        return 0
    try:
        return obter_rotacao_visual_do_frame_provider(provider)
    except Exception:
        return 0


def preparar_preview_referencia_visual_f3(image, rotacao: int):
    if image is None or getattr(image, "size", 0) == 0:
        return image
    return preparar_frame_visual_display(
        image,
        normalizar_rotacao_visual(rotacao),
    )


def _metadata_com_mascaras_do_projeto(
    repository,
    project_name: str,
    metadata: dict | None,
) -> dict:
    """Garante que o renderer final receba as máscaras mesmo sem wrappers prévios."""
    result = deepcopy(metadata) if isinstance(metadata, dict) else {}
    try:
        project = repository.carregar_projeto(project_name)
    except Exception:
        project = None
    if not isinstance(project, dict):
        return result

    resolution = normalizar_resolucao_display(project.get("master_resolution"))
    if "masks_reference" in result:
        masks = normalizar_mascaras_display(
            deepcopy(result.get("masks_reference", []))
        )
    else:
        overrides = (
            result.get("mask_overrides_reference", {})
            if isinstance(result.get("mask_overrides_reference"), dict)
            else {}
        )
        masks = []
        for mask in (project.get("masks", []) or []):
            if not isinstance(mask, dict) or mask.get("id") is None:
                continue
            mask_id = str(mask.get("id"))
            override = overrides.get(mask_id)
            masks.append(
                deepcopy(override)
                if isinstance(override, dict)
                else deepcopy(mask)
            )
    if resolution is not None:
        result["_display_master_resolution"] = tuple(resolution)
    result["_display_mask_regions"] = masks
    result["mask_region_count"] = len(masks)
    board = result.get("board_points_reference", [])
    if not (isinstance(board, (list, tuple)) and len(board) >= 3):
        # PLACA FORA DO SUPORTE não possui ajuste geométrico próprio, mas sua
        # preview deve mostrar a mesma geometria canônica do projeto usada em
        # "Máscaras". PLACA DESLIGADA continua preferindo seu contorno local.
        try:
            from src.platform.display_f3_object_tracking import (
                F3TrackingConfigStore,
                canonical_board_points,
            )
            board = canonical_board_points(
                project,
                F3TrackingConfigStore(repository),
            )
        except Exception:
            board = []
    if isinstance(board, (list, tuple)) and len(board) >= 3:
        result["_display_board_points_reference"] = deepcopy(board)
    result["comparison_mode"] = roi_module.DISPLAY_REFERENCE_MASK_COMPARE_MODE
    return result


def _fit_preview(image, target_width: int, target_height: int):
    if image is None or getattr(image, "size", 0) == 0:
        return image
    height, width = image.shape[:2]
    if width <= 0 or height <= 0:
        return image
    scale = min(
        max(1, int(target_width)) / float(width),
        max(1, int(target_height)) / float(height),
    )
    final_width = max(1, int(round(width * scale)))
    final_height = max(1, int(round(height * scale)))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    return cv2.resize(
        image,
        (final_width, final_height),
        interpolation=interpolation,
    )


def preparar_preview_referencia_com_mascaras_f3(
    *,
    image_raw,
    metadata: dict | None,
    repository,
    project_name: str,
    rotacao: int,
    target_width: int,
    target_height: int,
):
    """Miniatura de presença com o MESMO visual da preview de Máscaras.

    Tanto PLACA DESLIGADA NO SUPORTE quanto PLACA FORA DO SUPORTE exibem:
    - foto estática da referência;
    - contorno da placa;
    - segmentos/círculos/demais máscaras do Projeto Display.

    A referência de placa desligada pode ter ajustes locais; suporte vazio usa
    a geometria canônica do projeto. A foto é reduzida antes dos overlays, para
    os traços não virarem um bloco espesso na miniatura.
    """
    if image_raw is None or getattr(image_raw, "size", 0) == 0:
        return image_raw, 0

    enriched = _metadata_com_mascaras_do_projeto(
        repository,
        project_name,
        metadata,
    )
    masks = list(enriched.get("_display_mask_regions", []) or [])
    board_original = list(
        enriched.get("_display_board_points_reference", []) or []
    )
    resolution = normalizar_resolucao_display(
        enriched.get("_display_master_resolution")
    )
    angle = normalizar_rotacao_visual(rotacao)

    if resolution is not None:
        image_visual, visual_resolution, visual_masks = preparar_check_visual_display(
            image_raw,
            resolution,
            masks,
            angle,
        )
        visual_board = preparar_pontos_visuais_display(
            board_original,
            int(resolution[0]),
            int(resolution[1]),
            angle,
        ) if len(board_original) >= 3 else []
    else:
        image_visual = preparar_preview_referencia_visual_f3(image_raw, angle)
        visual_masks = masks
        visual_board = board_original
        visual_resolution = (
            (image_visual.shape[1], image_visual.shape[0])
            if image_visual is not None and getattr(image_visual, "size", 0)
            else (1, 1)
        )

    preview = _fit_preview(image_visual, target_width, target_height)
    if preview is None or getattr(preview, "size", 0) == 0:
        return preview, len(visual_masks)

    source_w = max(1.0, float(visual_resolution[0]))
    source_h = max(1.0, float(visual_resolution[1]))
    ph, pw = preview.shape[:2]
    sx = pw / source_w
    sy = ph / source_h

    try:
        from src.platform.display_f3_object_tracking import (
            transform_mask,
            transform_points,
        )
        from src.platform.display_f3_tracking_orientation_ui import (
            draw_reference_geometry,
        )

        matrix = (
            (sx, 0.0, 0.0),
            (0.0, sy, 0.0),
        )
        board_preview = (
            transform_points(visual_board, matrix)
            if len(visual_board) >= 3
            else []
        )
        masks_preview = [
            transform_mask(mask, matrix)
            for mask in visual_masks
            if isinstance(mask, dict)
        ]
        preview = draw_reference_geometry(
            preview,
            board_preview,
            [mask for mask in masks_preview if mask is not None],
            alpha=0.74,
            board_thickness=2,
            mask_thickness=1,
        )
    except Exception:
        # A foto continua útil mesmo se um overlay legado estiver inválido.
        pass

    return preview, len(visual_masks)


def _install_project_reference_preview() -> None:
    cls = visual_module.DisplayProjectConfigPresenceWindow
    if bool(getattr(cls, "_display_f3_reference_preview_rotation", False)):
        return

    def update_detail(self) -> None:
        store = getattr(self, "_project_presence_store", None)
        if store is None:
            return
        project_name = self._selected_name()
        angle = _rotation(self)
        self._project_presence_photos.clear()
        labels = getattr(self, "_project_presence_roi_labels", {})

        for kind in visual_module.DISPLAY_PROJECT_REFERENCE_TYPES:
            canvas = self._project_presence_canvases.get(kind)
            status = self._project_presence_status.get(kind)
            roi_label = labels.get(kind)
            if canvas is None or status is None:
                continue
            canvas.delete("all")
            metadata = store.get(project_name or "", kind) if project_name else None
            if metadata is None:
                canvas.create_text(
                    87,
                    41,
                    text="SEM FOTO",
                    fill="#64748B",
                    font=("Segoe UI", 8, "bold"),
                )
                status.configure(text="SEM REFERÊNCIA", fg=self.MUTED)
                if roi_label is not None:
                    roi_label.configure(text="MÁSCARAS DO PROJETO", fg="#94A3B8")
                continue

            path = Path(str(metadata.get("image_path") or ""))
            image_raw = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.exists() else None
            if image_raw is None:
                canvas.create_text(
                    87,
                    41,
                    text="ARQUIVO AUSENTE",
                    fill="#FCA5A5",
                    font=("Segoe UI", 7, "bold"),
                )
                status.configure(text="ARQUIVO AUSENTE", fg="#FCA5A5")
                continue

            preview, mask_count = preparar_preview_referencia_com_mascaras_f3(
                image_raw=image_raw,
                metadata=metadata,
                repository=self.repository,
                project_name=project_name,
                rotacao=angle,
                target_width=170,
                target_height=78,
            )
            photo = visual_module._photo_from_image(preview, 170, 78)
            if photo is not None:
                self._project_presence_photos[kind] = photo
                canvas.create_image(87, 41, image=photo, anchor=tk.CENTER)

            if roi_label is not None:
                roi_label.configure(
                    text=f"MÁSCARAS DO PROJETO • {mask_count}",
                    fg=F3_REFERENCE_ROI_COLOR if mask_count else "#94A3B8",
                )
            status.configure(
                text=(
                    f"ATIVA • ROI {mask_count} máscara(s) • "
                    f"{int(metadata.get('width', 0))}x"
                    f"{int(metadata.get('height', 0))} • VISUAL {angle}°"
                ),
                fg="#86EFAC" if mask_count else "#FDE68A",
            )

    # O seletor retangular deixou de ter autoridade. A UI atual não oferece esse
    # botão; manter o método como no-op evita que atalhos antigos reabram o recorte.
    def select_roi(self, kind: str) -> None:
        del self, kind
        return None

    cls._update_project_presence_detail = update_detail
    cls.select_project_presence_reference_roi = select_roi
    cls._display_f3_reference_preview_rotation = True


def _install_check_reference_preview() -> None:
    cls = check_module.DisplayCheckManagerPresenceWindow
    if bool(getattr(cls, "_display_f3_reference_preview_rotation", False)):
        return

    def update_detail(self) -> None:
        canvas = getattr(self, "reference_canvas", None)
        status = getattr(self, "reference_status", None)
        store = getattr(self, "_presence_store", None)
        if canvas is None or status is None or store is None:
            return
        canvas.delete("all")
        self._presence_photo = None
        check_id = self._selected_id()
        if not check_id:
            status.configure(text="Selecione um CHECK.", fg=self.MUTED)
            return

        metadata = store.get(self.project_name, check_id)
        if metadata is not None:
            metadata = deepcopy(metadata)
            try:
                check = self.repository.carregar_check(
                    self.project_name,
                    check_id,
                )
            except Exception:
                check = None
            if isinstance(check, dict):
                if check.get("board_points_reference"):
                    metadata["board_points_reference"] = deepcopy(
                        check.get("board_points_reference")
                    )
                if isinstance(check.get("mask_overrides_reference"), dict):
                    metadata["mask_overrides_reference"] = deepcopy(
                        check.get("mask_overrides_reference")
                    )
        if metadata is None:
            status.configure(text="Nenhuma referência visual anexada.", fg=self.MUTED)
            canvas.create_text(
                165,
                46,
                text="SEM REFERÊNCIA",
                fill="#64748B",
                font=("Segoe UI", 9, "bold"),
            )
            label = getattr(self, "reference_roi_status", None)
            if label is not None:
                label.configure(text="MÁSCARAS DO PROJETO", fg="#94A3B8")
            return

        path = Path(str(metadata.get("image_path") or ""))
        image_raw = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.exists() else None
        if image_raw is None:
            status.configure(
                text="Referência configurada, mas o arquivo de imagem não foi encontrado.",
                fg="#FCA5A5",
            )
            canvas.create_text(
                165,
                46,
                text="ARQUIVO AUSENTE",
                fill="#FCA5A5",
                font=("Segoe UI", 9, "bold"),
            )
            return

        angle = _rotation(self)
        preview, mask_count = preparar_preview_referencia_com_mascaras_f3(
            image_raw=image_raw,
            metadata=metadata,
            repository=self.repository,
            project_name=self.project_name,
            rotacao=angle,
            target_width=326,
            target_height=88,
        )
        photo = self._photo_from_image(preview, 326, 88)
        if photo is not None:
            self._presence_photo = photo
            canvas.create_image(165, 46, image=photo, anchor=tk.CENTER)

        label = getattr(self, "reference_roi_status", None)
        if label is not None:
            label.configure(
                text=f"MÁSCARAS DO PROJETO • {mask_count}",
                fg=F3_REFERENCE_ROI_COLOR if mask_count else "#94A3B8",
            )
        threshold = float(
            metadata.get(
                "threshold",
                check_module.DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD,
            )
        )
        status.configure(
            text=(
                f"Referência ativa • ROI: {mask_count} máscara(s) • "
                f"mínimo {threshold * 100:.0f}% • "
                f"{int(metadata.get('width', 0))}x{int(metadata.get('height', 0))} • "
                f"VISUAL {angle}°"
            ),
            fg="#86EFAC" if mask_count else "#FDE68A",
        )

    def select_roi(self) -> None:
        del self
        return None

    cls._update_presence_detail = update_detail
    cls.select_presence_reference_roi = select_roi
    cls._display_f3_reference_preview_rotation = True


def instalar_rotacao_preview_referencias_display_f3() -> None:
    _install_project_reference_preview()
    _install_check_reference_preview()
