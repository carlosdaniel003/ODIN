from __future__ import annotations

"""Correção fina ponto a ponto das referências reais 90°/180°/270° do F2.

A geometria canônica da PCI continua sendo única no Projeto LED. Este módulo não
cria uma segunda ROI de placa: ele guarda, por slot angular, somente a posição
final dos mesmos vértices depois da transformação canônica -> referência. Assim o
operador pode corrigir pequenas diferenças físicas/perspectivas da foto real sem
alterar o contorno base usado em 0° e nos demais slots.
"""

from datetime import datetime, timezone
from tkinter import messagebox

import cv2
import numpy as np

import src.platform.f2_object_tracking_real_orientations as real_orientations
import src.platform.f2_tracking_orientation_references as orientation_refs
from src.core.roi_geometry import pontos_segmento
from src.platform.freeform_segment_roi import criar_segmento_livre_por_pontos


F2_ORIENTATION_BOARD_POINTS_KEY = "board_shape_reference_points"
F2_ORIENTATION_VERTEX_HIT_RADIUS_PX = 16.0

_PRESERVATION_INSTALLED = False
_EDITOR_INSTALLED = False


def normalizar_pontos_contorno_orientacao(valor) -> list[list[float]] | None:
    try:
        points = np.asarray(valor, dtype=np.float32).reshape(-1, 2)
    except Exception:
        return None
    if len(points) < 3 or not np.all(np.isfinite(points)):
        return None
    return [[float(x), float(y)] for x, y in points]


def _pontos_roi(roi) -> np.ndarray | None:
    try:
        points = np.asarray(pontos_segmento(roi), dtype=np.float32).reshape(-1, 2)
    except Exception:
        return None
    return points if len(points) >= 3 else None


def _criar_contorno_pelos_pontos(points, template):
    try:
        return criar_segmento_livre_por_pontos(
            [(float(x), float(y)) for x, y in np.asarray(points).reshape(-1, 2)],
            id_roi=str(getattr(template, "id", "F2_BOARD_SHAPE")),
        )
    except Exception:
        return None


def contorno_referencia_orientacao_f2(
    shape,
    matrix,
    entry: dict | None,
    width: int,
    height: int,
):
    """Retorna o mesmo contorno canônico com a correção local deste slot."""
    transformed = orientation_refs.transformar_rois_para_frame_atual_f2(
        shape,
        matrix,
        int(width),
        int(height),
    )
    if not transformed:
        return transformed

    saved = normalizar_pontos_contorno_orientacao(
        (entry or {}).get(F2_ORIENTATION_BOARD_POINTS_KEY)
        if isinstance(entry, dict)
        else None
    )
    if saved is None:
        return transformed

    base_points = _pontos_roi(transformed[0])
    if base_points is None or len(saved) != len(base_points):
        return transformed

    corrected = _criar_contorno_pelos_pontos(saved, transformed[0])
    return [corrected] if corrected is not None else transformed


def instalar_preservacao_pontos_orientacao_f2() -> None:
    """Faz o normalizador existente preservar os vértices finos por slot."""
    global _PRESERVATION_INSTALLED
    if _PRESERVATION_INSTALLED:
        return

    current = orientation_refs._normalizar_entrada
    if bool(getattr(current, "_odin_f2_orientation_vertices", False)):
        _PRESERVATION_INSTALLED = True
        return
    previous = current

    def normalize_with_vertices(entry, slot):
        normalized = previous(entry, slot)
        if not normalized:
            return normalized
        points = normalizar_pontos_contorno_orientacao(
            entry.get(F2_ORIENTATION_BOARD_POINTS_KEY)
            if isinstance(entry, dict)
            else None
        )
        if points is not None:
            normalized[F2_ORIENTATION_BOARD_POINTS_KEY] = points
        return normalized

    normalize_with_vertices._odin_f2_orientation_vertices = True
    normalize_with_vertices._odin_f2_orientation_vertices_base = previous
    orientation_refs._normalizar_entrada = normalize_with_vertices
    _PRESERVATION_INSTALLED = True


