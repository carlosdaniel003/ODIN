from __future__ import annotations

"""UI de configuração do tracking F3 e base de interação geométrica.

Os antigos slots angulares 90°/180°/270° foram retirados do produto. Este módulo
mantém somente:
- o toggle do tracking automático do Display F3;
- a base de interação reutilizada pelo editor canônico "Placa + Máscaras".

A pose produtiva é obtida pelo contorno canônico e refinada pelos segmentos
luminosos do CHECK atual; nenhuma imagem angular é capturada ou carregada.
"""

import math
import tkinter as tk
from copy import deepcopy

import cv2
import numpy as np

import src.platform.display_production_f3 as production_module
from src.platform.display_f3_object_tracking import (
    F3TrackingConfigStore,
    _normalize_points,
    _valid_frame,
    canonical_board_points,
    draw_reference_geometry,
    photo_from_bgr,
    reset_tracking_runtime,
    set_tracking_enabled,
    transform_points,
)
from src.platform.display_mask_geometry import numero_mascara_display
from src.platform.display_project_repository import normalizar_nome_projeto_display


F3_EDITOR_HISTORY_LIMIT = 5
F3_EDITOR_MAGNIFIER_SIZE = 210
F3_EDITOR_VERTEX_HIT_PX = 11.0
F3_EDITOR_MASK_VERTEX_HIT_PX = 10.0
F3_EDITOR_ZOOM_MIN = 1.0
F3_EDITOR_ZOOM_MAX = 5.0
F3_EDITOR_ZOOM_STEP = 1.16
F3_SAFE_WINDOW_MARGIN_X = 64
F3_SAFE_WINDOW_MARGIN_Y = 118

_INSTALLED = False


