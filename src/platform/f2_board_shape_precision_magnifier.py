from __future__ import annotations

"""Lupa de precisão para o desenho ponto a ponto do contorno da placa F2.

O editor de contorno reaproveita o editor de ROIs do ODIN. No modo Segmento por
pontos, porém, a lupa histórica desenhava a geometria de um segmento convencional
na posição do mouse. Para contornar uma PCI isso é enganoso: o operador está
fixando um vértice, não posicionando um segmento retangular.

Esta camada altera SOMENTE a lupa quando:
- o modo atual é ``editar_contorno_placa_f2``; e
- ``Segmento por pontos`` está ativo.

Nos demais modos a função original é chamada sem qualquer alteração.
"""

import tkinter as tk

import cv2
import numpy as np

from src.ui.main_window_parts.magnifier.desenhar_lupa_canvas import (
    TAG_LUPA,
    _converter_imagem_bgr_para_photoimage,
    _obter_controlador_preview,
    rotacionar_preview_lupa,
)
from src.ui.main_window_parts.image.rotacao_visual_principal import (
    normalizar_rotacao_visual,
)


F2_BOARD_SHAPE_EDIT_MODE = "editar_contorno_placa_f2"
F2_BOARD_POINT_MAGNIFIER_SIZE = 190
F2_BOARD_POINT_HALF_WINDOW_PX = 18
F2_BOARD_POINT_TARGET_BGR = (0, 214, 255)
F2_BOARD_POINT_CROSSHAIR_BGR = (94, 234, 212)
F2_BOARD_POINT_LAST_VERTEX_BGR = (72, 255, 110)
F2_BOARD_POINT_FIRST_VERTEX_BGR = (36, 197, 94)

_PATCH_INSTALADO = False


def _modo_ponto_a_ponto_placa_f2(view) -> bool:
    controller = _obter_controlador_preview(view)
    if controller is None:
        return False
    if str(getattr(controller, "modo_atual", "")) != F2_BOARD_SHAPE_EDIT_MODE:
        return False
    checker = getattr(controller, "_modo_segmento_livre_ativo", None)
    if not callable(checker):
        return False
    try:
        return bool(checker())
    except Exception:
        return False


def calcular_caixa_pixel_lupa_f2(
    imagem_x: int,
    imagem_y: int,
    x1: int,
    y1: int,
    escala_x: float,
    escala_y: float,
    tamanho_lupa: int = F2_BOARD_POINT_MAGNIFIER_SIZE,
) -> tuple[int, int, int, int]:
    """Projeta o pixel exato sob o cursor para o recorte ampliado."""
    left = int(round((int(imagem_x) - int(x1)) * float(escala_x)))
    top = int(round((int(imagem_y) - int(y1)) * float(escala_y)))
    right = int(round((int(imagem_x) + 1 - int(x1)) * float(escala_x))) - 1
    bottom = int(round((int(imagem_y) + 1 - int(y1)) * float(escala_y))) - 1
    limit = max(0, int(tamanho_lupa) - 1)
    return (
        max(0, min(limit, left)),
        max(0, min(limit, top)),
        max(0, min(limit, max(left, right))),
        max(0, min(limit, max(top, bottom))),
    )


def _projetar_ponto(
    ponto,
    x1: int,
    y1: int,
    escala_x: float,
    escala_y: float,
) -> tuple[int, int]:
    return (
        int(round((float(ponto[0]) - float(x1)) * float(escala_x))),
        int(round((float(ponto[1]) - float(y1)) * float(escala_y))),
    )


