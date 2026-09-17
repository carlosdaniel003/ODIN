from __future__ import annotations

"""Ajuste fino dos slots reais 90°/180°/270° do rastreamento F2.

Esta camada complementa o editor ponto a ponto da placa com três recursos:
- overlays mais transparentes somente nas referências angulares;
- uma lupa de precisão para vértices e ROIs circulares;
- correção local de centro/raio das ROIs circulares por slot angular.

As ROIs canônicas do Projeto LED nunca são sobrescritas. As correções circulares
ficam dentro da referência 90°/180°/270° e só são editáveis/aplicadas quando
"Ativar rastreamento automático de objetos" está ativo.
"""

from datetime import datetime, timezone
import math

import cv2
import numpy as np

import src.platform.f2_board_presence_mask_preview_native as preview_native
import src.platform.f2_object_tracking_visual_overlay as visual_overlay
import src.platform.f2_tracking_analysis_rois as analysis_rois
import src.platform.f2_tracking_orientation_references as orientation_refs
import src.platform.f2_tracking_orientation_vertex_editor as vertex_editor
from src.core.roi_geometry import TIPO_ROI_CIRCULO, normalizar_tipo_roi
from src.models.led_selection import LedSelection


F2_ORIENTATION_CIRCLE_OVERRIDES_KEY = "led_circle_reference_overrides"
F2_ORIENTATION_OVERLAY_ALPHA = 0.36
F2_ORIENTATION_BOARD_ALPHA = 0.42
F2_ORIENTATION_CIRCLE_HIT_CANVAS_PX = 12.0
F2_ORIENTATION_MAGNIFIER_SIZE = 210
F2_ORIENTATION_MAGNIFIER_HALF_WINDOW_PX = 22

_PRESERVATION_INSTALLED = False
_PATCH_INSTALLED = False
_ALPHA_CONTEXT_DEPTH = 0


def normalizar_correcoes_circulares_orientacao(valor) -> dict[str, dict[str, float]]:
    if not isinstance(valor, dict):
        return {}
    normalized: dict[str, dict[str, float]] = {}
    for raw_id, raw in valor.items():
        if not isinstance(raw, dict):
            continue
        roi_id = str(raw_id or "").strip()
        if not roi_id:
            continue
        try:
            x = float(raw.get("x"))
            y = float(raw.get("y"))
            radius = float(raw.get("radius"))
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(v) for v in (x, y, radius)) or radius < 1.0:
            continue
        normalized[roi_id] = {
            "x": float(x),
            "y": float(y),
            "radius": float(radius),
        }
    return normalized


def instalar_preservacao_correcoes_circulares_orientacao_f2() -> None:
    global _PRESERVATION_INSTALLED
    if _PRESERVATION_INSTALLED:
        return
    current = orientation_refs._normalizar_entrada
    if bool(getattr(current, "_odin_f2_orientation_circle_overrides", False)):
        _PRESERVATION_INSTALLED = True
        return
    previous = current

    def normalize_with_circle_overrides(entry, slot):
        normalized = previous(entry, slot)
        if not normalized:
            return normalized
        overrides = normalizar_correcoes_circulares_orientacao(
            entry.get(F2_ORIENTATION_CIRCLE_OVERRIDES_KEY)
            if isinstance(entry, dict)
            else None
        )
        if overrides:
            normalized[F2_ORIENTATION_CIRCLE_OVERRIDES_KEY] = overrides
        return normalized

    normalize_with_circle_overrides._odin_f2_orientation_circle_overrides = True
    normalize_with_circle_overrides._odin_f2_orientation_circle_overrides_base = previous
    orientation_refs._normalizar_entrada = normalize_with_circle_overrides
    _PRESERVATION_INSTALLED = True


