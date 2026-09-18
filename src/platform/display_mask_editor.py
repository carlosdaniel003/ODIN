from __future__ import annotations

import base64
import math
import tkinter as tk
from collections.abc import Callable
from copy import deepcopy

import cv2

from src.platform.display_f3_window_geometry import fit_f3_toplevel
from src.platform.display_mask_geometry import (
    DISPLAY_MASK_F2_PARITY_TOOLS,
    TOOL_CIRCLE,
    TOOL_FREEFORM,
    TOOL_MASS,
    TOOL_SEGMENT,
    _id,
    bbox_mascara_display,
    converter_mascara_legada_para_editor,
    criar_segmento_display_por_arrasto,
    mascara_display_contem_ponto,
    pontos_mascara_display,
)
import src.platform.display_check_zoom  # instala zoom somente no editor visual de CHECK do F3
from src.platform.display_mask_editor_interactions import (
    DisplayMaskEditorInteractionMixin,
)
from src.platform.display_project_repository import (
    normalizar_mascaras_display,
    normalizar_resolucao_display,
)
from src.ui.main_window_parts.image.selection_zoom import ZOOM_SELECAO_MIN

HANDLE_PX = 7
MAGNIFIER_SIZE_PX = 190


class DisplayMaskEditorWindow(DisplayMaskEditorInteractionMixin):
    """Editor F3 com as ferramentas do ``Selecionar LEDs`` do F2, estado isolado."""

    BG = "#020617"
    PANEL = "#07111F"
    MASK = "#22D3EE"
    SEL = "#FBBF24"
    ROT = "#A78BFA"

    def __init__(
        self,
        root,
        master_resolution,
        masks,
        frame=None,
        on_save: Callable[[list[dict]], None] | None = None,
        board_points=None,
        on_save_board: Callable[[list[list[float]]], None] | None = None,
    ):
        res = normalizar_resolucao_display(master_resolution)
        if res is None:
            raise ValueError("Resolução mestre inválida para o editor Display")
        self.root = root
        self.master_width, self.master_height = res
        self.on_save = on_save
        self.on_save_board = on_save_board
        self.masks = [
            converter_mascara_legada_para_editor(m)
            for m in normalizar_mascaras_display(deepcopy(masks or []))
        ]
        self.frame = None
        if frame is not None and getattr(frame, "size", 0) > 0:
            self.frame = (
                cv2.resize(
                    frame,
                    (self.master_width, self.master_height),
                    interpolation=cv2.INTER_AREA,
                )
                if tuple(frame.shape[:2]) != (self.master_height, self.master_width)
                else frame.copy()
            )

        self.board_points = []
        for point in (board_points or []):
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                try:
                    self.board_points.append(
                        [float(point[0]), float(point[1])]
                    )
                except (TypeError, ValueError):
                    pass
        if len(self.board_points) < 3:
            self.board_points = self._default_board_points()
        self.board_draw_mode = False
        self.board_draw_points: list[list[float]] = []
        self.board_selected_index = None
        self.board_drag_index = None
        self.tool = TOOL_SEGMENT
        self.selected_ids = set()
        self.mode = None
        self.handle = None
        self.press_canvas = None
        self.press_master = None
        self.current_master = None
        self.snapshot = []
        self.snapshot_sel = []
        self.snapshot_bbox = None
        self.draft_segment = None
        self.freeform = []
        self.freeform_mouse = None
        self.zoom_factor = ZOOM_SELECAO_MIN
        self.zoom_cx = None
        self.zoom_cy = None
        self.pan = False
        self.pan_last = None
        self._photo = None
        self._magnifier = None
        self.pointer_canvas = None
        self.pointer_master = None

        self.window = tk.Toplevel(root)
        self.window.title("ODIN • Projeto Display • Seleção e ajuste de máscaras")
        self.window.configure(bg=self.BG)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self._toolbar()

        self.canvas = tk.Canvas(
            self.window,
            bg=self.BG,
            highlightthickness=0,
            cursor="crosshair",
            bd=0,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.status = tk.Label(
            self.window,
            text="",
            font=("DejaVu Sans", 9, "bold"),
            fg="#AAB8C8",
            bg=self.PANEL,
            anchor="w",
        )
        self.status.pack(fill=tk.X, padx=14, pady=(5, 8))
        self._bind()
        self._maximize()
        self.set_tool(TOOL_SEGMENT)
        self.window.after(60, self.redraw)
        self.window.after(80, self.canvas.focus_set)

    @property
    def visible(self):
        try:
            return bool(self.window.winfo_exists())
        except Exception:
            return False

    def _toolbar(self):
        """Mantém as quatro ferramentas sempre visíveis, inclusive no JIG.

        A versão anterior colocava título, quatro ferramentas, zoom e OK em uma
        única faixa fixa de 72 px. Em telas menores o gerenciador de geometria
        acabava recortando os últimos controles. Agora o cabeçalho e as quatro
        ferramentas ocupam linhas próprias e a altura é determinada pelo Tk.
        """
        bar = tk.Frame(self.window, bg=self.PANEL)
        bar.pack(fill=tk.X)

        header = tk.Frame(bar, bg=self.PANEL)
        header.pack(fill=tk.X, padx=18, pady=(7, 3))
        text = tk.Frame(header, bg=self.PANEL)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Label(
            text,
            text="SELEÇÃO E AJUSTE DE MÁSCARAS • PROJETO DISPLAY",
            font=("DejaVu Sans", 12, "bold"),
            fg="#F9FAFB",
            bg=self.PANEL,
            anchor="w",
        ).pack(fill=tk.X)
        tk.Label(
            text,
            text=(
                "FUNDO ESTÁTICO DA CALIBRAÇÃO • máscaras + contorno da placa • "
                "Ctrl+scroll zoom • botão do meio arrasta • setas movem 1 px"
            ),
            font=("DejaVu Sans", 8),
            fg="#AAB8C8",
            bg=self.PANEL,
            anchor="w",
        ).pack(fill=tk.X, pady=(2, 0))

        tk.Button(
            header,
            text="OK",
            command=self.save,
            font=("DejaVu Sans", 10, "bold"),
            bg="#D6A900",
            fg="#111318",
            relief="flat",
            padx=24,
            pady=8,
        ).pack(side=tk.RIGHT, padx=(8, 0))
        self.zoom_label = tk.Label(
            header,
            text="ZOOM 100%",
            font=("DejaVu Sans", 9, "bold"),
            fg="#38BDF8",
            bg=self.PANEL,
            padx=8,
            pady=5,
        )
        self.zoom_label.pack(side=tk.RIGHT, padx=8)

        tools = tk.Frame(bar, bg=self.PANEL)
        tools.pack(fill=tk.X, padx=18, pady=(3, 8))
        for column in range(5):
            tools.grid_columnconfigure(column, weight=1, uniform="display_mask_tool")

        self.tool_buttons = {}
        tool_specs = (
            (TOOL_SEGMENT, "▰ Segmento"),
            (TOOL_CIRCLE, "● Círculo"),
            (TOOL_FREEFORM, "✎ Segmento por pontos"),
            (TOOL_MASS, "▣ Seleção em massa"),
        )
        for column, (tool, label) in enumerate(tool_specs):
            button = tk.Button(
                tools,
                text=label,
                command=lambda value=tool: self.set_tool(value),
                font=("DejaVu Sans", 8, "bold"),
                relief="flat",
                padx=10,
                pady=6,
            )
            button.grid(
                row=0,
                column=column,
                sticky="nsew",
                padx=(0 if column == 0 else 2, 0 if column == 3 else 2),
            )
            self.tool_buttons[tool] = button

        self.board_button = tk.Button(
            tools,
            text="⬡ Desenhar placa",
            command=self.start_board_mode,
            font=("DejaVu Sans", 8, "bold"),
            relief="flat",
            padx=10,
            pady=6,
            bg="#17314A",
            fg="#7DD3FC",
            activebackground="#1E4668",
            activeforeground="#FFFFFF",
        )
        self.board_button.grid(
            row=0,
            column=4,
            sticky="nsew",
            padx=(2, 0),
        )

    def _bind(self):
        bindings = (
            ("<Configure>", lambda _event: self.redraw()),
            ("<Button-1>", self._press),
            ("<B1-Motion>", self._drag),
            ("<ButtonRelease-1>", self._release),
            ("<Motion>", self._motion),
            ("<Leave>", self._leave),
            ("<Button-2>", self._start_pan),
            ("<B2-Motion>", self._drag_pan),
            ("<ButtonRelease-2>", self._end_pan),
            ("<Delete>", self._delete_selected),
            ("<BackSpace>", self._delete_selected),
            ("<Escape>", self._escape_editor),
            ("<Control-a>", self._select_all),
            ("<Control-A>", self._select_all),
            ("<Left>", self._move_keyboard_with_board),
            ("<Right>", self._move_keyboard_with_board),
            ("<Up>", self._move_keyboard_with_board),
            ("<Down>", self._move_keyboard_with_board),
            ("<Return>", self._finish_active_shape),
            ("<KP_Enter>", self._finish_active_shape),
        )
        for sequence, callback in bindings:
            self.canvas.bind(sequence, callback)
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind(sequence, self._wheel, add="+")

    def _maximize(self):
        fit_f3_toplevel(
            self.window,
            self.root,
            width_ratio=0.96,
            height_ratio=0.88,
            min_width=820,
            min_height=560,
        )

    def _default_board_points(self):
        if not self.masks:
            return [
                [0.0, 0.0],
                [float(self.master_width - 1), 0.0],
                [float(self.master_width - 1), float(self.master_height - 1)],
                [0.0, float(self.master_height - 1)],
            ]
        boxes = [bbox_mascara_display(mask) for mask in self.masks]
        x1 = min(box[0] for box in boxes)
        y1 = min(box[1] for box in boxes)
        x2 = max(box[2] for box in boxes)
        y2 = max(box[3] for box in boxes)
        pad_x = max(18.0, (x2 - x1) * 0.12)
        pad_y = max(18.0, (y2 - y1) * 0.12)
        return [
            [max(0.0, x1 - pad_x), max(0.0, y1 - pad_y)],
            [min(float(self.master_width - 1), x2 + pad_x), max(0.0, y1 - pad_y)],
            [min(float(self.master_width - 1), x2 + pad_x), min(float(self.master_height - 1), y2 + pad_y)],
            [max(0.0, x1 - pad_x), min(float(self.master_height - 1), y2 + pad_y)],
        ]

    def start_board_mode(self):
        self.freeform = []
        self.freeform_mouse = None
        self.draft_segment = None
        self.selected_ids = set()
        self.board_draw_mode = True
        self.board_draw_points = []
        self.board_selected_index = None
        self.board_drag_index = None
        try:
            self.board_button.configure(bg="#D6A900", fg="#111318")
        except Exception:
            pass
        self.status.configure(
            text=(
                "DESENHAR PLACA • clique ponto a ponto no contorno • "
                "Enter conclui • Esc cancela"
            )
        )
        self.redraw()
        self.canvas.focus_set()

    def set_tool(self, tool):
        self.board_draw_mode = False
        self.board_draw_points = []
        self.board_selected_index = None
        self.board_drag_index = None
        try:
            self.board_button.configure(bg="#17314A", fg="#7DD3FC")
        except Exception:
            pass
        return super().set_tool(tool)

    def _nearest_board_vertex(self, canvas_x: float, canvas_y: float):
        best = None
        for index, point in enumerate(self.board_points):
            x, y = self._to_canvas(point[0], point[1])
            distance = math.hypot(float(canvas_x) - x, float(canvas_y) - y)
            if distance <= 12.0 and (best is None or distance < best[0]):
                best = (distance, index)
        return None if best is None else int(best[1])

    def _press(self, event):
        point = self._to_master(event.x, event.y)
        if point is None:
            return "break"
        if self.board_draw_mode:
            self.board_draw_points.append([float(point[0]), float(point[1])])
            self.redraw()
            return "break"

        board_index = self._nearest_board_vertex(event.x, event.y)
        if board_index is not None:
            self.board_selected_index = board_index
            self.board_drag_index = board_index
            self.selected_ids = set()
            self.redraw()
            return "break"
        self.board_selected_index = None
        self.board_drag_index = None
        return super()._press(event)

    def _drag(self, event):
        if self.board_drag_index is not None:
            point = self._to_master(event.x, event.y)
            if point is not None and 0 <= self.board_drag_index < len(self.board_points):
                self.board_points[self.board_drag_index] = [
                    float(point[0]),
                    float(point[1]),
                ]
                self.redraw()
            return "break"
        if self.board_draw_mode:
            return "break"
        return super()._drag(event)

    def _release(self, event):
        if self.board_drag_index is not None:
            self.board_drag_index = None
            return "break"
        if self.board_draw_mode:
            return "break"
        return super()._release(event)

    def _finish_active_shape(self, event=None):
        if self.board_draw_mode:
            if len(self.board_draw_points) < 3:
                self.status.configure(
                    text="DESENHAR PLACA • use pelo menos 3 pontos antes de concluir."
                )
                return "break"
            self.board_points = deepcopy(self.board_draw_points)
            self.board_draw_points = []
            self.board_draw_mode = False
            self.board_selected_index = None
            try:
                self.board_button.configure(bg="#17314A", fg="#7DD3FC")
            except Exception:
                pass
            self.redraw()
            return "break"
        return super()._finish_freeform(event)

    def _escape_editor(self, event=None):
        if self.board_draw_mode:
            self.board_draw_mode = False
            self.board_draw_points = []
            try:
                self.board_button.configure(bg="#17314A", fg="#7DD3FC")
            except Exception:
                pass
            self.redraw()
            return "break"
        if self.board_selected_index is not None:
            self.board_selected_index = None
            self.redraw()
            return "break"
        return super()._escape(event)

    def _move_keyboard_with_board(self, event):
        if self.board_selected_index is not None:
            dx = {"Left": -1, "Right": 1}.get(getattr(event, "keysym", ""), 0)
            dy = {"Up": -1, "Down": 1}.get(getattr(event, "keysym", ""), 0)
            index = int(self.board_selected_index)
            if 0 <= index < len(self.board_points):
                self.board_points[index][0] = max(
                    0.0,
                    min(float(self.master_width - 1), self.board_points[index][0] + dx),
                )
                self.board_points[index][1] = max(
                    0.0,
                    min(float(self.master_height - 1), self.board_points[index][1] + dy),
                )
                self.redraw()
            return "break"
        return super()._move_keyboard(event)

    def _draw_board(self):
        if len(self.board_points) >= 3:
            coords = []
            for point in self.board_points:
                coords.extend(self._to_canvas(point[0], point[1]))
            self.canvas.create_polygon(
                *coords,
                fill="",
                outline="#22D3EE",
                width=2,
            )
            for index, point in enumerate(self.board_points):
                x, y = self._to_canvas(point[0], point[1])
                active = index == self.board_selected_index
                self.canvas.create_oval(
                    x - 5,
                    y - 5,
                    x + 5,
                    y + 5,
                    fill="#FBBF24" if active else "#38BDF8",
                    outline="#020617",
                    width=1,
                )

        if self.board_draw_mode and self.board_draw_points:
            coords = []
            for point in self.board_draw_points:
                x, y = self._to_canvas(point[0], point[1])
                coords.extend((x, y))
                self.canvas.create_oval(
                    x - 5,
                    y - 5,
                    x + 5,
                    y + 5,
                    fill="#FACC15",
                    outline="#020617",
                    width=1,
                )
            if len(coords) >= 4:
                self.canvas.create_line(
                    *coords,
                    fill="#FACC15",
                    width=2,
                )

    def _background(self, viewport):
        if self.frame is None:
            return None
        crop = self.frame[
            viewport.origem_visual_y : viewport.fim_visual_y,
            viewport.origem_visual_x : viewport.fim_visual_x,
        ]
        if crop.size == 0:
            return None
        image = cv2.resize(
            crop,
            (viewport.largura_render, viewport.altura_render),
            interpolation=(
                cv2.INTER_AREA if viewport.escala < 1 else cv2.INTER_LINEAR
            ),
        )
        ok, encoded = cv2.imencode(
            ".png",
            image,
            [cv2.IMWRITE_PNG_COMPRESSION, 1],
        )
        if not ok:
            return None
        return tk.PhotoImage(data=base64.b64encode(encoded).decode("ascii"))

    def _draw_mask(self, mask):
        color = self.SEL if _id(mask) in self.selected_ids else self.MASK
        width = 3 if _id(mask) in self.selected_ids else 2
        kind = str(mask.get("type", "")).lower()
        if kind == "circle":
            x, y = self._to_canvas(mask["cx"], mask["cy"])
            radius = mask["radius"] * self._vp().escala
            self.canvas.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                outline=color,
                width=width,
            )
            return

        coordinates = []
        for point in pontos_mascara_display(mask):
            coordinates.extend(self._to_canvas(point[0], point[1]))
        if len(coordinates) >= 6:
            self.canvas.create_polygon(
                *coordinates,
                fill="",
                outline=color,
                width=width,
            )

    def _draw_handles(self):
        handles = self._handles()
        for name, point in handles.items():
            x, y = self._to_canvas(*point)
            radius = HANDLE_PX
            if name == "rotate":
                if "n" in handles:
                    nx, ny = self._to_canvas(*handles["n"])
                    self.canvas.create_line(
                        nx,
                        ny,
                        x,
                        y,
                        fill=self.ROT,
                        width=2,
                        dash=(3, 3),
                    )
                self.canvas.create_oval(
                    x - radius,
                    y - radius,
                    x + radius,
                    y + radius,
                    fill=self.ROT,
                    outline="#111827",
                )
            else:
                self.canvas.create_rectangle(
                    x - radius,
                    y - radius,
                    x + radius,
                    y + radius,
                    fill="#38BDF8" if name in {"n", "e", "s", "w"} else self.SEL,
                    outline="#111827",
                )

    def _draw_freeform(self):
        if not self.freeform:
            return
        points = [self._to_canvas(*point) for point in self.freeform]
        if len(points) >= 2:
            self.canvas.create_line(
                *[value for point in points for value in point],
                fill="#38BDF8",
                width=3,
            )
        if self.freeform_mouse:
            self.canvas.create_line(
                *points[-1],
                *self._to_canvas(*self.freeform_mouse),
                fill="#7DD3FC",
                width=2,
                dash=(6, 4),
            )
        for index, (x, y) in enumerate(points):
            radius = 7 if index == 0 else 4
            self.canvas.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill="#FBBF24" if index == 0 else "#38BDF8",
            )

    def _draw_magnifier(self):
        if (
            self.frame is None
            or self.pointer_canvas is None
            or self.pointer_master is None
        ):
            return
        x, y = self.pointer_master
        radius = 28
        x1 = max(0, x - radius)
        x2 = min(self.master_width, x + radius)
        y1 = max(0, y - radius)
        y2 = min(self.master_height, y + radius)
        crop = self.frame[y1:y2, x1:x2]
        if crop.size == 0:
            return
        image = cv2.resize(
            crop,
            (MAGNIFIER_SIZE_PX, MAGNIFIER_SIZE_PX),
            interpolation=cv2.INTER_NEAREST,
        )
        ok, encoded = cv2.imencode(".png", image)
        if not ok:
            return
        self._magnifier = tk.PhotoImage(
            data=base64.b64encode(encoded).decode("ascii")
        )
        canvas_width = max(1, self.canvas.winfo_width())
        left = canvas_width - MAGNIFIER_SIZE_PX - 18
        if self.pointer_canvas[0] > left - 20:
            left = 18
        top = 42
        self.canvas.create_image(left, top, image=self._magnifier, anchor="nw")
        self.canvas.create_rectangle(
            left,
            top,
            left + MAGNIFIER_SIZE_PX,
            top + MAGNIFIER_SIZE_PX,
            outline="#38BDF8",
            width=2,
        )

    def redraw(self):
        if not self.visible:
            return
        self.canvas.delete("all")
        viewport = self._vp()
        self._photo = self._background(viewport)
        if self._photo:
            self.canvas.create_image(
                viewport.deslocamento_render_x,
                viewport.deslocamento_render_y,
                image=self._photo,
                anchor="nw",
            )
        else:
            self.canvas.create_rectangle(
                viewport.deslocamento_virtual_x,
                viewport.deslocamento_virtual_y,
                viewport.deslocamento_virtual_x + viewport.largura_virtual,
                viewport.deslocamento_virtual_y + viewport.altura_virtual,
                fill="#0B1220",
                outline="#1E293B",
            )
        self._draw_board()
        for mask in self.masks:
            self._draw_mask(mask)
        if self.draft_segment:
            self._draw_mask(self.draft_segment)
        self._draw_freeform()
        self._draw_handles()
        self._draw_magnifier()
        self.status.configure(
            text=(
                f"Projeto Display • fundo estático • {len(self.board_points)} pontos da placa • "
                f"{len(self.masks)} máscara(s) • {len(self.selected_ids)} selecionada(s) • "
                f"Zoom {int(round(self.zoom_factor * 100))}%"
            )
        )

    def save(self):
        if self.board_draw_mode:
            if len(self.board_draw_points) < 3:
                self.status.configure(
                    text="Conclua o contorno da placa com pelo menos 3 pontos antes de salvar."
                )
                return
            self._finish_active_shape()
        if self.freeform:
            self._finish_freeform()
        masks = normalizar_mascaras_display(deepcopy(self.masks))
        if self.on_save:
            self.on_save(masks)
        if self.on_save_board:
            self.on_save_board(deepcopy(self.board_points))
        self.close()

    def close(self):
        try:
            self.window.destroy()
        except Exception:
            pass
