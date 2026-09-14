from __future__ import annotations

"""Caminho leve para as referências visuais do Display F3.

As máscaras já desenhadas no Projeto Display são usadas como UMA única região
visual composta. Não existe recorte retangular e também não existe SSIM por
máscara para presença/estado visual. Isso mantém exatamente a região solicitada
pelo operador, mas com custo próximo ao antigo recorte único.

A análise funcional ACESO/APAGADO de cada segmento continua separada e não é
alterada por este módulo.
"""

import time
from copy import deepcopy

import numpy as np

import src.platform.display_f3_mask_reference_performance as perf
import src.platform.display_reference_roi as roi
from src.platform.display_project_repository import normalizar_resolucao_display


_PROJECT_CACHE: dict = {}
_UNION_MASK_CACHE: dict = {}
_PHYSICAL_STATE_CACHE: dict = {}
_VISUAL_STATE_CACHE: dict = {}

# A classificação física não precisa disputar a thread do Tk com o repaint em
# todo frame. O automático funcional continua no seu próprio fluxo.
F3_PHYSICAL_REFERENCE_REFRESH_SECONDS = 0.20
F3_VISUAL_REFERENCE_REFRESH_SECONDS = 0.50


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


def _union_key(masks: list[dict], width: int, height: int):
    return int(width), int(height), perf._mask_signature(list(masks or ()))


def _union_mask(masks: list[dict], width: int, height: int):
    key = _union_key(masks, width, height)
    cached = _UNION_MASK_CACHE.get(key)
    if cached is not None:
        return cached

    union = roi.construir_mascara_uniao_referencias_display(
        list(masks or ()),
        int(width),
        int(height),
    )
    _UNION_MASK_CACHE.clear()
    _UNION_MASK_CACHE[key] = union
    return union


def _union_similarity(reference_image, current_image, metadata: dict | None) -> dict:
    """Compara todos os segmentos desenhados em uma única operação vetorizada."""
    resolution, masks = perf._metadata_masks_no_copy(metadata)
    masks = list(masks or ())
    if (
        not masks
        or reference_image is None
        or current_image is None
        or getattr(reference_image, "size", 0) == 0
        or getattr(current_image, "size", 0) == 0
    ):
        return {
            "score": None,
            "mask_region_count": len(masks),
            "valid_mask_region_count": 0,
            "mask_scores": {},
            "comparison_mode": roi.DISPLAY_REFERENCE_MASK_COMPARE_MODE,
        }

    if resolution is None:
        resolution = (
            int(reference_image.shape[1]),
            int(reference_image.shape[0]),
        )

    reference = perf._prepare_bgr_readonly(reference_image, resolution)
    current = perf._prepare_bgr_readonly(current_image, resolution)
    if (
        reference is None
        or current is None
        or getattr(reference, "size", 0) == 0
        or getattr(current, "size", 0) == 0
    ):
        return {
            "score": None,
            "mask_region_count": len(masks),
            "valid_mask_region_count": 0,
            "mask_scores": {},
            "comparison_mode": roi.DISPLAY_REFERENCE_MASK_COMPARE_MODE,
        }

    height, width = reference.shape[:2]
    union = _union_mask(masks, width, height)
    selected = np.asarray(union) > 0
    if selected.shape[:2] != (height, width) or not np.any(selected):
        return {
            "score": None,
            "mask_region_count": len(masks),
            "valid_mask_region_count": 0,
            "mask_scores": {},
            "comparison_mode": roi.DISPLAY_REFERENCE_MASK_COMPARE_MODE,
        }

    try:
        ref_pixels = reference[selected].astype(np.float32)
        cur_pixels = current[selected].astype(np.float32)
    except Exception:
        return {
            "score": None,
            "mask_region_count": len(masks),
            "valid_mask_region_count": 0,
            "mask_scores": {},
            "comparison_mode": roi.DISPLAY_REFERENCE_MASK_COMPARE_MODE,
        }

    if ref_pixels.size == 0 or cur_pixels.size == 0:
        return {
            "score": None,
            "mask_region_count": len(masks),
            "valid_mask_region_count": 0,
            "mask_scores": {},
            "comparison_mode": roi.DISPLAY_REFERENCE_MASK_COMPARE_MODE,
        }

    color_error = float(np.mean(np.abs(ref_pixels - cur_pixels)) / 255.0)
    energy_error = min(
        1.0,
        abs(float(np.mean(ref_pixels)) - float(np.mean(cur_pixels))) / 255.0,
    )
    score = 1.0 - ((0.74 * color_error) + (0.26 * energy_error))
    score = max(0.0, min(1.0, float(score)))
    rounded = round(score, 4)

    # Mantém o contrato antigo para Debug Técnico/testes, mas a comparação foi
    # feita uma única vez sobre a união das regiões, não uma vez por máscara.
    mask_scores = {
        str(mask.get("id") or f"MASK_{index:03d}"): rounded
        for index, mask in enumerate(masks, start=1)
        if isinstance(mask, dict)
    }
    return {
        "score": rounded,
        "mask_region_count": len(masks),
        "valid_mask_region_count": len(mask_scores),
        "mask_scores": mask_scores,
        "comparison_mode": roi.DISPLAY_REFERENCE_MASK_COMPARE_MODE,
        "region_strategy": "single_union_of_project_masks",
    }


