from __future__ import annotations

"""Preview visual simples e legível para o Display F3.

Esta camada altera somente a apresentação das máscaras sobre a câmera do F3.
A classificação, a decisão OK/NG, o debounce e o fluxo produtivo continuam sob
as autoridades já instaladas.

Regra visual final:
- verde: segmento classificado como ACESO e coerente com o CHECK;
- vermelho: segmento classificado como APAGADO e coerente com o CHECK;
- amarelo: POUCA LUZ ou divergência ACESO/APAGADO contra o CHECK;
- nenhuma cor cinza/azul e nenhum texto "NG MASK_xxx" sobre a imagem;
- enquanto nenhum segmento ACESO foi reconhecido, segmentos APAGADOS não são
  pintados. Isso evita abrir o F3 com o H1 inteiro vermelho antes de a placa
  realmente acender.

A geometria das máscaras não depende de existir uma análise produtiva naquele
exato instante. Ela vem diretamente do Projeto Display ativo. A classificação
usa somente análises do CHECK lógico atual e possui fallbacks para o cache de
overlay e para a última sonda ao vivo, evitando a máscara desaparecer quando
algum gate limpa temporariamente ``_display_auto_last_analysis``.
"""

from copy import deepcopy

import cv2

import src.platform.display_f3_strict_mask_conformity as strict_module
import src.platform.display_live_roi_overlay as overlay_module
from src.platform.display_auto_check_analyzer import DISPLAY_AUTO_CLASS_LOW_LIGHT
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
    normalizar_resolucao_display,
)
from src.platform.display_visual_rotation import preparar_check_visual_display


# Mantém o segmento real visível, mas com cor suficiente para leitura rápida.
F3_PREVIEW_CLEAR_ALPHA = 0.22
F3_PREVIEW_CLEAR_CONTOUR_THICKNESS = 2

F3_PREVIEW_CLEAR_COLORS = {
    DISPLAY_CHECK_STATE_ON: (94, 197, 34),       # verde #22C55E
    DISPLAY_CHECK_STATE_OFF: (68, 68, 239),      # vermelho #EF4444
    "alert": (21, 204, 250),                     # amarelo #FACC15
}

F3_PREVIEW_CLEAR_LEGEND = (
    "VERDE: ACESO  •  VERMELHO: APAGADO  •  "
    "AMARELO: POUCA LUZ / DIVERGÊNCIA"
)


def estado_visual_mascara_f3(
    classified: str | None,
    expected: str | None,
    *,
    has_any_on: bool,
) -> str | None:
    """Converte classificação+gabarito em somente verde/vermelho/amarelo."""
    current = str(classified or "").strip().lower()
    target = str(expected or "").strip().lower()

    if current == DISPLAY_AUTO_CLASS_LOW_LIGHT:
        return "alert"

    if current == DISPLAY_CHECK_STATE_ON:
        if target == DISPLAY_CHECK_STATE_OFF and has_any_on:
            return "alert"
        return DISPLAY_CHECK_STATE_ON

    if current == DISPLAY_CHECK_STATE_OFF:
        if not has_any_on:
            return None
        if target == DISPLAY_CHECK_STATE_ON:
            return "alert"
        return DISPLAY_CHECK_STATE_OFF

    return None


