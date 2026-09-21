from __future__ import annotations

"""Configuração, captura guiada e editor das referências angulares do F3.

A UI é instalada como subclasse da classe final de configuração do Projeto Display.
Nenhuma classe do F2 é alterada. Os três slots 90°/180°/270° usam exclusivamente
F3TrackingConfigStore e as máscaras/checks já existentes do Projeto Display.
"""

import math
import queue
import threading
import tkinter as tk
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox

import cv2
import numpy as np

import src.platform.display_production_f3 as production_module
from src.platform.display_f3_object_tracking import (
    F3_ORIENTATION_ANGLE,
    F3_ORIENTATION_SLOTS,
    F3_ORIENTATION_UI,
    F3TrackingConfigStore,
    _normalize_mask_override,
    _normalize_points,
    _valid_frame,
    canonical_board_points,
    draw_reference_geometry,
    matrix_np,
    nominal_orientation_matrix,
    photo_from_bgr,
    reference_geometry,
    reset_tracking_runtime,
    set_tracking_enabled,
    transform_points,
    transformed_masks,
)
from src.platform.display_project_repository import (
    normalizar_mascaras_display,
    normalizar_nome_projeto_display,
    normalizar_resolucao_display,
)


F3_GUIDED_CAPTURE_INTERVAL_MS = 40
F3_EDITOR_HISTORY_LIMIT = 5
F3_EDITOR_MAGNIFIER_SIZE = 210
F3_EDITOR_VERTEX_HIT_PX = 11.0
F3_EDITOR_MASK_VERTEX_HIT_PX = 10.0
F3_EDITOR_ZOOM_MIN = 1.0
F3_EDITOR_ZOOM_MAX = 5.0
F3_EDITOR_ZOOM_STEP = 1.16
F3_SAFE_WINDOW_MARGIN_X = 64
F3_SAFE_WINDOW_MARGIN_Y = 118
F3_ORIENTATION_PREVIEW_STYLE_VERSION = 3

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


