from __future__ import annotations

"""Ajustes finais de interação do editor de precisão angular F2."""

import math

import src.platform.f2_object_tracking_visual_overlay as visual_overlay
import src.platform.f2_tracking_orientation_precision_roi_editor as precision
import src.platform.f2_tracking_orientation_references as orientation_refs
from src.core.roi_geometry import TIPO_ROI_CIRCULO, normalizar_tipo_roi


_PATCH_INSTALLED = False
CENTER_HIT_PX = 9.0
RADIUS_HANDLE_HIT_PX = 12.0


def _circle_hit_center_and_radius_handle(window, canvas_x: float, canvas_y: float):
    """Centro move a ROI; o handle à direita altera somente o raio."""
    if not precision._tracking_enabled(getattr(window, "app", None)):
        return None
    position = precision._canvas_to_image(window, canvas_x, canvas_y)
    states = getattr(window, "_odin_orientation_circle_states", None)
    if position is None or not isinstance(states, dict):
        return None

    scale = max(1e-6, float(getattr(window, "_display_scale", 1.0) or 1.0))
    px, py = float(position[0]), float(position[1])
    best = None
    for roi_id, state in states.items():
        cx = float(state["x"])
        cy = float(state["y"])
        radius = max(1.0, float(state["radius"]))
        center_distance_px = math.hypot(px - cx, py - cy) * scale
        radius_handle_distance_px = math.hypot(px - (cx + radius), py - cy) * scale

        if center_distance_px <= CENTER_HIT_PX:
            candidate = (center_distance_px, str(roi_id), "center")
        elif radius_handle_distance_px <= RADIUS_HANDLE_HIT_PX:
            candidate = (radius_handle_distance_px, str(roi_id), "radius")
        elif math.hypot(px - cx, py - cy) <= radius:
            # Clique dentro do círculo move a ROI. Redimensionamento fica restrito
            # ao pequeno handle quadrado desenhado na borda direita.
            candidate = (
                center_distance_px + RADIUS_HANDLE_HIT_PX,
                str(roi_id),
                "center",
            )
        else:
            continue

        if best is None or candidate[0] < best[0]:
            best = candidate

    return None if best is None else (best[1], best[2])


def _nominal_circle_states(window):
    try:
        transformed = visual_overlay.transformar_rois_para_frame_atual_f2(
            getattr(window, "leds", ()),
            window.matrix,
            int(window.width),
            int(window.height),
        )
    except Exception:
        transformed = []
    result = {}
    for roi in tuple(transformed or ()):
        if normalizar_tipo_roi(getattr(roi, "tipo_roi", None)) != TIPO_ROI_CIRCULO:
            continue
        roi_id = str(getattr(roi, "id", ""))
        if not roi_id:
            continue
        result[roi_id] = {
            "x": float(getattr(roi, "centro_x", 0)),
            "y": float(getattr(roi, "centro_y", 0)),
            "radius": float(max(1, int(getattr(roi, "raio", 1) or 1))),
        }
    return result


def _update_help(window) -> None:
    def walk(widget):
        try:
            children = tuple(widget.winfo_children())
        except Exception:
            children = ()
        for child in children:
            yield child
            yield from walk(child)

    tracking = precision._tracking_enabled(getattr(window, "app", None))
    suffix = (
        "Rastreamento ativo: clique dentro de um círculo para movê-lo e arraste o "
        "pequeno handle na borda direita para ajustar o raio. A lupa mostra o ponto "
        "ou círculo selecionado em zoom."
        if tracking
        else
        "As ROIs circulares ficam somente para visualização porque o rastreamento "
        "automático de objetos está desativado."
    )
    for widget in walk(getattr(window, "window", None)):
        try:
            text = str(widget.cget("text"))
        except Exception:
            continue
        if not text.startswith("Arraste um ponto do contorno ciano"):
            continue
        try:
            widget.configure(text=f"{text} {suffix}")
        except Exception:
            pass
        break


def instalar_ajustes_interacao_precisao_orientacao_f2() -> None:
    global _PATCH_INSTALLED
    if _PATCH_INSTALLED:
        return

    precision._circle_hit = _circle_hit_center_and_radius_handle

    cls = orientation_refs._OrientationCalibrationWindow

    current_init = cls.__init__
    if not bool(getattr(current_init, "_odin_f2_precision_help_fix", False)):
        previous_init = current_init

        def init_with_help(self, *args, **kwargs):
            previous_init(self, *args, **kwargs)
            _update_help(self)

        init_with_help._odin_f2_precision_help_fix = True
        init_with_help._odin_f2_precision_help_fix_base = previous_init
        cls.__init__ = init_with_help

    current_reset = cls.reset
    if not bool(getattr(current_reset, "_odin_f2_precision_reset_fix", False)):
        previous_reset = current_reset

        def reset_to_nominal(self):
            result = previous_reset(self)
            self._odin_orientation_circle_states = _nominal_circle_states(self)
            self._odin_orientation_circle_drag = None
            self._odin_orientation_circle_selected = None
            self._odin_orientation_precision_target = None
            try:
                self.schedule_render()
            except Exception:
                pass
            return result

        reset_to_nominal._odin_f2_precision_reset_fix = True
        reset_to_nominal._odin_f2_precision_reset_fix_base = previous_reset
        cls.reset = reset_to_nominal

    _PATCH_INSTALLED = True