def _desenhar_mira_ponto_a_ponto(
    image,
    pixel_box: tuple[int, int, int, int],
    target_center: tuple[int, int],
) -> None:
    """Mira sem forma de ROI: cruz + caixa do pixel real sob o cursor."""
    height, width = image.shape[:2]
    left, top, right, bottom = pixel_box
    cx, cy = int(target_center[0]), int(target_center[1])
    gap = 6

    cv2.line(
        image,
        (0, cy),
        (max(0, left - gap), cy),
        F2_BOARD_POINT_CROSSHAIR_BGR,
        1,
        cv2.LINE_AA,
    )
    cv2.line(
        image,
        (min(width - 1, right + gap), cy),
        (width - 1, cy),
        F2_BOARD_POINT_CROSSHAIR_BGR,
        1,
        cv2.LINE_AA,
    )
    cv2.line(
        image,
        (cx, 0),
        (cx, max(0, top - gap)),
        F2_BOARD_POINT_CROSSHAIR_BGR,
        1,
        cv2.LINE_AA,
    )
    cv2.line(
        image,
        (cx, min(height - 1, bottom + gap)),
        (cx, height - 1),
        F2_BOARD_POINT_CROSSHAIR_BGR,
        1,
        cv2.LINE_AA,
    )
    cv2.rectangle(
        image,
        (left, top),
        (right, bottom),
        F2_BOARD_POINT_TARGET_BGR,
        2,
        cv2.LINE_AA,
    )


def _desenhar_contexto_vertices(
    view,
    image,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    escala_x: float,
    escala_y: float,
    target_center: tuple[int, int],
) -> int:
    """Mostra último/primeiro vértice próximos e a linha até o próximo clique."""
    controller = _obter_controlador_preview(view)
    points = list(getattr(controller, "_segmento_livre_pontos", []) or ())
    if not points:
        return 0

    last = points[-1]
    last_local = _projetar_ponto(last, x1, y1, escala_x, escala_y)
    if x1 <= int(last[0]) < x2 and y1 <= int(last[1]) < y2:
        cv2.circle(
            image,
            last_local,
            5,
            F2_BOARD_POINT_LAST_VERTEX_BGR,
            2,
            cv2.LINE_AA,
        )
        cv2.line(
            image,
            last_local,
            (int(target_center[0]), int(target_center[1])),
            F2_BOARD_POINT_LAST_VERTEX_BGR,
            1,
            cv2.LINE_AA,
        )

    first = points[0]
    if len(points) >= 3 and x1 <= int(first[0]) < x2 and y1 <= int(first[1]) < y2:
        first_local = _projetar_ponto(first, x1, y1, escala_x, escala_y)
        cv2.circle(
            image,
            first_local,
            8,
            F2_BOARD_POINT_FIRST_VERTEX_BGR,
            2,
            cv2.LINE_AA,
        )
    return len(points)