def _save_orientation_image(
    store: F3TrackingConfigStore,
    project: dict,
    slot: str,
    image,
    *,
    calibrated: bool,
) -> bool:
    project_name = normalizar_nome_projeto_display(project.get("name"))
    resolution = normalizar_resolucao_display(project.get("master_resolution"))
    if not project_name or resolution is None or not _valid_frame(image):
        return False
    width, height = int(resolution[0]), int(resolution[1])
    if image.shape[:2] != (height, width):
        return False

    path = store.managed_image_path(project_name, slot)
    if not cv2.imwrite(str(path), image):
        return False
    matrix = nominal_orientation_matrix(project, store, slot)
    if matrix is None:
        return False

    board = transform_points(canonical_board_points(project, store), matrix)
    masks = transformed_masks(project, matrix)
    overrides = {
        str(mask.get("id") or ""): mask
        for mask in masks
        if str(mask.get("id") or "")
    }
    return store.save_orientation(
        project_name,
        slot,
        {
            "image_path": str(path),
            "width": width,
            "height": height,
            "angle_deg": float(F3_ORIENTATION_ANGLE[slot]),
            "canonical_to_reference": matrix.tolist(),
            "calibrated": bool(calibrated),
            "board_points_reference": board,
            "mask_overrides_reference": overrides,
            "masks_reference": deepcopy(masks),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


class F3GuidedOrientationCaptureWindow:
    def __init__(self, owner, slot: str) -> None:
        self.owner = owner
        self.store: F3TrackingConfigStore = owner._f3_tracking_store
        self.slot = slot
        self.project_name = owner._selected_name() or ""
        self.project = owner.repository.carregar_projeto(self.project_name)
        self._photo = None
        self._after_id = None
        self._latest_frame = None
        self._closing = False

        resolution = normalizar_resolucao_display(
            (self.project or {}).get("master_resolution")
        )
        self.width = int(resolution[0]) if resolution else 0
        self.height = int(resolution[1]) if resolution else 0
        self.matrix = (
            nominal_orientation_matrix(self.project, self.store, slot)
            if self.project is not None
            else None
        )
        self.board = (
            transform_points(
                canonical_board_points(self.project, self.store),
                self.matrix,
            )
            if self.project is not None and self.matrix is not None
            else []
        )
        self.masks = (
            transformed_masks(self.project, self.matrix)
            if self.project is not None and self.matrix is not None
            else []
        )

        self.window = tk.Toplevel(owner.window)
        self.window.title(
            f"ODIN • F3 • Captura guiada {F3_ORIENTATION_UI[slot]['short']}"
        )
        self.window.configure(bg="#08111F")
        _fit_toplevel_inside_screen(self.window)
        self.window.transient(owner.window)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        header = tk.Frame(self.window, bg="#111827")
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text=(
                f"DISPLAY F3 • CAPTURA GUIADA • "
                f"{F3_ORIENTATION_UI[slot]['short']}"
            ),
            font=("Segoe UI", 13, "bold"),
            fg="#E5E7EB",
            bg="#111827",
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(12, 3))
        tk.Label(
            header,
            text=(
                "A guia fica fixa. Posicione fisicamente a placa/display até o "
                "contorno CIANO e as máscaras AMARELAS coincidirem com os segmentos. "
                "A captura usa o mesmo frame da câmera do F3; nenhuma segunda câmera é aberta."
            ),
            font=("Segoe UI", 9),
            fg="#CBD5E1",
            bg="#111827",
            anchor="w",
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=16, pady=(0, 9))

        self.canvas = tk.Canvas(
            self.window,
            bg="#020617",
            bd=0,
            highlightthickness=0,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=12, pady=(10, 6))
        self.canvas.bind("<Configure>", lambda _e: self._render_latest())

        footer = tk.Frame(self.window, bg="#111827")
        footer.pack(fill=tk.X, padx=12, pady=(0, 12))
        self.status = tk.Label(
            footer,
            text="AGUARDANDO FRAME DA CÂMERA...",
            font=("Segoe UI", 9, "bold"),
            fg="#FBBF24",
            bg="#111827",
            anchor="w",
        )
        self.status.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8, pady=8)
        tk.Button(
            footer,
            text="CANCELAR",
            command=self.close,
            font=("Segoe UI", 9, "bold"),
            bg="#3A151A",
            fg="#FCA5A5",
            relief=tk.FLAT,
            bd=0,
            padx=16,
            pady=8,
        ).pack(side=tk.RIGHT, padx=(4, 8), pady=6)
        self.capture_button = tk.Button(
            footer,
            text="CAPTURAR",
            command=self.capture,
            state=tk.DISABLED,
            font=("Segoe UI", 9, "bold"),
            bg="#0F3A2B",
            fg="#86EFAC",
            disabledforeground="#64748B",
            relief=tk.FLAT,
            bd=0,
            padx=18,
            pady=8,
        )
        self.capture_button.pack(side=tk.RIGHT, padx=4, pady=6)

        self.window.bind("<Return>", lambda _event: self.capture())
        self.window.bind("<Escape>", lambda _event: self.close())
        try:
            self.window.grab_set()
            self.window.focus_force()
        except Exception:
            pass
        self._schedule(True)

    def _schedule(self, immediate: bool = False) -> None:
        if self._closing:
            return
        try:
            self._after_id = self.window.after(
                1 if immediate else F3_GUIDED_CAPTURE_INTERVAL_MS,
                self._update,
            )
        except Exception:
            self._after_id = None

    def _frame(self):
        try:
            return self.owner.frame_provider()
        except Exception:
            return None

    def _update(self) -> None:
        self._after_id = None
        if self._closing:
            return
        frame = self._frame()
        if not _valid_frame(frame):
            self._latest_frame = None
            self.capture_button.configure(state=tk.DISABLED)
            self.status.configure(
                text="CÂMERA SEM FRAME • mantenha a câmera ativa",
                fg="#FBBF24",
            )
            self._schedule()
            return

        h, w = frame.shape[:2]
        if (w, h) != (self.width, self.height):
            self._latest_frame = None
            self.capture_button.configure(state=tk.DISABLED)
            self.status.configure(
                text=(
                    f"RESOLUÇÃO INCOMPATÍVEL • câmera {w}x{h} • "
                    f"projeto {self.width}x{self.height}"
                ),
                fg="#FCA5A5",
            )
            self._render(frame, overlay=False)
            self._schedule()
            return

        self._latest_frame = frame.copy()
        self.capture_button.configure(state=tk.NORMAL)
        self.status.configure(
            text=(
                f"ALINHE O DISPLAY EM {F3_ORIENTATION_UI[self.slot]['short']} "
                "COM A GUIA E PRESSIONE CAPTURAR"
            ),
            fg="#86EFAC",
        )
        self._render(self._latest_frame, overlay=True)
        self._schedule()

    def _render(self, frame, *, overlay: bool) -> None:
        image = (
            draw_reference_geometry(
                frame,
                self.board,
                self.masks,
                alpha=0.46,
            )
            if overlay
            else frame
        )
        canvas_w = max(120, int(self.canvas.winfo_width()))
        canvas_h = max(120, int(self.canvas.winfo_height()))
        self._photo = photo_from_bgr(image, canvas_w, canvas_h)
        if self._photo is None:
            return
        self.canvas.delete("all")
        self.canvas.create_image(
            canvas_w / 2.0,
            canvas_h / 2.0,
            image=self._photo,
            anchor="center",
        )

    def _render_latest(self) -> None:
        if _valid_frame(self._latest_frame):
            self._render(self._latest_frame, overlay=True)

    def capture(self) -> None:
        if not _valid_frame(self._latest_frame) or self.project is None:
            return
        if not _save_orientation_image(
            self.store,
            self.project,
            self.slot,
            self._latest_frame.copy(),
            calibrated=True,
        ):
            messagebox.showerror(
                "Falha na captura",
                "Não foi possível salvar a referência angular do Display F3.",
                parent=self.window,
            )
            return
        self.close(refresh=True)

    def close(self, refresh: bool = False) -> None:
        if self._closing:
            return
        self._closing = True
        if self._after_id is not None:
            try:
                self.window.after_cancel(self._after_id)
            except Exception:
                pass
        try:
            self.window.grab_release()
        except Exception:
            pass
        try:
            self.window.destroy()
        except Exception:
            pass
        if refresh:
            self.owner._render_f3_tracking_panel()
            self.owner._invalidate_f3_tracking_runtime()


