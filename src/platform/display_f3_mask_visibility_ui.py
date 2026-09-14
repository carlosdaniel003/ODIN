from __future__ import annotations

"""Ajustes puramente visuais para as máscaras do Display F3.

Esta camada resolve duas necessidades de interface sem alterar classificação,
OK/NG, sequência de CHECKS ou leitura da câmera:

1. Ao abrir o F3, a geometria das máscaras já fica visível antes da primeira
   classificação. Nesse período ela aparece somente como contorno neutro claro,
   sem preencher a ROI e sem afirmar ACESO/APAGADO. Assim preservamos a proteção
   que impede o H1 inteiro de ficar vermelho enquanto a placa ainda está
   desligada/inicializando.
2. No editor visual de máscaras, cada ROI exibe o número derivado do seu ID
   (MASK_001 -> 1, MASK_026 -> 26), facilitando identificar qual segmento está
   sendo ajustado.

Não existe timer, segunda leitura de câmera ou nova análise nesta camada.
"""

import re

import cv2

import src.platform.display_f3_preview_clarity_fix as clarity_module
import src.platform.display_live_roi_overlay as overlay_module
import src.platform.display_mask_editor as editor_module
from src.platform.display_mask_geometry import _id, bbox_mascara_display


# Contorno de geometria, não estado de análise. Branco frio para não competir
# com as três cores semânticas da produção (verde/vermelho/amarelo).
F3_PREVIEW_STARTUP_GUIDE_BGR = (240, 232, 226)  # RGB #E2E8F0
F3_PREVIEW_STARTUP_GUIDE_THICKNESS = 2

# Mantemos uma referência imutável do renderer semântico. O instalador abaixo
# apenas o complementa com os contornos que ele deliberadamente omite antes de
# existir evidência de segmento ACESO.
_BASE_CLEAR_RENDERER = clarity_module.renderizar_preview_claro_display_f3

_MASK_NUMBER_RE = re.compile(r"(\d+)$")


def numero_visual_mascara_display_f3(mask: dict | None) -> str:
    """Retorna o número estável do ID da máscara para exibição no editor."""
    if not isinstance(mask, dict):
        return ""
    mask_id = str(_id(mask) or "").strip()
    if not mask_id:
        return ""
    match = _MASK_NUMBER_RE.search(mask_id)
    if match is None:
        return mask_id
    try:
        return str(int(match.group(1)))
    except (TypeError, ValueError):
        return match.group(1)


def centro_visual_mascara_display_f3(mask: dict | None) -> tuple[float, float] | None:
    """Centro do bbox em coordenadas mestre; funciona para todos os tipos F3."""
    if not isinstance(mask, dict):
        return None
    try:
        x1, y1, x2, y2 = bbox_mascara_display(mask)
    except Exception:
        return None
    return (
        (float(x1) + float(x2)) / 2.0,
        (float(y1) + float(y2)) / 2.0,
    )


def _draw_guide_contour(result, mask: dict, sx: float, sy: float) -> None:
    kind = str(mask.get("type") or "").lower()
    color = F3_PREVIEW_STARTUP_GUIDE_BGR
    thickness = F3_PREVIEW_STARTUP_GUIDE_THICKNESS

    if kind == "circle":
        center = (
            int(round(float(mask.get("cx", 0)) * sx)),
            int(round(float(mask.get("cy", 0)) * sy)),
        )
        axes = (
            max(1, int(round(float(mask.get("radius", 1)) * sx))),
            max(1, int(round(float(mask.get("radius", 1)) * sy))),
        )
        cv2.ellipse(
            result,
            center,
            axes,
            0,
            0,
            360,
            color,
            thickness,
            cv2.LINE_AA,
        )
        return

    polygon = overlay_module._scaled_polygon(mask, sx, sy)
    if polygon is None or len(polygon) < 3:
        return
    cv2.polylines(
        result,
        [polygon],
        True,
        color,
        thickness,
        cv2.LINE_AA,
    )