def desenhar_lupa_ponto_a_ponto_placa_f2(
    view,
    canvas_x: int,
    canvas_y: int,
    imagem_x: int,
    imagem_y: int,
) -> None:
    """Lupa especializada: o alvo representa um VÉRTICE/pixel, não uma ROI."""
    image = getattr(view, "imagem_canvas_original", None)
    if image is None or getattr(image, "size", 0) == 0:
        view.limpar_lupa_canvas()
        return

    image_height, image_width = image.shape[:2]
    half = int(F2_BOARD_POINT_HALF_WINDOW_PX)
    x1 = max(0, int(imagem_x) - half)
    y1 = max(0, int(imagem_y) - half)
    x2 = min(int(image_width), int(imagem_x) + half + 1)
    y2 = min(int(image_height), int(imagem_y) + half + 1)
    if x2 <= x1 or y2 <= y1:
        view.limpar_lupa_canvas()
        return

    crop = image[y1:y2, x1:x2].copy()
    if crop.size == 0:
        view.limpar_lupa_canvas()
        return

    size = int(F2_BOARD_POINT_MAGNIFIER_SIZE)
    enlarged = cv2.resize(
        crop,
        (size, size),
        interpolation=cv2.INTER_NEAREST,
    )
    scale_x = size / max(1, x2 - x1)
    scale_y = size / max(1, y2 - y1)
    cx = int(round((int(imagem_x) + 0.5 - x1) * scale_x))
    cy = int(round((int(imagem_y) + 0.5 - y1) * scale_y))
    cx = max(0, min(size - 1, cx))
    cy = max(0, min(size - 1, cy))

    pixel_box = calcular_caixa_pixel_lupa_f2(
        imagem_x,
        imagem_y,
        x1,
        y1,
        scale_x,
        scale_y,
        size,
    )
    fixed_points = _desenhar_contexto_vertices(
        view,
        enlarged,
        x1,
        y1,
        x2,
        y2,
        scale_x,
        scale_y,
        (cx, cy),
    )
    _desenhar_mira_ponto_a_ponto(enlarged, pixel_box, (cx, cy))

    cv2.rectangle(
        enlarged,
        (0, 0),
        (size - 1, size - 1),
        F2_BOARD_POINT_TARGET_BGR,
        2,
    )
    enlarged = rotacionar_preview_lupa(
        enlarged,
        getattr(view, "rotacao_visual_principal", 0),
    )
    image_tk = _converter_imagem_bgr_para_photoimage(enlarged)
    if image_tk is None:
        view.limpar_lupa_canvas()
        return

    view.lupa_tk = image_tk
    view.canvas.delete(TAG_LUPA)

    canvas_width, _ = view.obter_tamanho_canvas_principal()
    magnifier_x = int(canvas_width) - size - 18
    magnifier_y = 42
    mouse_over = (
        int(canvas_x) >= magnifier_x - 20
        and int(canvas_x) <= magnifier_x + size + 20
        and int(canvas_y) >= magnifier_y - 40
        and int(canvas_y) <= magnifier_y + size + 50
    )
    if mouse_over:
        magnifier_x = 18
    magnifier_x = max(12, magnifier_x)
    magnifier_y = max(12, magnifier_y)

    angle = normalizar_rotacao_visual(
        getattr(view, "rotacao_visual_principal", 0)
    )
    top_text = (
        f"PONTO A PONTO • X {int(imagem_x)}  Y {int(imagem_y)}"
        f" • {fixed_points} fixo(s) • {angle}°"
    )

    view.canvas.create_rectangle(
        magnifier_x - 6,
        magnifier_y - 30,
        magnifier_x + size + 6,
        magnifier_y + size + 8,
        fill="#020617",
        outline="#FBBF24",
        width=2,
        tags=(TAG_LUPA,),
    )
    view.canvas.create_rectangle(
        magnifier_x - 5,
        magnifier_y - 29,
        magnifier_x + size + 5,
        magnifier_y - 2,
        fill="#07111F",
        outline="",
        tags=(TAG_LUPA,),
    )
    view.canvas.create_text(
        magnifier_x,
        magnifier_y - 16,
        text=top_text,
        fill="#E2E8F0",
        font=("Segoe UI", 7, "bold"),
        anchor=tk.W,
        tags=(TAG_LUPA,),
    )
    view.canvas.create_image(
        magnifier_x,
        magnifier_y,
        image=view.lupa_tk,
        anchor=tk.NW,
        tags=(TAG_LUPA,),
    )
    view.canvas.create_rectangle(
        magnifier_x,
        magnifier_y,
        magnifier_x + size,
        magnifier_y + size,
        outline="#FBBF24",
        width=2,
        tags=(TAG_LUPA,),
    )
    view.canvas.tag_raise(TAG_LUPA)
    view._lupa_visivel = True


def instalar_lupa_precisao_contorno_placa_f2() -> None:
    """Instala a lupa especializada sem alterar Selecionar LEDs/F3/outros modos."""
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return

    from src.ui.main_window import ODINView

    current = ODINView.desenhar_lupa_canvas
    if bool(getattr(current, "_odin_f2_board_point_precision", False)):
        _PATCH_INSTALADO = True
        return
    previous = current

    def desenhar_lupa_com_precisao_f2(
        self,
        canvas_x: int,
        canvas_y: int,
        imagem_x: int,
        imagem_y: int,
    ) -> None:
        if not _modo_ponto_a_ponto_placa_f2(self):
            return previous(self, canvas_x, canvas_y, imagem_x, imagem_y)
        return desenhar_lupa_ponto_a_ponto_placa_f2(
            self,
            canvas_x,
            canvas_y,
            imagem_x,
            imagem_y,
        )

    desenhar_lupa_com_precisao_f2._odin_f2_board_point_precision = True
    desenhar_lupa_com_precisao_f2._odin_f2_board_point_precision_base = previous
    ODINView.desenhar_lupa_canvas = desenhar_lupa_com_precisao_f2
    _PATCH_INSTALADO = True