def _matrix_key(matrix) -> tuple[float, ...] | None:
    try:
        value = np.asarray(matrix, dtype=np.float32).reshape(2, 3)
    except Exception:
        return None
    return tuple(float(v) for v in np.round(value.reshape(-1), 5))


def _base_points(window, base_transformed_shape) -> np.ndarray | None:
    try:
        shape = base_transformed_shape(window)
    except Exception:
        return None
    if not shape:
        return None
    return _pontos_roi(shape[0])


def _apply_matrix_delta_to_points(window, old_matrix) -> None:
    points = getattr(window, "_odin_orientation_vertex_points", None)
    if points is None:
        return
    try:
        old_h = np.vstack(
            [np.asarray(old_matrix, dtype=np.float32).reshape(2, 3), [0.0, 0.0, 1.0]]
        )
        new_h = np.vstack(
            [np.asarray(window.matrix, dtype=np.float32).reshape(2, 3), [0.0, 0.0, 1.0]]
        )
        delta = new_h @ np.linalg.inv(old_h)
        values = np.asarray(points, dtype=np.float32).reshape(-1, 2)
        homogeneous = np.concatenate(
            [values, np.ones((len(values), 1), dtype=np.float32)],
            axis=1,
        )
        window._odin_orientation_vertex_points = (homogeneous @ delta.T)[:, :2]
    except Exception:
        pass


def _canvas_to_image(window, x: float, y: float) -> tuple[float, float] | None:
    image = getattr(window, "image", None)
    if image is None or getattr(image, "size", 0) == 0:
        return None
    scale = max(1e-6, float(getattr(window, "_display_scale", 1.0) or 1.0))
    try:
        canvas_w = max(1.0, float(window.canvas.winfo_width()))
        canvas_h = max(1.0, float(window.canvas.winfo_height()))
    except Exception:
        return None
    height, width = image.shape[:2]
    display_w = float(width) * scale
    display_h = float(height) * scale
    offset_x = (canvas_w - display_w) / 2.0
    offset_y = (canvas_h - display_h) / 2.0
    return (
        (float(x) - offset_x) / scale,
        (float(y) - offset_y) / scale,
    )


def _nearest_vertex(window, x: float, y: float) -> int | None:
    position = _canvas_to_image(window, x, y)
    points = getattr(window, "_odin_orientation_vertex_points", None)
    if position is None or points is None:
        return None
    values = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    if not len(values):
        return None
    scale = max(1e-6, float(getattr(window, "_display_scale", 1.0) or 1.0))
    target = np.asarray(position, dtype=np.float32)
    distances = np.linalg.norm(values - target, axis=1) * scale
    index = int(np.argmin(distances))
    return index if float(distances[index]) <= F2_ORIENTATION_VERTEX_HIT_RADIUS_PX else None


def _update_help_text(window) -> None:
    def walk(widget):
        try:
            children = tuple(widget.winfo_children())
        except Exception:
            children = ()
        for child in children:
            yield child
            yield from walk(child)

    for widget in walk(getattr(window, "window", None)):
        try:
            text = str(widget.cget("text"))
        except Exception:
            continue
        if not text.startswith("Arraste a imagem para mover a máscara"):
            continue
        try:
            widget.configure(
                text=(
                    "Arraste um ponto do contorno ciano para corrigir somente aquele vértice. "
                    "Arraste fora dos pontos para mover a máscara inteira. Roda do mouse gira 1°; "
                    "Shift + roda ajusta a escala. SALVAR mantém a mesma ROI canônica e grava apenas "
                    "a correção fina desta rotação."
                )
            )
        except Exception:
            pass
        break


