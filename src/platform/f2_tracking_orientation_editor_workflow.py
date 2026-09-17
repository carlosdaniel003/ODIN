from __future__ import annotations

"""Interação fluida do editor 90°/180°/270° do rastreamento F2.

Esta camada é deliberadamente restrita ao calibrador das referências reais do F2.
Ela troca o render por debounce por um render limitado em frequência, mantém até
cinco estados para Ctrl+Z, acrescenta zoom visual com Ctrl+roda e aproxima a edição
de círculos do comportamento do editor "Selecionar LEDs".
"""

import copy
import math

import cv2
import numpy as np

import src.platform.f2_board_presence_mask_preview_native as preview_native
import src.platform.f2_tracking_orientation_precision_roi_editor as precision
import src.platform.f2_tracking_orientation_references as orientation_refs
import src.platform.f2_tracking_orientation_vertex_editor as vertex_editor


F2_ORIENTATION_HISTORY_LIMIT = 5
F2_ORIENTATION_RENDER_INTERVAL_MS = 28
F2_ORIENTATION_ZOOM_MIN = 1.0
F2_ORIENTATION_ZOOM_MAX = 5.0
F2_ORIENTATION_ZOOM_STEP = 1.16
F2_ORIENTATION_CIRCLE_RADIUS_STEP_PX = 1.0

_PATCH_INSTALLED = False
_ORIGINAL_CANVAS_TO_IMAGE = None


def _ctrl_pressed(event) -> bool:
    try:
        return bool(int(getattr(event, "state", 0) or 0) & 0x0004)
    except Exception:
        return False


def _wheel_direction(event) -> int:
    delta = int(getattr(event, "delta", 0) or 0)
    number = getattr(event, "num", None)
    if delta > 0 or number == 4:
        return 1
    if delta < 0 or number == 5:
        return -1
    return 0


def _copy_points(value):
    if value is None:
        return None
    try:
        return np.asarray(value, dtype=np.float32).reshape(-1, 2).copy()
    except Exception:
        return None


def _snapshot(window) -> dict:
    return {
        "matrix": np.asarray(window.matrix, dtype=np.float32).reshape(2, 3).copy(),
        "points": _copy_points(getattr(window, "_odin_orientation_vertex_points", None)),
        "circles": copy.deepcopy(getattr(window, "_odin_orientation_circle_states", {}) or {}),
        "selected_circle": getattr(window, "_odin_orientation_circle_selected", None),
        "selected_vertex": getattr(window, "_odin_orientation_vertex_selected_index", None),
        "target": copy.deepcopy(getattr(window, "_odin_orientation_precision_target", None)),
    }


def _snapshot_signature(snapshot: dict) -> tuple:
    matrix = np.asarray(snapshot.get("matrix"), dtype=np.float32).reshape(2, 3)
    points = snapshot.get("points")
    point_key = None
    if points is not None:
        point_key = tuple(float(v) for v in np.round(np.asarray(points).reshape(-1), 4))
    circles = snapshot.get("circles", {})
    circle_key = tuple(
        (
            str(key),
            round(float(value.get("x", 0.0)), 4),
            round(float(value.get("y", 0.0)), 4),
            round(float(value.get("radius", 0.0)), 4),
        )
        for key, value in sorted(dict(circles or {}).items())
        if isinstance(value, dict)
    )
    return (
        tuple(float(v) for v in np.round(matrix.reshape(-1), 5)),
        point_key,
        circle_key,
    )


def _push_history(window, snapshot: dict | None = None) -> None:
    if bool(getattr(window, "_odin_orientation_history_restoring", False)):
        return
    history = getattr(window, "_odin_orientation_history", None)
    if not isinstance(history, list):
        history = []
        window._odin_orientation_history = history
    state = snapshot if isinstance(snapshot, dict) else _snapshot(window)
    if history and _snapshot_signature(history[-1]) == _snapshot_signature(state):
        return
    history.append(state)
    del history[:-F2_ORIENTATION_HISTORY_LIMIT]