def _project_preview_context(window, visual_rotation: int) -> dict | None:
    """Carrega geometria/estado esperado direto do projeto, sem depender da análise."""
    app = overlay_module._app_from_window(window)
    if app is None:
        return None

    repository = getattr(app, "display_project_repository", None)
    if repository is None:
        return None

    try:
        project_name = str(repository.obter_projeto_ativo() or "")
    except Exception:
        project_name = ""
    check_id = overlay_module._current_check_id(app)
    if not project_name or not check_id:
        return None

    cache_key = (
        project_name,
        check_id,
        int(visual_rotation or 0) % 360,
        overlay_module._config_signature(repository),
    )
    if cache_key == getattr(window, "_display_f3_clear_preview_project_key", None):
        cached = getattr(window, "_display_f3_clear_preview_project_context", None)
        return deepcopy(cached) if isinstance(cached, dict) else None

    try:
        project = repository.carregar_projeto(project_name)
    except Exception:
        project = None
    if not isinstance(project, dict):
        return None

    resolution = normalizar_resolucao_display(project.get("master_resolution"))
    if resolution is None:
        return None

    checks = list(project.get("checks", []) or [])
    check = next(
        (
            item
            for item in checks
            if isinstance(item, dict)
            and str(item.get("id") or "") == check_id
        ),
        None,
    )
    if not isinstance(check, dict):
        return None

    states = (
        check.get("mask_states", {})
        if isinstance(check.get("mask_states"), dict)
        else {}
    )
    expected = {
        str(mask_id): str(state).strip().lower()
        for mask_id, state in states.items()
        if str(state).strip().lower()
        in (DISPLAY_CHECK_STATE_ON, DISPLAY_CHECK_STATE_OFF)
    }
    active_masks = [
        deepcopy(mask)
        for mask in (project.get("masks", []) or [])
        if isinstance(mask, dict)
        and expected.get(str(mask.get("id") or ""))
        in (DISPLAY_CHECK_STATE_ON, DISPLAY_CHECK_STATE_OFF)
    ]

    try:
        _, visual_resolution, visual_masks = preparar_check_visual_display(
            None,
            resolution,
            active_masks,
            int(visual_rotation or 0) % 360,
        )
    except Exception:
        return None

    result = {
        "project_name": project_name,
        "check_id": check_id,
        "resolution": tuple(visual_resolution),
        "masks": tuple(visual_masks),
        "expected_states": expected,
    }
    window._display_f3_clear_preview_project_key = cache_key
    window._display_f3_clear_preview_project_context = deepcopy(result)
    return result


def _classifications_from_analysis(
    analysis: dict | None,
    *,
    project_name: str,
    check_id: str,
) -> dict[str, str]:
    if not isinstance(analysis, dict):
        return {}
    if str(analysis.get("project_name") or "") != str(project_name or ""):
        return {}
    if str(analysis.get("check_id") or "") != str(check_id or ""):
        return {}

    result = {}
    for item in analysis.get("mask_results", []) or []:
        if not isinstance(item, dict):
            continue
        mask_id = str(item.get("mask_id") or "")
        state = str(item.get("classified") or "").strip().lower()
        if mask_id and state:
            result[mask_id] = state
    return result


def _classifications_for_current_check(
    window,
    *,
    project_name: str,
    check_id: str,
    base: dict | None = None,
) -> dict[str, str]:
    """Obtém a leitura atual sem deixar gates transitórios apagarem o overlay."""
    classifications = {
        str(key): str(value).strip().lower()
        for key, value in dict((base or {}).get("classifications") or {}).items()
    }
    if classifications:
        return classifications

    app = overlay_module._app_from_window(window)
    if app is None:
        return {}

    for attr in (
        "_display_auto_last_analysis",
        "_display_f3_overlay_analysis_cache",
        "_display_f3_live_probe_last_analysis",
    ):
        analysis = getattr(app, attr, None)
        classifications = _classifications_from_analysis(
            analysis,
            project_name=project_name,
            check_id=check_id,
        )
        if classifications:
            return classifications
    return {}


def _contexto_preview_claro(original):
    def build(window, visual_rotation: int):
        base = original(window, visual_rotation)
        project_context = _project_preview_context(window, visual_rotation)

        if not isinstance(project_context, dict):
            return base

        result = dict(base) if isinstance(base, dict) else {}
        result["resolution"] = project_context["resolution"]
        result["masks"] = project_context["masks"]
        result["expected_states"] = dict(project_context["expected_states"])

        classifications = _classifications_for_current_check(
            window,
            project_name=str(project_context.get("project_name") or ""),
            check_id=str(project_context.get("check_id") or ""),
            base=result,
        )
        result["classifications"] = classifications
        result["has_any_on"] = any(
            str(state).strip().lower() == DISPLAY_CHECK_STATE_ON
            for state in classifications.values()
        )
        return result

    return build


def _draw_mask(tint, mask: dict, sx: float, sy: float, color):
    kind = str(mask.get("type") or "").lower()
    if kind == "circle":
        center = (
            int(round(float(mask.get("cx", 0)) * sx)),
            int(round(float(mask.get("cy", 0)) * sy)),
        )
        axes = (
            max(1, int(round(float(mask.get("radius", 1)) * sx))),
            max(1, int(round(float(mask.get("radius", 1)) * sy))),
        )
        cv2.ellipse(tint, center, axes, 0, 0, 360, color, -1, cv2.LINE_AA)
        return ("circle", center, axes)

    polygon = overlay_module._scaled_polygon(mask, sx, sy)
    if polygon is None or len(polygon) < 3:
        return None
    cv2.fillPoly(tint, [polygon], color, lineType=cv2.LINE_AA)
    return ("polygon", polygon)


