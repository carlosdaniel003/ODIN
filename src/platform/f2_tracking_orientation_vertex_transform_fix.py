from __future__ import annotations

"""Mantém a transformação base independente do wrapper visual dos slots F2.

O editor de vértices acrescenta uma camada de preview em
``f2_tracking_orientation_references``. A correção ponto a ponto, porém, precisa
sempre partir da transformação afim original; caso contrário a própria camada de
preview poderia voltar a chamar a correção local recursivamente.
"""

import numpy as np

import src.platform.f2_tracking_orientation_vertex_editor as vertex_editor
from src.platform.f2_object_tracking_visual_overlay import (
    transformar_rois_para_frame_atual_f2 as transformar_rois_base_f2,
)


_PATCH_INSTALADO = False


def _contorno_referencia_sem_recursao(
    shape,
    matrix,
    entry: dict | None,
    width: int,
    height: int,
):
    transformed = transformar_rois_base_f2(
        shape,
        matrix,
        int(width),
        int(height),
    )
    if not transformed:
        return transformed

    saved = vertex_editor.normalizar_pontos_contorno_orientacao(
        (entry or {}).get(vertex_editor.F2_ORIENTATION_BOARD_POINTS_KEY)
        if isinstance(entry, dict)
        else None
    )
    if saved is None:
        return transformed

    base_points = vertex_editor._pontos_roi(transformed[0])
    if base_points is None or len(saved) != len(base_points):
        return transformed

    corrected = vertex_editor._criar_contorno_pelos_pontos(
        np.asarray(saved, dtype=np.float32),
        transformed[0],
    )
    return [corrected] if corrected is not None else transformed


def instalar_transformacao_base_editor_vertices_orientacao_f2() -> None:
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return
    vertex_editor.contorno_referencia_orientacao_f2 = (
        _contorno_referencia_sem_recursao
    )
    _PATCH_INSTALADO = True