def _restore_snapshot(window, snapshot: dict) -> None:
    window._odin_orientation_history_restoring = True
    try:
        window.matrix = np.asarray(snapshot["matrix"], dtype=np.float32).reshape(2, 3).copy()
        window._odin_orientation_vertex_points = _copy_points(snapshot.get("points"))
        window._odin_orientation_circle_states = copy.deepcopy(snapshot.get("circles", {}) or {})
        window._odin_orientation_circle_selected = snapshot.get("selected_circle")
        window._odin_orientation_vertex_selected_index = snapshot.get("selected_vertex")
        window._odin_orientation_precision_target = copy.deepcopy(snapshot.get("target"))
        window._odin_orientation_circle_drag = None
        window._drag_last = None
    finally:
        window._odin_orientation_history_restoring = False
    window.schedule_render()


def _undo(window) -> str:
    history = getattr(window, "_odin_orientation_history", None)
    if not isinstance(history, list) or not history:
        return "break"
    _restore_snapshot(window, history.pop())
    return "break"


def _canvas_to_image_with_view(window, x: float, y: float):
    scale = float(getattr(window, "_display_scale", 0.0) or 0.0)
    tx = getattr(window, "_odin_orientation_view_tx", None)
    ty = getattr(window, "_odin_orientation_view_ty", None)
    if scale > 0.0 and tx is not None and ty is not None:
        return (
            (float(x) - float(tx)) / scale,
            (float(y) - float(ty)) / scale,
        )
    if callable(_ORIGINAL_CANVAS_TO_IMAGE):
        return _ORIGINAL_CANVAS_TO_IMAGE(window, x, y)
    return None


def _draw_vertex_handles(window, tx: float, ty: float, scale: float) -> None:
    points = getattr(window, "_odin_orientation_vertex_points", None)
    try:
        values = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    except Exception:
        return
    selected = getattr(window, "_odin_orientation_vertex_selected_index", None)
    window.canvas.delete("odin_orientation_vertex_handle")
    for index, (x, y) in enumerate(values):
        cx = float(tx) + float(x) * float(scale)
        cy = float(ty) + float(y) * float(scale)
        radius = 6.0 if selected == index else 5.0
        fill = "#FBBF24" if selected == index else "#67E8F9"
        window.canvas.create_oval(
            cx - radius,
            cy - radius,
            cx + radius,
            cy + radius,
            fill=fill,
            outline="#0F172A",
            width=2,
            tags=("odin_orientation_vertex_handle",),
        )


def _draw_circle_handles(window, tx: float, ty: float, scale: float) -> None:
    window.canvas.delete("odin_orientation_circle_handle")
    if not precision._tracking_enabled(getattr(window, "app", None)):
        return
    states = getattr(window, "_odin_orientation_circle_states", None)
    if not isinstance(states, dict):
        return
    selected = getattr(window, "_odin_orientation_circle_selected", None)
    for roi_id, state in states.items():
        cx = float(tx) + float(state["x"]) * float(scale)
        cy = float(ty) + float(state["y"]) * float(scale)
        rr = max(2.0, float(state["radius"]) * float(scale))
        active = str(selected or "") == str(roi_id)
        color = "#FBBF24" if active else "#7DD3FC"
        window.canvas.create_oval(
            cx - 4,
            cy - 4,
            cx + 4,
            cy + 4,
            fill=color,
            outline="#0F172A",
            width=1,
            tags=("odin_orientation_circle_handle",),
        )
        hx = cx + rr
        window.canvas.create_rectangle(
            hx - 4,
            cy - 4,
            hx + 4,
            cy + 4,
            fill=color,
            outline="#0F172A",
            width=1,
            tags=("odin_orientation_circle_handle",),
        )


def _draw_zoom_badge(window) -> None:
    try:
        zoom = float(getattr(window, "_odin_orientation_view_zoom", 1.0) or 1.0)
        window.canvas.delete("odin_orientation_zoom_badge")
        if zoom <= 1.001:
            return
        window.canvas.create_text(
            14,
            14,
            text=f"ZOOM {zoom:.2f}x • Ctrl + roda",
            fill="#E2E8F0",
            font=("Segoe UI", 8, "bold"),
            anchor="nw",
            tags=("odin_orientation_zoom_badge",),
        )
        window.canvas.tag_raise("odin_orientation_zoom_badge")
    except Exception:
        pass