def _install_calibration_window_patch() -> None:
    cls = orientation_refs._OrientationCalibrationWindow
    if bool(getattr(cls, "_odin_f2_orientation_vertex_editor", False)):
        return

    original_init = cls.__init__
    original_transformed_shape = cls.transformed_shape
    original_translate = cls.translate
    original_rotate = cls.rotate
    original_scale = cls.scale
    original_reset = cls.reset
    original_start_drag = cls._start_drag
    original_drag = cls._drag
    original_stop_drag = cls._stop_drag
    original_render = cls.render

    def init_with_vertices(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        base = _base_points(self, original_transformed_shape)
        saved = normalizar_pontos_contorno_orientacao(
            self.entry.get(F2_ORIENTATION_BOARD_POINTS_KEY)
            if isinstance(self.entry, dict)
            else None
        )
        if base is not None and saved is not None and len(saved) == len(base):
            self._odin_orientation_vertex_points = np.asarray(saved, dtype=np.float32)
        else:
            self._odin_orientation_vertex_points = (
                base.copy() if base is not None else None
            )
        self._odin_orientation_vertex_drag_index = None
        self._odin_orientation_vertex_selected_index = None
        _update_help_text(self)
        self.schedule_render()

    def transformed_shape_with_vertices(self):
        base = original_transformed_shape(self)
        points = getattr(self, "_odin_orientation_vertex_points", None)
        if not base or points is None:
            return base
        base_points = _pontos_roi(base[0])
        values = np.asarray(points, dtype=np.float32).reshape(-1, 2)
        if base_points is None or len(values) != len(base_points):
            return base
        corrected = _criar_contorno_pelos_pontos(values, base[0])
        return [corrected] if corrected is not None else base

    def translate_with_vertices(self, dx, dy):
        old = np.asarray(self.matrix, dtype=np.float32).copy()
        result = original_translate(self, dx, dy)
        _apply_matrix_delta_to_points(self, old)
        return result

    def rotate_with_vertices(self, angle):
        old = np.asarray(self.matrix, dtype=np.float32).copy()
        result = original_rotate(self, angle)
        _apply_matrix_delta_to_points(self, old)
        return result

    def scale_with_vertices(self, factor):
        old = np.asarray(self.matrix, dtype=np.float32).copy()
        result = original_scale(self, factor)
        _apply_matrix_delta_to_points(self, old)
        return result

    def reset_with_vertices(self):
        result = original_reset(self)
        base = _base_points(self, original_transformed_shape)
        self._odin_orientation_vertex_points = (
            base.copy() if base is not None else None
        )
        self._odin_orientation_vertex_drag_index = None
        self._odin_orientation_vertex_selected_index = None
        self.schedule_render()
        return result

    def start_drag_with_vertices(self, event):
        index = _nearest_vertex(self, float(event.x), float(event.y))
        if index is None:
            self._odin_orientation_vertex_drag_index = None
            return original_start_drag(self, event)
        self._odin_orientation_vertex_drag_index = int(index)
        self._odin_orientation_vertex_selected_index = int(index)
        self._drag_last = None
        try:
            self.canvas.configure(cursor="crosshair")
        except Exception:
            pass
        self.schedule_render()
        return None

    def drag_with_vertices(self, event):
        index = getattr(self, "_odin_orientation_vertex_drag_index", None)
        if index is None:
            return original_drag(self, event)
        position = _canvas_to_image(self, float(event.x), float(event.y))
        points = getattr(self, "_odin_orientation_vertex_points", None)
        if position is None or points is None:
            return None
        values = np.asarray(points, dtype=np.float32).reshape(-1, 2).copy()
        if not 0 <= int(index) < len(values):
            return None
        x = min(max(float(position[0]), 0.0), max(0.0, float(self.width - 1)))
        y = min(max(float(position[1]), 0.0), max(0.0, float(self.height - 1)))
        values[int(index)] = (x, y)
        self._odin_orientation_vertex_points = values
        self.schedule_render()
        return None

    def stop_drag_with_vertices(self):
        if getattr(self, "_odin_orientation_vertex_drag_index", None) is not None:
            self._odin_orientation_vertex_drag_index = None
            try:
                self.canvas.configure(cursor="fleur")
            except Exception:
                pass
            self.schedule_render()
            return None
        return original_stop_drag(self)

    def render_with_vertices(self):
        result = original_render(self)
        points = getattr(self, "_odin_orientation_vertex_points", None)
        image = getattr(self, "image", None)
        if points is None or image is None or getattr(image, "size", 0) == 0:
            return result
        try:
            values = np.asarray(points, dtype=np.float32).reshape(-1, 2)
            scale = max(1e-6, float(self._display_scale))
            canvas_w = max(1.0, float(self.canvas.winfo_width()))
            canvas_h = max(1.0, float(self.canvas.winfo_height()))
            height, width = image.shape[:2]
            offset_x = (canvas_w - float(width) * scale) / 2.0
            offset_y = (canvas_h - float(height) * scale) / 2.0
            selected = getattr(self, "_odin_orientation_vertex_selected_index", None)
            self.canvas.delete("odin_orientation_vertex_handle")
            for index, (x, y) in enumerate(values):
                cx = offset_x + float(x) * scale
                cy = offset_y + float(y) * scale
                radius = 6.0 if selected == index else 5.0
                fill = "#FBBF24" if selected == index else "#67E8F9"
                self.canvas.create_oval(
                    cx - radius,
                    cy - radius,
                    cx + radius,
                    cy + radius,
                    fill=fill,
                    outline="#0F172A",
                    width=2,
                    tags=("odin_orientation_vertex_handle",),
                )
        except Exception:
            pass
        return result

    def save_with_vertices(self):
        if not self._shape_inside():
            messagebox.showwarning(
                "Contorno fora da imagem",
                "A máscara da placa precisa ficar completamente dentro da imagem antes de salvar.",
                parent=self.window,
            )
            return

        repository = self.app.config_repository
        config = repository.carregar_configuracao_existente_sem_alerta()
        current = orientation_refs.obter_referencias_orientacao_projeto(
            config,
            self.project,
        ).get(self.slot, {})
        if not current:
            return
        current = dict(current)
        current["canonical_to_reference"] = np.asarray(
            self.matrix,
            dtype=np.float32,
        ).reshape(2, 3).tolist()
        points = getattr(self, "_odin_orientation_vertex_points", None)
        normalized_points = normalizar_pontos_contorno_orientacao(points)
        if normalized_points is not None:
            current[F2_ORIENTATION_BOARD_POINTS_KEY] = normalized_points
        else:
            current.pop(F2_ORIENTATION_BOARD_POINTS_KEY, None)
        current["calibrated"] = True
        current["base_shape_updated_at"] = orientation_refs._shape_stamp(
            self.controller,
            self.project,
        )
        current["updated_at"] = datetime.now(timezone.utc).isoformat()
        config = orientation_refs.definir_referencia_orientacao_projeto(
            config,
            self.project,
            self.slot,
            current,
        )
        orientation_refs.escrever_configuracao(repository, config)
        orientation_refs._invalidar_tracking(self.controller)
        self.close(refresh=True)

    cls.__init__ = init_with_vertices
    cls.transformed_shape = transformed_shape_with_vertices
    cls.translate = translate_with_vertices
    cls.rotate = rotate_with_vertices
    cls.scale = scale_with_vertices
    cls.reset = reset_with_vertices
    cls._start_drag = start_drag_with_vertices
    cls._drag = drag_with_vertices
    cls._stop_drag = stop_drag_with_vertices
    cls.render = render_with_vertices
    cls.save = save_with_vertices
    cls._odin_f2_orientation_vertex_editor = True


def _is_board_shape(rois, shape_id: str | None) -> bool:
    values = list(rois or [])
    if len(values) != 1:
        return False
    roi = values[0]
    if shape_id and str(getattr(roi, "id", "")) != str(shape_id):
        return False
    return _pontos_roi(roi) is not None


def _install_settings_preview_patch() -> None:
    current_render = orientation_refs._render_orientation_section
    if bool(getattr(current_render, "_odin_f2_orientation_vertices", False)):
        return
    previous_render = current_render
    previous_transform = orientation_refs.transformar_rois_para_frame_atual_f2

    def transform_with_preview_vertices(rois, matrix, width, height):
        context = getattr(orientation_refs, "_odin_orientation_vertex_preview_context", None)
        if isinstance(context, dict) and _is_board_shape(rois, context.get("shape_id")):
            entry = context.get("entries_by_matrix", {}).get(_matrix_key(matrix))
            if isinstance(entry, dict):
                return contorno_referencia_orientacao_f2(
                    rois,
                    matrix,
                    entry,
                    width,
                    height,
                )
        return previous_transform(rois, matrix, width, height)

    def render_with_preview_vertices(controller, window):
        project = str(controller.project_name() or "").strip()
        resolution = controller.master_resolution(project) if project else None
        entries = orientation_refs._entries(controller, project) if project else {}
        shape = []
        if project and resolution:
            shape = orientation_refs.carregar_contorno_placa_leds(
                controller,
                project,
                int(resolution[0]),
                int(resolution[1]),
            )
        shape_id = str(getattr(shape[0], "id", "")) if shape else None
        by_matrix = {}
        for entry in dict(entries or {}).values():
            points = normalizar_pontos_contorno_orientacao(
                entry.get(F2_ORIENTATION_BOARD_POINTS_KEY)
                if isinstance(entry, dict)
                else None
            )
            matrix = orientation_refs.matriz_orientacao_np(entry)
            key = _matrix_key(matrix) if matrix is not None else None
            if points is not None and key is not None:
                by_matrix[key] = entry

        old_context = getattr(
            orientation_refs,
            "_odin_orientation_vertex_preview_context",
            None,
        )
        orientation_refs._odin_orientation_vertex_preview_context = {
            "shape_id": shape_id,
            "entries_by_matrix": by_matrix,
        }
        try:
            return previous_render(controller, window)
        finally:
            orientation_refs._odin_orientation_vertex_preview_context = old_context

    transform_with_preview_vertices._odin_f2_orientation_vertices = True
    render_with_preview_vertices._odin_f2_orientation_vertices = True
    orientation_refs.transformar_rois_para_frame_atual_f2 = transform_with_preview_vertices
    orientation_refs._render_orientation_section = render_with_preview_vertices


def _rebuild_real_orientation_masks_with_vertices(tracker, controller) -> bool:
    project = str(controller.project_name() or "").strip() if controller is not None else ""
    resolution = controller.master_resolution(project) if project and controller else None
    if not project or not resolution:
        return False
    width, height = int(resolution[0]), int(resolution[1])
    repository = getattr(controller.app, "config_repository", None)
    if repository is None:
        return False
    try:
        config = repository.carregar_configuracao_existente_sem_alerta()
    except Exception:
        return False

    entries = orientation_refs.obter_referencias_orientacao_projeto(config, project)
    stamp = real_orientations._shape_stamp(controller, project)
    shape = orientation_refs.carregar_contorno_placa_leds(
        controller,
        project,
        width,
        height,
    )
    if not shape:
        return False
    leds = tracker._load_leds(controller, project)
    board_major, board_minor = real_orientations._dimensoes_contorno(shape)
    orb = cv2.ORB_create(
        nfeatures=int(real_orientations.F2_REAL_ORIENTATION_ORB_FEATURES),
        scaleFactor=1.2,
        nlevels=8,
        edgeThreshold=int(real_orientations.F2_REAL_ORIENTATION_EDGE_THRESHOLD),
        fastThreshold=int(real_orientations.F2_REAL_ORIENTATION_FAST_THRESHOLD),
    )

    rebuilt = 0
    for slot in orientation_refs.F2_ORIENTATION_SLOTS:
        entry = entries.get(slot, {})
        points = normalizar_pontos_contorno_orientacao(
            entry.get(F2_ORIENTATION_BOARD_POINTS_KEY)
            if isinstance(entry, dict)
            else None
        )
        if points is None or not orientation_refs.referencia_orientacao_calibrada(entry, stamp):
            continue
        image_path = str(entry.get("image_path") or "").strip()
        image = cv2.imread(image_path) if image_path else None
        if image is None or getattr(image, "size", 0) == 0:
            continue
        if image.shape[1] != width or image.shape[0] != height:
            continue
        matrix = orientation_refs.matriz_orientacao_np(entry)
        if matrix is None:
            continue

        corrected_shape = contorno_referencia_orientacao_f2(
            shape,
            matrix,
            entry,
            width,
            height,
        )
        transformed_leds = previous_transform = orientation_refs.transformar_rois_para_frame_atual_f2(
            leds,
            matrix,
            width,
            height,
        )
        if not corrected_shape or (leds and len(transformed_leds) != len(leds)):
            continue
        mask = real_orientations.construir_mascara_rastreamento_f2(
            corrected_shape,
            transformed_leds,
            width,
            height,
        )
        if mask is None:
            continue
        gray = tracker._prepare_gray(image)
        if gray is None:
            continue
        keypoints, descriptors = orb.detectAndCompute(gray, mask)
        if descriptors is None or len(keypoints) < int(real_orientations.F2_TRACKING_MIN_MATCHES):
            continue
        mapped = real_orientations._mapear_keypoints_para_canonico(keypoints, matrix)
        if len(mapped) != len(keypoints) or len(mapped) < int(real_orientations.F2_TRACKING_MIN_MATCHES):
            continue

        tracker.references[slot] = (mapped, descriptors)
        tracker._f2_real_orientation_slots.add(slot)
        view = dict(getattr(tracker, "_f2_real_orientation_views", {}).get(slot, {}) or {})
        view.update(
            {
                "angle": float(orientation_refs.F2_ORIENTATION_ANGLE[slot]),
                "keypoints": mapped,
                "descriptors": descriptors,
                "cardinal": True,
                "board_major": float(board_major),
                "board_minor": float(board_minor),
                "real_orientation": True,
                "orientation_slot": slot,
                "vertex_corrected_mask": True,
            }
        )
        bank = getattr(tracker, "_f2_multiview_bank", None)
        if not isinstance(bank, dict):
            bank = {}
            tracker._f2_multiview_bank = bank
        bank[slot] = [view]
        tracker._f2_real_orientation_views[slot] = view
        rebuilt += 1

    return rebuilt > 0


def _install_real_orientation_runtime_patch() -> None:
    current = real_orientations._carregar_referencias_reais
    if bool(getattr(current, "_odin_f2_orientation_vertices", False)):
        return
    previous = current

    def load_with_vertex_masks(tracker, controller):
        was_configured = bool(
            getattr(tracker, "_f2_real_orientation_configured", False)
        )
        result = bool(previous(tracker, controller))
        signature = getattr(tracker, "_f2_real_orientation_signature", None)
        if (
            was_configured
            and signature is not None
            and getattr(tracker, "_odin_f2_orientation_vertex_signature", None)
            == signature
        ):
            return result
        rebuilt = False
        try:
            rebuilt = _rebuild_real_orientation_masks_with_vertices(tracker, controller)
        except Exception:
            rebuilt = False
        tracker._odin_f2_orientation_vertex_signature = signature
        return bool(result or rebuilt)

    load_with_vertex_masks._odin_f2_orientation_vertices = True
    load_with_vertex_masks._odin_f2_orientation_vertices_base = previous
    real_orientations._carregar_referencias_reais = load_with_vertex_masks


def instalar_editor_vertices_referencias_orientacao_f2() -> None:
    """Ativa edição local de vértices nos três botões Desenhar placa do F2."""
    global _EDITOR_INSTALLED
    if _EDITOR_INSTALLED:
        return
    instalar_preservacao_pontos_orientacao_f2()
    _install_calibration_window_patch()
    _install_settings_preview_patch()
    _install_real_orientation_runtime_patch()
    _EDITOR_INSTALLED = True


instalar_preservacao_pontos_orientacao_f2()