def renderizar_preview_com_guias_inicio_f3(frame, context):
    """Mantém máscaras visíveis desde o primeiro frame, sem inventar estado.

    A camada semântica continua sendo a autoridade visual. Só desenhamos o
    contorno neutro das máscaras para as quais ela ainda não possui uma
    apresentação válida. Não há preenchimento neutro.
    """
    result = _BASE_CLEAR_RENDERER(frame, context)
    if frame is None or getattr(frame, "size", 0) == 0:
        return result
    if not isinstance(context, dict):
        return result

    resolution = context.get("resolution")
    masks = tuple(context.get("masks") or ())
    if (
        not isinstance(resolution, (list, tuple))
        or len(resolution) < 2
        or not masks
    ):
        return result

    source_width = max(1, int(resolution[0]))
    source_height = max(1, int(resolution[1]))
    frame_height, frame_width = frame.shape[:2]
    sx = frame_width / float(source_width)
    sy = frame_height / float(source_height)

    classifications = {
        str(key): str(value).strip().lower()
        for key, value in dict(context.get("classifications") or {}).items()
    }
    expected_states = {
        str(key): str(value).strip().lower()
        for key, value in dict(context.get("expected_states") or {}).items()
    }
    failed_mask_ids = {
        str(mask_id)
        for mask_id in (context.get("failed_mask_ids") or ())
        if str(mask_id)
    }
    failed_mask_ids.update(
        str(mask_id)
        for mask_id in dict(context.get("failed_masks") or {}).keys()
        if str(mask_id)
    )
    has_any_on = bool(
        context.get("has_any_on")
        or any(
            state == "on"
            for state in classifications.values()
        )
    )

    for mask in masks:
        if not isinstance(mask, dict):
            continue
        mask_id = str(mask.get("id") or "")
        presentation = clarity_module.estado_visual_mascara_f3(
            classifications.get(mask_id),
            expected_states.get(mask_id),
            has_any_on=has_any_on,
        )
        if mask_id in failed_mask_ids and has_any_on:
            presentation = "alert"

        # A máscara já ganhou verde/vermelho/amarelo pelo renderer semântico.
        if presentation is not None:
            continue

        # Ainda sem decisão visual: mostramos só a geometria, nunca um estado.
        _draw_guide_contour(result, mask, sx, sy)

    return result


def instalar_guias_mascaras_inicio_display_f3() -> None:
    """Reafirma o renderer com guia neutra; seguro chamar mais de uma vez."""
    overlay_module.renderizar_overlay_rois_display_f3 = (
        renderizar_preview_com_guias_inicio_f3
    )
    overlay_module._display_f3_startup_mask_guides_installed = True


def instalar_numeros_editor_mascaras_display_f3() -> None:
    """Adiciona número legível a cada máscara apenas no editor visual F3."""
    cls = editor_module.DisplayMaskEditorWindow
    if bool(getattr(cls, "_odin_display_f3_mask_numbers", False)):
        return

    original_draw_mask = cls._draw_mask

    def draw_mask_with_number(self, mask):
        result = original_draw_mask(self, mask)
        label = numero_visual_mascara_display_f3(mask)
        center = centro_visual_mascara_display_f3(mask)
        if not label or center is None:
            return result

        try:
            x, y = self._to_canvas(*center)
        except Exception:
            return result

        selected = str(_id(mask) or "") in getattr(self, "selected_ids", set())
        foreground = self.SEL if selected else "#F8FAFC"
        font = ("DejaVu Sans", 9, "bold")

        # Sombra simples evita que o número desapareça sobre segmentos claros,
        # sem criar badge/pill ou bloco opaco sobre a imagem.
        self.canvas.create_text(
            x + 1,
            y + 1,
            text=label,
            fill="#020617",
            font=font,
            tags=("display-mask-number",),
        )
        self.canvas.create_text(
            x,
            y,
            text=label,
            fill=foreground,
            font=font,
            tags=("display-mask-number",),
        )
        return result

    cls._draw_mask = draw_mask_with_number
    cls._odin_display_f3_mask_numbers = True
