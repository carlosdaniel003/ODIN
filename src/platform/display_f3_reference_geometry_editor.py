from __future__ import annotations

"""Editor de geometria reutilizável para referências físicas do Display F3.

Reaproveita exatamente a interação visual do editor 90°/180°/270°:
contorno da placa, máscaras, lupa, zoom, arraste, rotação, escala, histórico e
redesenho ponto a ponto. Não possui estados ACESO/APAGADO/IGNORAR.
"""

from copy import deepcopy
from tkinter import messagebox
import math
import tkinter as tk

import numpy as np

from src.platform.display_f3_tracking_orientation_ui import (
    F3OrientationGeometryEditor,
    _fit_toplevel_inside_screen,
    _valid_frame,
)
from src.platform.display_mask_geometry import (
    criar_segmento_display_por_arrasto,
    numero_mascara_display,
    pontos_mascara_display,
)


F3_REFERENCE_HISTORY_LIMIT = 30
F3_MASK_BODY_HIT_PX = 9.0
F3_POLYGON_CLOSE_HIT_PX = 14.0


def _segment_polygon_from_drag(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    mask_id: str,
) -> dict:
    """Cria a forma real de segmento, mas persiste como polígono compatível com o F3."""
    segment = criar_segmento_display_por_arrasto(
        x1,
        y1,
        x2,
        y2,
        id_mascara=str(mask_id),
    )
    return {
        "id": str(mask_id),
        "type": "polygon",
        "points": [
            [float(x), float(y)]
            for x, y in pontos_mascara_display(segment)
        ],
    }


def _mask_display_number(mask: dict, fallback_index: int) -> str:
    """Compatibilidade: a fonte real da numeração é sempre o MASK_ID canônico."""
    return numero_mascara_display(mask, fallback_index)


def _next_available_mask_id(masks) -> str:
    """Reutiliza sempre o menor número MASK_NNN que estiver livre."""
    used_numbers = set()
    for mask in masks or ():
        if not isinstance(mask, dict):
            continue
        mask_id = str(mask.get("id") or "").strip().upper()
        if not mask_id.startswith("MASK_"):
            continue
        suffix = mask_id[5:]
        if suffix.isdigit():
            used_numbers.add(int(suffix))
    index = 1
    while index in used_numbers:
        index += 1
    return f"MASK_{index:03d}"


def _mask_geometry_bounds(mask: dict) -> tuple[float, float, float, float] | None:
    if not isinstance(mask, dict):
        return None
    kind = str(mask.get("type") or "").lower()
    if kind == "circle":
        try:
            cx = float(mask.get("cx", 0))
            cy = float(mask.get("cy", 0))
            radius = max(1.0, float(mask.get("radius", 1)))
        except (TypeError, ValueError):
            return None
        return cx - radius, cy - radius, cx + radius, cy + radius

    points = mask.get("points", [])
    valid = []
    if isinstance(points, (list, tuple)):
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            try:
                valid.append((float(point[0]), float(point[1])))
            except (TypeError, ValueError):
                continue
    if not valid:
        return None
    xs = [point[0] for point in valid]
    ys = [point[1] for point in valid]
    return min(xs), min(ys), max(xs), max(ys)


def _transform_mask_geometry(
    mask: dict,
    *,
    center_x: float,
    center_y: float,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    degrees: float = 0.0,
    dx: float = 0.0,
    dy: float = 0.0,
) -> dict:
    """Transforma uma máscara sem afetar placa ou outras máscaras."""
    result = deepcopy(mask)
    sx = max(0.05, float(scale_x))
    sy = max(0.05, float(scale_y))
    angle = math.radians(float(degrees))
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    cx = float(center_x)
    cy = float(center_y)

    def transform_point(x: float, y: float) -> list[float]:
        px = (float(x) - cx) * sx
        py = (float(y) - cy) * sy
        rx = px * cos_a - py * sin_a
        ry = px * sin_a + py * cos_a
        return [rx + cx + float(dx), ry + cy + float(dy)]

    kind = str(result.get("type") or "").lower()
    if kind == "circle":
        try:
            mask_cx = float(result.get("cx", 0))
            mask_cy = float(result.get("cy", 0))
            radius = max(1.0, float(result.get("radius", 1)))
        except (TypeError, ValueError):
            return result
        transformed_center = transform_point(mask_cx, mask_cy)
        if abs(sx - sy) <= 1e-6:
            result["cx"] = transformed_center[0]
            result["cy"] = transformed_center[1]
            result["radius"] = max(1.0, radius * sx)
            return result

        # Esticar um círculo produz elipse; o F3 persiste isso como polígono.
        points = []
        for index in range(32):
            theta = (2.0 * math.pi * index) / 32.0
            points.append(
                transform_point(
                    mask_cx + radius * math.cos(theta),
                    mask_cy + radius * math.sin(theta),
                )
            )
        result["type"] = "polygon"
        result["points"] = points
        result.pop("cx", None)
        result.pop("cy", None)
        result.pop("radius", None)
        return result

    points = result.get("points", [])
    transformed = []
    if isinstance(points, (list, tuple)):
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            try:
                transformed.append(transform_point(float(point[0]), float(point[1])))
            except (TypeError, ValueError):
                continue
    if transformed:
        result["type"] = "polygon"
        result["points"] = transformed
    return result


def _distance_point_to_segment(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> float:
    vx = float(bx) - float(ax)
    vy = float(by) - float(ay)
    wx = float(px) - float(ax)
    wy = float(py) - float(ay)
    length_sq = vx * vx + vy * vy
    if length_sq <= 1e-9:
        return math.hypot(float(px) - float(ax), float(py) - float(ay))
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / length_sq))
    cx = float(ax) + t * vx
    cy = float(ay) + t * vy
    return math.hypot(float(px) - cx, float(py) - cy)