def _render_smooth(window) -> None:
    window._render_after = None
    image = getattr(window, "image", None)
    if image is None or getattr(image, "size", 0) == 0:
        return

    try:
        precision._enter_alpha_context()
        try:
            decorated, _ = preview_native.desenhar_rois_na_referencia_f2(
                image,
                window.transformed_leds(),
            )
            decorated, _ = preview_native.desenhar_contorno_placa_na_referencia_f2(
                decorated,
                window.transformed_shape(),
            )
        finally:
            precision._leave_alpha_context()

        canvas_w = max(100, int(window.canvas.winfo_width()))
        canvas_h = max(100, int(window.canvas.winfo_height()))
        height, width = decorated.shape[:2]
        fit = min(canvas_w / float(width), canvas_h / float(height))
        zoom = min(
            F2_ORIENTATION_ZOOM_MAX,
            max(F2_ORIENTATION_ZOOM_MIN, float(getattr(window, "_odin_orientation_view_zoom", 1.0) or 1.0)),
        )
        scale = max(0.01, fit * zoom)
        pan_x = float(getattr(window, "_odin_orientation_view_pan_x", 0.0) or 0.0)
        pan_y = float(getattr(window, "_odin_orientation_view_pan_y", 0.0) or 0.0)
        if zoom <= 1.001:
            pan_x = 0.0
            pan_y = 0.0
            window._odin_orientation_view_pan_x = 0.0
            window._odin_orientation_view_pan_y = 0.0

        tx = canvas_w / 2.0 + pan_x - float(width) * scale / 2.0
        ty = canvas_h / 2.0 + pan_y - float(height) * scale / 2.0
        affine = np.asarray([[scale, 0.0, tx], [0.0, scale, ty]], dtype=np.float32)
        display = cv2.warpAffine(
            decorated,
            affine,
            (canvas_w, canvas_h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(2, 6, 23),
        )
        rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
        pil = orientation_refs.Image.fromarray(rgb)
        photo = orientation_refs.ImageTk.PhotoImage(pil)
        window._photo = photo
        window._display_scale = scale
        window._odin_orientation_view_tx = tx
        window._odin_orientation_view_ty = ty

        item = getattr(window, "_odin_orientation_editor_image_item", None)
        if item is None:
            window.canvas.delete("all")
            item = window.canvas.create_image(
                0,
                0,
                image=photo,
                anchor="nw",
                tags=("odin_orientation_editor_image",),
            )
            window._odin_orientation_editor_image_item = item
        else:
            window.canvas.itemconfigure(item, image=photo)
            window.canvas.coords(item, 0, 0)

        _draw_vertex_handles(window, tx, ty, scale)
        _draw_circle_handles(window, tx, ty, scale)
        precision._draw_precision_magnifier(window)
        _draw_zoom_badge(window)
    except Exception:
        # O editor não pode morrer por uma falha de preview. Um novo evento tenta
        # renderizar novamente mantendo a geometria em memória.
        return


def _zoom_at_cursor(window, event, direction: int) -> str:
    if direction == 0:
        return "break"
    try:
        canvas_w = max(1.0, float(window.canvas.winfo_width()))
        canvas_h = max(1.0, float(window.canvas.winfo_height()))
        image = window.image
        height, width = image.shape[:2]
        old_zoom = float(getattr(window, "_odin_orientation_view_zoom", 1.0) or 1.0)
        new_zoom = old_zoom * (F2_ORIENTATION_ZOOM_STEP if direction > 0 else 1.0 / F2_ORIENTATION_ZOOM_STEP)
        new_zoom = min(F2_ORIENTATION_ZOOM_MAX, max(F2_ORIENTATION_ZOOM_MIN, new_zoom))
        if abs(new_zoom - old_zoom) < 1e-6:
            return "break"

        image_pos = _canvas_to_image_with_view(window, float(event.x), float(event.y))
        fit = min(canvas_w / float(width), canvas_h / float(height))
        new_scale = max(0.01, fit * new_zoom)
        if new_zoom <= 1.001 or image_pos is None:
            pan_x = 0.0
            pan_y = 0.0
        else:
            ix, iy = image_pos
            pan_x = float(event.x) - canvas_w / 2.0 - (float(ix) - width / 2.0) * new_scale
            pan_y = float(event.y) - canvas_h / 2.0 - (float(iy) - height / 2.0) * new_scale

        window._odin_orientation_view_zoom = new_zoom
        window._odin_orientation_view_pan_x = pan_x
        window._odin_orientation_view_pan_y = pan_y
        window.schedule_render()
    except Exception:
        pass
    return "break"


def _selected_circle_under_pointer(window, event):
    if not precision._tracking_enabled(getattr(window, "app", None)):
        return None
    roi_id = getattr(window, "_odin_orientation_circle_selected", None)
    states = getattr(window, "_odin_orientation_circle_states", None)
    if not roi_id or not isinstance(states, dict):
        return None
    state = states.get(str(roi_id))
    position = _canvas_to_image_with_view(window, float(event.x), float(event.y))
    if not isinstance(state, dict) or position is None:
        return None
    distance = math.hypot(
        float(position[0]) - float(state["x"]),
        float(position[1]) - float(state["y"]),
    )
    tolerance = 12.0 / max(1e-6, float(getattr(window, "_display_scale", 1.0) or 1.0))
    if distance <= float(state["radius"]) + tolerance:
        return str(roi_id), state
    return None


def _resize_selected_circle(window, event, direction: int) -> str | None:
    selected = _selected_circle_under_pointer(window, event)
    if selected is None or direction == 0:
        return None
    roi_id, state = selected
    _push_history(window)
    maximum = max(1.0, min(float(window.width), float(window.height)) / 2.0)
    step = float(F2_ORIENTATION_CIRCLE_RADIUS_STEP_PX)
    state["radius"] = min(maximum, max(1.0, float(state["radius"]) + direction * step))
    window._odin_orientation_precision_target = ("circle", roi_id)
    window.schedule_render()
    return "break"


def _move_selected(window, dx: float, dy: float) -> str:
    if precision._tracking_enabled(getattr(window, "app", None)):
        roi_id = getattr(window, "_odin_orientation_circle_selected", None)
        states = getattr(window, "_odin_orientation_circle_states", None)
        state = states.get(str(roi_id)) if roi_id and isinstance(states, dict) else None
        if isinstance(state, dict):
            _push_history(window)
            state["x"] = min(max(0.0, float(state["x"]) + dx), max(0.0, float(window.width - 1)))
            state["y"] = min(max(0.0, float(state["y"]) + dy), max(0.0, float(window.height - 1)))
            window._odin_orientation_precision_target = ("circle", str(roi_id))
            window.schedule_render()
            return "break"

    vertex = getattr(window, "_odin_orientation_vertex_selected_index", None)
    points = getattr(window, "_odin_orientation_vertex_points", None)
    if vertex is not None and points is not None:
        try:
            values = np.asarray(points, dtype=np.float32).reshape(-1, 2).copy()
            index = int(vertex)
            if 0 <= index < len(values):
                _push_history(window)
                values[index, 0] = min(max(0.0, float(values[index, 0]) + dx), max(0.0, float(window.width - 1)))
                values[index, 1] = min(max(0.0, float(values[index, 1]) + dy), max(0.0, float(window.height - 1)))
                window._odin_orientation_vertex_points = values
                window._odin_orientation_precision_target = ("vertex", index)
                window.schedule_render()
                return "break"
        except Exception:
            pass

    window.translate(dx, dy)
    return "break"


def instalar_fluxo_interacao_editor_orientacao_f2() -> None:
    """Ativa render fluido, histórico, zoom e edição estilo Selecionar LEDs."""
    global _PATCH_INSTALLED, _ORIGINAL_CANVAS_TO_IMAGE
    if _PATCH_INSTALLED:
        return

    cls = orientation_refs._OrientationCalibrationWindow
    if bool(getattr(cls, "_odin_f2_orientation_editor_workflow", False)):
        _PATCH_INSTALLED = True
        return

    _ORIGINAL_CANVAS_TO_IMAGE = vertex_editor._canvas_to_image
    vertex_editor._canvas_to_image = _canvas_to_image_with_view

    previous_init = cls.__init__
    previous_translate = cls.translate
    previous_rotate = cls.rotate
    previous_scale = cls.scale
    previous_reset = cls.reset
    previous_start = cls._start_drag
    previous_drag = cls._drag
    previous_stop = cls._stop_drag
    previous_wheel = cls._wheel

    def init_workflow(self, *args, **kwargs):
        previous_init(self, *args, **kwargs)
        self._odin_orientation_history = []
        self._odin_orientation_history_restoring = False
        self._odin_orientation_drag_snapshot = None
        self._odin_orientation_drag_changed = False
        self._odin_orientation_in_drag = False
        self._odin_orientation_view_zoom = 1.0
        self._odin_orientation_view_pan_x = 0.0
        self._odin_orientation_view_pan_y = 0.0
        self._odin_orientation_view_tx = None
        self._odin_orientation_view_ty = None
        self._odin_orientation_editor_image_item = None

        try:
            self.window.bind("<Control-z>", lambda _event: _undo(self))
            self.window.bind("<Control-Z>", lambda _event: _undo(self))
            self.window.bind("<Left>", lambda _event: _move_selected(self, -1.0, 0.0))
            self.window.bind("<Right>", lambda _event: _move_selected(self, 1.0, 0.0))
            self.window.bind("<Up>", lambda _event: _move_selected(self, 0.0, -1.0))
            self.window.bind("<Down>", lambda _event: _move_selected(self, 0.0, 1.0))
        except Exception:
            pass
        self.schedule_render()

    def schedule_throttled(self):
        if getattr(self, "_render_after", None) is not None:
            return
        try:
            self._render_after = self.window.after(
                F2_ORIENTATION_RENDER_INTERVAL_MS,
                self.render,
            )
        except Exception:
            self._render_after = None

    def translate_history(self, dx, dy):
        if not bool(getattr(self, "_odin_orientation_in_drag", False)):
            _push_history(self)
        return previous_translate(self, dx, dy)

    def rotate_history(self, angle):
        if not bool(getattr(self, "_odin_orientation_in_drag", False)):
            _push_history(self)
        return previous_rotate(self, angle)

    def scale_history(self, factor):
        if not bool(getattr(self, "_odin_orientation_in_drag", False)):
            _push_history(self)
        return previous_scale(self, factor)

    def reset_history(self):
        _push_history(self)
        return previous_reset(self)

    def start_history(self, event):
        self._odin_orientation_in_drag = True
        self._odin_orientation_drag_snapshot = _snapshot(self)
        self._odin_orientation_drag_changed = False
        return previous_start(self, event)

    def drag_history(self, event):
        if not bool(getattr(self, "_odin_orientation_drag_changed", False)):
            snapshot = getattr(self, "_odin_orientation_drag_snapshot", None)
            if isinstance(snapshot, dict):
                _push_history(self, snapshot)
            self._odin_orientation_drag_changed = True
        return previous_drag(self, event)

    def stop_history(self):
        try:
            return previous_stop(self)
        finally:
            self._odin_orientation_in_drag = False
            self._odin_orientation_drag_snapshot = None
            self._odin_orientation_drag_changed = False

    def wheel_workflow(self, event):
        direction = _wheel_direction(event)
        if _ctrl_pressed(event):
            return _zoom_at_cursor(self, event, direction)
        resized = _resize_selected_circle(self, event, direction)
        if resized is not None:
            return resized
        return previous_wheel(self, event)

    cls.__init__ = init_workflow
    cls.schedule_render = schedule_throttled
    cls.translate = translate_history
    cls.rotate = rotate_history
    cls.scale = scale_history
    cls.reset = reset_history
    cls._start_drag = start_history
    cls._drag = drag_history
    cls._stop_drag = stop_history
    cls._wheel = wheel_workflow
    cls.render = _render_smooth
    cls._odin_f2_orientation_editor_workflow = True
    _PATCH_INSTALLED = True