class F3OrientationGeometryEditor:
    def __init__(self, owner, slot: str) -> None:
        self.owner = owner
        self.store: F3TrackingConfigStore = owner._f3_tracking_store
        self.slot = slot
        self.project_name = owner._selected_name() or ""
        self.project = owner.repository.carregar_projeto(self.project_name)
        self.entry = self.store.orientations(self.project_name).get(slot, {})
        self.image = cv2.imread(
            str(self.entry.get("image_path") or ""),
            cv2.IMREAD_COLOR,
        )
        resolution = normalizar_resolucao_display(
            (self.project or {}).get("master_resolution")
        )
        self.width = int(resolution[0]) if resolution else 0
        self.height = int(resolution[1]) if resolution else 0

        stored = matrix_np(self.entry)
        nominal = (
            nominal_orientation_matrix(self.project, self.store, slot)
            if self.project is not None
            else None
        )
        self.nominal = (
            nominal.copy()
            if nominal is not None
            else np.asarray([[1, 0, 0], [0, 1, 0]], dtype=np.float32)
        )
        self.matrix = stored.copy() if stored is not None else self.nominal.copy()
        self.board, self.masks = (
            reference_geometry(self.project, self.store, slot, self.entry)
            if self.project is not None
            else ([], [])
        )
        if not self.board and self.project is not None:
            self.board = transform_points(
                canonical_board_points(self.project, self.store),
                self.matrix,
            )
        if not self.masks and self.project is not None:
            self.masks = transformed_masks(self.project, self.matrix)

        self.history: list[dict] = []
        self.drag_target = None
        self.drag_last_image = None
        self.drag_snapshot_pushed = False
        self.selected = None
        self.draw_board_mode = False
        self.draw_board_points: list[list[float]] = []
        self.redraw_board_committed = False
        self.view_zoom = 1.0
        self.view_pan_x = 0.0
        self.view_pan_y = 0.0
        self._display_scale = 1.0
        self._view_tx = 0.0
        self._view_ty = 0.0
        self._precision_cursor = None
        self._photo = None
        self._magnifier_photo = None
        self._render_after = None
        self._last_decorated = None

        self.window = tk.Toplevel(owner.window)
        self.window.title(
            f"ODIN • F3 • Desenhar placa {F3_ORIENTATION_UI[slot]['short']}"
        )
        self.window.configure(bg="#08111F")
        _fit_toplevel_inside_screen(self.window)
        self.window.transient(owner.window)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        header = tk.Frame(self.window, bg="#111827")
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text=(
                f"F3 • REFERÊNCIA REAL {F3_ORIENTATION_UI[slot]['short']} • "
                "CONTORNO + SEGMENTOS"
            ),
            font=("Segoe UI", 12, "bold"),
            fg="#E5E7EB",
            bg="#111827",
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(10, 2))
        tk.Label(
            header,
            text=(
                "Arraste pontos do contorno ciano ou das máscaras. A lupa de precisão acompanha "
                "o cursor/seleção. Círculo: arraste para mover e roda altera o raio. Setas movem 1 px. "
                "Ctrl+Z desfaz até 5 ações. Ctrl+roda dá zoom ancorado no cursor. "
                "Roda sem seleção gira 1°; Shift+roda escala 1%."
            ),
            font=("Segoe UI", 8),
            fg="#94A3B8",
            bg="#111827",
            anchor="w",
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=16, pady=(0, 8))

        self.canvas = tk.Canvas(
            self.window,
            bg="#020617",
            bd=0,
            highlightthickness=0,
            cursor="crosshair",
        )
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)
        self.canvas.bind("<Configure>", lambda _e: self.schedule_render())
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", self._leave_canvas)
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind(sequence, self._wheel, add="+")

        toolbar = tk.Frame(self.window, bg="#111827")
        toolbar.pack(fill=tk.X, padx=10, pady=(0, 10))

        def button(text, command, bg="#182231", fg="#E5E7EB"):
            tk.Button(
                toolbar,
                text=text,
                command=command,
                font=("Segoe UI", 8, "bold"),
                bg=bg,
                fg=fg,
                relief=tk.FLAT,
                bd=0,
                padx=8,
                pady=7,
            ).pack(side=tk.LEFT, padx=(0, 4))

        button("← 5px", lambda: self.translate_all(-5, 0))
        button("→ 5px", lambda: self.translate_all(5, 0))
        button("↑ 5px", lambda: self.translate_all(0, -5))
        button("↓ 5px", lambda: self.translate_all(0, 5))
        button("ROT -1°", lambda: self.rotate_all(-1.0))
        button("ROT +1°", lambda: self.rotate_all(1.0))
        button("ESC -1%", lambda: self.scale_all(0.99))
        button("ESC +1%", lambda: self.scale_all(1.01))
        button(
            "REDESENHAR PLACA",
            self.start_redraw_board,
            bg="#17314A",
            fg="#7DD3FC",
        )
        button("RESET", self.reset, bg="#3F2B12", fg="#FCD34D")
        tk.Frame(toolbar, bg="#111827").pack(side=tk.LEFT, fill=tk.X, expand=True)
        button("CANCELAR", self.close, bg="#3A151A", fg="#FCA5A5")
        button("SALVAR", self.save, bg="#0F3A2B", fg="#86EFAC")

        self.status = tk.Label(
            self.window,
            text="",
            font=("Segoe UI", 8, "bold"),
            fg="#94A3B8",
            bg="#111827",
            anchor="w",
        )
        self.status.pack(fill=tk.X, padx=14, pady=(0, 8))

        self.window.bind("<Escape>", self._escape)
        self.window.bind("<Return>", self._enter)
        self.window.bind("<Control-z>", lambda _e: self.undo())
        self.window.bind("<Control-Z>", lambda _e: self.undo())
        self.window.bind("<Left>", lambda _e: self._keyboard_move(-1, 0))
        self.window.bind("<Right>", lambda _e: self._keyboard_move(1, 0))
        self.window.bind("<Up>", lambda _e: self._keyboard_move(0, -1))
        self.window.bind("<Down>", lambda _e: self._keyboard_move(0, 1))
        try:
            self.window.grab_set()
            self.window.focus_force()
            self.canvas.focus_set()
        except Exception:
            pass
        self.schedule_render()

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
        if self.project is None or not _valid_frame(self.image):
            return
        if len(self.board) < 3:
            messagebox.showwarning(
                "Contorno necessário",
                "Defina pelo menos 3 pontos para o contorno da placa/display.",
                parent=self.window,
            )
            return
        try:
            inverse = cv2.invertAffineTransform(
                np.asarray(self.matrix, dtype=np.float32).reshape(2, 3)
            )
        except Exception:
            inverse = None

        if (
            inverse is not None
            and (
                not self.store.board_points(self.project_name)
                or self.redraw_board_committed
            )
        ):
            canonical = transform_points(self.board, inverse)
            self.store.save_board_points(self.project_name, canonical)

        overrides = {
            str(mask.get("id") or ""): _normalize_mask_override(mask)
            for mask in self.masks
            if str(mask.get("id") or "")
        }
        overrides = {
            key: value for key, value in overrides.items() if value is not None
        }
        current = dict(self.entry)
        current.update(
            {
                "canonical_to_reference": np.asarray(
                    self.matrix,
                    dtype=np.float32,
                ).reshape(2, 3).tolist(),
                "calibrated": True,
                "board_points_reference": deepcopy(self.board),
                "mask_overrides_reference": overrides,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        if not self.store.save_orientation(self.project_name, self.slot, current):
            messagebox.showerror(
                "Falha ao salvar",
                "Não foi possível salvar os ajustes desta orientação.",
                parent=self.window,
            )
            return
        self.owner._invalidate_f3_tracking_runtime()
        self.close(refresh=True)

    def close(self, refresh: bool = False) -> None:
        try:
            self.window.grab_release()
        except Exception:
            pass
        try:
            self.window.destroy()
        except Exception:
            pass
        if refresh:
            self.owner._render_f3_tracking_panel()


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
            self._f3_tracking_cards = None
            self._f3_tracking_photos: dict[str, object] = {}
            self._f3_tracking_preview_canvases: dict[str, tk.Canvas] = {}
            self._f3_tracking_preview_generation = 0
            self._f3_tracking_preview_cache: dict[tuple, object] = {}
            self._f3_tracking_preview_results = queue.Queue()
            self._f3_tracking_preview_poll_after = None
            self._f3_tracking_enabled_var = tk.BooleanVar(
                master=root,
                value=self._f3_tracking_store.enabled(),
            )

            # Ao abrir configurações, suspendemos somente o ORB/RANSAC pesado do
            # F3. A câmera continua viva para captura de referências, mas nenhuma
            # decisão automática roda enquanto a janela está aberta.
            if self._f3_tracking_app is not None:
                self._f3_tracking_app._display_f3_tracking_config_open = True

            # Qualquer alteração normal do Projeto Display (máscaras, CHECKS,
            # referências, resolução) invalida o banco ORB do F3. Assim o runtime
            # pode permanecer totalmente cacheado entre frames sem ficar lendo
            # configuração do disco no Raspberry.
            external_on_change = on_change
            external_on_close = on_close

            def on_change_with_tracking_reset():
                app = self._f3_tracking_app
                if app is not None:
                    try:
                        reset_tracking_runtime(app)
                    except Exception:
                        pass
                if callable(external_on_change):
                    external_on_change()

            def on_close_with_tracking_resume():
                app = self._f3_tracking_app
                if app is not None:
                    app._display_f3_tracking_config_open = False
                self._f3_tracking_preview_generation += 1
                poll_after = self._f3_tracking_preview_poll_after
                self._f3_tracking_preview_poll_after = None
                if poll_after is not None:
                    try:
                        self.window.after_cancel(poll_after)
                    except Exception:
                        pass
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

        def _invalidate_f3_tracking_runtime(self) -> None:
            app = self._f3_tracking_app
            if app is not None:
                try:
                    reset_tracking_runtime(app)
                except Exception:
                    pass
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
                    "Rastreamento automático de objetos do F3 ativado."
                    if enabled
                    else "Rastreamento automático de objetos do F3 desativado."
                )
            )

        def _install_f3_tracking_panel(self) -> None:
            parent = self.activate_button.master
            panel = tk.Frame(parent, bg="#0F1B2C")
            panel.pack(
                fill=tk.X,
                padx=16,
                pady=(0, 9),
                before=self.activate_button,
            )
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
                    "Configuração exclusiva do F3. Desativada, o Display F3 continua "
                    "exatamente no fluxo atual. Ativada, o frame é localizado e alinhado "
                    "antes de presença, CHECKS, máscaras e análise automática."
                ),
                font=("Segoe UI", 8),
                fg=self.MUTED,
                bg="#0F1B2C",
                justify=tk.LEFT,
                wraplength=620,
                anchor="w",
            ).pack(fill=tk.X, padx=12, pady=(0, 8))

            self._f3_tracking_cards = tk.Frame(panel, bg="#0F1B2C")
            self._f3_tracking_cards.pack(fill=tk.X, padx=8, pady=(0, 9))

        def _show_no_project(self) -> None:
            result = super()._show_no_project()
            if self._f3_tracking_cards is not None:
                self._render_f3_tracking_panel()
            return result

        def _load_selected(self) -> None:
            result = super()._load_selected()
            if self._f3_tracking_cards is not None:
                self._render_f3_tracking_panel()
            return result

        def _render_f3_tracking_panel(self) -> None:
            cards = self._f3_tracking_cards
            if cards is None:
                return
            self._f3_tracking_preview_generation += 1
            generation = int(self._f3_tracking_preview_generation)
            for child in tuple(cards.winfo_children()):
                try:
                    child.destroy()
                except Exception:
                    pass
            self._f3_tracking_photos.clear()
            self._f3_tracking_preview_canvases.clear()

            project_name = self._selected_name()
            project = self.repository.carregar_projeto(project_name)
            enabled = bool(self._f3_tracking_enabled_var.get())
            if project is None:
                tk.Label(
                    cards,
                    text="Selecione um Projeto Display para configurar as orientações.",
                    font=("Segoe UI", 8, "bold"),
                    fg=self.MUTED,
                    bg="#0F1B2C",
                ).pack(fill=tk.X, padx=4, pady=8)
                return

            resolution = normalizar_resolucao_display(project.get("master_resolution"))
            entries = self._f3_tracking_store.orientations(project_name)
            for column in range(3):
                cards.grid_columnconfigure(column, weight=1, uniform="f3_tracking_orientation")

            for column, slot in enumerate(F3_ORIENTATION_SLOTS):
                ui = F3_ORIENTATION_UI[slot]
                entry = entries.get(slot, {})
                card = tk.Frame(
                    cards,
                    bg="#0B1728",
                    highlightthickness=1,
                    highlightbackground="#253247",
                )
                card.grid(
                    row=0,
                    column=column,
                    sticky="nsew",
                    padx=(0 if column == 0 else 4, 0 if column == 2 else 4),
                )
                tk.Label(
                    card,
                    text=ui["title"],
                    font=("Segoe UI", 8, "bold"),
                    fg=ui["color"],
                    bg="#0B1728",
                ).pack(fill=tk.X, padx=7, pady=(7, 4))

                preview = tk.Canvas(
                    card,
                    width=190,
                    height=112,
                    bg="#020617",
                    bd=0,
                    highlightthickness=0,
                )
                preview.pack(fill=tk.X, padx=7, pady=(0, 4))
                self._f3_tracking_preview_canvases[slot] = preview
                if entry and str(entry.get("image_path") or "").strip():
                    preview.create_text(
                        95,
                        56,
                        text="CARREGANDO PREVIEW...",
                        fill="#64748B",
                        font=("Segoe UI", 7, "bold"),
                    )
                else:
                    preview.create_text(
                        95,
                        56,
                        text="SEM IMAGEM",
                        fill="#64748B",
                        font=("Segoe UI", 8, "bold"),
                    )

                calibrated = bool(entry.get("calibrated")) if entry else False
                tk.Label(
                    card,
                    text=(
                        "CALIBRADA"
                        if calibrated
                        else ("AJUSTE PENDENTE" if entry else "SEM REFERÊNCIA")
                    ),
                    font=("Segoe UI", 7, "bold"),
                    fg="#86EFAC" if calibrated else "#FBBF24",
                    bg="#0B1728",
                ).pack(fill=tk.X, padx=7, pady=(0, 4))

                state = (
                    tk.NORMAL
                    if enabled and resolution is not None
                    else tk.DISABLED
                )
                actions = tk.Frame(card, bg="#0B1728")
                actions.pack(fill=tk.X, padx=7, pady=(0, 7))
                self._button(
                    actions,
                    "Capturar câmera",
                    lambda s=slot: self._capture_f3_orientation(s),
                    primary=True,
                ).pack(fill=tk.X)
                self._button(
                    actions,
                    "Carregar imagem",
                    lambda s=slot: self._load_f3_orientation(s),
                ).pack(fill=tk.X, pady=(3, 0))
                draw_button = self._button(
                    actions,
                    "Desenhar placa e máscaras",
                    lambda s=slot: self._edit_f3_orientation(s),
                )
                draw_button.pack(fill=tk.X, pady=(3, 0))

                for widget in actions.winfo_children():
                    try:
                        widget.configure(state=state)
                    except Exception:
                        pass

                if entry:
                    remove = self._button(
                        actions,
                        "Remover",
                        lambda s=slot: self._remove_f3_orientation(s),
                        danger=True,
                    )
                    remove.pack(fill=tk.X, pady=(3, 0))
                    remove.configure(state=tk.NORMAL if enabled else tk.DISABLED)

            # A janela já está pronta e responsiva neste ponto. As imagens são
            # decodificadas e desenhadas fora da thread Tk, uma por vez.
            # O worker não precisa da sequência de CHECKS nem de outros
            # metadados do projeto. Copiar o projeto inteiro aqui era outro custo
            # síncrono perceptível em projetos F3 grandes.
            preview_project = {
                "name": str(project.get("name") or ""),
                "master_resolution": deepcopy(project.get("master_resolution")),
                "masks": deepcopy(project.get("masks", [])),
                "updated_at": str(project.get("updated_at") or ""),
            }
            self._schedule_f3_tracking_previews(
                generation,
                project_name,
                preview_project,
                entries,
            )

        @staticmethod
        def _f3_tracking_preview_key(project_name: str, project: dict, slot: str, entry: dict) -> tuple:
            path = Path(str(entry.get("image_path") or ""))
            try:
                stat = path.stat()
                file_stamp = (int(stat.st_mtime_ns), int(stat.st_size))
            except OSError:
                file_stamp = (0, 0)
            return (
                str(project_name or ""),
                str(slot),
                str(path),
                file_stamp,
                str(entry.get("updated_at") or ""),
                str(project.get("updated_at") or ""),
                F3_ORIENTATION_PREVIEW_STYLE_VERSION,
            )

        def _schedule_f3_tracking_previews(
            self,
            generation: int,
            project_name: str,
            project: dict,
            entries: dict,
        ) -> None:
            jobs = []
            for slot in F3_ORIENTATION_SLOTS:
                entry = entries.get(slot, {}) if isinstance(entries, dict) else {}
                path = str((entry or {}).get("image_path") or "").strip()
                if not path:
                    continue
                key = self._f3_tracking_preview_key(
                    project_name,
                    project,
                    slot,
                    entry,
                )
                jobs.append((slot, deepcopy(entry), key))

            if not jobs:
                return

            def worker() -> None:
                worker_store = F3TrackingConfigStore(self.repository)
                for slot, entry, key in jobs:
                    if generation != self._f3_tracking_preview_generation:
                        return

                    thumbnail = self._f3_tracking_preview_cache.get(key)
                    if thumbnail is None:
                        image = cv2.imread(
                            str(entry.get("image_path") or ""),
                            cv2.IMREAD_COLOR,
                        )
                        if _valid_frame(image):
                            board, masks = reference_geometry(
                                project,
                                worker_store,
                                slot,
                                entry,
                            )
                            # Reduza a FOTO antes de desenhar a geometria. Quando
                            # desenhávamos em 1920x1080 e só depois reduzíamos para
                            # ~184 px, linhas de 2/3 px desapareciam por subpixel.
                            h, w = image.shape[:2]
                            scale = min(184.0 / max(1, w), 106.0 / max(1, h))
                            tw = max(1, int(round(w * scale)))
                            th = max(1, int(round(h * scale)))
                            thumbnail = cv2.resize(
                                image,
                                (tw, th),
                                interpolation=cv2.INTER_AREA,
                            )
                            preview_matrix = np.asarray(
                                [[scale, 0.0, 0.0], [0.0, scale, 0.0]],
                                dtype=np.float32,
                            )
                            board_preview = transform_points(
                                board,
                                preview_matrix,
                            )
                            masks_preview = [
                                _transform_reference_mask(mask, preview_matrix)
                                for mask in tuple(masks or ())
                                if isinstance(mask, dict)
                            ]
                            # Mesmo visual da preview principal de "Máscaras",
                            # mas com traço proporcional ao card menor. Antes,
                            # 2/3 px em uma miniatura de ~184 px fazia dezenas de
                            # segmentos se fundirem numa "caixa" amarela sobre o display.
                            thumbnail = draw_reference_geometry(
                                thumbnail,
                                board_preview,
                                masks_preview,
                                alpha=0.74,
                                board_thickness=2,
                                mask_thickness=1,
                            )
                            self._f3_tracking_preview_cache[key] = thumbnail

                    self._f3_tracking_preview_results.put(
                        (generation, slot, key, thumbnail)
                    )
                self._f3_tracking_preview_results.put(
                    (generation, None, None, None)
                )

            threading.Thread(
                target=worker,
                name="odin-f3-config-preview",
                daemon=True,
            ).start()
            self._schedule_f3_tracking_preview_poll()

        def _schedule_f3_tracking_preview_poll(self) -> None:
            if self._f3_tracking_preview_poll_after is not None:
                return
            try:
                self._f3_tracking_preview_poll_after = self.window.after(
                    24,
                    self._poll_f3_tracking_preview_results,
                )
            except Exception:
                self._f3_tracking_preview_poll_after = None

        def _poll_f3_tracking_preview_results(self) -> None:
            self._f3_tracking_preview_poll_after = None
            done_current_generation = False
            while True:
                try:
                    generation, slot, key, thumbnail = (
                        self._f3_tracking_preview_results.get_nowait()
                    )
                except queue.Empty:
                    break

                if generation != self._f3_tracking_preview_generation:
                    continue
                if slot is None:
                    done_current_generation = True
                    continue
                self._apply_f3_tracking_preview(
                    generation,
                    slot,
                    key,
                    thumbnail,
                )

            if not done_current_generation:
                self._schedule_f3_tracking_preview_poll()

        def _apply_f3_tracking_preview(
            self,
            generation: int,
            slot: str,
            key: tuple,
            thumbnail,
        ) -> None:
            if generation != self._f3_tracking_preview_generation:
                return
            canvas = self._f3_tracking_preview_canvases.get(slot)
            if canvas is None:
                return
            try:
                if not bool(canvas.winfo_exists()):
                    return
            except Exception:
                return

            canvas.delete("all")
            if not _valid_frame(thumbnail):
                canvas.create_text(
                    95,
                    56,
                    text="ARQUIVO AUSENTE",
                    fill="#FCA5A5",
                    font=("Segoe UI", 7, "bold"),
                )
                return
            photo = photo_from_bgr(thumbnail, 184, 106)
            if photo is None:
                return
            self._f3_tracking_photos[slot] = photo
            canvas.create_image(95, 56, image=photo, anchor="center")

        def _capture_f3_orientation(self, slot: str) -> None:
            if not bool(self._f3_tracking_enabled_var.get()):
                return
            project_name = self._selected_name()
            project = self.repository.carregar_projeto(project_name)
            if project is None or normalizar_resolucao_display(
                project.get("master_resolution")
            ) is None:
                messagebox.showwarning(
                    "Projeto necessário",
                    "Selecione um Projeto Display com resolução mestre.",
                    parent=self.window,
                )
                return
            if not normalizar_mascaras_display(project.get("masks", [])):
                messagebox.showwarning(
                    "Máscaras necessárias",
                    "Configure primeiro as máscaras/segmentos do Display.",
                    parent=self.window,
                )
                return
            F3GuidedOrientationCaptureWindow(self, slot)

        def _load_f3_orientation(self, slot: str) -> None:
            if not bool(self._f3_tracking_enabled_var.get()):
                return
            project_name = self._selected_name()
            project = self.repository.carregar_projeto(project_name)
            if project is None:
                return
            resolution = normalizar_resolucao_display(project.get("master_resolution"))
            if resolution is None:
                return
            path = filedialog.askopenfilename(
                parent=self.window,
                title=f"Selecionar referência real {F3_ORIENTATION_UI[slot]['short']} • F3",
                filetypes=[
                    ("Imagens", "*.png *.jpg *.jpeg *.bmp"),
                    ("Todos os arquivos", "*.*"),
                ],
            )
            if not path:
                return
            image = cv2.imread(path, cv2.IMREAD_COLOR)
            if not _valid_frame(image):
                messagebox.showwarning(
                    "Imagem inválida",
                    "Não foi possível ler a imagem selecionada.",
                    parent=self.window,
                )
                return
            if image.shape[:2] != (int(resolution[1]), int(resolution[0])):
                messagebox.showwarning(
                    "Resolução incompatível",
                    (
                        f"O projeto usa {resolution[0]}x{resolution[1]}, mas a imagem "
                        f"possui {image.shape[1]}x{image.shape[0]}."
                    ),
                    parent=self.window,
                )
                return
            if not _save_orientation_image(
                self._f3_tracking_store,
                project,
                slot,
                image,
                calibrated=False,
            ):
                messagebox.showerror(
                    "Falha ao salvar",
                    "Não foi possível salvar a referência angular.",
                    parent=self.window,
                )
                return
            self._render_f3_tracking_panel()
            self._invalidate_f3_tracking_runtime()

        def _edit_f3_orientation(self, slot: str) -> None:
            if not bool(self._f3_tracking_enabled_var.get()):
                return
            project_name = self._selected_name() or ""
            project = self.repository.carregar_projeto(project_name)
            entry = self._f3_tracking_store.orientations(project_name).get(slot, {})
            if project is None or not entry:
                messagebox.showwarning(
                    "Referência necessária",
                    "Capture ou carregue primeiro a imagem deste slot.",
                    parent=self.window,
                )
                return

            resolution = normalizar_resolucao_display(
                project.get("master_resolution")
            )
            image = cv2.imread(
                str(entry.get("image_path") or ""),
                cv2.IMREAD_COLOR,
            )
            if resolution is None or not _valid_frame(image):
                messagebox.showwarning(
                    "Imagem indisponível",
                    "A imagem deste slot não pôde ser carregada.",
                    parent=self.window,
                )
                return

            matrix = matrix_np(entry)
            if matrix is None:
                matrix = nominal_orientation_matrix(
                    project,
                    self._f3_tracking_store,
                    slot,
                )
            if matrix is None:
                matrix = np.asarray(
                    [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                    dtype=np.float32,
                )

            board, masks = reference_geometry(
                project,
                self._f3_tracking_store,
                slot,
                entry,
            )
            has_full_masks = isinstance(entry, dict) and "masks_reference" in entry
            if not board:
                board = transform_points(
                    canonical_board_points(project, self._f3_tracking_store),
                    matrix,
                )
            if not masks and not has_full_masks:
                masks = transformed_masks(project, matrix)

            def save_geometry(board_points, edited_masks) -> bool:
                overrides = {
                    str(mask.get("id") or ""): _normalize_mask_override(mask)
                    for mask in (edited_masks or [])
                    if isinstance(mask, dict) and str(mask.get("id") or "")
                }
                overrides = {
                    key: value
                    for key, value in overrides.items()
                    if value is not None
                }
                full_masks = [
                    normalized
                    for normalized in (
                        _normalize_mask_override(mask)
                        for mask in (edited_masks or [])
                        if isinstance(mask, dict)
                    )
                    if normalized is not None
                ]
                current = dict(entry)
                current.update(
                    {
                        "canonical_to_reference": np.asarray(
                            matrix,
                            dtype=np.float32,
                        ).reshape(2, 3).tolist(),
                        "calibrated": True,
                        "board_points_reference": deepcopy(board_points),
                        "mask_overrides_reference": overrides,
                        "masks_reference": deepcopy(full_masks),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                saved = self._f3_tracking_store.save_orientation(
                    project_name,
                    slot,
                    current,
                )
                if saved:
                    self._invalidate_f3_tracking_runtime()
                    self._render_f3_tracking_panel()
                return bool(saved)

            from src.platform.display_f3_reference_geometry_editor import (
                F3ReferenceGeometryEditor,
            )

            F3ReferenceGeometryEditor(
                parent=self.window,
                image=image,
                width=int(resolution[0]),
                height=int(resolution[1]),
                board_points=board,
                masks=masks,
                on_save=save_geometry,
                title=(
                    f"ODIN • F3 • Desenhar placa "
                    f"{F3_ORIENTATION_UI[slot]['short']}"
                ),
                header_title=(
                    f"F3 • REFERÊNCIA REAL {F3_ORIENTATION_UI[slot]['short']} • "
                    "CONTORNO + MÁSCARAS"
                ),
                on_close=self._render_f3_tracking_panel,
                allow_mask_creation=True,
            )

        def _remove_f3_orientation(self, slot: str) -> None:
            project_name = self._selected_name()
            if not project_name:
                return
            entry = self._f3_tracking_store.orientations(project_name).get(slot, {})
            if not entry:
                return
            if not messagebox.askyesno(
                "Remover referência",
                (
                    f"Remover a referência real "
                    f"{F3_ORIENTATION_UI[slot]['short']} do F3?"
                ),
                parent=self.window,
            ):
                return
            self._f3_tracking_store.remove_orientation(project_name, slot)
            self._render_f3_tracking_panel()
            self._invalidate_f3_tracking_runtime()

    DisplayF3TrackingProjectConfigWindow.__name__ = (
        "DisplayF3TrackingProjectConfigWindow"
    )
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
        store = F3TrackingConfigStore(self)
        data = store._load()
        saved = deepcopy(data.get("projects", {}).get(old))
        changed = previous_rename(self, old_name, new_name)
        if changed and isinstance(saved, dict) and old != new:
            data = store._load()
            data["projects"].pop(old, None)
            data["projects"][new] = saved
            store._write(data)
        return changed

    def remove(self, project_name: str) -> bool:
        normalized = normalizar_nome_projeto_display(project_name)
        store = F3TrackingConfigStore(self)
        entries = store.orientations(normalized)
        removed = previous_remove(self, project_name)
        if removed:
            data = store._load()
            data.get("projects", {}).pop(normalized, None)
            store._write(data)
            for entry in entries.values():
                path = Path(str((entry or {}).get("image_path") or ""))
                try:
                    if path.is_file() and store.image_dir.resolve() in path.resolve().parents:
                        path.unlink()
                except OSError:
                    pass
        return removed

    cls.renomear_projeto = rename
    cls.remover_projeto = remove
    cls._odin_f3_tracking_lifecycle_hooks = True


def instalar_ui_rastreamento_objetos_display_f3() -> None:
    """Acrescenta opção + três slots ao Projeto Display final."""
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