class F3ReferenceGeometryEditor(F3OrientationGeometryEditor):
    """Mesmo editor geométrico das orientações, sem semântica de CHECK."""

    def __init__(
        self,
        *,
        parent,
        image,
        width: int,
        height: int,
        board_points,
        masks,
        on_save,
        title: str,
        header_title: str,
        on_close=None,
        allow_mask_creation: bool = False,
    ) -> None:
        self.owner = None
        self.store = None
        self.slot = "reference_geometry"
        self.project_name = ""
        self.project = {}
        self.entry = {}
        self.image = image.copy() if _valid_frame(image) else image
        self.width = max(1, int(width))
        self.height = max(1, int(height))

        self.nominal = np.asarray(
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            dtype=np.float32,
        )
        self.matrix = self.nominal.copy()
        self.board = deepcopy(list(board_points or []))
        self.masks = deepcopy(list(masks or []))
        self._initial_board = deepcopy(self.board)
        self._initial_masks = deepcopy(self.masks)
        self._on_save_reference_geometry = on_save
        self._on_close_reference_geometry = on_close
        self.allow_mask_creation = bool(allow_mask_creation)
        self.mask_draw_mode = None
        self.mask_draw_start = None
        self.mask_draw_current = None
        self.mask_draw_points: list[list[float]] = []
        self.mask_draw_buttons: dict[str, tk.Button] = {}
        self.mask_draw_button_labels: dict[str, str] = {}
        self.selected_mask_ids: set[str] = set()
        self.transform_drag_initial_masks: dict[str, dict] = {}
        self.transform_drag_bounds = None
        self.transform_drag_start_canvas = None
        self.transform_drag_start_image = None
        self.view_pan_active = False
        self.view_pan_last: tuple[float, float] | None = None

        self.history: list[dict] = []
        self.drag_target = None
        self.drag_last_image = None
        self.drag_snapshot_pushed = False
        self.selected = None
        self.selected_mask_ids.clear()
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

        self.window = tk.Toplevel(parent)
        self.window.title(str(title))
        self.window.configure(bg="#08111F")
        _fit_toplevel_inside_screen(self.window)
        self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        header = tk.Frame(self.window, bg="#111827")
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text=str(header_title),
            font=("Segoe UI", 12, "bold"),
            fg="#E5E7EB",
            bg="#111827",
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(10, 2))
        tk.Label(
            header,
            text=(
                (
                    "Desenhe e ajuste placa + máscaras. Use a barra MÁSCARAS para criar "
                    "segmento, círculo ou polígono por pontos. "
                    if self.allow_mask_creation
                    else "Ajuste somente a geometria. "
                )
                + "Selecione uma máscara e arraste para mover somente ela. Pontos/vértices "
                  "ajustam apenas a forma selecionada. Setas movem 1 px; Shift+setas movem "
                  "5 px. Ctrl+Z desfaz até 30 ações. Ctrl+roda dá zoom; rodinha pressionada "
                  "move a visualização ampliada."
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
        self.canvas.bind("<ButtonPress-2>", self._start_view_pan)
        self.canvas.bind("<B2-Motion>", self._drag_view_pan)
        self.canvas.bind("<ButtonRelease-2>", self._end_view_pan)
        self.canvas.bind("<Delete>", self.delete_selected_mask)
        self.canvas.bind("<BackSpace>", self.delete_selected_mask)
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

        tk.Label(
            toolbar,
            text="GLOBAL",
            font=("Segoe UI", 8, "bold"),
            fg="#94A3B8",
            bg="#111827",
        ).pack(side=tk.LEFT, padx=(4, 8))
        button("←5", lambda: self.translate_all(-5, 0))
        button("→5", lambda: self.translate_all(5, 0))
        button("↑5", lambda: self.translate_all(0, -5))
        button("↓5", lambda: self.translate_all(0, 5))
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

        self.mask_toolbar = tk.Frame(self.window, bg="#0B1728")
        self.mask_toolbar.pack(fill=tk.X, padx=10, pady=(0, 8))
        tk.Label(
            self.mask_toolbar,
            text="MÁSCARAS",
            font=("Segoe UI", 8, "bold"),
            fg="#94A3B8",
            bg="#0B1728",
        ).pack(side=tk.LEFT, padx=(6, 10))

        def mask_button(
            text,
            mode=None,
            command=None,
            danger=False,
            key=None,
        ):
            callback = command or (lambda value=mode: self.set_mask_draw_mode(value))
            widget = tk.Button(
                self.mask_toolbar,
                text=text,
                command=callback,
                font=("Segoe UI", 8, "bold"),
                bg="#3A151A" if danger else "#17314A",
                fg="#FCA5A5" if danger else "#7DD3FC",
                activebackground="#1E4668",
                activeforeground="#FFFFFF",
                relief=tk.FLAT,
                bd=0,
                padx=10,
                pady=6,
                cursor="hand2",
            )
            widget.pack(side=tk.LEFT, padx=(0, 4))
            if not danger and key:
                key_name = str(key)
                self.mask_draw_buttons[key_name] = widget
                self.mask_draw_button_labels[key_name] = str(text)
            return widget

        mask_button("SELECIONAR", mode=None, key="select")
        if self.allow_mask_creation:
            mask_button("+ SEGMENTO", mode="segment", key="segment")
            mask_button("+ CÍRCULO", mode="circle", key="circle")
            mask_button("+ POR PONTOS", mode="polygon", key="polygon")
        mask_button("SELECIONAR TUDO", command=self.select_all_masks)
        mask_button("LIMPAR SELEÇÃO", command=self.clear_mask_selection)
        if self.allow_mask_creation:
            mask_button(
                "EXCLUIR MÁSCARA",
                command=self.delete_selected_mask,
                danger=True,
            )
        self._update_mask_draw_buttons()

        self.mask_transform_toolbar = tk.Frame(self.window, bg="#0A1322")
        self.mask_transform_toolbar.pack(fill=tk.X, padx=10, pady=(0, 8))
        tk.Label(
            self.mask_transform_toolbar,
            text="EDIÇÃO DA SELEÇÃO",
            font=("Segoe UI", 8, "bold"),
            fg="#94A3B8",
            bg="#0A1322",
        ).pack(side=tk.LEFT, padx=(6, 10))

        def transform_button(text, command):
            tk.Button(
                self.mask_transform_toolbar,
                text=text,
                command=command,
                font=("Segoe UI", 8, "bold"),
                bg="#172033",
                fg="#CBD5E1",
                activebackground="#25324A",
                activeforeground="#FFFFFF",
                relief=tk.FLAT,
                bd=0,
                padx=7,
                pady=5,
                cursor="hand2",
            ).pack(side=tk.LEFT, padx=(0, 4))

        transform_button("←1", lambda: self.transform_selected(dx=-1))
        transform_button("→1", lambda: self.transform_selected(dx=1))
        transform_button("↑1", lambda: self.transform_selected(dy=-1))
        transform_button("↓1", lambda: self.transform_selected(dy=1))
        transform_button("MENOR -5%", lambda: self.transform_selected(scale_x=0.95, scale_y=0.95))
        transform_button("MAIOR +5%", lambda: self.transform_selected(scale_x=1.05, scale_y=1.05))
        transform_button("X -5%", lambda: self.transform_selected(scale_x=0.95, scale_y=1.0))
        transform_button("X +5%", lambda: self.transform_selected(scale_x=1.05, scale_y=1.0))
        transform_button("Y -5%", lambda: self.transform_selected(scale_x=1.0, scale_y=0.95))
        transform_button("Y +5%", lambda: self.transform_selected(scale_x=1.0, scale_y=1.05))
        transform_button("ROT -1°", lambda: self.transform_selected(degrees=-1.0))
        transform_button("ROT +1°", lambda: self.transform_selected(degrees=1.0))

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
        self.window.bind("<Control-a>", self.select_all_masks)
        self.window.bind("<Control-A>", self.select_all_masks)
        self.window.bind("<Control-d>", self.clear_mask_selection)
        self.window.bind("<Control-D>", self.clear_mask_selection)
        self.window.bind("<Delete>", self.delete_selected_mask)
        self.window.bind("<BackSpace>", self.delete_selected_mask)
        self.window.bind("<Left>", lambda _e: self._keyboard_move(-1, 0))
        self.window.bind("<Right>", lambda _e: self._keyboard_move(1, 0))
        self.window.bind("<Up>", lambda _e: self._keyboard_move(0, -1))
        self.window.bind("<Down>", lambda _e: self._keyboard_move(0, 1))
        self.window.bind("<Shift-Left>", lambda _e: self._keyboard_move(-5, 0))
        self.window.bind("<Shift-Right>", lambda _e: self._keyboard_move(5, 0))
        self.window.bind("<Shift-Up>", lambda _e: self._keyboard_move(0, -5))
        self.window.bind("<Shift-Down>", lambda _e: self._keyboard_move(0, 5))
        try:
            self.window.grab_set()
            self.window.focus_force()
            self.canvas.focus_set()
        except Exception:
            pass
        self.schedule_render()

    def _snapshot(self) -> dict:
        state = super()._snapshot()
        state["selected_mask_ids"] = sorted(self.selected_mask_ids)
        return state

    def _push_history(self, snapshot=None) -> None:
        """Histórico maior no editor operacional F3, sem alterar outros editores."""
        self.history.append(
            snapshot if isinstance(snapshot, dict) else self._snapshot()
        )
        if len(self.history) > F3_REFERENCE_HISTORY_LIMIT:
            self.history = self.history[-F3_REFERENCE_HISTORY_LIMIT:]

    def undo(self) -> str:
        if not self.history:
            return super().undo()
        state = self.history[-1]
        result = super().undo()
        valid_ids = {
            str(mask.get("id") or "")
            for mask in self.masks
            if isinstance(mask, dict)
        }
        restored = {
            str(mask_id)
            for mask_id in state.get("selected_mask_ids", [])
            if str(mask_id) in valid_ids
        }
        if not restored:
            primary = self._selected_mask_id()
            if primary in valid_ids:
                restored.add(primary)
        self.selected_mask_ids = restored
        self.schedule_render()
        return result

    def reset(self) -> None:
        self._push_history()
        self.matrix = self.nominal.copy()
        self.board = deepcopy(self._initial_board)
        self.masks = deepcopy(self._initial_masks)
        self.selected = None
        self.selected_mask_ids.clear()
        self.draw_board_mode = False
        self.draw_board_points = []
        self.redraw_board_committed = False
        self.mask_draw_mode = None
        self.mask_draw_start = None
        self.mask_draw_current = None
        self.mask_draw_points = []
        self.schedule_render()

    def _next_mask_id(self) -> str:
        return _next_available_mask_id(self.masks)

    def _update_mask_draw_buttons(self) -> None:
        active = self.mask_draw_mode if self.mask_draw_mode else "select"
        for key, button in self.mask_draw_buttons.items():
            enabled = key == active
            base_text = self.mask_draw_button_labels.get(key, str(key))
            try:
                button.configure(
                    text=(f"● {base_text}" if enabled else base_text),
                    bg="#FACC15" if enabled else "#17314A",
                    fg="#111318" if enabled else "#7DD3FC",
                    activebackground="#FDE047" if enabled else "#1E4668",
                    activeforeground="#111318" if enabled else "#FFFFFF",
                    relief=tk.SUNKEN if enabled else tk.FLAT,
                    bd=2 if enabled else 0,
                    highlightthickness=2 if enabled else 0,
                    highlightbackground="#FEF08A" if enabled else "#17314A",
                    highlightcolor="#FEF08A" if enabled else "#17314A",
                )
            except Exception:
                pass

    def _mask_draw_status_text(self) -> str:
        if self.mask_draw_mode == "segment":
            return (
                "MÁSCARA • SEGMENTO • clique e arraste no sentido da barra. "
                "O comprimento e o ângulo acompanham o arrasto."
            )
        if self.mask_draw_mode == "circle":
            return "MÁSCARA • CÍRCULO • clique no centro e arraste o raio."
        if self.mask_draw_mode == "polygon":
            if len(self.mask_draw_points) >= 3:
                return (
                    f"MÁSCARA • POR PONTOS ATIVO • {len(self.mask_draw_points)} ponto(s) • "
                    "clique no PRIMEIRO PONTO para fechar ou pressione Enter • Esc cancela."
                )
            return (
                f"MÁSCARA • POR PONTOS ATIVO • {len(self.mask_draw_points)} ponto(s) • "
                "adicione pelo menos 3 pontos • Esc cancela."
            )
        return (
            "SELECIONAR • arraste para mover • alças laterais esticam • cantos redimensionam • "
            "alça roxa rotaciona • Ctrl+clique seleciona várias • Ctrl+A seleciona todas."
        )

    def set_mask_draw_mode(self, mode=None) -> None:
        next_mode = (
            mode
            if self.allow_mask_creation and mode in {"segment", "circle", "polygon"}
            else None
        )
        self.mask_draw_mode = next_mode
        self.mask_draw_start = None
        self.mask_draw_current = None
        self.mask_draw_points = []
        self.drag_target = None
        if next_mode is not None:
            self.selected = None
            self.selected_mask_ids.clear()
        self._update_mask_draw_buttons()
        self.status.configure(text=self._mask_draw_status_text())
        self.schedule_render()
        try:
            self.canvas.focus_set()
        except Exception:
            pass

    def _selected_mask_id(self) -> str | None:
        target = self.selected
        if (
            isinstance(target, tuple)
            and len(target) >= 2
            and target[0] in {"mask", "mask_vertex"}
        ):
            mask_id = str(target[1] or "").strip()
            return mask_id or None
        if self.selected_mask_ids:
            return sorted(self.selected_mask_ids)[0]
        return None

    def _selected_ids(self) -> set[str]:
        valid_ids = {
            str(mask.get("id") or "")
            for mask in self.masks
            if isinstance(mask, dict) and str(mask.get("id") or "")
        }
        selected = {
            str(mask_id)
            for mask_id in self.selected_mask_ids
            if str(mask_id) in valid_ids
        }
        primary = self._selected_mask_id()
        if primary in valid_ids:
            selected.add(primary)
        self.selected_mask_ids = selected
        return set(selected)

    def select_all_masks(self, _event=None) -> str:
        if self.mask_draw_mode is not None:
            self.mask_draw_mode = None
            self.mask_draw_points = []
            self.mask_draw_start = None
            self.mask_draw_current = None
            self._update_mask_draw_buttons()
        self.selected_mask_ids = {
            str(mask.get("id") or "")
            for mask in self.masks
            if isinstance(mask, dict) and str(mask.get("id") or "")
        }
        if self.selected_mask_ids:
            self.selected = ("mask", sorted(self.selected_mask_ids)[0])
            self.status.configure(
                text=(
                    f"{len(self.selected_mask_ids)} máscara(s) selecionada(s) • "
                    "arraste uma delas para mover o grupo ou use EDIÇÃO DA SELEÇÃO."
                )
            )
        else:
            self.selected = None
            self.status.configure(text="Não há máscaras para selecionar.")
        self.schedule_render()
        return "break"

    def clear_mask_selection(self, _event=None) -> str:
        self.selected_mask_ids.clear()
        if (
            isinstance(self.selected, tuple)
            and self.selected
            and self.selected[0] in {"mask", "mask_vertex"}
        ):
            self.selected = None
        self.drag_target = None
        self.status.configure(text=self._mask_draw_status_text())
        self.schedule_render()
        return "break"

    def delete_selected_mask(self, _event=None) -> str:
        """Exclui uma ou várias máscaras apenas no editor canônico."""
        if not self.allow_mask_creation:
            self.status.configure(
                text=(
                    "ESTRUTURA BLOQUEADA • crie/exclua máscaras em "
                    "'Desenhar placa e máscaras'. Aqui ajuste somente a geometria."
                )
            )
            return "break"
        selected_ids = self._selected_ids()
        if not selected_ids:
            self.status.configure(
                text=(
                    "EXCLUIR MÁSCARA • selecione uma máscara, use Ctrl+clique para várias "
                    "ou SELECIONAR TUDO."
                )
            )
            return "break"

        self._push_history()
        self.masks = [
            mask
            for mask in self.masks
            if str(mask.get("id") or "") not in selected_ids
        ]
        count = len(selected_ids)
        self.selected = None
        self.selected_mask_ids.clear()
        self.drag_target = None
        self.drag_last_image = None
        self.mask_draw_start = None
        self.mask_draw_current = None
        self.mask_draw_points = []
        next_id = self._next_mask_id()
        self.status.configure(
            text=(
                f"{count} máscara(s) excluída(s) • próxima máscara nova: {next_id} • "
                "Ctrl+Z desfaz • SALVAR confirma."
            )
        )
        self.schedule_render()
        try:
            self.canvas.focus_set()
        except Exception:
            pass
        return "break"

    def _selection_bounds(self, ids=None):
        selected_ids = set(ids or self._selected_ids())
        bounds = []
        for mask in self.masks:
            mask_id = str(mask.get("id") or "") if isinstance(mask, dict) else ""
            if mask_id not in selected_ids:
                continue
            value = _mask_geometry_bounds(mask)
            if value is not None:
                bounds.append(value)
        if not bounds:
            return None
        return (
            min(value[0] for value in bounds),
            min(value[1] for value in bounds),
            max(value[2] for value in bounds),
            max(value[3] for value in bounds),
        )

    def _selection_center(self, ids=None):
        bounds = self._selection_bounds(ids)
        if bounds is None:
            return None
        return (
            (float(bounds[0]) + float(bounds[2])) / 2.0,
            (float(bounds[1]) + float(bounds[3])) / 2.0,
        )

    def transform_selected(
        self,
        *,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        degrees: float = 0.0,
        dx: float = 0.0,
        dy: float = 0.0,
        push: bool = True,
        center=None,
        source_masks=None,
    ) -> str:
        selected_ids = self._selected_ids()
        if not selected_ids:
            self.status.configure(
                text="EDIÇÃO DA SELEÇÃO • selecione uma ou mais máscaras primeiro."
            )
            return "break"
        transform_center = center or self._selection_center(selected_ids)
        if transform_center is None:
            return "break"
        if push:
            self._push_history()

        source_by_id = source_masks if isinstance(source_masks, dict) else None
        updated = []
        for mask in self.masks:
            mask_id = str(mask.get("id") or "") if isinstance(mask, dict) else ""
            if mask_id not in selected_ids:
                updated.append(mask)
                continue
            source = (
                deepcopy(source_by_id.get(mask_id))
                if source_by_id is not None and mask_id in source_by_id
                else mask
            )
            updated.append(
                _transform_mask_geometry(
                    source,
                    center_x=float(transform_center[0]),
                    center_y=float(transform_center[1]),
                    scale_x=float(scale_x),
                    scale_y=float(scale_y),
                    degrees=float(degrees),
                    dx=float(dx),
                    dy=float(dy),
                )
            )
        self.masks = updated
        self.schedule_render()
        return "break"

    def _selection_handles_canvas(self) -> dict[str, tuple[float, float]]:
        bounds = self._selection_bounds()
        if bounds is None:
            return {}
        x1, y1 = self._image_to_canvas(bounds[0], bounds[1])
        x2, y2 = self._image_to_canvas(bounds[2], bounds[3])
        left, right = min(x1, x2), max(x1, x2)
        top, bottom = min(y1, y2), max(y1, y2)
        mid_x = (left + right) / 2.0
        mid_y = (top + bottom) / 2.0
        return {
            "nw": (left, top),
            "n": (mid_x, top),
            "ne": (right, top),
            "e": (right, mid_y),
            "se": (right, bottom),
            "s": (mid_x, bottom),
            "sw": (left, bottom),
            "w": (left, mid_y),
            "rotate": (mid_x, top - 30.0),
        }

    def _selection_handle_at(self, cx: float, cy: float) -> str | None:
        for name, point in self._selection_handles_canvas().items():
            if math.hypot(float(cx) - point[0], float(cy) - point[1]) <= 9.0:
                return name
        return None

    def _begin_selection_handle_drag(self, handle: str, event) -> None:
        selected_ids = self._selected_ids()
        bounds = self._selection_bounds(selected_ids)
        if not selected_ids or bounds is None:
            return
        self.drag_target = ("selection_handle", str(handle))
        self.drag_snapshot_pushed = False
        self.transform_drag_initial_masks = {
            str(mask.get("id") or ""): deepcopy(mask)
            for mask in self.masks
            if isinstance(mask, dict)
            and str(mask.get("id") or "") in selected_ids
        }
        self.transform_drag_bounds = tuple(float(value) for value in bounds)
        self.transform_drag_start_canvas = (float(event.x), float(event.y))
        self.transform_drag_start_image = self._canvas_to_image(event.x, event.y)

    def _drag_selection_handle(self, event) -> None:
        if (
            not isinstance(self.drag_target, tuple)
            or not self.drag_target
            or self.drag_target[0] != "selection_handle"
            or self.transform_drag_bounds is None
        ):
            return
        handle = str(self.drag_target[1])
        if not self.drag_snapshot_pushed:
            self._push_history()
            self.drag_snapshot_pushed = True

        left, top, right, bottom = self.transform_drag_bounds
        width = max(1.0, right - left)
        height = max(1.0, bottom - top)
        center = ((left + right) / 2.0, (top + bottom) / 2.0)
        current = self._canvas_to_image(event.x, event.y)

        if handle == "rotate":
            center_canvas = self._image_to_canvas(center[0], center[1])
            start = self.transform_drag_start_canvas or (float(event.x), float(event.y))
            start_angle = math.atan2(start[1] - center_canvas[1], start[0] - center_canvas[0])
            current_angle = math.atan2(
                float(event.y) - center_canvas[1],
                float(event.x) - center_canvas[0],
            )
            degrees = math.degrees(current_angle - start_angle)
            self.transform_selected(
                degrees=degrees,
                push=False,
                center=center,
                source_masks=self.transform_drag_initial_masks,
            )
            return

        if handle in {"w", "nw", "sw"}:
            anchor_x = right
            original = max(1.0, right - left)
            scale_x = max(0.05, (anchor_x - float(current[0])) / original)
        elif handle in {"e", "ne", "se"}:
            anchor_x = left
            original = max(1.0, right - left)
            scale_x = max(0.05, (float(current[0]) - anchor_x) / original)
        else:
            anchor_x = center[0]
            scale_x = 1.0

        if handle in {"n", "nw", "ne"}:
            anchor_y = bottom
            original = max(1.0, bottom - top)
            scale_y = max(0.05, (anchor_y - float(current[1])) / original)
        elif handle in {"s", "sw", "se"}:
            anchor_y = top
            original = max(1.0, bottom - top)
            scale_y = max(0.05, (float(current[1]) - anchor_y) / original)
        else:
            anchor_y = center[1]
            scale_y = 1.0

        if handle in {"nw", "ne", "se", "sw"}:
            factor = max(0.05, min(scale_x, scale_y))
            scale_x = factor
            scale_y = factor
            anchor = (
                right if handle in {"nw", "sw"} else left,
                bottom if handle in {"nw", "ne"} else top,
            )
        elif handle in {"w", "e"}:
            anchor = (anchor_x, center[1])
        else:
            anchor = (center[0], anchor_y)

        self.transform_selected(
            scale_x=scale_x,
            scale_y=scale_y,
            push=False,
            center=anchor,
            source_masks=self.transform_drag_initial_masks,
        )

    def _nearest_mask_body_canvas(self, cx: float, cy: float) -> str | None:
        """Aceita clique ligeiramente fora da máscara para facilitar segmentos finos."""
        tolerance = float(F3_MASK_BODY_HIT_PX)
        for mask in reversed(self.masks):
            if not isinstance(mask, dict):
                continue
            mask_id = str(mask.get("id") or "")
            kind = str(mask.get("type") or "").lower()
            if kind == "circle":
                try:
                    center_x, center_y = self._image_to_canvas(
                        float(mask.get("cx", 0)),
                        float(mask.get("cy", 0)),
                    )
                    radius_canvas = (
                        max(1.0, float(mask.get("radius", 1)))
                        * max(1e-6, float(self._display_scale))
                    )
                except (TypeError, ValueError):
                    continue
                if math.hypot(float(cx) - center_x, float(cy) - center_y) <= (
                    radius_canvas + tolerance
                ):
                    return mask_id
                continue

            points = mask.get("points", [])
            canvas_points = []
            for point in points if isinstance(points, (list, tuple)) else ():
                if not isinstance(point, (list, tuple)) or len(point) < 2:
                    continue
                try:
                    canvas_points.append(
                        self._image_to_canvas(float(point[0]), float(point[1]))
                    )
                except (TypeError, ValueError):
                    continue
            if len(canvas_points) < 2:
                continue
            for index, start in enumerate(canvas_points):
                end = canvas_points[(index + 1) % len(canvas_points)]
                if _distance_point_to_segment(
                    float(cx),
                    float(cy),
                    float(start[0]),
                    float(start[1]),
                    float(end[0]),
                    float(end[1]),
                ) <= tolerance:
                    return mask_id
        return None

    def _polygon_close_target_hit(self, canvas_x: float, canvas_y: float) -> bool:
        if self.mask_draw_mode != "polygon" or len(self.mask_draw_points) < 3:
            return False
        first = self.mask_draw_points[0]
        first_x, first_y = self._image_to_canvas(first[0], first[1])
        return math.hypot(
            float(canvas_x) - float(first_x),
            float(canvas_y) - float(first_y),
        ) <= float(F3_POLYGON_CLOSE_HIT_PX)

    def _finish_polygon_mask(self) -> str:
        if self.mask_draw_mode != "polygon":
            return "break"
        if len(self.mask_draw_points) < 3:
            self.status.configure(
                text="POR PONTOS • use pelo menos 3 pontos antes de fechar a máscara."
            )
            return "break"

        self._push_history()
        mask = {
            "id": self._next_mask_id(),
            "type": "polygon",
            "points": deepcopy(self.mask_draw_points),
        }
        self.masks.append(mask)
        mask_id = str(mask.get("id") or "")
        self.selected = ("mask", mask_id)
        self.selected_mask_ids = {mask_id}
        self.mask_draw_points = []
        self.mask_draw_current = None
        self._update_mask_draw_buttons()
        self.status.configure(
            text=(
                f"{mask_id} fechada • + POR PONTOS continua ativo para a próxima máscara • "
                "use SELECIONAR quando quiser editar."
            )
        )
        self.schedule_render()
        return "break"

    def _press(self, event) -> None:
        if self.draw_board_mode:
            return super()._press(event)

        if self.allow_mask_creation and self.mask_draw_mode is not None:
            self.canvas.focus_set()
            point = self._canvas_to_image(event.x, event.y)
            if self.mask_draw_mode == "polygon":
                if self._polygon_close_target_hit(event.x, event.y):
                    self._finish_polygon_mask()
                    return
                self.mask_draw_points.append([float(point[0]), float(point[1])])
                self.mask_draw_current = point
                self.status.configure(text=self._mask_draw_status_text())
            else:
                self.mask_draw_start = point
                self.mask_draw_current = point
            self.schedule_render()
            return

        # Modo selecionar: handles > máscara > placa. Clique vazio nunca move tudo.
        self.canvas.focus_set()
        image_pos = self._canvas_to_image(event.x, event.y)
        ctrl = bool(int(getattr(event, "state", 0) or 0) & 0x0004)

        handle = self._selection_handle_at(float(event.x), float(event.y))
        if handle is not None and self._selected_ids():
            self._begin_selection_handle_drag(handle, event)
            self.drag_last_image = image_pos
            self.schedule_render()
            return

        mask_vertex = self._nearest_mask_vertex(float(event.x), float(event.y))
        if mask_vertex is not None and len(self._selected_ids()) <= 1:
            self.selected_mask_ids = {str(mask_vertex[0])}
            self.selected = ("mask_vertex", mask_vertex[0], mask_vertex[1])
            self.drag_target = self.selected
        else:
            mask_id = self._mask_at(*image_pos) or self._nearest_mask_body_canvas(
                float(event.x),
                float(event.y),
            )
            if mask_id:
                if ctrl:
                    if mask_id in self.selected_mask_ids:
                        self.selected_mask_ids.discard(mask_id)
                        self.selected = (
                            ("mask", sorted(self.selected_mask_ids)[0])
                            if self.selected_mask_ids
                            else None
                        )
                        self.drag_target = None
                    else:
                        self.selected_mask_ids.add(mask_id)
                        self.selected = ("mask", mask_id)
                        self.drag_target = None
                else:
                    if mask_id not in self.selected_mask_ids:
                        self.selected_mask_ids = {mask_id}
                    self.selected = ("mask", mask_id)
                    self.drag_target = ("mask_group", mask_id)
            else:
                board_index = self._nearest_board_vertex(
                    float(event.x),
                    float(event.y),
                )
                if board_index is not None:
                    self.selected_mask_ids.clear()
                    self.selected = ("board_vertex", board_index)
                    self.drag_target = self.selected
                else:
                    self.selected = None
                    self.selected_mask_ids.clear()
                    self.drag_target = None

        self.drag_last_image = image_pos
        self.drag_snapshot_pushed = False
        self.schedule_render()

    def _drag(self, event) -> None:
        if self.mask_draw_mode is None:
            if (
                isinstance(self.drag_target, tuple)
                and self.drag_target
                and self.drag_target[0] == "selection_handle"
            ):
                self._drag_selection_handle(event)
                return
            if (
                isinstance(self.drag_target, tuple)
                and self.drag_target
                and self.drag_target[0] == "mask_group"
            ):
                current = self._canvas_to_image(event.x, event.y)
                previous = self.drag_last_image or current
                dx = float(current[0] - previous[0])
                dy = float(current[1] - previous[1])
                if abs(dx) < 1e-6 and abs(dy) < 1e-6:
                    return
                if not self.drag_snapshot_pushed:
                    self._push_history()
                    self.drag_snapshot_pushed = True
                self.transform_selected(dx=dx, dy=dy, push=False)
                self.drag_last_image = current
                return
            return super()._drag(event)
        if self.allow_mask_creation and self.mask_draw_mode in {"segment", "circle"} and self.mask_draw_start is not None:
            self.mask_draw_current = self._canvas_to_image(event.x, event.y)
            self.schedule_render()

    def _release(self, event) -> None:
        if self.mask_draw_mode is None:
            self.transform_drag_initial_masks = {}
            self.transform_drag_bounds = None
            self.transform_drag_start_canvas = None
            self.transform_drag_start_image = None
            return super()._release(event)
        if (
            not self.allow_mask_creation
            or self.mask_draw_mode not in {"segment", "circle"}
            or self.mask_draw_start is None
        ):
            return
        current = self._canvas_to_image(event.x, event.y)
        x1, y1 = self.mask_draw_start
        x2, y2 = current
        mask = None
        if self.mask_draw_mode == "circle":
            radius = max(1.0, math.hypot(float(x2 - x1), float(y2 - y1)))
            mask = {
                "id": self._next_mask_id(),
                "type": "circle",
                "cx": float(x1),
                "cy": float(y1),
                "radius": float(radius),
            }
        else:
            mask = _segment_polygon_from_drag(
                float(x1),
                float(y1),
                float(x2),
                float(y2),
                self._next_mask_id(),
            )
        if mask is not None:
            self._push_history()
            self.masks.append(mask)
            mask_id = str(mask.get("id") or "")
            self.selected = ("mask", mask_id)
            self.selected_mask_ids = {mask_id}
            self._update_mask_draw_buttons()
            self.status.configure(
                text=(
                    f"{mask_id} criada • ferramenta {self.mask_draw_mode.upper()} continua ativa • "
                    "crie outra ou use SELECIONAR para editar."
                )
            )
        self.mask_draw_start = None
        self.mask_draw_current = None
        self.schedule_render()

    def _motion(self, event) -> None:
        if self.view_pan_active:
            return
        if self.draw_board_mode:
            return super()._motion(event)
        if self.mask_draw_mode is None:
            super()._motion(event)
            image_pos = self._canvas_to_image(event.x, event.y)
            mask_id = self._mask_at(*image_pos) or self._nearest_mask_body_canvas(
                float(event.x),
                float(event.y),
            )
            try:
                self.canvas.configure(cursor="fleur" if mask_id else "crosshair")
            except Exception:
                pass
            if mask_id and self.drag_target is None:
                self.status.configure(
                    text=(
                        f"{mask_id} • arraste para mover • Ctrl+clique adiciona/remove da seleção • "
                        "alças redimensionam/esticam/rotacionam."
                    )
                )
            return
        point = self._canvas_to_image(event.x, event.y)
        self._precision_cursor = (
            float(point[0]),
            float(point[1]),
            float(event.x),
            float(event.y),
        )
        self.mask_draw_current = point
        if self.mask_draw_mode == "polygon":
            if self._polygon_close_target_hit(event.x, event.y):
                self.status.configure(
                    text=(
                        f"FECHAR MÁSCARA • {len(self.mask_draw_points)} pontos • "
                        "clique agora no ponto inicial."
                    )
                )
            else:
                self.status.configure(text=self._mask_draw_status_text())
        self.schedule_render()

    def _start_view_pan(self, event) -> str:
        if float(self.view_zoom) <= 1.001:
            self.status.configure(
                text="PAN • use Ctrl+roda para ampliar; depois segure a rodinha e arraste."
            )
            return "break"
        self.view_pan_active = True
        self.view_pan_last = (float(event.x), float(event.y))
        self._precision_cursor = None
        try:
            self.canvas.configure(cursor="fleur")
            self.canvas.focus_set()
        except Exception:
            pass
        return "break"

    def _clamp_view_pan(self) -> None:
        cw = max(1.0, float(self.canvas.winfo_width()))
        ch = max(1.0, float(self.canvas.winfo_height()))
        fit = min(
            cw / max(1.0, float(self.width)),
            ch / max(1.0, float(self.height)),
        )
        scale = max(0.01, fit * float(self.view_zoom))
        overflow_x = max(0.0, (float(self.width) * scale - cw) / 2.0)
        overflow_y = max(0.0, (float(self.height) * scale - ch) / 2.0)
        self.view_pan_x = max(-overflow_x, min(overflow_x, float(self.view_pan_x)))
        self.view_pan_y = max(-overflow_y, min(overflow_y, float(self.view_pan_y)))

    def _drag_view_pan(self, event) -> str:
        if not self.view_pan_active or self.view_pan_last is None:
            return "break"
        current = (float(event.x), float(event.y))
        dx = current[0] - self.view_pan_last[0]
        dy = current[1] - self.view_pan_last[1]
        self.view_pan_last = current
        self.view_pan_x = float(self.view_pan_x) + dx
        self.view_pan_y = float(self.view_pan_y) + dy
        self._clamp_view_pan()
        self.schedule_render()
        return "break"

    def _end_view_pan(self, _event=None) -> str:
        self.view_pan_active = False
        self.view_pan_last = None
        try:
            self.canvas.configure(cursor="crosshair")
        except Exception:
            pass
        return "break"

    def _keyboard_move(self, dx: float, dy: float) -> str:
        selected_ids = self._selected_ids()
        if selected_ids:
            return self.transform_selected(dx=dx, dy=dy, push=True)
        if (
            isinstance(self.selected, tuple)
            and self.selected
            and self.selected[0] == "board_vertex"
        ):
            return super()._keyboard_move(dx, dy)
        self.status.configure(
            text=(
                "Nenhuma máscara/ponto selecionado • as setas não movem o conjunto. "
                "Selecione máscaras ou use os controles GLOBAL."
            )
        )
        return "break"

    def _wheel(self, event) -> str:
        state = int(getattr(event, "state", 0) or 0)
        if self.allow_mask_creation and self.mask_draw_mode is not None and not (state & 0x0004):
            return "break"
        return super()._wheel(event)

    def _enter(self, event=None) -> str:
        if self.allow_mask_creation and self.mask_draw_mode == "polygon":
            return self._finish_polygon_mask()
        return super()._enter(event)

    def _escape(self, event=None) -> str:
        if self.allow_mask_creation and self.mask_draw_mode is not None:
            self.mask_draw_mode = None
            self.mask_draw_start = None
            self.mask_draw_current = None
            self.mask_draw_points = []
            self._update_mask_draw_buttons()
            self.status.configure(text=self._mask_draw_status_text())
            self.schedule_render()
            return "break"
        if self._selected_ids():
            return self.clear_mask_selection(event)
        return super()._escape(event)

    @staticmethod
    def _mask_label_center(mask: dict) -> tuple[float, float] | None:
        if not isinstance(mask, dict):
            return None
        kind = str(mask.get("type") or "").lower()
        if kind == "circle":
            try:
                return float(mask.get("cx", 0)), float(mask.get("cy", 0))
            except (TypeError, ValueError):
                return None
        points = mask.get("points", [])
        if not isinstance(points, (list, tuple)):
            return None
        valid = []
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            try:
                valid.append((float(point[0]), float(point[1])))
            except (TypeError, ValueError):
                continue
        if not valid:
            return None
        return (
            sum(point[0] for point in valid) / len(valid),
            sum(point[1] for point in valid) / len(valid),
        )

    def _draw_selected_mask_outline(self) -> None:
        selected_ids = self._selected_ids()
        if not selected_ids:
            return

        for mask in self.masks:
            if not isinstance(mask, dict):
                continue
            mask_id = str(mask.get("id") or "")
            if mask_id not in selected_ids:
                continue
            kind = str(mask.get("type") or "").lower()
            if kind == "circle":
                try:
                    cx, cy = self._image_to_canvas(
                        float(mask.get("cx", 0)),
                        float(mask.get("cy", 0)),
                    )
                    radius = (
                        max(1.0, float(mask.get("radius", 1)))
                        * max(1e-6, float(self._display_scale))
                    )
                except (TypeError, ValueError):
                    continue
                self.canvas.create_oval(
                    cx-radius,
                    cy-radius,
                    cx+radius,
                    cy+radius,
                    outline="#FBBF24",
                    width=3,
                    tags=("f3_selected_mask",),
                )
            else:
                coords = []
                points = mask.get("points", [])
                for point in points if isinstance(points, (list, tuple)) else ():
                    if not isinstance(point, (list, tuple)) or len(point) < 2:
                        continue
                    try:
                        x, y = self._image_to_canvas(float(point[0]), float(point[1]))
                    except (TypeError, ValueError):
                        continue
                    coords.extend((x, y))
                if len(coords) >= 6:
                    self.canvas.create_polygon(
                        *coords,
                        fill="",
                        outline="#FBBF24",
                        width=3,
                        tags=("f3_selected_mask",),
                    )

        if self.mask_draw_mode is not None:
            return

        bounds = self._selection_bounds(selected_ids)
        handles = self._selection_handles_canvas()
        if bounds is None or not handles:
            return
        x1, y1 = self._image_to_canvas(bounds[0], bounds[1])
        x2, y2 = self._image_to_canvas(bounds[2], bounds[3])
        left, right = min(x1, x2), max(x1, x2)
        top, bottom = min(y1, y2), max(y1, y2)
        self.canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            outline="#38BDF8",
            width=2,
            dash=(6, 4),
            tags=("f3_selection_box",),
        )
        rotate = handles.get("rotate")
        north = handles.get("n")
        if rotate is not None and north is not None:
            self.canvas.create_line(
                north[0],
                north[1],
                rotate[0],
                rotate[1],
                fill="#38BDF8",
                width=2,
                tags=("f3_selection_box",),
            )

        for name, (x, y) in handles.items():
            if name == "rotate":
                self.canvas.create_oval(
                    x-6,
                    y-6,
                    x+6,
                    y+6,
                    fill="#A78BFA",
                    outline="#FFFFFF",
                    width=2,
                    tags=("f3_selection_handle",),
                )
            else:
                self.canvas.create_rectangle(
                    x-5,
                    y-5,
                    x+5,
                    y+5,
                    fill="#38BDF8",
                    outline="#FFFFFF",
                    width=1,
                    tags=("f3_selection_handle",),
                )

    def _draw_mask_numbers(self) -> None:
        """Desenha a numeração em cima das máscaras existentes e recém-criadas."""
        for index, mask in enumerate(self.masks, start=1):
            center = self._mask_label_center(mask)
            if center is None:
                continue
            mask_id = str(mask.get("id") or "")
            selected = mask_id in self._selected_ids()
            x, y = self._image_to_canvas(center[0], center[1])
            label = _mask_display_number(mask, index)
            half_width = max(9, 5 + 4 * len(label))
            half_height = 9
            self.canvas.create_rectangle(
                x - half_width,
                y - half_height,
                x + half_width,
                y + half_height,
                fill="#FBBF24" if selected else "#07111F",
                outline="#111827" if selected else "#38BDF8",
                width=1,
                tags=("f3_mask_number",),
            )
            self.canvas.create_text(
                x,
                y,
                text=label,
                fill="#111318" if selected else "#F8FAFC",
                font=("Segoe UI", 8, "bold"),
                tags=("f3_mask_number",),
            )

    def _draw_handles(self) -> None:
        super()._draw_handles()
        if self.mask_draw_mode is None:
            return
        if not self.allow_mask_creation:
            return

        if self.mask_draw_mode == "polygon":
            points = list(self.mask_draw_points)
            preview_points = list(points)
            if self.mask_draw_current is not None and points:
                preview_points.append(
                    [
                        float(self.mask_draw_current[0]),
                        float(self.mask_draw_current[1]),
                    ]
                )
            coords = []
            for point in preview_points:
                x, y = self._image_to_canvas(point[0], point[1])
                coords.extend((x, y))
            if len(coords) >= 4:
                self.canvas.create_line(*coords, fill="#FACC15", width=2)

            if len(points) >= 3 and self.mask_draw_current is not None:
                first_x, first_y = self._image_to_canvas(points[0][0], points[0][1])
                current_x, current_y = self._image_to_canvas(
                    self.mask_draw_current[0],
                    self.mask_draw_current[1],
                )
                close_ready = math.hypot(
                    current_x - first_x,
                    current_y - first_y,
                ) <= float(F3_POLYGON_CLOSE_HIT_PX)
                self.canvas.create_line(
                    current_x,
                    current_y,
                    first_x,
                    first_y,
                    fill="#22C55E" if close_ready else "#64748B",
                    width=2,
                    dash=(5, 4),
                )

            for index, point in enumerate(points):
                x, y = self._image_to_canvas(point[0], point[1])
                if index == 0:
                    ready = (
                        len(points) >= 3
                        and self.mask_draw_current is not None
                        and math.hypot(
                            self._image_to_canvas(
                                self.mask_draw_current[0],
                                self.mask_draw_current[1],
                            )[0] - x,
                            self._image_to_canvas(
                                self.mask_draw_current[0],
                                self.mask_draw_current[1],
                            )[1] - y,
                        ) <= float(F3_POLYGON_CLOSE_HIT_PX)
                    )
                    radius = 8 if len(points) >= 3 else 5
                    self.canvas.create_oval(
                        x-radius,
                        y-radius,
                        x+radius,
                        y+radius,
                        fill="#22C55E" if ready else "#FACC15",
                        outline="#FFFFFF",
                        width=2,
                    )
                    if len(points) >= 3:
                        self.canvas.create_text(
                            x,
                            y-14,
                            text="FECHAR",
                            fill="#86EFAC" if ready else "#FDE68A",
                            font=("Segoe UI", 7, "bold"),
                        )
                else:
                    self.canvas.create_oval(
                        x-4,
                        y-4,
                        x+4,
                        y+4,
                        fill="#FACC15",
                        outline="#020617",
                    )
            return

        if self.mask_draw_start is None or self.mask_draw_current is None:
            return
        x1, y1 = self.mask_draw_start
        x2, y2 = self.mask_draw_current
        cx1, cy1 = self._image_to_canvas(x1, y1)
        cx2, cy2 = self._image_to_canvas(x2, y2)
        if self.mask_draw_mode == "circle":
            radius = math.hypot(cx2-cx1, cy2-cy1)
            self.canvas.create_oval(
                cx1-radius, cy1-radius, cx1+radius, cy1+radius,
                outline="#FACC15", width=2,
            )
        else:
            preview = _segment_polygon_from_drag(
                float(x1),
                float(y1),
                float(x2),
                float(y2),
                "__PREVIEW__",
            )
            coords = []
            for point in preview.get("points", []):
                px, py = self._image_to_canvas(point[0], point[1])
                coords.extend((px, py))
            if len(coords) >= 6:
                self.canvas.create_polygon(
                    *coords,
                    fill="",
                    outline="#FACC15",
                    width=2,
                )

    def render(self) -> None:
        super().render()
        self._draw_selected_mask_outline()
        if self.allow_mask_creation and self.mask_draw_mode is not None:
            try:
                self.status.configure(text=self._mask_draw_status_text())
            except Exception:
                pass

    def save(self) -> None:
        if not _valid_frame(self.image):
            return
        if len(self.board) < 3:
            messagebox.showwarning(
                "Contorno necessário",
                "Defina pelo menos 3 pontos para o contorno da placa/display.",
                parent=self.window,
            )
            return
        try:
            saved = self._on_save_reference_geometry(
                deepcopy(self.board),
                deepcopy(self.masks),
            )
        except Exception:
            saved = False
        if saved is False:
            messagebox.showerror(
                "Falha ao salvar",
                "Não foi possível salvar os ajustes de geometria.",
                parent=self.window,
            )
            return
        self.close()

    def close(self, refresh: bool = False) -> None:
        del refresh
        try:
            self.window.grab_release()
        except Exception:
            pass
        try:
            self.window.destroy()
        except Exception:
            pass
        callback = self._on_close_reference_geometry
        if callable(callback):
            try:
                callback()
            except Exception:
                pass
