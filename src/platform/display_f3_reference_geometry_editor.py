from __future__ import annotations

"""Editor de geometria reutilizável para referências físicas do Display F3.

Reaproveita exatamente a interação visual do editor 90°/180°/270°:
contorno da placa, máscaras, lupa, zoom, arraste, rotação, escala, histórico e
redesenho ponto a ponto. Não possui estados ACESO/APAGADO/IGNORAR.
"""

from copy import deepcopy
from tkinter import messagebox
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
                "Ajuste somente a geometria. Arraste pontos do contorno ciano ou "
                "das máscaras. Círculo: arraste para mover e roda altera o raio. "
                "Setas movem 1 px. Ctrl+Z desfaz até 5 ações. Ctrl+roda dá zoom. "
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

    def reset(self) -> None:
        self._push_history()
        self.matrix = self.nominal.copy()
        self.board = deepcopy(self._initial_board)
        self.masks = deepcopy(self._initial_masks)
        self.selected = None
        self.draw_board_mode = False
        self.draw_board_points = []
        self.redraw_board_committed = False
        self.schedule_render()

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
