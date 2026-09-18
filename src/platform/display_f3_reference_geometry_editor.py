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
    F3_EDITOR_HISTORY_LIMIT,
    _fit_toplevel_inside_screen,
    _valid_frame,
)


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
                + "Arraste pontos do contorno ciano ou das máscaras. Círculo: arraste "
                  "para mover e roda altera o raio. Setas movem 1 px. Ctrl+Z desfaz "
                  "até 5 ações. Ctrl+roda dá zoom."
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

        self.mask_toolbar = None
        if self.allow_mask_creation:
            self.mask_toolbar = tk.Frame(self.window, bg="#0B1728")
            self.mask_toolbar.pack(fill=tk.X, padx=10, pady=(0, 8))
            tk.Label(
                self.mask_toolbar,
                text="MÁSCARAS",
                font=("Segoe UI", 8, "bold"),
                fg="#94A3B8",
                bg="#0B1728",
            ).pack(side=tk.LEFT, padx=(6, 10))

            def mask_button(text, mode=None, command=None, danger=False):
                callback = command or (lambda value=mode: self.set_mask_draw_mode(value))
                tk.Button(
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
                ).pack(side=tk.LEFT, padx=(0, 4))

            mask_button("SELECIONAR", mode=None)
            mask_button("+ SEGMENTO", mode="segment")
            mask_button("+ CÍRCULO", mode="circle")
            mask_button("+ POR PONTOS", mode="polygon")
            mask_button(
                "EXCLUIR SELEÇÃO",
                command=self.delete_selected_mask,
                danger=True,
            )

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

    def reset(self) -> None:
        self._push_history()
        self.matrix = self.nominal.copy()
        self.board = deepcopy(self._initial_board)
        self.masks = deepcopy(self._initial_masks)
        self.selected = None
        self.draw_board_mode = False
        self.draw_board_points = []
        self.redraw_board_committed = False
        self.mask_draw_mode = None
        self.mask_draw_start = None
        self.mask_draw_current = None
        self.mask_draw_points = []
        self.schedule_render()

    def _next_mask_id(self) -> str:
        used = {str(mask.get("id") or "") for mask in self.masks if isinstance(mask, dict)}
        index = 1
        while f"MASK_{index:03d}" in used:
            index += 1
        return f"MASK_{index:03d}"

    def set_mask_draw_mode(self, mode=None) -> None:
        self.mask_draw_mode = mode if mode in {"segment", "circle", "polygon"} else None
        self.mask_draw_start = None
        self.mask_draw_current = None
        self.mask_draw_points = []
        self.drag_target = None
        self.selected = None
        if self.mask_draw_mode == "segment":
            text = "MÁSCARA • SEGMENTO • clique e arraste para desenhar."
        elif self.mask_draw_mode == "circle":
            text = "MÁSCARA • CÍRCULO • clique no centro e arraste o raio."
        elif self.mask_draw_mode == "polygon":
            text = "MÁSCARA • POR PONTOS • clique ponto a ponto; Enter conclui; Esc cancela."
        else:
            text = "SELECIONAR • clique em placa/máscara para ajustar."
        self.status.configure(text=text)
        self.schedule_render()

    def delete_selected_mask(self) -> None:
        target = self.selected
        if not isinstance(target, tuple) or not target or target[0] not in {"mask", "mask_vertex"}:
            self.status.configure(text="Selecione uma máscara para excluir.")
            return
        mask_id = str(target[1])
        self._push_history()
        self.masks = [
            mask for mask in self.masks
            if str(mask.get("id") or "") != mask_id
        ]
        self.selected = None
        self.schedule_render()

    def _press(self, event) -> None:
        if not self.allow_mask_creation or self.mask_draw_mode is None:
            return super()._press(event)
        self.canvas.focus_set()
        point = self._canvas_to_image(event.x, event.y)
        if self.mask_draw_mode == "polygon":
            self.mask_draw_points.append([float(point[0]), float(point[1])])
            self.mask_draw_current = point
        else:
            self.mask_draw_start = point
            self.mask_draw_current = point
        self.schedule_render()

    def _drag(self, event) -> None:
        if not self.allow_mask_creation or self.mask_draw_mode is None:
            return super()._drag(event)
        if self.mask_draw_mode in {"segment", "circle"} and self.mask_draw_start is not None:
            self.mask_draw_current = self._canvas_to_image(event.x, event.y)
            self.schedule_render()

    def _release(self, event) -> None:
        if not self.allow_mask_creation or self.mask_draw_mode is None:
            return super()._release(event)
        if self.mask_draw_mode not in {"segment", "circle"} or self.mask_draw_start is None:
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
            left, right = sorted((float(x1), float(x2)))
            top, bottom = sorted((float(y1), float(y2)))
            if right - left >= 2.0 and bottom - top >= 2.0:
                mask = {
                    "id": self._next_mask_id(),
                    "type": "polygon",
                    "points": [
                        [left, top],
                        [right, top],
                        [right, bottom],
                        [left, bottom],
                    ],
                }
        if mask is not None:
            self._push_history()
            self.masks.append(mask)
            self.selected = ("mask", str(mask.get("id") or ""))
        self.mask_draw_start = None
        self.mask_draw_current = None
        self.schedule_render()

    def _motion(self, event) -> None:
        if not self.allow_mask_creation or self.mask_draw_mode is None:
            return super()._motion(event)
        point = self._canvas_to_image(event.x, event.y)
        self._precision_cursor = (
            float(point[0]),
            float(point[1]),
            float(event.x),
            float(event.y),
        )
        self.mask_draw_current = point
        if self.mask_draw_mode == "polygon":
            self.status.configure(
                text=(
                    f"MÁSCARA • POR PONTOS • {len(self.mask_draw_points)} ponto(s) • "
                    "Enter conclui • Esc cancela"
                )
            )
        self.schedule_render()

    def _wheel(self, event) -> str:
        state = int(getattr(event, "state", 0) or 0)
        if self.allow_mask_creation and self.mask_draw_mode is not None and not (state & 0x0004):
            return "break"
        return super()._wheel(event)

    def _enter(self, event=None) -> str:
        if self.allow_mask_creation and self.mask_draw_mode == "polygon":
            if len(self.mask_draw_points) < 3:
                self.status.configure(text="Use pelo menos 3 pontos para concluir a máscara.")
                return "break"
            self._push_history()
            mask = {
                "id": self._next_mask_id(),
                "type": "polygon",
                "points": deepcopy(self.mask_draw_points),
            }
            self.masks.append(mask)
            self.selected = ("mask", str(mask.get("id") or ""))
            self.mask_draw_points = []
            self.mask_draw_current = None
            self.mask_draw_mode = None
            self.schedule_render()
            return "break"
        return super()._enter(event)

    def _escape(self, event=None) -> str:
        if self.allow_mask_creation and self.mask_draw_mode is not None:
            self.mask_draw_mode = None
            self.mask_draw_start = None
            self.mask_draw_current = None
            self.mask_draw_points = []
            self.schedule_render()
            return "break"
        return super()._escape(event)

    def _draw_handles(self) -> None:
        super()._draw_handles()
        if not self.allow_mask_creation or self.mask_draw_mode is None:
            return

        if self.mask_draw_mode == "polygon":
            points = list(self.mask_draw_points)
            if self.mask_draw_current is not None and points:
                points = points + [[float(self.mask_draw_current[0]), float(self.mask_draw_current[1])]]
            coords = []
            for point in points:
                x, y = self._image_to_canvas(point[0], point[1])
                coords.extend((x, y))
            if len(coords) >= 4:
                self.canvas.create_line(*coords, fill="#FACC15", width=2)
            for point in self.mask_draw_points:
                x, y = self._image_to_canvas(point[0], point[1])
                self.canvas.create_oval(
                    x-4, y-4, x+4, y+4,
                    fill="#FACC15", outline="#020617",
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
            self.canvas.create_rectangle(
                cx1, cy1, cx2, cy2,
                outline="#FACC15", width=2,
            )

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
