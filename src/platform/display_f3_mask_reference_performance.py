from __future__ import annotations

"""Reduz o custo das referencias visuais por mascara do Display F3.

A comparacao por mascaras e mais especifica que o antigo recorte retangular, mas
na primeira implementacao ela reconstruia as mesmas geometrias e decodificava os
mesmos JPEGs para cada referencia em praticamente todo frame. Como o loop do F3
roda na thread do Tk, esse custo podia impedir o repaint da janela e fazer o
Windows marcar o aplicativo como "nao respondendo".

Esta camada nao muda a autoridade do F3. Ela somente:
- mantem as fotos de referencia decodificadas em memoria enquanto o arquivo nao
  muda;
- compila a geometria das mascaras uma unica vez por configuracao/resolucao;
- evita copiar o frame Full HD quando ele ja esta no formato/resolucao esperados;
- limita a atualizacao dos scores de cena/referencia a alguns Hz. A analise
  funcional ACESO/APAGADO/NG do CHECK continua executando no fluxo normal.

Nenhum modulo F2 e importado ou alterado.
"""

import json
import time
from copy import deepcopy
from pathlib import Path

import cv2

import src.platform.display_check_presence_reference as check_module
import src.platform.display_reference_roi as roi_module
from src.core.roi_geometry import criar_mascaras_roi
from src.platform.display_project_repository import normalizar_resolucao_display


# Presenca/estado visual nao precisa ser recalculado a ~22 FPS. O valor apenas
# acompanha a cena e os gates fisicos; 180 ms ainda responde rapidamente a troca
# de placa/estado e deixa tempo livre para preview, overlay e analise funcional.
F3_MASK_REFERENCE_REFRESH_SECONDS = 0.18
F3_REFERENCE_IMAGE_CACHE_MAX = 32
F3_MASK_GEOMETRY_CACHE_MAX = 24

_REFERENCE_IMAGE_CACHE: dict[str, tuple[tuple[int, int], object]] = {}
_MASK_GEOMETRY_CACHE: dict[tuple[int, int, str], list[dict]] = {}
_RECENT_SCORE_CACHE: dict[tuple[str, int, int, str], tuple[float, dict]] = {}


def _valid_image(image) -> bool:
    return image is not None and getattr(image, "size", 0) > 0


def _trim_cache(cache: dict, maximum: int) -> None:
    while len(cache) > max(1, int(maximum)):
        try:
            cache.pop(next(iter(cache)))
        except (KeyError, StopIteration):
            break


def _reference_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return int(stat.st_mtime_ns), int(stat.st_size)


def _cached_reference_image(metadata: dict | None):
    path = Path(str((metadata or {}).get("image_path") or ""))
    if not path.is_file():
        return None, path

    signature = _reference_signature(path)
    if signature is None:
        return None, path

    key = str(path)
    cached = _REFERENCE_IMAGE_CACHE.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1], path

    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if not _valid_image(image):
        _REFERENCE_IMAGE_CACHE.pop(key, None)
        return None, path

    _REFERENCE_IMAGE_CACHE[key] = (signature, image)
    _trim_cache(_REFERENCE_IMAGE_CACHE, F3_REFERENCE_IMAGE_CACHE_MAX)
    return image, path


