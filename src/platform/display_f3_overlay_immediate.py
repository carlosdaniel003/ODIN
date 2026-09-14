from __future__ import annotations

from copy import deepcopy

import src.platform.display_f3_live_runtime_fix as live_runtime
import src.platform.display_f3_mask_status as mask_status
import src.platform.display_live_roi_overlay as overlay
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
    normalizar_resolucao_display,
)
from src.platform.display_visual_rotation import preparar_check_visual_display


def _matches(analysis, project_name: str, check_id: str) -> bool:
    return bool(
        isinstance(analysis, dict)
        and str(analysis.get("project_name") or "") == project_name
        and str(analysis.get("check_id") or "") == check_id
    )


def _context(window, visual_rotation: int):
    app = overlay._app_from_window(window)
    repository = getattr(app, "display_project_repository", None) if app else None
    if repository is None:
        return None
    try:
        project_name = str(repository.obter_projeto_ativo() or "")
    except Exception:
        return None
    check_id = overlay._current_check_id(app)
    if not project_name or not check_id:
        return None

    key = (
        project_name,
        check_id,
        int(visual_rotation),
        overlay._config_signature(repository),
    )
    if key != getattr(window, "_display_roi_overlay_cache_key", None):
        project = repository.carregar_projeto(project_name)
        if not isinstance(project, dict):
            return None
        resolution = normalizar_resolucao_display(project.get("master_resolution"))
        check = next(
            (
                item for item in (project.get("checks", []) or [])
                if isinstance(item, dict)
                and str(item.get("id") or "") == check_id
            ),
            None,
        )
        if resolution is None or not isinstance(check, dict):
            return None
        states = check.get("mask_states", {}) if isinstance(check.get("mask_states"), dict) else {}
        masks = [
            deepcopy(item)
            for item in (project.get("masks", []) or [])
            if isinstance(item, dict)
            and states.get(str(item.get("id") or ""))
            in (DISPLAY_CHECK_STATE_ON, DISPLAY_CHECK_STATE_OFF)
        ]
        _, visual_resolution, visual_masks = preparar_check_visual_display(
            None, resolution, masks, visual_rotation
        )
        window._display_roi_overlay_cache_key = key
        window._display_roi_overlay_resolution = tuple(visual_resolution)
        window._display_roi_overlay_masks = tuple(visual_masks)

    analysis = getattr(app, "_display_auto_last_analysis", None)
    classifications = {}
    if _matches(analysis, project_name, check_id):
        for item in analysis.get("mask_results", []) or []:
            if isinstance(item, dict) and item.get("mask_id"):
                classifications[str(item["mask_id"])] = str(
                    item.get("classified") or "unknown"
                )
    return {
        "resolution": getattr(window, "_display_roi_overlay_resolution", None),
        "masks": getattr(window, "_display_roi_overlay_masks", ()),
        "classifications": classifications,
    }


def _no_extra_analysis(app):
    try:
        context = app._display_auto_current_context()
    except Exception:
        return None
    analysis = getattr(app, "_display_auto_last_analysis", None)
    if not isinstance(context, dict):
        return None
    if _matches(
        analysis,
        str(context.get("project_name") or ""),
        str(context.get("check_id") or ""),
    ):
        return analysis
    return None


def instalar_overlay_imediato_display_f3() -> None:
    overlay._overlay_context = _context
    live_runtime.atualizar_classificacao_overlay_f3 = _no_extra_analysis
    mask_status.atualizar_classificacao_overlay_f3 = _no_extra_analysis
