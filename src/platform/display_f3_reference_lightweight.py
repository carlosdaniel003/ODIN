from __future__ import annotations

from copy import deepcopy

import numpy as np

import src.platform.display_f3_mask_reference_performance as perf
import src.platform.display_reference_roi as roi
from src.platform.display_project_repository import normalizar_resolucao_display


_PROJECT_CACHE = {}
F3_VISUAL_REFERENCE_REFRESH_SECONDS = 0.45


def _signature(repository):
    try:
        stat = repository.config_file.stat()
        return int(stat.st_mtime_ns), int(stat.st_size)
    except Exception:
        return 0, 0


def _project_context(repository, project_name: str):
    if repository is None:
        return None, []
    key = (id(repository), str(project_name or ""), _signature(repository))
    cached = _PROJECT_CACHE.get(key)
    if cached is not None:
        return cached[0], list(cached[1])
    try:
        project = repository.carregar_projeto(project_name)
    except Exception:
        project = None
    if not isinstance(project, dict):
        return None, []
    resolution = normalizar_resolucao_display(project.get("master_resolution"))
    masks = tuple(
        deepcopy(item)
        for item in (project.get("masks", []) or [])
        if isinstance(item, dict) and item.get("id") is not None
    )
    _PROJECT_CACHE.clear()
    _PROJECT_CACHE[key] = (resolution, masks)
    return resolution, list(masks)


def _similarity(reference_roi, current_roi, mask):
    if reference_roi is None or current_roi is None or mask is None:
        return None
    selected = np.asarray(mask) > 0
    if selected.shape[:2] != reference_roi.shape[:2] or not np.any(selected):
        return None
    try:
        reference = reference_roi[selected].astype(np.float32)
        current = current_roi[selected].astype(np.float32)
    except Exception:
        return None
    if reference.size == 0 or current.size == 0:
        return None
    color_error = float(np.mean(np.abs(reference - current)) / 255.0)
    energy_error = min(
        1.0,
        abs(float(np.mean(reference)) - float(np.mean(current))) / 255.0,
    )
    score = 1.0 - ((0.72 * color_error) + (0.28 * energy_error))
    return max(0.0, min(1.0, float(score)))


def limpar_cache_projeto_f3() -> None:
    _PROJECT_CACHE.clear()


def instalar_referencias_leves_display_f3() -> None:
    perf.F3_MASK_REFERENCE_REFRESH_SECONDS = F3_VISUAL_REFERENCE_REFRESH_SECONDS
    roi._project_mask_context = _project_context
    roi._metadata_masks = perf._metadata_masks_no_copy
    roi._masked_ssim = _similarity
