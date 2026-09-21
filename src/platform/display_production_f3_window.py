from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from src.platform.display_visual_rotation import preparar_frame_visual_display
from src.ui.operation_window_raspberry import RaspberryOperationWindow


class DisplayProductionF3Window(RaspberryOperationWindow):
    """Tela de Produção Display F3, isolada da Produção F2."""

    CHECK_CURRENT = "#D6A900"
    CHECK_COMPLETED = "#166534"
    CHECK_PENDING = "#172033"
    CHECK_BORDER = "#475569"

    DISPLAY_READOUT_PANEL = "#0B1220"
    DISPLAY_READOUT_SCREEN = "#020617"
    DISPLAY_READOUT_BORDER = "#334155"
    DISPLAY_READOUT_ACTIVE = "#FBBF24"
    DISPLAY_READOUT_INACTIVE = "#2B2508"
    DISPLAY_READOUT_TITLE = "#E2E8F0"

    def __init__(
        self,
        root,
        on_close: Callable[[], None],
        on_configure: Callable[[], None] | None = None,
        on_discard: Callable[[], None] | None = None,
        preview_width: int = 640,
        preview_height: int = 480,
    ) -> None:
        super().__init__(
            root=root,
            on_trigger=lambda: None,
            on_close=on_close,
            preview_width=preview_width,
            preview_height=preview_height,
        )

        self.on_configure = on_configure
        self.on_discard = on_discard
        self.visual_rotation = 0
        self._camera_ready = False
        self._camera_detail = "Aguardando câmera"
        self._waiting_camera_ui_active = False
        self._check_snapshot: dict = {
            "checks": [],
            "current_check": None,
            "current_index": None,
            "total": 0,
            "ok": 0,
            "ng": 0,
        }

        self.brand_label.configure(text="ODIN  |  PRODUÇÃO DISPLAY  F3")
        self.mode_label.configure(text="DISPLAY • FLUXO SEQUENCIAL DE CHECKS")
        self.preview_title.configure(text="DISPLAY • CÂMERA AO VIVO")
        self.preview_legend.configure(
            text="CHECK ATUAL • MONITORAMENTO CONTÍNUO",
            fg=self.PREVIEW_MUTED,
        )

        # Reserva visual para o futuro espelhamento lógico do display físico.
        # Por enquanto é somente apresentação: nenhuma regra de CHECK depende dele.
        self._build_display_readout()

        self.footer_label.configure(
            text="1: DESCARTAR PLACA  •  F3 ou ESC: voltar ao ODIN"
        )

        self.led_summary_label.grid_remove()

        self.status_frame.grid_rowconfigure(0, weight=0)
        self.status_frame.grid_rowconfigure(1, weight=0)
        self.status_frame.grid_rowconfigure(2, weight=1)
        self.status_label.configure(font=("DejaVu Sans", 30, "bold"))
        self.detail_label.configure(font=("DejaVu Sans", 13))

        self.check_flow_frame = tk.Frame(
            self.status_frame,
            bg=self.COLOR_WAITING,
            highlightthickness=0,
        )
        self.check_flow_frame.grid(
            row=2,
            column=0,
            sticky="nsew",
            padx=8,
            pady=(6, 2),
        )
        self.check_flow_frame.grid_columnconfigure(0, weight=1)

        self.project_frame = tk.Frame(
            self.analysis_panel,
            bg="#0B1220",
            highlightbackground="#334155",
            highlightthickness=1,
        )
        self.project_frame.grid(
            row=3,
            column=0,
            sticky="ew",
            padx=20,
            pady=(4, 8),
        )
        self.project_frame.grid_columnconfigure(0, weight=1)

        self.project_info_label = tk.Label(
            self.project_frame,
            text="PROJETO DISPLAY: NENHUM",
            font=("DejaVu Sans", 10, "bold"),
            bg="#0B1220",
            fg="#E2E8F0",
            anchor="w",
            justify="left",
        )
        self.project_info_label.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=10,
            pady=(7, 1),
        )

        self.project_detail_label = tk.Label(
            self.project_frame,
            text="Resolução mestre: --  •  Máscaras: 0  •  CHECKS: 0",
            font=("DejaVu Sans", 8),
            bg="#0B1220",
            fg="#94A3B8",
            anchor="w",
            justify="left",
        )
        self.project_detail_label.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=10,
            pady=(0, 7),
        )

        self.project_config_button = tk.Button(
            self.project_frame,
            text="CONFIGURAR",
            command=self._open_project_config,
            font=("DejaVu Sans", 8, "bold"),
            bg="#0E7490",
            fg="#FFFFFF",
            activebackground="#0891B2",
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=11,
            pady=6,
            cursor="hand2",
        )
        self.project_config_button.grid(
            row=0,
            column=1,
            rowspan=2,
            sticky="e",
            padx=10,
            pady=7,
        )

        # Reaproveita os cards TOTAL/OK/NG da janela-base, mas os valores são
        # exclusivos da sessão F3 e nunca usam os contadores da Produção F2.
        self.metrics_frame.grid()
        self.metrics_frame.grid_configure(
            row=4,
            column=0,
            sticky="ew",
            padx=20,
            pady=(0, 8),
        )

        self.discard_button = tk.Button(
            self.analysis_panel,
            text="DESCARTAR PLACA  [1]",
            command=self._discard_plate,
            font=("DejaVu Sans", 10, "bold"),
            bg="#7F1D1D",
            fg="#FFFFFF",
            activebackground="#991B1B",
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=14,
            pady=7,
            cursor="hand2",
        )
        self.discard_button.grid(
            row=5,
            column=0,
            sticky="ew",
            padx=20,
            pady=(0, 14),
        )

        self.container.bind("<Return>", self._ignorar_trigger)
        self.container.bind("<KP_Enter>", self._ignorar_trigger)
        self.container.bind("<F2>", self._ignorar_trigger)
        self.container.bind("<F3>", self._handle_close)
        self.container.bind("<Escape>", self._handle_close)
        self.container.bind("<KeyPress-1>", self._handle_discard)
        self.container.bind("<KP_1>", self._handle_discard)
        self.container.unbind("<F1>")

        self.set_check_sequence(self._check_snapshot)

    def _build_display_readout(self) -> None:
        """Cria um visor 7 segmentos independente da lógica dos CHECKS."""
        self.display_readout_value = "88:88"

        # O status "Ao vivo" desce uma linha; a câmera continua sendo a área
        # expansível da coluna direita.
        self.preview_status.grid_configure(
            row=3,
            pady=(7, 11),
        )
        self.preview_frame.grid_rowconfigure(2, weight=0)
        self.preview_frame.grid_rowconfigure(3, weight=0)

        self.display_readout_frame = tk.Frame(
            self.preview_frame,
            bg=self.DISPLAY_READOUT_PANEL,
            highlightbackground=self.DISPLAY_READOUT_BORDER,
            highlightthickness=1,
        )
        self.display_readout_frame.grid(
            row=2,
            column=0,
            sticky="ew",
            padx=12,
            pady=(9, 0),
        )
        self.display_readout_frame.grid_columnconfigure(0, weight=1)

        self.display_readout_title = tk.Label(
            self.display_readout_frame,
            text="VISOR DO DISPLAY",
            font=("DejaVu Sans", 9, "bold"),
            bg=self.DISPLAY_READOUT_PANEL,
            fg=self.DISPLAY_READOUT_TITLE,
            anchor="w",
            justify="left",
        )
        self.display_readout_title.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=10,
            pady=(7, 2),
        )

        self.display_readout_canvas = tk.Canvas(
            self.display_readout_frame,
            bg=self.DISPLAY_READOUT_SCREEN,
            highlightbackground=self.DISPLAY_READOUT_BORDER,
            highlightthickness=1,
            bd=0,
            width=320,
            height=68,
        )
        self.display_readout_canvas.grid(
            row=1,
            column=0,
            sticky="",
            padx=10,
            pady=(0, 8),
        )
        self.display_readout_canvas.bind(
            "<Configure>",
            self._redraw_display_readout,
        )

        try:
            self.root.after_idle(self._redraw_display_readout)
        except tk.TclError:
            pass

    @staticmethod
    def _seven_segment_points(
        x: float,
        y: float,
        width: float,
        height: float,
        thickness: float,
    ) -> dict[str, list[float]]:
        """Polígonos afilados A..G para um dígito de sete segmentos."""
        t = float(thickness)
        half = height / 2.0
        bevel = max(2.0, t * 0.42)

        def horizontal(top_y: float):
            return [
                x + t * 0.72, top_y,
                x + width - t * 0.72, top_y,
                x + width - bevel, top_y + t / 2.0,
                x + width - t * 0.72, top_y + t,
                x + t * 0.72, top_y + t,
                x + bevel, top_y + t / 2.0,
            ]

        def vertical(left_x: float, top_y: float, bottom_y: float):
            return [
                left_x, top_y + t * 0.72,
                left_x + t / 2.0, top_y + bevel,
                left_x + t, top_y + t * 0.72,
                left_x + t, bottom_y - t * 0.72,
                left_x + t / 2.0, bottom_y - bevel,
                left_x, bottom_y - t * 0.72,
            ]

        return {
            "a": horizontal(y),
            "g": horizontal(y + half - t / 2.0),
            "d": horizontal(y + height - t),
            "f": vertical(x, y, y + half),
            "b": vertical(x + width - t, y, y + half),
            "e": vertical(x, y + half, y + height),
            "c": vertical(x + width - t, y + half, y + height),
        }

    def _draw_seven_segment_digit(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        character: str,
    ) -> None:
        canvas = self.display_readout_canvas
        segment_map = {
            "0": "abcdef",
            "1": "bc",
            "2": "abdeg",
            "3": "abcdg",
            "4": "bcfg",
            "5": "acdfg",
            "6": "acdefg",
            "7": "abc",
            "8": "abcdefg",
            "9": "abcdfg",
            "-": "g",
            " ": "",
        }
        active = set(segment_map.get(str(character), "abcdefg"))
        thickness = max(4.0, min(width, height) * 0.115)
        polygons = self._seven_segment_points(
            x,
            y,
            width,
            height,
            thickness,
        )
        for name, points in polygons.items():
            canvas.create_polygon(
                points,
                fill=(
                    self.DISPLAY_READOUT_ACTIVE
                    if name in active
                    else self.DISPLAY_READOUT_INACTIVE
                ),
                outline="",
                tags=("display-readout-segment",),
            )

    def _redraw_display_readout(self, _event=None) -> None:
        canvas = getattr(self, "display_readout_canvas", None)
        if canvas is None:
            return
        try:
            canvas.delete("all")
            width = max(280, int(canvas.winfo_width()))
            height = max(62, int(canvas.winfo_height()))
        except tk.TclError:
            return

        value = str(getattr(self, "display_readout_value", "88:88") or "88:88")
        if ":" not in value:
            value = "88:88"
        left, right = value.split(":", 1)
        left = (left + "88")[:2]
        right = (right + "88")[:2]
        digits = [left[0], left[1], right[0], right[1]]

        digit_height = min(50.0, max(40.0, height - 14.0))
        digit_width = digit_height * 0.56
        digit_gap = max(7.0, digit_width * 0.20)
        colon_width = max(13.0, digit_width * 0.38)
        total_width = (
            digit_width * 4.0
            + digit_gap * 3.0
            + colon_width
        )
        start_x = (width - total_width) / 2.0
        y = (height - digit_height) / 2.0

        x = start_x
        self._draw_seven_segment_digit(x, y, digit_width, digit_height, digits[0])
        x += digit_width + digit_gap
        self._draw_seven_segment_digit(x, y, digit_width, digit_height, digits[1])
        x += digit_width + digit_gap * 0.55

        dot_radius = max(2.7, digit_width * 0.075)
        colon_x = x + colon_width / 2.0
        for cy in (y + digit_height * 0.36, y + digit_height * 0.66):
            canvas.create_oval(
                colon_x - dot_radius,
                cy - dot_radius,
                colon_x + dot_radius,
                cy + dot_radius,
                fill=self.DISPLAY_READOUT_ACTIVE,
                outline="",
                tags=("display-readout-colon",),
            )

        x += colon_width + digit_gap * 0.45
        self._draw_seven_segment_digit(x, y, digit_width, digit_height, digits[2])
        x += digit_width + digit_gap
        self._draw_seven_segment_digit(x, y, digit_width, digit_height, digits[3])

    def set_display_readout(self, value: str = "88:88") -> None:
        """Ponto de integração futuro; atualmente apenas atualiza o desenho."""
        text = str(value or "88:88").strip()
        if len(text) != 5 or text[2] != ":":
            text = "88:88"
        self.display_readout_value = text
        self._redraw_display_readout()

    def _open_project_config(self) -> None:
        if self.on_configure is not None:
            self.on_configure()

    @staticmethod
    def _ignorar_trigger(_event=None):
        return "break"

    def _discard_plate(self) -> None:
        if self.on_discard is not None:
            self.on_discard()

    def _handle_discard(self, _event=None) -> str:
        self._discard_plate()
        return "break"

    def set_project_info(
        self,
        name: str | None,
        master_resolution=None,
        mask_count: int = 0,
        check_count: int = 0,
    ) -> None:
        project_name = str(name or "NENHUM")
        resolution_text = "--"
        if isinstance(master_resolution, (list, tuple)) and len(master_resolution) >= 2:
            resolution_text = f"{int(master_resolution[0])}x{int(master_resolution[1])}"
        self.project_info_label.configure(text=f"PROJETO DISPLAY: {project_name}")
        self.project_detail_label.configure(
            text=(
                f"Resolução mestre: {resolution_text}  •  "
                f"Máscaras: {int(mask_count)}  •  CHECKS: {int(check_count)}"
            )
        )

    def _render_check_cards(
        self,
        snapshot: dict,
        force_all_completed: bool = False,
    ) -> None:
        for child in self.check_flow_frame.winfo_children():
            child.destroy()

        checks = list(snapshot.get("checks", []) or [])
        if not checks:
            tk.Label(
                self.check_flow_frame,
                text="Nenhum CHECK configurado no Projeto Display.",
                font=("DejaVu Sans", 11, "bold"),
                bg=self.COLOR_WAITING,
                fg="#FCA5A5",
                anchor="center",
                justify="center",
            ).grid(row=0, column=0, sticky="nsew", pady=8)
            return

        for indice, check in enumerate(checks):
            state = "completed" if force_all_completed else str(check.get("state", "pending"))
            if state == "completed":
                bg = self.CHECK_COMPLETED
                border = "#22C55E"
                status = "CONCLUÍDO"
                fg = "#FFFFFF"
            elif state == "current":
                bg = "#3B3205"
                border = self.CHECK_CURRENT
                status = "AGUARDANDO"
                fg = "#FDE68A"
            else:
                bg = self.CHECK_PENDING
                border = self.CHECK_BORDER
                status = "PRÓXIMO"
                fg = "#94A3B8"

            card = tk.Frame(
                self.check_flow_frame,
                bg=bg,
                highlightbackground=border,
                highlightthickness=2 if state == "current" else 1,
            )
            card.grid(
                row=indice,
                column=0,
                sticky="ew",
                pady=(0, 5),
            )
            card.grid_columnconfigure(1, weight=1)
            tk.Label(
                card,
                text=str(indice + 1),
                font=("DejaVu Sans", 10, "bold"),
                bg=bg,
                fg=fg,
                width=3,
            ).grid(row=0, column=0, padx=(7, 3), pady=7)
            tk.Label(
                card,
                text=str(check.get("name") or check.get("id") or "CHECK"),
                font=("DejaVu Sans", 11, "bold"),
                bg=bg,
                fg="#FFFFFF",
                anchor="w",
            ).grid(row=0, column=1, sticky="ew", padx=4, pady=7)
            tk.Label(
                card,
                text=status,
                font=("DejaVu Sans", 8, "bold"),
                bg=bg,
                fg=fg,
                anchor="e",
            ).grid(row=0, column=2, padx=(6, 9), pady=7)

    def set_check_sequence(self, snapshot: dict | None) -> None:
        self._check_snapshot = dict(snapshot or {})
        total = int(self._check_snapshot.get("total", 0) or 0)
        ok_count = int(self._check_snapshot.get("ok", 0) or 0)
        ng_count = int(self._check_snapshot.get("ng", 0) or 0)
        self._set_counters(total, ok_count, ng_count)
        self._render_check_cards(self._check_snapshot)

        checks = list(self._check_snapshot.get("checks", []) or [])
        current = self._check_snapshot.get("current_check")
        if not checks or not isinstance(current, dict):
            self._waiting_camera_ui_active = not self._camera_ready
            self._set_state(
                background=self.COLOR_WAITING,
                foreground="#FFFFFF",
                status="SEM CHECKS",
                detail="Configure os CHECKS do Projeto Display para iniciar.",
            )
            self.status_label.configure(font=("DejaVu Sans", 30, "bold"))
            return

        indice = int(self._check_snapshot.get("current_index", 0) or 0)
        nome = str(current.get("name") or current.get("id") or "CHECK")
        if not self._camera_ready:
            self._waiting_camera_ui_active = True
            self._set_state(
                background=self.COLOR_WAITING,
                foreground="#FFFFFF",
                status="AGUARDANDO CÂMERA",
                detail=(
                    f"CHECK {indice + 1} DE {len(checks)}  •  "
                    "A sequência iniciará quando houver imagem válida."
                ),
            )
            self.status_label.configure(font=("DejaVu Sans", 28, "bold"))
            return

        self._waiting_camera_ui_active = False
        self._set_state(
            background=self.COLOR_WAITING,
            foreground="#FFFFFF",
            status=f"AGUARDANDO {nome}",
            detail=(
                f"CHECK {indice + 1} DE {len(checks)}  •  {self._camera_detail}"
            ),
        )
        self.status_label.configure(font=("DejaVu Sans", 28, "bold"))

    def show_plate_result(
        self,
        is_ok: bool,
        snapshot: dict,
        discarded: bool = False,
    ) -> None:
        self._waiting_camera_ui_active = False
        self._check_snapshot = dict(snapshot or {})
        self._set_counters(
            int(self._check_snapshot.get("total", 0) or 0),
            int(self._check_snapshot.get("ok", 0) or 0),
            int(self._check_snapshot.get("ng", 0) or 0),
        )
        if is_ok:
            self._render_check_cards(self._check_snapshot, force_all_completed=True)
            self._set_state(
                background=self.COLOR_OK,
                foreground="#FFFFFF",
                status="PLACA APROVADA",
                detail="Todos os CHECKS foram concluídos. Preparando próxima placa.",
            )
        else:
            self._render_check_cards(self._check_snapshot)
            self._set_state(
                background=self.COLOR_NG,
                foreground="#FFFFFF",
                status="PLACA DESCARTADA" if discarded else "PLACA NG",
                detail=(
                    "CHECKS reiniciados. A próxima placa começará pelo primeiro CHECK."
                ),
            )
        self.status_label.configure(font=("DejaVu Sans", 28, "bold"))

    def show_waiting_camera(self) -> None:
        already_waiting = self._waiting_camera_ui_active and not self._camera_ready
        self._camera_ready = False
        self._camera_detail = "Aguardando câmera"
        if already_waiting:
            return

        self._waiting_camera_ui_active = True
        self._set_state(
            background=self.COLOR_WAITING,
            foreground="#FFFFFF",
            status="AGUARDANDO CÂMERA",
            detail="A sequência de CHECKS iniciará quando houver imagem válida.",
        )
        self.status_label.configure(font=("DejaVu Sans", 28, "bold"))
        self.set_preview_status("Aguardando câmera", self.PREVIEW_MUTED)

    def show_camera_ready(
        self,
        width: int,
        height: int,
        visual_rotation: int = 0,
    ) -> None:
        self._waiting_camera_ui_active = False
        self._camera_ready = True
        self._camera_detail = (
            f"Câmera {int(width)}x{int(height)} • Visual {int(visual_rotation)}°"
        )
        self.set_check_sequence(self._check_snapshot)

    def update_camera_preview(self, frame, visual_rotation: int = 0) -> bool:
        """Renderiza apenas uma cópia visual, sem tocar em câmera ou F2."""
        if frame is None or getattr(frame, "size", 0) == 0:
            self.show_waiting_camera()
            return False

        try:
            rotation = int(visual_rotation) % 360
        except (TypeError, ValueError):
            rotation = 0
        if rotation not in (0, 90, 180, 270):
            rotation = 0
        self.visual_rotation = rotation

        visual_frame = preparar_frame_visual_display(frame, rotation)
        if visual_frame is None or getattr(visual_frame, "size", 0) == 0:
            self.show_waiting_camera()
            return False

        height, width = visual_frame.shape[:2]
        rendered = self.update_preview(visual_frame, leds=())
        if rendered:
            camera_changed = (
                not self._camera_ready
                or self._camera_detail
                != f"Câmera {int(width)}x{int(height)} • Visual {int(rotation)}°"
            )
            if camera_changed:
                self.show_camera_ready(width, height, rotation)
        return rendered