def _tracking_enabled(app) -> bool:
    variable = getattr(app, "_f2_object_tracking_settings_var", None)
    if variable is not None:
        try:
            return bool(variable.get())
        except Exception:
            pass
    checker = getattr(app, "_f2_tracking_enabled", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False
    return bool(getattr(app, "rastreamento_automatico_f2", False))


def _circle_copy(roi, x: float, y: float, radius: float) -> LedSelection:
    return LedSelection(
        id=str(getattr(roi, "id", "ROI")),
        centro_x=int(round(float(x))),
        centro_y=int(round(float(y))),
        raio=max(1, int(round(float(radius)))),
        tipo_roi=TIPO_ROI_CIRCULO,
    )


def _apply_reference_overrides(rois, entry: dict | None):
    overrides = normalizar_correcoes_circulares_orientacao(
        (entry or {}).get(F2_ORIENTATION_CIRCLE_OVERRIDES_KEY)
        if isinstance(entry, dict)
        else None
    )
    if not overrides:
        return list(rois or ())
    result = []
    for roi in tuple(rois or ()):
        roi_id = str(getattr(roi, "id", ""))
        correction = overrides.get(roi_id)
        if (
            correction is None
            or normalizar_tipo_roi(getattr(roi, "tipo_roi", None)) != TIPO_ROI_CIRCULO
        ):
            result.append(roi)
            continue
        result.append(
            _circle_copy(
                roi,
                correction["x"],
                correction["y"],
                correction["radius"],
            )
        )
    return result


def _matrix_scale(matrix) -> float:
    try:
        affine = np.asarray(matrix, dtype=np.float32).reshape(2, 3)
        sx = math.hypot(float(affine[0, 0]), float(affine[1, 0]))
        sy = math.hypot(float(affine[0, 1]), float(affine[1, 1]))
        return max(1e-6, (sx + sy) / 2.0)
    except Exception:
        return 1.0


def _correct_canonical_circles(rois, entry: dict | None):
    """Converte a correção salva na foto real de volta ao sistema canônico."""
    overrides = normalizar_correcoes_circulares_orientacao(
        (entry or {}).get(F2_ORIENTATION_CIRCLE_OVERRIDES_KEY)
        if isinstance(entry, dict)
        else None
    )
    matrix = orientation_refs.matriz_orientacao_np(entry)
    if not overrides or matrix is None:
        return list(rois or ())
    try:
        inverse = cv2.invertAffineTransform(matrix)
        scale = _matrix_scale(matrix)
    except Exception:
        return list(rois or ())

    result = []
    for roi in tuple(rois or ()):
        roi_id = str(getattr(roi, "id", ""))
        correction = overrides.get(roi_id)
        if (
            correction is None
            or normalizar_tipo_roi(getattr(roi, "tipo_roi", None)) != TIPO_ROI_CIRCULO
        ):
            result.append(roi)
            continue
        point = inverse @ np.asarray(
            [correction["x"], correction["y"], 1.0],
            dtype=np.float32,
        )
        result.append(
            _circle_copy(
                roi,
                float(point[0]),
                float(point[1]),
                float(correction["radius"]) / scale,
            )
        )
    return result


def _entry_for_current_reference(app) -> dict | None:
    if app is None or not _tracking_enabled(app):
        return None
    status = getattr(app, "_f2_object_tracking_last_status", {})
    if not isinstance(status, dict):
        return None
    slot = str(status.get("reference", "") or "")
    if slot not in orientation_refs.F2_ORIENTATION_SLOTS:
        return None
    controller = getattr(app, "_f2_board_presence_refs", None)
    if controller is None:
        return None
    project = str(controller.project_name() or "").strip()
    if not project:
        return None
    entry = orientation_refs._entries(controller, project).get(slot, {})
    if not isinstance(entry, dict) or not entry:
        return None
    return entry


def _enter_alpha_context() -> None:
    global _ALPHA_CONTEXT_DEPTH
    _ALPHA_CONTEXT_DEPTH += 1


def _leave_alpha_context() -> None:
    global _ALPHA_CONTEXT_DEPTH
    _ALPHA_CONTEXT_DEPTH = max(0, _ALPHA_CONTEXT_DEPTH - 1)


def _blend_overlay(base, decorated, alpha: float):
    if (
        base is None
        or decorated is None
        or getattr(base, "size", 0) == 0
        or getattr(decorated, "size", 0) == 0
        or base.shape != decorated.shape
    ):
        return decorated
    try:
        return cv2.addWeighted(
            base,
            max(0.0, min(1.0, 1.0 - float(alpha))),
            decorated,
            max(0.0, min(1.0, float(alpha))),
            0.0,
        )
    except Exception:
        return decorated


def _install_transparent_orientation_overlays() -> None:
    current_led = preview_native.desenhar_rois_na_referencia_f2
    if not bool(getattr(current_led, "_odin_f2_orientation_transparent", False)):
        previous_led = current_led

        def draw_leds_transparent(image, leds):
            result, count = previous_led(image, leds)
            if _ALPHA_CONTEXT_DEPTH <= 0:
                return result, count
            return _blend_overlay(image, result, F2_ORIENTATION_OVERLAY_ALPHA), count

        draw_leds_transparent._odin_f2_orientation_transparent = True
        draw_leds_transparent._odin_f2_orientation_transparent_base = previous_led
        preview_native.desenhar_rois_na_referencia_f2 = draw_leds_transparent

    current_board = preview_native.desenhar_contorno_placa_na_referencia_f2
    if not bool(getattr(current_board, "_odin_f2_orientation_transparent", False)):
        previous_board = current_board

        def draw_board_transparent(image, shape):
            result, count = previous_board(image, shape)
            if _ALPHA_CONTEXT_DEPTH <= 0:
                return result, count
            return _blend_overlay(image, result, F2_ORIENTATION_BOARD_ALPHA), count

        draw_board_transparent._odin_f2_orientation_transparent = True
        draw_board_transparent._odin_f2_orientation_transparent_base = previous_board
        preview_native.desenhar_contorno_placa_na_referencia_f2 = draw_board_transparent


def _working_circle_states(window, base_transformed_leds) -> dict[str, dict[str, float]]:
    try:
        transformed = list(base_transformed_leds(window) or ())
    except Exception:
        transformed = []
    saved = normalizar_correcoes_circulares_orientacao(
        window.entry.get(F2_ORIENTATION_CIRCLE_OVERRIDES_KEY)
        if isinstance(getattr(window, "entry", None), dict)
        else None
    )
    result: dict[str, dict[str, float]] = {}
    for roi in transformed:
        if normalizar_tipo_roi(getattr(roi, "tipo_roi", None)) != TIPO_ROI_CIRCULO:
            continue
        roi_id = str(getattr(roi, "id", ""))
        if not roi_id:
            continue
        correction = saved.get(roi_id)
        if correction is not None:
            result[roi_id] = dict(correction)
        else:
            result[roi_id] = {
                "x": float(getattr(roi, "centro_x", 0)),
                "y": float(getattr(roi, "centro_y", 0)),
                "radius": float(max(1, int(getattr(roi, "raio", 1) or 1))),
            }
    return result


def _apply_matrix_delta_to_circles(window, old_matrix) -> None:
    states = getattr(window, "_odin_orientation_circle_states", None)
    if not isinstance(states, dict) or not states:
        return
    try:
        old_h = np.vstack(
            [np.asarray(old_matrix, dtype=np.float32).reshape(2, 3), [0.0, 0.0, 1.0]]
        )
        new_h = np.vstack(
            [np.asarray(window.matrix, dtype=np.float32).reshape(2, 3), [0.0, 0.0, 1.0]]
        )
        delta = new_h @ np.linalg.inv(old_h)
        linear = delta[:2, :2]
        sx = float(np.linalg.norm(linear[:, 0]))
        sy = float(np.linalg.norm(linear[:, 1]))
        radius_scale = max(1e-6, (sx + sy) / 2.0)
        for state in states.values():
            point = delta @ np.asarray(
                [float(state["x"]), float(state["y"]), 1.0],
                dtype=np.float32,
            )
            state["x"] = float(point[0])
            state["y"] = float(point[1])
            state["radius"] = max(1.0, float(state["radius"]) * radius_scale)
    except Exception:
        pass


def _circle_state_to_roi(roi, state):
    return _circle_copy(roi, state["x"], state["y"], state["radius"])


def _canvas_to_image(window, x: float, y: float):
    return vertex_editor._canvas_to_image(window, x, y)


def _circle_hit(window, canvas_x: float, canvas_y: float):
    if not _tracking_enabled(getattr(window, "app", None)):
        return None
    position = _canvas_to_image(window, canvas_x, canvas_y)
    states = getattr(window, "_odin_orientation_circle_states", None)
    if position is None or not isinstance(states, dict):
        return None
    scale = max(1e-6, float(getattr(window, "_display_scale", 1.0) or 1.0))
    px, py = position
    best = None
    for roi_id, state in states.items():
        dx = float(px) - float(state["x"])
        dy = float(py) - float(state["y"])
        distance = math.hypot(dx, dy)
        radius = max(1.0, float(state["radius"]))
        border_error = abs(distance - radius) * scale
        center_distance = distance * scale
        if border_error <= F2_ORIENTATION_CIRCLE_HIT_CANVAS_PX:
            score = border_error
            candidate = (score, roi_id, "radius")
        elif distance <= radius or center_distance <= F2_ORIENTATION_CIRCLE_HIT_CANVAS_PX:
            score = center_distance + F2_ORIENTATION_CIRCLE_HIT_CANVAS_PX
            candidate = (score, roi_id, "center")
        else:
            continue
        if best is None or candidate[0] < best[0]:
            best = candidate
    return None if best is None else (best[1], best[2])


def _target_at(window, canvas_x: float, canvas_y: float):
    try:
        vertex = vertex_editor._nearest_vertex(window, canvas_x, canvas_y)
    except Exception:
        vertex = None
    if vertex is not None:
        return ("vertex", int(vertex))
    circle = _circle_hit(window, canvas_x, canvas_y)
    if circle is not None:
        return ("circle", str(circle[0]))
    return None


def _draw_circle_handles(window) -> None:
    if not _tracking_enabled(getattr(window, "app", None)):
        return
    states = getattr(window, "_odin_orientation_circle_states", None)
    if not isinstance(states, dict):
        return
    try:
        image = window.image
        height, width = image.shape[:2]
        scale = max(1e-6, float(window._display_scale))
        canvas_w = max(1.0, float(window.canvas.winfo_width()))
        canvas_h = max(1.0, float(window.canvas.winfo_height()))
        offset_x = (canvas_w - float(width) * scale) / 2.0
        offset_y = (canvas_h - float(height) * scale) / 2.0
        selected = getattr(window, "_odin_orientation_circle_selected", None)
        window.canvas.delete("odin_orientation_circle_handle")
        for roi_id, state in states.items():
            cx = offset_x + float(state["x"]) * scale
            cy = offset_y + float(state["y"]) * scale
            rr = max(2.0, float(state["radius"]) * scale)
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
    except Exception:
        pass


def _draw_precision_magnifier(window) -> None:
    target = getattr(window, "_odin_orientation_precision_target", None)
    image = getattr(window, "image", None)
    if target is None or image is None or getattr(image, "size", 0) == 0:
        try:
            window.canvas.delete("odin_orientation_precision_magnifier")
        except Exception:
            pass
        return

    kind, key = target
    center = None
    radius = None
    if kind == "vertex":
        points = getattr(window, "_odin_orientation_vertex_points", None)
        try:
            values = np.asarray(points, dtype=np.float32).reshape(-1, 2)
            if 0 <= int(key) < len(values):
                center = (float(values[int(key), 0]), float(values[int(key), 1]))
        except Exception:
            center = None
    elif kind == "circle":
        states = getattr(window, "_odin_orientation_circle_states", {})
        state = states.get(str(key)) if isinstance(states, dict) else None
        if isinstance(state, dict):
            center = (float(state["x"]), float(state["y"]))
            radius = float(state["radius"])
    if center is None:
        return

    height, width = image.shape[:2]
    half = int(F2_ORIENTATION_MAGNIFIER_HALF_WINDOW_PX)
    if radius is not None:
        half = max(half, min(48, int(math.ceil(radius * 1.45))))
    cx = int(round(center[0]))
    cy = int(round(center[1]))
    x1 = max(0, cx - half)
    y1 = max(0, cy - half)
    x2 = min(width, cx + half + 1)
    y2 = min(height, cy + half + 1)
    if x2 <= x1 or y2 <= y1:
        return
    crop = image[y1:y2, x1:x2].copy()
    if crop.size == 0:
        return

    size = int(F2_ORIENTATION_MAGNIFIER_SIZE)
    zoom = cv2.resize(crop, (size, size), interpolation=cv2.INTER_NEAREST)
    scale_x = size / max(1.0, float(x2 - x1))
    scale_y = size / max(1.0, float(y2 - y1))
    zx = int(round((center[0] - x1) * scale_x))
    zy = int(round((center[1] - y1) * scale_y))
    zx = max(0, min(size - 1, zx))
    zy = max(0, min(size - 1, zy))

    if kind == "circle" and radius is not None:
        zr = max(2, int(round(radius * (scale_x + scale_y) / 2.0)))
        overlay = zoom.copy()
        cv2.circle(overlay, (zx, zy), zr, (250, 204, 21), 3, cv2.LINE_AA)
        zoom = cv2.addWeighted(zoom, 0.45, overlay, 0.55, 0.0)
        cv2.circle(zoom, (zx, zy), 4, (248, 189, 56), -1, cv2.LINE_AA)
        title = f"PRECISÃO • CÍRCULO {key} • X {center[0]:.1f} Y {center[1]:.1f} R {radius:.1f}"
    else:
        cv2.line(zoom, (0, zy), (size - 1, zy), (94, 234, 212), 1, cv2.LINE_AA)
        cv2.line(zoom, (zx, 0), (zx, size - 1), (94, 234, 212), 1, cv2.LINE_AA)
        cv2.circle(zoom, (zx, zy), 6, (0, 214, 255), 2, cv2.LINE_AA)
        title = f"PRECISÃO • PONTO {int(key) + 1} • X {center[0]:.1f} Y {center[1]:.1f}"

    try:
        rgb = cv2.cvtColor(zoom, cv2.COLOR_BGR2RGB)
        pil = orientation_refs.Image.fromarray(rgb)
        photo = orientation_refs.ImageTk.PhotoImage(pil)
        window._odin_orientation_precision_photo = photo
        canvas_w = max(1, int(window.canvas.winfo_width()))
        x = max(14, canvas_w - size - 24)
        y = 46
        window.canvas.delete("odin_orientation_precision_magnifier")
        window.canvas.create_rectangle(
            x - 8,
            y - 28,
            x + size + 8,
            y + size + 8,
            fill="#020617",
            outline="#38BDF8",
            width=2,
            tags=("odin_orientation_precision_magnifier",),
        )
        window.canvas.create_text(
            x,
            y - 15,
            text=title,
            fill="#E2E8F0",
            font=("Segoe UI", 7, "bold"),
            anchor="w",
            tags=("odin_orientation_precision_magnifier",),
        )
        window.canvas.create_image(
            x,
            y,
            image=photo,
            anchor="nw",
            tags=("odin_orientation_precision_magnifier",),
        )
        window.canvas.tag_raise("odin_orientation_precision_magnifier")
    except Exception:
        pass


def _install_calibration_precision_patch() -> None:
    cls = orientation_refs._OrientationCalibrationWindow
    if bool(getattr(cls, "_odin_f2_orientation_precision_roi", False)):
        return

    previous_init = cls.__init__
    previous_transformed_leds = cls.transformed_leds
    previous_translate = cls.translate
    previous_rotate = cls.rotate
    previous_scale = cls.scale
    previous_reset = cls.reset
    previous_start = cls._start_drag
    previous_drag = cls._drag
    previous_stop = cls._stop_drag
    previous_render = cls.render
    previous_save = cls.save

    def init_precision(self, *args, **kwargs):
        previous_init(self, *args, **kwargs)
        self._odin_orientation_circle_states = _working_circle_states(
            self,
            previous_transformed_leds,
        )
        self._odin_orientation_circle_drag = None
        self._odin_orientation_circle_selected = None
        self._odin_orientation_precision_target = None
        self._odin_orientation_precision_photo = None

        def on_motion(event):
            target = _target_at(self, float(event.x), float(event.y))
            if target != getattr(self, "_odin_orientation_precision_target", None):
                self._odin_orientation_precision_target = target
                self.schedule_render()

        def on_leave(_event):
            if getattr(self, "_odin_orientation_circle_drag", None) is None:
                self._odin_orientation_precision_target = None
                self.schedule_render()

        try:
            self.canvas.bind("<Motion>", on_motion, add="+")
            self.canvas.bind("<Leave>", on_leave, add="+")
        except Exception:
            pass
        self.schedule_render()

    def transformed_leds_precision(self):
        base = list(previous_transformed_leds(self) or ())
        states = getattr(self, "_odin_orientation_circle_states", None)
        if not isinstance(states, dict):
            return base
        result = []
        for roi in base:
            roi_id = str(getattr(roi, "id", ""))
            state = states.get(roi_id)
            if (
                state is not None
                and normalizar_tipo_roi(getattr(roi, "tipo_roi", None)) == TIPO_ROI_CIRCULO
            ):
                result.append(_circle_state_to_roi(roi, state))
            else:
                result.append(roi)
        return result

    def translate_precision(self, dx, dy):
        old = np.asarray(self.matrix, dtype=np.float32).copy()
        result = previous_translate(self, dx, dy)
        _apply_matrix_delta_to_circles(self, old)
        return result

    def rotate_precision(self, angle):
        old = np.asarray(self.matrix, dtype=np.float32).copy()
        result = previous_rotate(self, angle)
        _apply_matrix_delta_to_circles(self, old)
        return result

    def scale_precision(self, factor):
        old = np.asarray(self.matrix, dtype=np.float32).copy()
        result = previous_scale(self, factor)
        _apply_matrix_delta_to_circles(self, old)
        return result

    def reset_precision(self):
        result = previous_reset(self)
        self._odin_orientation_circle_states = _working_circle_states(
            self,
            previous_transformed_leds,
        )
        self._odin_orientation_circle_drag = None
        self._odin_orientation_circle_selected = None
        self._odin_orientation_precision_target = None
        self.schedule_render()
        return result

    def start_precision(self, event):
        try:
            vertex = vertex_editor._nearest_vertex(self, float(event.x), float(event.y))
        except Exception:
            vertex = None
        if vertex is not None:
            self._odin_orientation_precision_target = ("vertex", int(vertex))
            return previous_start(self, event)

        hit = _circle_hit(self, float(event.x), float(event.y))
        if hit is None:
            self._odin_orientation_circle_drag = None
            self._odin_orientation_circle_selected = None
            return previous_start(self, event)
        roi_id, mode = hit
        self._odin_orientation_circle_drag = (str(roi_id), str(mode))
        self._odin_orientation_circle_selected = str(roi_id)
        self._odin_orientation_precision_target = ("circle", str(roi_id))
        self._drag_last = None
        try:
            self.canvas.configure(cursor="crosshair")
        except Exception:
            pass
        self.schedule_render()
        return None

    def drag_precision(self, event):
        active = getattr(self, "_odin_orientation_circle_drag", None)
        if active is None:
            result = previous_drag(self, event)
            target = _target_at(self, float(event.x), float(event.y))
            if target is not None:
                self._odin_orientation_precision_target = target
                self.schedule_render()
            return result

        roi_id, mode = active
        states = getattr(self, "_odin_orientation_circle_states", {})
        state = states.get(str(roi_id)) if isinstance(states, dict) else None
        position = _canvas_to_image(self, float(event.x), float(event.y))
        if not isinstance(state, dict) or position is None:
            return None
        x = min(max(float(position[0]), 0.0), max(0.0, float(self.width - 1)))
        y = min(max(float(position[1]), 0.0), max(0.0, float(self.height - 1)))
        if mode == "radius":
            max_radius = max(1.0, min(float(self.width), float(self.height)) / 2.0)
            state["radius"] = min(
                max_radius,
                max(1.0, math.hypot(x - float(state["x"]), y - float(state["y"]))),
            )
        else:
            state["x"] = x
            state["y"] = y
        self._odin_orientation_precision_target = ("circle", str(roi_id))
        self.schedule_render()
        return None

    def stop_precision(self):
        if getattr(self, "_odin_orientation_circle_drag", None) is not None:
            self._odin_orientation_circle_drag = None
            try:
                self.canvas.configure(cursor="fleur")
            except Exception:
                pass
            self.schedule_render()
            return None
        return previous_stop(self)

    def render_precision(self):
        _enter_alpha_context()
        try:
            result = previous_render(self)
        finally:
            _leave_alpha_context()
        _draw_circle_handles(self)
        _draw_precision_magnifier(self)
        return result

    def save_precision(self):
        if _tracking_enabled(getattr(self, "app", None)) and self._shape_inside():
            states = getattr(self, "_odin_orientation_circle_states", None)
            if isinstance(states, dict):
                repository = self.app.config_repository
                config = repository.carregar_configuracao_existente_sem_alerta()
                current = orientation_refs.obter_referencias_orientacao_projeto(
                    config,
                    self.project,
                ).get(self.slot, {})
                if current:
                    current = dict(current)
                    current[F2_ORIENTATION_CIRCLE_OVERRIDES_KEY] = (
                        normalizar_correcoes_circulares_orientacao(states)
                    )
                    current["updated_at"] = datetime.now(timezone.utc).isoformat()
                    config = orientation_refs.definir_referencia_orientacao_projeto(
                        config,
                        self.project,
                        self.slot,
                        current,
                    )
                    orientation_refs.escrever_configuracao(repository, config)
        return previous_save(self)

    cls.__init__ = init_precision
    cls.transformed_leds = transformed_leds_precision
    cls.translate = translate_precision
    cls.rotate = rotate_precision
    cls.scale = scale_precision
    cls.reset = reset_precision
    cls._start_drag = start_precision
    cls._drag = drag_precision
    cls._stop_drag = stop_precision
    cls.render = render_precision
    cls.save = save_precision
    cls._odin_f2_orientation_precision_roi = True


def _install_settings_preview_patch() -> None:
    current_transform = orientation_refs.transformar_rois_para_frame_atual_f2
    if not bool(getattr(current_transform, "_odin_f2_orientation_circle_preview", False)):
        previous_transform = current_transform

        def transform_with_circle_preview(rois, matrix, width, height):
            transformed = previous_transform(rois, matrix, width, height)
            context = getattr(
                orientation_refs,
                "_odin_orientation_vertex_preview_context",
                None,
            )
            if not isinstance(context, dict):
                return transformed
            key = vertex_editor._matrix_key(matrix)
            entry = context.get("entries_by_matrix", {}).get(key)
            if not isinstance(entry, dict):
                return transformed
            # O wrapper de vértices já tratou o contorno da placa. Aqui corrigimos
            # somente círculos com IDs presentes no Projeto LED.
            return _apply_reference_overrides(transformed, entry)

        transform_with_circle_preview._odin_f2_orientation_circle_preview = True
        transform_with_circle_preview._odin_f2_orientation_circle_preview_base = previous_transform
        orientation_refs.transformar_rois_para_frame_atual_f2 = transform_with_circle_preview

    current_render = orientation_refs._render_orientation_section
    if not bool(getattr(current_render, "_odin_f2_orientation_transparency", False)):
        previous_render = current_render

        def render_orientation_transparent(controller, window):
            _enter_alpha_context()
            try:
                return previous_render(controller, window)
            finally:
                _leave_alpha_context()

        render_orientation_transparent._odin_f2_orientation_transparency = True
        render_orientation_transparent._odin_f2_orientation_transparency_base = previous_render
        orientation_refs._render_orientation_section = render_orientation_transparent


def _install_runtime_circle_corrections() -> None:
    current_preview = visual_overlay.preparar_preview_rastreamento_f2
    if not bool(getattr(current_preview, "_odin_f2_orientation_circle_runtime", False)):
        previous_preview = current_preview

        def preview_with_circle_corrections(app, raw_frame):
            result = previous_preview(app, raw_frame)
            entry = _entry_for_current_reference(app)
            if result is None or entry is None:
                return result
            overrides = normalizar_correcoes_circulares_orientacao(
                entry.get(F2_ORIENTATION_CIRCLE_OVERRIDES_KEY)
            )
            if not overrides:
                return result
            tracker = getattr(app, "_f2_object_tracker", None)
            reference_to_current = visual_overlay.inverter_matriz_rastreamento_f2(
                getattr(tracker, "last_matrix", None)
            )
            if reference_to_current is None:
                return result
            _shape, base_leds = visual_overlay._carregar_geometria_visual(app)
            corrected = _correct_canonical_circles(base_leds, entry)
            height, width = raw_frame.shape[:2]
            tracked = visual_overlay.transformar_rois_para_frame_atual_f2(
                corrected,
                reference_to_current,
                int(width),
                int(height),
            )
            if len(tracked) != len(tuple(base_leds or ())):
                return result
            decorated, _old_leds = result
            return decorated, tracked

        preview_with_circle_corrections._odin_f2_orientation_circle_runtime = True
        preview_with_circle_corrections._odin_f2_orientation_circle_runtime_base = previous_preview
        visual_overlay.preparar_preview_rastreamento_f2 = preview_with_circle_corrections

    current_analysis = analysis_rois.obter_rois_rastreadas_analise_f2
    if not bool(getattr(current_analysis, "_odin_f2_orientation_circle_runtime", False)):
        previous_analysis = current_analysis

        def analysis_with_circle_corrections(app, raw_frame):
            nominal = previous_analysis(app, raw_frame)
            entry = _entry_for_current_reference(app)
            if not nominal or entry is None:
                return nominal
            overrides = normalizar_correcoes_circulares_orientacao(
                entry.get(F2_ORIENTATION_CIRCLE_OVERRIDES_KEY)
            )
            if not overrides:
                return nominal
            tracker = getattr(app, "_f2_object_tracker", None)
            reference_to_current = visual_overlay.inverter_matriz_rastreamento_f2(
                getattr(tracker, "last_matrix", None)
            )
            if reference_to_current is None:
                return nominal
            base_rois = analysis_rois._rois_base_analise_f2(app)
            corrected = _correct_canonical_circles(base_rois, entry)
            height, width = raw_frame.shape[:2]
            tracked = visual_overlay.transformar_rois_para_frame_atual_f2(
                corrected,
                reference_to_current,
                int(width),
                int(height),
            )
            if len(tracked) != len(tuple(base_rois or ())):
                return nominal
            return tuple(tracked)

        analysis_with_circle_corrections._odin_f2_orientation_circle_runtime = True
        analysis_with_circle_corrections._odin_f2_orientation_circle_runtime_base = previous_analysis
        analysis_rois.obter_rois_rastreadas_analise_f2 = analysis_with_circle_corrections


def instalar_precisao_rois_referencias_orientacao_f2() -> None:
    """Instala transparência, lupa e edição circular nos três slots angulares."""
    global _PATCH_INSTALLED
    if _PATCH_INSTALLED:
        return
    instalar_preservacao_correcoes_circulares_orientacao_f2()
    _install_transparent_orientation_overlays()
    _install_calibration_precision_patch()
    _install_settings_preview_patch()
    _install_runtime_circle_corrections()
    _PATCH_INSTALLED = True