def _fit_toplevel_inside_screen(
    window,
    *,
    width_ratio: float = 0.92,
    height_ratio: float = 0.84,
    min_width: int = 760,
    min_height: int = 520,
) -> None:
    """Dimensiona a janela sem esconder a barra inferior/botões.

    Usar exatamente screenwidth x screenheight em Linux/Raspberry ignora a área
    reservada pelo painel/decoração do gerenciador de janelas. Por isso a janela
    guiada podia ultrapassar a área útil e esconder CAPTURAR/CANCELAR.
    """
    try:
        sw = max(1, int(window.winfo_screenwidth()))
        sh = max(1, int(window.winfo_screenheight()))
        available_w = max(480, sw - F3_SAFE_WINDOW_MARGIN_X)
        available_h = max(420, sh - F3_SAFE_WINDOW_MARGIN_Y)
        width = min(
            available_w,
            max(min_width, int(round(sw * float(width_ratio)))),
        )
        height = min(
            available_h,
            max(min_height, int(round(sh * float(height_ratio)))),
        )
        x = max(0, (sw - width) // 2)
        y = max(8, (sh - height) // 2 - 8)
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.maxsize(available_w, available_h)
    except Exception:
        pass


def _matrix_homogeneous(matrix) -> np.ndarray:
    value = np.asarray(matrix, dtype=np.float32).reshape(2, 3)
    return np.asarray(
        [
            [value[0, 0], value[0, 1], value[0, 2]],
            [value[1, 0], value[1, 1], value[1, 2]],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )


def _compose_left(adjustment, current) -> np.ndarray:
    result = _matrix_homogeneous(adjustment) @ _matrix_homogeneous(current)
    return np.asarray(result[:2, :], dtype=np.float32)


def _points_center(points) -> tuple[float, float]:
    normalized = _normalize_points(points, minimum=1)
    if not normalized:
        return 0.0, 0.0
    values = np.asarray(normalized, dtype=np.float32).reshape(-1, 2)
    center = np.mean(values, axis=0)
    return float(center[0]), float(center[1])


def _mask_points(mask: dict) -> list[list[float]]:
    if not isinstance(mask, dict):
        return []
    if str(mask.get("type") or "").lower() == "circle":
        return []
    return _normalize_points(mask.get("points"), minimum=3)


def _translate_mask(mask: dict, dx: float, dy: float) -> dict:
    result = deepcopy(mask)
    if str(result.get("type") or "").lower() == "circle":
        result["cx"] = float(result.get("cx", 0)) + float(dx)
        result["cy"] = float(result.get("cy", 0)) + float(dy)
    else:
        result["points"] = [
            [float(x) + float(dx), float(y) + float(dy)]
            for x, y in _normalize_points(result.get("points"), minimum=3)
        ]
    return result


def _transform_reference_mask(mask: dict, adjustment) -> dict:
    result = deepcopy(mask)
    affine = np.asarray(adjustment, dtype=np.float32).reshape(2, 3)
    kind = str(result.get("type") or "").lower()
    if kind == "circle":
        point = affine @ np.asarray(
            [float(result.get("cx", 0)), float(result.get("cy", 0)), 1.0],
            dtype=np.float32,
        )
        a = float(affine[0, 0])
        b = float(affine[0, 1])
        c = float(affine[1, 0])
        d = float(affine[1, 1])
        scale = (math.hypot(a, c) + math.hypot(b, d)) / 2.0
        result["cx"] = float(point[0])
        result["cy"] = float(point[1])
        result["radius"] = max(1.0, float(result.get("radius", 1)) * max(1e-6, scale))
        return result
    result["points"] = transform_points(result.get("points"), affine)
    return result


def _point_inside_mask(mask: dict, x: float, y: float) -> bool:
    kind = str(mask.get("type") or "").lower()
    if kind == "circle":
        dx = float(x) - float(mask.get("cx", 0))
        dy = float(y) - float(mask.get("cy", 0))
        return dx * dx + dy * dy <= max(1.0, float(mask.get("radius", 1))) ** 2
    points = _normalize_points(mask.get("points"), minimum=3)
    if not points:
        return False
    polygon = np.asarray(points, dtype=np.float32)
    try:
        return cv2.pointPolygonTest(polygon, (float(x), float(y)), False) >= 0
    except Exception:
        return False


class F3GeometryEditorInteractionBase:
    """Interações comuns de geometria; a subclasse concreta fornece estado e persistência."""

    def __init__(self, *args, **kwargs) -> None:
        raise TypeError(
            "Use F3ReferenceGeometryEditor; slots angulares não existem mais."
        )

    def _snapshot(self) -> dict:
        return {
            "matrix": np.asarray(self.matrix, dtype=np.float32).copy(),
            "board": deepcopy(self.board),
            "masks": deepcopy(self.masks),
            "selected": deepcopy(self.selected),
            "redraw_board_committed": bool(self.redraw_board_committed),
        }

    def _push_history(self, snapshot=None) -> None:
        self.history.append(snapshot if isinstance(snapshot, dict) else self._snapshot())
        if len(self.history) > F3_EDITOR_HISTORY_LIMIT:
            self.history = self.history[-F3_EDITOR_HISTORY_LIMIT:]

    def undo(self) -> str:
        if not self.history:
            self.status.configure(text="Nada para desfazer.")
            return "break"
        state = self.history.pop()
        self.matrix = np.asarray(state["matrix"], dtype=np.float32).copy()
        self.board = deepcopy(state["board"])
        self.masks = deepcopy(state["masks"])
        self.selected = deepcopy(state.get("selected"))
        self.redraw_board_committed = bool(state.get("redraw_board_committed", False))
        self.draw_board_mode = False
        self.draw_board_points = []
        self.schedule_render()
        self.status.configure(text=f"Desfeito • {len(self.history)} ação(ões) anteriores disponíveis.")
        return "break"

    def _view_transform(self) -> tuple[float, float, float]:
        cw = max(1.0, float(self.canvas.winfo_width()))
        ch = max(1.0, float(self.canvas.winfo_height()))
        width = max(1.0, float(self.width))
        height = max(1.0, float(self.height))
        fit = min(cw / width, ch / height)
        zoom = min(
            F3_EDITOR_ZOOM_MAX,
            max(F3_EDITOR_ZOOM_MIN, float(self.view_zoom)),
        )
        if zoom <= 1.001:
            self.view_pan_x = 0.0
            self.view_pan_y = 0.0
        scale = max(0.01, fit * zoom)
        tx = cw / 2.0 + float(self.view_pan_x) - width * scale / 2.0
        ty = ch / 2.0 + float(self.view_pan_y) - height * scale / 2.0
        self._display_scale = scale
        self._view_tx = tx
        self._view_ty = ty
        return scale, tx, ty

    def _image_to_canvas(self, x: float, y: float):
        scale = max(1e-6, float(self._display_scale))
        return (
            float(self._view_tx) + float(x) * scale,
            float(self._view_ty) + float(y) * scale,
        )

    def _canvas_to_image(self, x: float, y: float):
        scale = max(1e-6, float(self._display_scale))
        px = (float(x) - float(self._view_tx)) / scale
        py = (float(y) - float(self._view_ty)) / scale
        return (
            min(max(px, 0.0), max(0.0, self.width - 1.0)),
            min(max(py, 0.0), max(0.0, self.height - 1.0)),
        )

    def _nearest_board_vertex(self, cx: float, cy: float):
        best = None
        for index, point in enumerate(self.board):
            x, y = self._image_to_canvas(point[0], point[1])
            distance = math.hypot(cx - x, cy - y)
            if distance <= F3_EDITOR_VERTEX_HIT_PX and (
                best is None or distance < best[0]
            ):
                best = (distance, index)
        return None if best is None else int(best[1])

    def _nearest_mask_vertex(self, cx: float, cy: float):
        best = None
        for mask in self.masks:
            if str(mask.get("type") or "").lower() == "circle":
                continue
            for index, point in enumerate(_mask_points(mask)):
                x, y = self._image_to_canvas(point[0], point[1])
                distance = math.hypot(cx - x, cy - y)
                if distance <= F3_EDITOR_MASK_VERTEX_HIT_PX and (
                    best is None or distance < best[0]
                ):
                    best = (distance, str(mask.get("id") or ""), index)
        return None if best is None else (best[1], int(best[2]))

    def _mask_at(self, image_x: float, image_y: float):
        for mask in reversed(self.masks):
            if _point_inside_mask(mask, image_x, image_y):
                return str(mask.get("id") or "")
        return None

    def _mask_by_id(self, mask_id: str):
        return next(
            (mask for mask in self.masks if str(mask.get("id") or "") == str(mask_id)),
            None,
        )

    def _press(self, event) -> None:
        self.canvas.focus_set()
        image_pos = self._canvas_to_image(event.x, event.y)
        if self.draw_board_mode:
            self.draw_board_points.append([float(image_pos[0]), float(image_pos[1])])
            self.schedule_render()
            return

        board_index = self._nearest_board_vertex(float(event.x), float(event.y))
        if board_index is not None:
            self.selected = ("board_vertex", board_index)
            self.drag_target = self.selected
        else:
            mask_vertex = self._nearest_mask_vertex(float(event.x), float(event.y))
            if mask_vertex is not None:
                self.selected = ("mask_vertex", mask_vertex[0], mask_vertex[1])
                self.drag_target = self.selected
            else:
                mask_id = self._mask_at(*image_pos)
                if mask_id:
                    self.selected = ("mask", mask_id)
                    self.drag_target = self.selected
                else:
                    self.selected = None
                    self.drag_target = ("all",)

        self.drag_last_image = image_pos
        self.drag_snapshot_pushed = False
        self.schedule_render()

    def _drag(self, event) -> None:
        if self.drag_target is None or self.draw_board_mode:
            return
        current = self._canvas_to_image(event.x, event.y)
        previous = self.drag_last_image or current
        dx = float(current[0] - previous[0])
        dy = float(current[1] - previous[1])
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return
        if not self.drag_snapshot_pushed:
            self._push_history()
            self.drag_snapshot_pushed = True

        kind = self.drag_target[0]
        if kind == "board_vertex":
            index = int(self.drag_target[1])
            if 0 <= index < len(self.board):
                self.board[index] = [float(current[0]), float(current[1])]
        elif kind == "mask":
            mask_id = str(self.drag_target[1])
            for index, mask in enumerate(self.masks):
                if str(mask.get("id") or "") == mask_id:
                    self.masks[index] = _translate_mask(mask, dx, dy)
                    break
        elif kind == "mask_vertex":
            mask_id, vertex_index = str(self.drag_target[1]), int(self.drag_target[2])
            mask = self._mask_by_id(mask_id)
            if mask is not None:
                points = _mask_points(mask)
                if 0 <= vertex_index < len(points):
                    points[vertex_index] = [float(current[0]), float(current[1])]
                    mask["type"] = "polygon"
                    mask["points"] = points
        elif kind == "all":
            self._apply_global_translation(dx, dy, push=False)

        self.drag_last_image = current
        self.schedule_render()

    def _release(self, _event) -> None:
        self.drag_target = None
        self.drag_last_image = None
        self.drag_snapshot_pushed = False

    def _motion(self, event) -> None:
        image_pos = self._canvas_to_image(event.x, event.y)
        self._precision_cursor = (
            float(image_pos[0]),
            float(image_pos[1]),
            float(event.x),
            float(event.y),
        )
        if self.drag_target is not None:
            self.schedule_render()
            return
        if self.draw_board_mode:
            self.status.configure(
                text=(
                    f"REDESENHAR PLACA • X {image_pos[0]:.1f} Y {image_pos[1]:.1f} • "
                    "clique para fixar o próximo ponto"
                )
            )
            self.schedule_render()
            return
        board = self._nearest_board_vertex(float(event.x), float(event.y))
        if board is not None:
            self.status.configure(text=f"Ponto da placa {board + 1} • arraste para corrigir.")
            self.schedule_render()
            return
        mask_vertex = self._nearest_mask_vertex(float(event.x), float(event.y))
        if mask_vertex is not None:
            self.status.configure(
                text=f"{mask_vertex[0]} • ponto {mask_vertex[1] + 1} • arraste para corrigir."
            )
            self.schedule_render()
            return
        mask_id = self._mask_at(*image_pos)
        if mask_id:
            self.status.configure(
                text=f"{mask_id} • clique/arraste para mover; círculo aceita roda para raio."
            )
        else:
            self.status.configure(
                text=f"X {image_pos[0]:.1f} • Y {image_pos[1]:.1f} • Ctrl+roda = zoom"
            )
        self.schedule_render()

    def _leave_canvas(self, _event=None) -> None:
        if self.drag_target is None:
            self._precision_cursor = None
            self.schedule_render()

    @staticmethod
    def _wheel_direction(event) -> int:
        delta = int(getattr(event, "delta", 0) or 0)
        num = getattr(event, "num", None)
        return 1 if delta > 0 or num == 4 else -1

    def _wheel(self, event) -> str:
        direction = self._wheel_direction(event)
        state = int(getattr(event, "state", 0) or 0)
        ctrl = bool(state & 0x0004)
        shift = bool(state & 0x0001)
        if ctrl:
            old = float(self.view_zoom)
            new = old * (
                F3_EDITOR_ZOOM_STEP
                if direction > 0
                else 1.0 / F3_EDITOR_ZOOM_STEP
            )
            new = max(F3_EDITOR_ZOOM_MIN, min(F3_EDITOR_ZOOM_MAX, new))
            if abs(new - old) > 1e-6:
                target = self._canvas_to_image(event.x, event.y)
                cw = max(1.0, float(self.canvas.winfo_width()))
                ch = max(1.0, float(self.canvas.winfo_height()))
                fit = min(
                    cw / max(1.0, float(self.width)),
                    ch / max(1.0, float(self.height)),
                )
                new_scale = max(0.01, fit * new)
                if new <= 1.001:
                    self.view_pan_x = 0.0
                    self.view_pan_y = 0.0
                else:
                    self.view_pan_x = (
                        float(event.x)
                        - cw / 2.0
                        - (float(target[0]) - self.width / 2.0) * new_scale
                    )
                    self.view_pan_y = (
                        float(event.y)
                        - ch / 2.0
                        - (float(target[1]) - self.height / 2.0) * new_scale
                    )
                self.view_zoom = new
                self._precision_cursor = (
                    float(target[0]),
                    float(target[1]),
                    float(event.x),
                    float(event.y),
                )
                self.schedule_render()
            return "break"

        image_pos = self._canvas_to_image(event.x, event.y)
        mask_id = self._mask_at(*image_pos)
        selected_id = (
            str(self.selected[1])
            if isinstance(self.selected, tuple)
            and self.selected
            and self.selected[0] == "mask"
            else ""
        )
        target_id = mask_id or selected_id
        mask = self._mask_by_id(target_id) if target_id else None
        if mask is not None and str(mask.get("type") or "").lower() == "circle":
            self._push_history()
            mask["radius"] = max(
                1.0,
                float(mask.get("radius", 1)) + (1.0 if direction > 0 else -1.0),
            )
            self.selected = ("mask", target_id)
            self.schedule_render()
            return "break"

        if shift:
            self.scale_all(1.01 if direction > 0 else 0.99)
        else:
            self.rotate_all(1.0 if direction > 0 else -1.0)
        return "break"

    def _apply_adjustment(self, adjustment, *, push: bool = True) -> None:
        if push:
            self._push_history()
        self.matrix = _compose_left(adjustment, self.matrix)
        self.board = transform_points(self.board, adjustment)
        self.masks = [
            _transform_reference_mask(mask, adjustment)
            for mask in self.masks
        ]
        self.masks = [mask for mask in self.masks if mask is not None]
        self.schedule_render()

    def _apply_global_translation(self, dx: float, dy: float, *, push: bool = True) -> None:
        adjustment = np.asarray(
            [[1.0, 0.0, float(dx)], [0.0, 1.0, float(dy)]],
            dtype=np.float32,
        )
        self._apply_adjustment(adjustment, push=push)

    def translate_all(self, dx: float, dy: float) -> None:
        self._apply_global_translation(dx, dy, push=True)

    def rotate_all(self, degrees: float) -> None:
        cx, cy = _points_center(self.board)
        adjustment = cv2.getRotationMatrix2D(
            (float(cx), float(cy)),
            float(degrees),
            1.0,
        ).astype(np.float32)
        self._apply_adjustment(adjustment, push=True)

    def scale_all(self, factor: float) -> None:
        cx, cy = _points_center(self.board)
        adjustment = cv2.getRotationMatrix2D(
            (float(cx), float(cy)),
            0.0,
            float(factor),
        ).astype(np.float32)
        self._apply_adjustment(adjustment, push=True)

    def _keyboard_move(self, dx: float, dy: float) -> str:
        target = self.selected
        if isinstance(target, tuple) and target:
            self._push_history()
            if target[0] == "board_vertex":
                index = int(target[1])
                if 0 <= index < len(self.board):
                    self.board[index][0] += float(dx)
                    self.board[index][1] += float(dy)
            elif target[0] == "mask":
                mask_id = str(target[1])
                for index, mask in enumerate(self.masks):
                    if str(mask.get("id") or "") == mask_id:
                        self.masks[index] = _translate_mask(mask, dx, dy)
                        break
            elif target[0] == "mask_vertex":
                mask = self._mask_by_id(str(target[1]))
                points = _mask_points(mask) if mask is not None else []
                vertex_index = int(target[2])
                if mask is not None and 0 <= vertex_index < len(points):
                    points[vertex_index][0] += float(dx)
                    points[vertex_index][1] += float(dy)
                    mask["type"] = "polygon"
                    mask["points"] = points
            self.schedule_render()
            return "break"

        self.translate_all(dx, dy)
        return "break"

    def start_redraw_board(self) -> None:
        self.draw_board_mode = True
        self.draw_board_points = []
        self.status.configure(
            text="REDESENHAR PLACA • clique ponto a ponto no contorno; Enter conclui; Esc cancela."
        )
        self.schedule_render()

    def _enter(self, _event=None) -> str:
        if not self.draw_board_mode:
            return "break"
        if len(self.draw_board_points) < 3:
            self.status.configure(text="Use pelo menos 3 pontos para concluir o contorno.")
            return "break"
        self._push_history()
        self.board = deepcopy(self.draw_board_points)
        self.draw_board_points = []
        self.draw_board_mode = False
        self.redraw_board_committed = True
        self.status.configure(text="Novo contorno da placa definido. SALVAR para persistir.")
        self.schedule_render()
        return "break"

    def _escape(self, _event=None) -> str:
        if self.draw_board_mode:
            self.draw_board_mode = False
            self.draw_board_points = []
            self.schedule_render()
            return "break"
        self.close()
        return "break"

    def reset(self) -> None:
        self._push_history()
        self.matrix = self.nominal.copy()
        self.board = transform_points(
            canonical_board_points(self.project, self.store),
            self.matrix,
        )
        self.masks = transformed_masks(self.project, self.matrix)
        self.selected = None
        self.draw_board_mode = False
        self.draw_board_points = []
        self.redraw_board_committed = False
        self.schedule_render()

    def schedule_render(self) -> None:
        if self._render_after is not None:
            return
        try:
            self._render_after = self.window.after(24, self.render)
        except Exception:
            self._render_after = None

    def _draw_mask_numbers(self) -> None:
        """Exibe o mesmo MASK_ID canônico usado em máscaras, CHECK e presença."""
        for index, mask in enumerate(self.masks, start=1):
            if not isinstance(mask, dict):
                continue
            mask_id = str(mask.get("id") or "").strip()
            if not mask_id:
                continue

            kind = str(mask.get("type") or "").lower()
            if kind == "circle":
                try:
                    center = (
                        float(mask.get("cx", 0)),
                        float(mask.get("cy", 0)),
                    )
                except (TypeError, ValueError):
                    continue
            else:
                points = _mask_points(mask)
                if not points:
                    continue
                center = _points_center(points)

            x, y = self._image_to_canvas(center[0], center[1])
            label = numero_mascara_display(mask, index)
            half_width = max(9, 5 + 4 * len(label))
            self.canvas.create_rectangle(
                x - half_width,
                y - 9,
                x + half_width,
                y + 9,
                fill="#07111F",
                outline="#38BDF8",
                width=1,
                tags=("f3_mask_number",),
            )
            self.canvas.create_text(
                x,
                y,
                text=label,
                fill="#F8FAFC",
                font=("Segoe UI", 8, "bold"),
                tags=("f3_mask_number",),
            )

    def _draw_handles(self) -> None:
        for index, point in enumerate(self.board):
            x, y = self._image_to_canvas(point[0], point[1])
            active = (
                isinstance(self.selected, tuple)
                and self.selected[:2] == ("board_vertex", index)
            )
            self.canvas.create_oval(
                x - 4,
                y - 4,
                x + 4,
                y + 4,
                fill="#FACC15" if active else "#38BDF8",
                outline="#020617",
                width=1,
                tags=("f3_tracking_handle",),
            )

        for mask in self.masks:
            mask_id = str(mask.get("id") or "")
            kind = str(mask.get("type") or "").lower()
            if kind == "circle":
                x, y = self._image_to_canvas(
                    float(mask.get("cx", 0)),
                    float(mask.get("cy", 0)),
                )
                self.canvas.create_oval(
                    x - 4,
                    y - 4,
                    x + 4,
                    y + 4,
                    fill="#FBBF24" if self.selected == ("mask", mask_id) else "#7DD3FC",
                    outline="#020617",
                    width=1,
                    tags=("f3_tracking_handle",),
                )
            else:
                for vertex_index, point in enumerate(_mask_points(mask)):
                    x, y = self._image_to_canvas(point[0], point[1])
                    active = self.selected == ("mask_vertex", mask_id, vertex_index)
                    self.canvas.create_rectangle(
                        x - 3,
                        y - 3,
                        x + 3,
                        y + 3,
                        fill="#FBBF24" if active else "#67E8F9",
                        outline="#020617",
                        width=1,
                        tags=("f3_tracking_handle",),
                    )

        if self.draw_board_mode:
            for point in self.draw_board_points:
                x, y = self._image_to_canvas(point[0], point[1])
                self.canvas.create_oval(
                    x - 4,
                    y - 4,
                    x + 4,
                    y + 4,
                    fill="#FACC15",
                    outline="#020617",
                    tags=("f3_tracking_handle",),
                )

    def _selected_center(self):
        target = self.selected
        if not isinstance(target, tuple) or not target:
            return None
        if target[0] == "board_vertex":
            index = int(target[1])
            if 0 <= index < len(self.board):
                return tuple(self.board[index])
        if target[0] == "mask":
            mask = self._mask_by_id(str(target[1]))
            if mask is None:
                return None
            if str(mask.get("type") or "").lower() == "circle":
                return float(mask.get("cx", 0)), float(mask.get("cy", 0))
            points = _mask_points(mask)
            return _points_center(points) if points else None
        if target[0] == "mask_vertex":
            mask = self._mask_by_id(str(target[1]))
            points = _mask_points(mask) if mask is not None else []
            index = int(target[2])
            if 0 <= index < len(points):
                return tuple(points[index])
        return None

    def _magnifier_target(self):
        target = self.selected
        center = self._selected_center()
        radius = None
        title = "CURSOR"

        if isinstance(target, tuple) and target and center is not None:
            if target[0] == "board_vertex":
                title = f"PLACA • PONTO {int(target[1]) + 1}"
            elif target[0] == "mask_vertex":
                title = (
                    f"{str(target[1])} • PONTO {int(target[2]) + 1}"
                )
            elif target[0] == "mask":
                mask = self._mask_by_id(str(target[1]))
                title = str(target[1])
                if (
                    mask is not None
                    and str(mask.get("type") or "").lower() == "circle"
                ):
                    radius = max(1.0, float(mask.get("radius", 1)))
                    title = f"CÍRCULO {str(target[1])}"
            return center, radius, title

        cursor = self._precision_cursor
        if isinstance(cursor, tuple) and len(cursor) >= 2:
            return (
                (float(cursor[0]), float(cursor[1])),
                None,
                "CURSOR",
            )
        return None, None, ""

    def _draw_magnifier(self) -> None:
        center, radius, title = self._magnifier_target()
        if center is None or not _valid_frame(self.image):
            try:
                self.canvas.delete("f3_tracking_magnifier")
            except Exception:
                pass
            return

        cx, cy = int(round(center[0])), int(round(center[1]))
        half = 22
        if radius is not None:
            half = max(half, min(48, int(math.ceil(radius * 1.45))))
        x1 = max(0, cx - half)
        y1 = max(0, cy - half)
        x2 = min(self.width, cx + half + 1)
        y2 = min(self.height, cy + half + 1)
        if x2 <= x1 or y2 <= y1:
            return

        crop = self.image[y1:y2, x1:x2].copy()
        if not _valid_frame(crop):
            return
        size = int(F3_EDITOR_MAGNIFIER_SIZE)
        zoom = cv2.resize(
            crop,
            (size, size),
            interpolation=cv2.INTER_NEAREST,
        )
        scale_x = size / max(1.0, float(x2 - x1))
        scale_y = size / max(1.0, float(y2 - y1))
        zx = int(round((float(center[0]) - x1) * scale_x))
        zy = int(round((float(center[1]) - y1) * scale_y))
        zx = max(0, min(size - 1, zx))
        zy = max(0, min(size - 1, zy))

        if radius is not None:
            zr = max(2, int(round(radius * (scale_x + scale_y) / 2.0)))
            overlay = zoom.copy()
            cv2.circle(
                overlay,
                (zx, zy),
                zr,
                (250, 204, 21),
                3,
                cv2.LINE_AA,
            )
            zoom = cv2.addWeighted(zoom, 0.45, overlay, 0.55, 0.0)
            cv2.circle(
                zoom,
                (zx, zy),
                4,
                (248, 189, 56),
                -1,
                cv2.LINE_AA,
            )
            detail = (
                f"PRECISÃO • {title} • X {center[0]:.1f} "
                f"Y {center[1]:.1f} R {radius:.1f}"
            )
        else:
            cv2.line(
                zoom,
                (0, zy),
                (size - 1, zy),
                (94, 234, 212),
                1,
                cv2.LINE_AA,
            )
            cv2.line(
                zoom,
                (zx, 0),
                (zx, size - 1),
                (94, 234, 212),
                1,
                cv2.LINE_AA,
            )
            cv2.circle(
                zoom,
                (zx, zy),
                6,
                (0, 214, 255),
                2,
                cv2.LINE_AA,
            )
            detail = (
                f"PRECISÃO • {title} • X {center[0]:.1f} "
                f"Y {center[1]:.1f}"
            )

        self._magnifier_photo = photo_from_bgr(zoom, size, size)
        if self._magnifier_photo is None:
            return

        cw = max(1, int(self.canvas.winfo_width()))
        ch = max(1, int(self.canvas.winfo_height()))
        x = max(14, cw - size - 24)
        y = 42

        # Se o cursor estiver exatamente sobre a lupa, mova-a para o outro lado
        # para que o ponto de precisão nunca fique escondido.
        cursor = self._precision_cursor
        if isinstance(cursor, tuple) and len(cursor) >= 4:
            canvas_x = float(cursor[2])
            canvas_y = float(cursor[3])
            if (
                x - 18 <= canvas_x <= x + size + 18
                and y - 34 <= canvas_y <= y + size + 20
            ):
                x = 18

        if y + size + 36 > ch:
            y = max(34, ch - size - 36)

        self.canvas.delete("f3_tracking_magnifier")
        self.canvas.create_rectangle(
            x - 8,
            y - 28,
            x + size + 8,
            y + size + 8,
            fill="#020617",
            outline="#38BDF8",
            width=2,
            tags=("f3_tracking_magnifier",),
        )
        self.canvas.create_text(
            x,
            y - 15,
            text=detail,
            fill="#E2E8F0",
            font=("Segoe UI", 7, "bold"),
            anchor="w",
            tags=("f3_tracking_magnifier",),
        )
        self.canvas.create_image(
            x,
            y,
            image=self._magnifier_photo,
            anchor="nw",
            tags=("f3_tracking_magnifier",),
        )
        self.canvas.tag_raise("f3_tracking_magnifier")

    def _draw_zoom_badge(self) -> None:
        self.canvas.delete("f3_tracking_zoom_badge")
        if float(self.view_zoom) <= 1.001:
            return
        self.canvas.create_text(
            14,
            14,
            text=f"ZOOM {float(self.view_zoom):.2f}x • Ctrl + roda",
            fill="#E2E8F0",
            font=("Segoe UI", 8, "bold"),
            anchor="nw",
            tags=("f3_tracking_zoom_badge",),
        )
        self.canvas.tag_raise("f3_tracking_zoom_badge")

    def render(self) -> None:
        self._render_after = None
        if not _valid_frame(self.image):
            return
        selected_id = (
            str(self.selected[1])
            if isinstance(self.selected, tuple)
            and self.selected
            and self.selected[0] in {"mask", "mask_vertex"}
            else None
        )
        decorated = draw_reference_geometry(
            self.image,
            self.board,
            self.masks,
            alpha=0.40,
            selected_mask_id=selected_id,
        )
        self._last_decorated = decorated

        cw = max(120, int(self.canvas.winfo_width()))
        ch = max(120, int(self.canvas.winfo_height()))
        scale, tx, ty = self._view_transform()
        affine = np.asarray(
            [[scale, 0.0, tx], [0.0, scale, ty]],
            dtype=np.float32,
        )
        display = cv2.warpAffine(
            decorated,
            affine,
            (cw, ch),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(2, 6, 23),
        )
        self._photo = photo_from_bgr(display, cw, ch)
        if self._photo is None:
            return

        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")
        self._draw_handles()
        self._draw_mask_numbers()
        self._draw_magnifier()
        self._draw_zoom_badge()
        self.status.configure(
            text=(
                f"Zoom {self.view_zoom * 100:.0f}% • "
                f"{len(self.board)} pontos da placa • {len(self.masks)} máscaras • "
                f"Ctrl+Z: {len(self.history)}/{F3_EDITOR_HISTORY_LIMIT}"
            )
        )

    def save(self) -> None:
        raise NotImplementedError

    def close(self, refresh: bool = False) -> None:
        raise NotImplementedError


def _build_tracking_config_class(base_cls):
    class DisplayF3TrackingProjectConfigWindow(base_cls):
        def __init__(
            self,
            root,
            repository,
            frame_provider,
            on_change=None,
            on_close=None,
            *args,
            **kwargs,
        ) -> None:
            self._f3_tracking_store = F3TrackingConfigStore(repository)
            self._f3_tracking_app = getattr(frame_provider, "__self__", None)
            self._f3_tracking_panel = None
            self._f3_tracking_state_label = None
            self._f3_tracking_enabled_var = tk.BooleanVar(
                master=root,
                value=self._f3_tracking_store.enabled(),
            )
            if self._f3_tracking_app is not None:
                self._f3_tracking_app._display_f3_tracking_config_open = True

            external_on_change = on_change
            external_on_close = on_close

            def on_change_with_tracking_reset():
                self._invalidate_f3_tracking_runtime(notify=False)
                if callable(external_on_change):
                    external_on_change()

            def on_close_with_tracking_resume():
                app = self._f3_tracking_app
                if app is not None:
                    app._display_f3_tracking_config_open = False
                if callable(external_on_close):
                    external_on_close()

            try:
                super().__init__(
                    root=root,
                    repository=repository,
                    frame_provider=frame_provider,
                    on_change=on_change_with_tracking_reset,
                    on_close=on_close_with_tracking_resume,
                    *args,
                    **kwargs,
                )
            except Exception:
                if self._f3_tracking_app is not None:
                    self._f3_tracking_app._display_f3_tracking_config_open = False
                raise
            self._install_f3_tracking_panel()
            self._render_f3_tracking_panel()

        def _invalidate_f3_tracking_runtime(self, *, notify: bool = True) -> None:
            app = self._f3_tracking_app
            if app is not None:
                try:
                    reset_tracking_runtime(app)
                except Exception:
                    pass
            if notify:
                try:
                    self._notify_change()
                except Exception:
                    pass

        def _on_f3_tracking_toggle(self) -> None:
            enabled = bool(self._f3_tracking_enabled_var.get())
            app = self._f3_tracking_app
            if app is not None:
                set_tracking_enabled(app, enabled)
            else:
                self._f3_tracking_store.set_enabled(enabled)
            self._render_f3_tracking_panel()
            self.status.configure(
                text=(
                    "Rastreamento F3 por contorno + segmentos luminosos ativado."
                    if enabled
                    else "Rastreamento automático de objetos do F3 desativado."
                )
            )

        def _install_f3_tracking_panel(self) -> None:
            parent = self.activate_button.master
            panel = tk.Frame(parent, bg="#0F1B2C")
            panel.pack(fill=tk.X, padx=16, pady=(0, 9), before=self.activate_button)
            self._f3_tracking_panel = panel

            tk.Label(
                panel,
                text="RASTREAMENTO AUTOMÁTICO DE OBJETOS • DISPLAY F3",
                font=("Segoe UI", 9, "bold"),
                fg=self.MUTED,
                bg="#0F1B2C",
                anchor="w",
            ).pack(fill=tk.X, padx=12, pady=(10, 4))

            tk.Checkbutton(
                panel,
                text="Ativar rastreamento automático de objetos",
                variable=self._f3_tracking_enabled_var,
                command=self._on_f3_tracking_toggle,
                font=("Segoe UI", 9, "bold"),
                fg=self.TEXT,
                bg="#0F1B2C",
                activebackground="#0F1B2C",
                activeforeground=self.TEXT,
                selectcolor="#020617",
                anchor="w",
            ).pack(fill=tk.X, padx=12, pady=(0, 4))

            tk.Label(
                panel,
                text=(
                    "CONTORNO + SEGMENTOS LUMINOSOS • O contorno salvo em "
                    "'Placa + Máscaras' limita a região de busca. O ODIN procura "
                    "os segmentos que o CHECK espera acesos, ajusta a pose às "
                    "emissões encontradas e então reprojeta/classifica as máscaras. "
                    "Não existem imagens ou slots de rotação 90°/180°/270°."
                ),
                font=("Segoe UI", 8),
                fg=self.MUTED,
                bg="#0F1B2C",
                justify=tk.LEFT,
                wraplength=620,
                anchor="w",
            ).pack(fill=tk.X, padx=12, pady=(0, 5))

            self._f3_tracking_state_label = tk.Label(
                panel,
                text="",
                font=("Segoe UI", 8, "bold"),
                fg=self.MUTED,
                bg="#0F1B2C",
                justify=tk.LEFT,
                anchor="w",
            )
            self._f3_tracking_state_label.pack(fill=tk.X, padx=12, pady=(0, 9))

        def _show_no_project(self) -> None:
            result = super()._show_no_project()
            self._render_f3_tracking_panel()
            return result

        def _load_selected(self) -> None:
            result = super()._load_selected()
            self._render_f3_tracking_panel()
            return result

        def _render_f3_tracking_panel(self) -> None:
            label = self._f3_tracking_state_label
            if label is None:
                return
            project_name = self._selected_name()
            project = self.repository.carregar_projeto(project_name)
            if project is None:
                label.configure(
                    text="Selecione um Projeto Display para validar o contorno.",
                    fg=self.MUTED,
                )
                return
            saved_board = self._f3_tracking_store.board_points(project_name)
            if len(saved_board) >= 3:
                label.configure(
                    text=(
                        f"CONTORNO CONFIGURADO • {len(saved_board)} pontos • "
                        "nenhuma referência angular necessária"
                    ),
                    fg="#86EFAC",
                )
            else:
                label.configure(
                    text=(
                        "CONTORNO NÃO CONFIGURADO • abra 'Placa + Máscaras', "
                        "desenhe o contorno e salve antes da produção."
                    ),
                    fg="#FBBF24",
                )

    DisplayF3TrackingProjectConfigWindow.__name__ = "DisplayF3TrackingProjectConfigWindow"
    return DisplayF3TrackingProjectConfigWindow


def _install_project_lifecycle_hooks() -> None:
    from src.platform.display_project_repository import DisplayProjectRepository

    cls = DisplayProjectRepository
    if bool(getattr(cls, "_odin_f3_tracking_lifecycle_hooks", False)):
        return
    previous_rename = cls.renomear_projeto
    previous_remove = cls.remover_projeto

    def rename(self, old_name: str, new_name: str) -> bool:
        old = normalizar_nome_projeto_display(old_name)
        new = normalizar_nome_projeto_display(new_name)
        changed = previous_rename(self, old_name, new_name)
        if changed and old != new:
            F3TrackingConfigStore(self).rename_project(old, new)
        return changed

    def remove(self, project_name: str) -> bool:
        normalized = normalizar_nome_projeto_display(project_name)
        removed = previous_remove(self, project_name)
        if removed:
            F3TrackingConfigStore(self).remove_project(normalized)
        return removed

    cls.renomear_projeto = rename
    cls.remover_projeto = remove
    cls._odin_f3_tracking_lifecycle_hooks = True


def instalar_ui_rastreamento_objetos_display_f3() -> None:
    """Acrescenta somente a opção de tracking por contorno + segmentos luminosos."""
    global _INSTALLED
    if _INSTALLED:
        return

    _install_project_lifecycle_hooks()
    current = production_module.DisplayProjectConfigWindow
    if not bool(getattr(current, "_odin_f3_object_tracking_ui", False)):
        wrapped = _build_tracking_config_class(current)
        wrapped._odin_f3_object_tracking_ui = True
        wrapped._odin_f3_object_tracking_ui_base = current
        production_module.DisplayProjectConfigWindow = wrapped

    try:
        import src.platform.display_project_config as config_module
        config_module.DisplayProjectConfigWindow = production_module.DisplayProjectConfigWindow
    except Exception:
        pass

    _INSTALLED = True