def renderizar_preview_claro_display_f3(frame, context):
    """Render final do F3 sem sobreposição de paletas concorrentes."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return frame
    if not isinstance(context, dict):
        return frame.copy()

    resolution = context.get("resolution")
    masks = tuple(context.get("masks") or ())
    if (
        not isinstance(resolution, (list, tuple))
        or len(resolution) < 2
        or not masks
    ):
        return frame.copy()

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
    has_any_on = bool(
        context.get("has_any_on")
        or any(
            state == DISPLAY_CHECK_STATE_ON
            for state in classifications.values()
        )
    )

    result = frame.copy()
    tint = result.copy()
    geometries = []

    for mask in masks:
        if not isinstance(mask, dict):
            continue
        mask_id = str(mask.get("id") or "")
        presentation = estado_visual_mascara_f3(
            classifications.get(mask_id),
            expected_states.get(mask_id),
            has_any_on=has_any_on,
        )
        if presentation is None:
            continue

        color = F3_PREVIEW_CLEAR_COLORS[presentation]
        geometry = _draw_mask(tint, mask, sx, sy, color)
        if geometry is not None:
            geometries.append((geometry, color))

    if not geometries:
        return result

    cv2.addWeighted(
        tint,
        F3_PREVIEW_CLEAR_ALPHA,
        result,
        1.0 - F3_PREVIEW_CLEAR_ALPHA,
        0.0,
        dst=result,
    )

    for geometry, color in geometries:
        if geometry[0] == "circle":
            _kind, center, axes = geometry
            cv2.ellipse(
                result,
                center,
                axes,
                0,
                0,
                360,
                color,
                F3_PREVIEW_CLEAR_CONTOUR_THICKNESS,
                cv2.LINE_AA,
            )
        else:
            _kind, polygon = geometry
            cv2.polylines(
                result,
                [polygon],
                True,
                color,
                F3_PREVIEW_CLEAR_CONTOUR_THICKNESS,
                cv2.LINE_AA,
            )

    return result


def _aplicar_render_final() -> None:
    """Reafirma o renderer final; o contexto é embrulhado somente uma vez."""
    if not bool(
        getattr(overlay_module, "_display_f3_clear_preview_context_installed", False)
    ):
        overlay_module._overlay_context = _contexto_preview_claro(
            overlay_module._overlay_context
        )
        overlay_module._display_f3_clear_preview_context_installed = True

    # Estas atribuições são deliberadamente repetíveis. Alguns instaladores F3
    # históricos substituem o renderer durante a construção do app; uma chamada
    # posterior restaura esta camada sem duplicar wrappers nem callbacks.
    overlay_module.renderizar_overlay_rois_display_f3 = (
        renderizar_preview_claro_display_f3
    )
    overlay_module.DISPLAY_ROI_OVERLAY_ALPHA = F3_PREVIEW_CLEAR_ALPHA
    overlay_module.DISPLAY_ROI_OVERLAY_NEUTRAL_ALPHA = 0.0
    overlay_module.DISPLAY_ROI_OVERLAY_COLORS.clear()
    overlay_module.DISPLAY_ROI_OVERLAY_COLORS.update(
        {
            "on": F3_PREVIEW_CLEAR_COLORS[DISPLAY_CHECK_STATE_ON],
            "off": F3_PREVIEW_CLEAR_COLORS[DISPLAY_CHECK_STATE_OFF],
            "low_light": F3_PREVIEW_CLEAR_COLORS["alert"],
            "mismatch": F3_PREVIEW_CLEAR_COLORS["alert"],
        }
    )
    overlay_module.DISPLAY_ROI_OVERLAY_LEGEND = F3_PREVIEW_CLEAR_LEGEND
    overlay_module._display_f3_clear_preview_installed = True


_INSTALLED = False


def instalar_preview_claro_display_f3() -> None:
    """Garante que esta apresentação seja a última camada visual do F3."""
    global _INSTALLED

    if not _INSTALLED:
        previous = strict_module._install_failed_mask_overlay

        def install_failed_mask_overlay_then_clear() -> None:
            previous()
            _aplicar_render_final()

        strict_module._install_failed_mask_overlay = install_failed_mask_overlay_then_clear
        _INSTALLED = True

    # Também é seguro chamar depois da construção completa do app para recuperar
    # o renderer caso qualquer camada posterior o tenha substituído.
    _aplicar_render_final()