def _context_check_id(context) -> str:
    return str((context or {}).get("check_id") or "") if isinstance(context, dict) else ""


def _install_scene_throttle() -> None:
    """Evita recomputar todas as referências visuais em cada repaint do Tk."""
    import src.platform.display_f3_operational_status as operational

    if bool(getattr(operational, "_display_f3_mask_union_throttle_installed", False)):
        return

    base_physical = operational._build_operational_state
    base_visual = operational._build_visual_analysis_state

    def physical(self, frame, project_name: str, context: dict | None):
        now = time.monotonic()
        key = (
            id(self),
            str(project_name or ""),
            _context_check_id(context),
            bool(getattr(self, "_display_f3_waiting_empty_rearm", False)),
        )
        cached = _PHYSICAL_STATE_CACHE.get(key)
        if cached is not None and now - float(cached[0]) < F3_PHYSICAL_REFERENCE_REFRESH_SECONDS:
            return deepcopy(cached[1])
        state = base_physical(self, frame, project_name, context)
        _PHYSICAL_STATE_CACHE.clear()
        _PHYSICAL_STATE_CACHE[key] = (now, deepcopy(state))
        return state

    def visual(self, frame, project_name: str):
        now = time.monotonic()
        key = (id(self), str(project_name or ""))
        cached = _VISUAL_STATE_CACHE.get(key)
        if cached is not None and now - float(cached[0]) < F3_VISUAL_REFERENCE_REFRESH_SECONDS:
            return deepcopy(cached[1])
        state = base_visual(self, frame, project_name)
        _VISUAL_STATE_CACHE.clear()
        _VISUAL_STATE_CACHE[key] = (now, deepcopy(state))
        return state

    operational._build_operational_state = physical
    operational._build_visual_analysis_state = visual
    operational._display_f3_mask_union_throttle_installed = True


def limpar_cache_projeto_f3() -> None:
    _PROJECT_CACHE.clear()
    _UNION_MASK_CACHE.clear()
    _PHYSICAL_STATE_CACHE.clear()
    _VISUAL_STATE_CACHE.clear()


def instalar_referencias_leves_display_f3() -> None:
    """Instala a versão simples: uma união de máscaras, sem recorte e sem SSIM."""
    roi._project_mask_context = _project_context
    roi._metadata_masks = perf._metadata_masks_no_copy
    roi.calcular_similaridade_referencia_por_mascaras = _union_similarity
    perf._fast_similarity_by_masks = _union_similarity

    # Referências em disco ainda aproveitam o cache de imagem criado na camada
    # anterior, porém o score deixa de percorrer cada máscara individualmente.
    roi._reference_image = perf._cached_reference_image

    try:
        import src.platform.display_f3_visual_analysis_relative_fallback as fallback

        fallback._score_reference_full_roi = roi._score_exact_reference_by_masks
    except Exception:
        pass

    _install_scene_throttle()