def _mask_signature(masks: list[dict]) -> str:
    try:
        return json.dumps(
            masks,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return repr(masks)


def _metadata_masks_no_copy(metadata: dict | None):
    data = metadata if isinstance(metadata, dict) else {}
    resolution = normalizar_resolucao_display(
        data.get("_display_master_resolution")
    )
    masks = [
        mask
        for mask in (data.get("_display_mask_regions", []) or [])
        if isinstance(mask, dict) and mask.get("id") is not None
    ]
    return resolution, masks


def _prepare_bgr_readonly(image, resolution):
    if not _valid_image(image):
        return None
    normalized = normalizar_resolucao_display(resolution)
    if normalized is None:
        return image

    width, height = int(normalized[0]), int(normalized[1])
    if (
        getattr(image, "ndim", 0) == 3
        and image.shape[2] == 3
        and image.shape[:2] == (height, width)
    ):
        # A comparacao e somente leitura; nao ha motivo para copiar ~6 MB por
        # referencia quando camera e fotos ja estao na resolucao mestre.
        return image
    return check_module._prepare_bgr(image, (width, height))


def _compiled_mask_regions(metadata: dict | None, width: int, height: int):
    _resolution, masks = _metadata_masks_no_copy(metadata)
    signature = _mask_signature(masks)
    key = (int(width), int(height), signature)
    cached = _MASK_GEOMETRY_CACHE.get(key)
    if cached is not None:
        return cached, signature, len(masks)

    compiled: list[dict] = []
    for index, mask in enumerate(masks, start=1):
        try:
            selection = roi_module._mask_selection(mask)
        except Exception:
            selection = None
        if selection is None:
            continue
        try:
            prepared = criar_mascaras_roi(selection, int(width), int(height))
        except Exception:
            prepared = None
        if prepared is None:
            continue
        x1, y1, x2, y2, local_mask, _inner, _ring = prepared
        if local_mask is None or getattr(local_mask, "size", 0) == 0:
            continue
        compiled.append(
            {
                "mask_id": str(mask.get("id") or f"MASK_{index:03d}"),
                "x1": int(x1),
                "y1": int(y1),
                "x2": int(x2),
                "y2": int(y2),
                "mask": local_mask,
            }
        )

    _MASK_GEOMETRY_CACHE[key] = compiled
    _trim_cache(_MASK_GEOMETRY_CACHE, F3_MASK_GEOMETRY_CACHE_MAX)
    return compiled, signature, len(masks)


def _score_cache_key(metadata: dict | None, width: int, height: int, mask_signature: str):
    path = str((metadata or {}).get("image_path") or "")
    return path, int(width), int(height), str(mask_signature)


def _score_regions_uncached(reference, current, compiled: list[dict], mask_count: int):
    scores: dict[str, float] = {}
    for item in compiled:
        x1 = int(item["x1"])
        y1 = int(item["y1"])
        x2 = int(item["x2"])
        y2 = int(item["y2"])
        reference_roi = reference[y1:y2, x1:x2]
        current_roi = current[y1:y2, x1:x2]
        score = roi_module._masked_ssim(
            reference_roi,
            current_roi,
            item["mask"],
        )
        if score is None:
            continue
        scores[str(item["mask_id"])] = round(float(score), 4)

    final_score = (
        float(sum(scores.values()) / len(scores))
        if scores
        else None
    )
    return {
        "score": None if final_score is None else round(final_score, 4),
        "mask_region_count": int(mask_count),
        "valid_mask_region_count": len(scores),
        "mask_scores": scores,
        "comparison_mode": roi_module.DISPLAY_REFERENCE_MASK_COMPARE_MODE,
    }


def _fast_similarity_by_masks(reference_image, current_image, metadata: dict | None) -> dict:
    resolution, masks = _metadata_masks_no_copy(metadata)
    if not masks or not _valid_image(reference_image) or not _valid_image(current_image):
        return {
            "score": None,
            "mask_region_count": len(masks),
            "valid_mask_region_count": 0,
            "mask_scores": {},
            "comparison_mode": roi_module.DISPLAY_REFERENCE_MASK_COMPARE_MODE,
        }

    if resolution is None:
        resolution = (
            int(reference_image.shape[1]),
            int(reference_image.shape[0]),
        )

    reference = _prepare_bgr_readonly(reference_image, resolution)
    current = _prepare_bgr_readonly(current_image, resolution)
    if not _valid_image(reference) or not _valid_image(current):
        return {
            "score": None,
            "mask_region_count": len(masks),
            "valid_mask_region_count": 0,
            "mask_scores": {},
            "comparison_mode": roi_module.DISPLAY_REFERENCE_MASK_COMPARE_MODE,
        }

    height, width = reference.shape[:2]
    compiled, mask_signature, mask_count = _compiled_mask_regions(
        metadata,
        width,
        height,
    )
    if not compiled:
        return {
            "score": None,
            "mask_region_count": int(mask_count),
            "valid_mask_region_count": 0,
            "mask_scores": {},
            "comparison_mode": roi_module.DISPLAY_REFERENCE_MASK_COMPARE_MODE,
        }

    key = _score_cache_key(metadata, width, height, mask_signature)
    now = time.monotonic()
    recent = _RECENT_SCORE_CACHE.get(key)
    if recent is not None and now - float(recent[0]) < F3_MASK_REFERENCE_REFRESH_SECONDS:
        result = deepcopy(recent[1])
        result["score_cache_hit"] = True
        return result

    result = _score_regions_uncached(
        reference,
        current,
        compiled,
        mask_count,
    )
    result["score_cache_hit"] = False
    _RECENT_SCORE_CACHE[key] = (now, deepcopy(result))
    # Ha no maximo poucas referencias por projeto, mas evita crescimento caso o
    # operador alterne por muitos projetos na mesma sessao.
    _trim_cache(_RECENT_SCORE_CACHE, F3_REFERENCE_IMAGE_CACHE_MAX * 2)
    return result


def limpar_cache_referencias_mascaras_f3() -> None:
    _REFERENCE_IMAGE_CACHE.clear()
    _MASK_GEOMETRY_CACHE.clear()
    _RECENT_SCORE_CACHE.clear()


def instalar_desempenho_referencias_mascaras_display_f3() -> None:
    """Troca somente helpers de custo alto, preservando o contrato produtivo."""
    roi_module._reference_image = _cached_reference_image
    roi_module.calcular_similaridade_referencia_por_mascaras = (
        _fast_similarity_by_masks
    )

    # A funcao abaixo foi atribuida ao gabarito fisico por objeto de funcao. Ela
    # consulta os helpers acima pelo namespace de display_reference_roi em tempo
    # de execucao, portanto passa a aproveitar os caches sem alterar a decisao.
    try:
        import src.platform.display_f3_visual_analysis_relative_fallback as fallback_module

        # Este modulo importou o scorer antigo por nome. Alinhamos explicitamente
        # para que um caminho sem score operacional tambem use as ROIs das mascaras.
        fallback_module._score_reference_full_roi = (
            roi_module._score_exact_reference_by_masks
        )
    except Exception:
        pass

    # Limpa qualquer score calculado antes da instalacao durante o bootstrap.
    _RECENT_SCORE_CACHE.clear()
