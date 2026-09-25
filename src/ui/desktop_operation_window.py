from __future__ import annotations

import base64
import tkinter as tk
from collections.abc import Callable

import cv2


class DesktopOperationWindow:
    """Tela operacional responsiva para o produto desktop Windows/Linux."""

    COLOR_WAITING = "#0F172A"
    COLOR_WAITING_AFTER_OK = "#14532D"
    COLOR_WAITING_AFTER_NG = "#7F1D1D"
    COLOR_POSITIONING = "#1D4ED8"
    COLOR_WAITING_REMOVAL = "#334155"
    COLOR_PROCESSING = "#F59E0B"
    COLOR_OK = "#16A34A"
    COLOR_NG = "#DC2626"
    COLOR_ERROR = "#7F1D1D"

    PREVIEW_BACKGROUND = "#020617"
    PREVIEW_PANEL = "#07111F"
    PREVIEW_BORDER = "#334155"
    PREVIEW_GUIDE = "#22D3EE"
    PREVIEW_BOARD_GUIDE = "#FBBF24"
    PREVIEW_FAILED = "#FF3B30"
    PREVIEW_TEXT = "#E2E8F0"
    PREVIEW_MUTED = "#94A3B8"

    STATUS_FONT_SIZES = {
        "OK": 82,
        "NG": 82,
        "ERRO": 50,
        "AGUARDANDO": 40,
        "POSICIONANDO": 34,
        "PROCESSANDO": 36,
        "RETIRE A PLACA": 32,
        "PREPARANDO": 34,
    }

    PREVIEW_RESIZE_DEBOUNCE_MS = 140

    def __init__(
        self,
        root: tk.Tk,
        on_trigger: Callable[[], None],
        on_close: Callable[[], None],
        preview_width: int = 320,
        preview_height: int = 240,
    ) -> None:
        self.root = root
        self.on_trigger = on_trigger
        self.on_close = on_close
        self.preview_width = max(320, int(preview_width))
        self.preview_height = max(240, int(preview_height))

        self._preview_tk = None
        self._preview_image_item = None
        self._preview_use_ppm = True
        self._preview_resize_after_id = None
        self._latest_frame = None
        self._latest_leds = ()
        self._failed_led_ids: frozenset[str] = frozenset()
        self._configured_led_count = 0
        self._has_led_result = False
        self._last_result_ok: bool | None = None

        self.container = tk.Frame(
            root,
            bg=self.PREVIEW_BACKGROUND,
            highlightthickness=0,
            takefocus=True,
        )
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_rowconfigure(1, weight=0)
        self.container.grid_columnconfigure(0, weight=1)

        self.body_frame = tk.Frame(
            self.container,
            bg=self.PREVIEW_BACKGROUND,
            highlightthickness=0,
        )
        self.body_frame.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=14,
            pady=(14, 8),
        )
        self.body_frame.grid_rowconfigure(0, weight=1)
        self.body_frame.grid_columnconfigure(
            0,
            weight=1,
            uniform="production_halves",
        )
        self.body_frame.grid_columnconfigure(
            1,
            weight=1,
            uniform="production_halves",
        )

        self.analysis_panel = tk.Frame(
            self.body_frame,
            bg=self.COLOR_WAITING,
            highlightbackground="#1E293B",
            highlightthickness=1,
        )
        self.analysis_panel.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, 7),
        )
        self.analysis_panel.grid_rowconfigure(2, weight=1)
        self.analysis_panel.grid_columnconfigure(0, weight=1)
        self.analysis_panel.bind(
            "<Configure>",
            self._on_analysis_resize,
        )

        self.brand_label = tk.Label(
            self.analysis_panel,
            text="ODIN  |  MODO PRODUÇÃO",
            font=("DejaVu Sans", 18, "bold"),
            bg=self.COLOR_WAITING,
            fg="#FFFFFF",
            anchor="w",
            justify="left",
        )
        self.brand_label.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=24,
            pady=(20, 2),
        )

        self.mode_label = tk.Label(
            self.analysis_panel,
            text="INSPEÇÃO VISUAL DE LEDS",
            font=("DejaVu Sans", 10, "bold"),
            bg=self.COLOR_WAITING,
            fg="#CBD5E1",
            anchor="w",
            justify="left",
        )
        self.mode_label.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=24,
            pady=(0, 8),
        )

        self.status_frame = tk.Frame(
            self.analysis_panel,
            bg=self.COLOR_WAITING,
            highlightthickness=0,
        )
        self.status_frame.grid(
            row=2,
            column=0,
            sticky="nsew",
            padx=20,
            pady=8,
        )
        self.status_frame.grid_rowconfigure(0, weight=1)
        self.status_frame.grid_columnconfigure(0, weight=1)

        self.status_label = tk.Label(
            self.status_frame,
            text="AGUARDANDO",
            font=("DejaVu Sans", 40, "bold"),
            bg=self.COLOR_WAITING,
            fg="#FFFFFF",
            anchor="center",
            justify="center",
        )
        self.status_label.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=8,
        )

        self.detail_label = tk.Label(
            self.status_frame,
            text="Insira uma placa para iniciar",
            font=("DejaVu Sans", 17),
            bg=self.COLOR_WAITING,
            fg="#FFFFFF",
            anchor="center",
            justify="center",
            wraplength=480,
        )
        self.detail_label.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=16,
            pady=(0, 8),
        )

        self.led_summary_label = tk.Label(
            self.analysis_panel,
            text="LEDS CONFIGURADOS: 0",
            font=("DejaVu Sans", 16, "bold"),
            bg=self.COLOR_WAITING,
            fg="#FFFFFF",
            anchor="center",
            justify="center",
        )
        self.led_summary_label.grid(
            row=3,
            column=0,
            sticky="ew",
            padx=24,
            pady=(4, 12),
        )

        self.metrics_frame = tk.Frame(
            self.analysis_panel,
            bg=self.COLOR_WAITING,
            highlightthickness=0,
        )
        self.metrics_frame.grid(
            row=4,
            column=0,
            sticky="ew",
            padx=20,
            pady=(0, 18),
        )
        for column in range(3):
            self.metrics_frame.grid_columnconfigure(
                column,
                weight=1,
                uniform="production_metrics",
            )

        self.total_value_label = self._create_metric(
            self.metrics_frame,
            column=0,
            title="TOTAL",
        )
        self.ok_value_label = self._create_metric(
            self.metrics_frame,
            column=1,
            title="OK",
        )
        self.ng_value_label = self._create_metric(
            self.metrics_frame,
            column=2,
            title="NG",
        )

        # Mantido para compatibilidade com qualquer integração que ainda leia
        # diretamente o rótulo antigo de contadores. Ele não participa do layout.
        self.counter_label = tk.Label(
            self.analysis_panel,
            text="TOTAL 0    OK 0    NG 0",
            bg=self.COLOR_WAITING,
            fg="#FFFFFF",
        )

        self.preview_frame = tk.Frame(
            self.body_frame,
            bg=self.PREVIEW_PANEL,
            highlightbackground=self.PREVIEW_BORDER,
            highlightthickness=1,
        )
        self.preview_frame.grid(
            row=0,
            column=1,
            sticky="nsew",
            padx=(7, 0),
        )
        self.preview_frame.grid_rowconfigure(1, weight=1)
        self.preview_frame.grid_columnconfigure(0, weight=1)

        self.preview_header = tk.Frame(
            self.preview_frame,
            bg=self.PREVIEW_PANEL,
            highlightthickness=0,
        )
        self.preview_header.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=14,
            pady=(12, 8),
        )
        self.preview_header.grid_columnconfigure(0, weight=1)

        self.preview_title = tk.Label(
            self.preview_header,
            text="CÂMERA AO VIVO",
            font=("DejaVu Sans", 15, "bold"),
            bg=self.PREVIEW_PANEL,
            fg=self.PREVIEW_TEXT,
            anchor="w",
            justify="left",
        )
        self.preview_title.grid(
            row=0,
            column=0,
            sticky="w",
        )

        self.preview_legend = tk.Label(
            self.preview_header,
            text="CÍRCULO VERMELHO: LED APAGADO",
            font=("DejaVu Sans", 9, "bold"),
            bg=self.PREVIEW_PANEL,
            fg=self.PREVIEW_FAILED,
            anchor="e",
            justify="right",
        )
        self.preview_legend.grid(
            row=0,
            column=1,
            sticky="e",
        )

        self.preview_canvas = tk.Canvas(
            self.preview_frame,
            bg=self.PREVIEW_BACKGROUND,
            highlightbackground="#1E293B",
            highlightthickness=1,
            bd=0,
            width=self.preview_width,
            height=self.preview_height,
        )
        self.preview_canvas.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=12,
            pady=0,
        )
        self.preview_canvas.bind(
            "<Configure>",
            self._on_preview_resize,
        )

        self.preview_status = tk.Label(
            self.preview_frame,
            text="Aguardando câmera",
            font=("DejaVu Sans", 11),
            bg=self.PREVIEW_PANEL,
            fg=self.PREVIEW_MUTED,
            anchor="center",
            justify="center",
        )
        self.preview_status.grid(
            row=2,
            column=0,
            sticky="ew",
            padx=12,
            pady=(8, 12),
        )

        self.footer_label = tk.Label(
            self.container,
            text="F1 ou ESC: parametrização",
            font=("DejaVu Sans", 11),
            bg="#020617",
            fg="#CBD5E1",
            anchor="center",
            justify="center",
        )
        self.footer_label.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=14,
            pady=(0, 10),
        )

        self.container.bind("<Return>", self._handle_trigger)
        self.container.bind("<KP_Enter>", self._handle_trigger)
        self.container.bind("<F1>", self._handle_close)
        self.container.bind("<Escape>", self._handle_close)

    def _create_metric(
        self,
        parent,
        column: int,
        title: str,
    ) -> tk.Label:
        card = tk.Frame(
            parent,
            bg="#0B1220",
            highlightbackground="#475569",
            highlightthickness=1,
        )
        card.grid(
            row=0,
            column=column,
            sticky="ew",
            padx=(0 if column == 0 else 5, 0 if column == 2 else 5),
        )

        title_label = tk.Label(
            card,
            text=title,
            font=("DejaVu Sans", 9, "bold"),
            bg="#0B1220",
            fg="#94A3B8",
            anchor="center",
        )
        title_label.pack(fill="x", pady=(7, 0))

        value_label = tk.Label(
            card,
            text="0",
            font=("DejaVu Sans", 22, "bold"),
            bg="#0B1220",
            fg="#FFFFFF",
            anchor="center",
        )
        value_label.pack(fill="x", pady=(0, 7))
        return value_label

    @property
    def visible(self) -> bool:
        return bool(self.container.winfo_ismapped())

    def show(self) -> None:
        self.container.place(
            x=0,
            y=0,
            relwidth=1.0,
            relheight=1.0,
        )
        self.container.lift()
        self.container.focus_force()
        self.root.update_idletasks()
        self._render_latest_preview()

    def hide(self) -> None:
        self.container.place_forget()

    def _on_analysis_resize(self, event) -> None:
        wraplength = max(220, int(event.width) - 72)
        self.detail_label.configure(wraplength=wraplength)

    def _on_preview_resize(self, _event=None) -> None:
        if self._preview_resize_after_id is not None:
            try:
                self.root.after_cancel(self._preview_resize_after_id)
            except Exception:
                pass

        try:
            self._preview_resize_after_id = self.root.after(
                self.PREVIEW_RESIZE_DEBOUNCE_MS,
                self._render_latest_preview,
            )
        except tk.TclError:
            self._preview_resize_after_id = None

    def _get_canvas_size(self) -> tuple[int, int]:
        width = int(self.preview_canvas.winfo_width())
        height = int(self.preview_canvas.winfo_height())

        if width <= 2:
            width = self.preview_width
        if height <= 2:
            height = self.preview_height

        return max(1, width), max(1, height)

    def update_preview(self, frame, leds=()) -> bool:
        if frame is None or getattr(frame, "size", 0) == 0:
            self.set_preview_status("Sem imagem da câmera", "#FCA5A5")
            return False

        self._latest_frame = frame.copy()
        self._latest_leds = tuple(leds or ())
        rendered = self._render_latest_preview()
        if rendered:
            self.set_preview_status(
                "Ao vivo • atualização otimizada",
                "#86EFAC",
            )
        return rendered

    def _render_latest_preview(self) -> bool:
        self._preview_resize_after_id = None
        frame = self._latest_frame

        if frame is None or getattr(frame, "size", 0) == 0:
            return False

        frame_height, frame_width = frame.shape[:2]
        if frame_width <= 0 or frame_height <= 0:
            return False

        canvas_width, canvas_height = self._get_canvas_size()
        scale = min(
            canvas_width / float(frame_width),
            canvas_height / float(frame_height),
        )
        render_width = max(1, int(round(frame_width * scale)))
        render_height = max(1, int(round(frame_height * scale)))
        offset_x = max(0, (canvas_width - render_width) // 2)
        offset_y = max(0, (canvas_height - render_height) // 2)

        interpolation = (
            cv2.INTER_AREA
            if render_width < frame_width or render_height < frame_height
            else cv2.INTER_LINEAR
        )
        if (render_width, render_height) == (frame_width, frame_height):
            preview = frame
        else:
            preview = cv2.resize(
                frame,
                (render_width, render_height),
                interpolation=interpolation,
            )
        image_tk = self._create_preview_image(preview)
        if image_tk is None:
            self.set_preview_status("Falha ao renderizar prévia", "#FCA5A5")
            return False

        self._preview_tk = image_tk
        # Reutiliza o item do canvas: apagar e recriar a imagem inteira em todo
        # frame aumenta trabalho do Tcl/Tk e piora a sensação de atraso.
        self.preview_canvas.delete("preview_guide")
        updated = False
        if self._preview_image_item is not None:
            try:
                self.preview_canvas.itemconfigure(
                    self._preview_image_item,
                    image=image_tk,
                )
                self.preview_canvas.coords(
                    self._preview_image_item,
                    offset_x,
                    offset_y,
                )
                updated = True
            except tk.TclError:
                self._preview_image_item = None
        if not updated:
            self._preview_image_item = self.preview_canvas.create_image(
                offset_x,
                offset_y,
                image=image_tk,
                anchor=tk.NW,
                tags=("preview_image",),
            )
        self._draw_guides(
            leds=self._latest_leds,
            frame_width=frame_width,
            frame_height=frame_height,
            scale=scale,
            offset_x=offset_x,
            offset_y=offset_y,
        )
        self.preview_canvas.tag_lower("preview_image")
        self.preview_canvas.tag_raise("preview_guide")
        return True

    def _create_preview_image(self, preview):
        height, width = preview.shape[:2]

        if self._preview_use_ppm:
            try:
                rgb = cv2.cvtColor(preview, cv2.COLOR_BGR2RGB)
                header = f"P6\n{width} {height}\n255\n".encode("ascii")
                return tk.PhotoImage(
                    data=header + rgb.tobytes(),
                    format="PPM",
                )
            except tk.TclError:
                self._preview_use_ppm = False

        encoded, buffer = cv2.imencode(
            ".png",
            preview,
            [cv2.IMWRITE_PNG_COMPRESSION, 1],
        )
        if not encoded:
            return None

        image_data = base64.b64encode(buffer).decode("ascii")
        return tk.PhotoImage(data=image_data)

    def _draw_guides(
        self,
        leds,
        frame_width: int,
        frame_height: int,
        scale: float,
        offset_x: int,
        offset_y: int,
    ) -> None:
        led_list = list(leds or ())
        if not led_list:
            return

        left = offset_x + int(frame_width * scale)
        top = offset_y + int(frame_height * scale)
        right = offset_x
        bottom = offset_y

        for led in led_list:
            led_id = str(getattr(led, "id", ""))
            center_x = offset_x + int(
                round(int(getattr(led, "centro_x", 0)) * scale)
            )
            center_y = offset_y + int(
                round(int(getattr(led, "centro_y", 0)) * scale)
            )
            radius = max(
                3,
                int(round(int(getattr(led, "raio", 1)) * scale)),
            )
            failed = led_id in self._failed_led_ids
            color = self.PREVIEW_FAILED if failed else self.PREVIEW_GUIDE
            line_width = 3 if failed else 1

            left = min(left, center_x - radius)
            top = min(top, center_y - radius)
            right = max(right, center_x + radius)
            bottom = max(bottom, center_y + radius)

            self.preview_canvas.create_oval(
                center_x - radius,
                center_y - radius,
                center_x + radius,
                center_y + radius,
                outline=color,
                width=line_width,
                tags=("preview_guide",),
            )

            if failed:
                dot_radius = max(3, radius // 4)
                self.preview_canvas.create_oval(
                    center_x - dot_radius,
                    center_y - dot_radius,
                    center_x + dot_radius,
                    center_y + dot_radius,
                    fill=self.PREVIEW_FAILED,
                    outline="#FFFFFF",
                    width=1,
                    tags=("preview_guide",),
                )
                self.preview_canvas.create_text(
                    center_x,
                    max(offset_y + 12, center_y - radius - 9),
                    text=f"{led_id} APAGADO",
                    fill="#FFFFFF",
                    font=("DejaVu Sans", 9, "bold"),
                    anchor="s",
                    tags=("preview_guide",),
                )

        margin = max(6, int(round(8 * scale)))
        self.preview_canvas.create_rectangle(
            left - margin,
            top - margin,
            right + margin,
            bottom + margin,
            outline=self.PREVIEW_BOARD_GUIDE,
            width=2,
            dash=(6, 4),
            tags=("preview_guide",),
        )

    def set_failed_led_ids(self, failed_led_ids=()) -> None:
        new_ids = frozenset(str(item) for item in (failed_led_ids or ()))
        if new_ids == self._failed_led_ids:
            return

        self._failed_led_ids = new_ids
        self._render_latest_preview()

    def set_preview_status(self, message: str, color: str) -> None:
        self.preview_status.configure(text=message, fg=color)

    def set_preview_paused(self, paused: bool) -> None:
        if paused:
            self.set_preview_status(
                "Imagem mantida • processando",
                "#FDE68A",
            )
        else:
            self.set_preview_status(
                "Ao vivo • atualização otimizada",
                "#86EFAC",
            )

    def clear_preview(self, message: str = "Aguardando câmera") -> None:
        self._preview_tk = None
        self._preview_image_item = None
        self._latest_frame = None
        self._latest_leds = ()
        self._failed_led_ids = frozenset()
        self.preview_canvas.delete("all")
        self.set_preview_status(message, self.PREVIEW_MUTED)

    def show_preparing(
        self,
        detail: str = "Preparando câmera e parâmetros",
    ) -> None:
        self.set_failed_led_ids(())
        self._set_state(
            background=self.COLOR_PROCESSING,
            foreground="#111827",
            status="PREPARANDO",
            detail=detail,
        )

    def show_waiting(
        self,
        led_count: int,
        total: int,
        ok_count: int,
        ng_count: int,
    ) -> None:
        led_count = max(0, int(led_count))
        if led_count != self._configured_led_count:
            self._configured_led_count = led_count
            self._has_led_result = False
            self._last_result_ok = None
            self.set_failed_led_ids(())

        if self._has_led_result and self._last_result_ok is not None:
            if self._last_result_ok:
                background = self.COLOR_WAITING_AFTER_OK
                detail = "Última placa: OK — insira uma nova placa"
            else:
                background = self.COLOR_WAITING_AFTER_NG
                detail = "Última placa: NG — pontos apagados destacados na câmera"
        else:
            background = self.COLOR_WAITING
            detail = f"{led_count} LEDs preparados — insira uma placa"
            self.led_summary_label.configure(
                text=f"LEDS CONFIGURADOS: {led_count}"
            )

        self._set_state(
            background=background,
            foreground="#FFFFFF",
            status="AGUARDANDO",
            detail=detail,
        )
        self._set_counters(total, ok_count, ng_count)

    def show_positioning(
        self,
        delay_seconds: float,
        total: int,
        ok_count: int,
        ng_count: int,
    ) -> None:
        self.set_failed_led_ids(())
        self._set_state(
            background=self.COLOR_POSITIONING,
            foreground="#FFFFFF",
            status="POSICIONANDO",
            detail=(
                "Placa detectada — estabilizando por "
                f"{delay_seconds:.1f} s"
            ),
        )
        self._set_counters(total, ok_count, ng_count)

    def show_waiting_removal(
        self,
        total: int,
        ok_count: int,
        ng_count: int,
    ) -> None:
        self._set_state(
            background=self.COLOR_WAITING_REMOVAL,
            foreground="#FFFFFF",
            status="RETIRE A PLACA",
            detail="A próxima inspeção será liberada após retirar a placa",
        )
        self._set_counters(total, ok_count, ng_count)

    def show_processing(
        self,
        total: int,
        ok_count: int,
        ng_count: int,
    ) -> None:
        self.set_failed_led_ids(())
        self._set_state(
            background=self.COLOR_PROCESSING,
            foreground="#111827",
            status="PROCESSANDO",
            detail="Inspeção em andamento",
        )
        self._set_counters(total, ok_count, ng_count)

    def show_result(
        self,
        is_ok: bool,
        elapsed_seconds: float,
        failed_led_ids: tuple[str, ...],
        total: int,
        ok_count: int,
        ng_count: int,
    ) -> None:
        background = self.COLOR_OK if is_ok else self.COLOR_NG
        status = "OK" if is_ok else "NG"
        off_count = len(failed_led_ids)
        lit_count = max(0, self._configured_led_count - off_count)

        self._has_led_result = True
        self._last_result_ok = bool(is_ok)
        self.led_summary_label.configure(
            text=f"ACESOS: {lit_count}    APAGADOS: {off_count}"
        )
        self.set_failed_led_ids(failed_led_ids)

        if is_ok:
            detail = f"Todos os LEDs acesos\nTempo: {elapsed_seconds:.3f} s"
        else:
            failed_text = ", ".join(failed_led_ids[:10])
            if len(failed_led_ids) > 10:
                failed_text += f" e mais {len(failed_led_ids) - 10}"
            detail = (
                f"LEDs apagados: {failed_text}"
                f"\nMarcados em vermelho na câmera"
                f"\nTempo: {elapsed_seconds:.3f} s"
            )

        self._set_state(
            background=background,
            foreground="#FFFFFF",
            status=status,
            detail=detail,
        )
        self._set_counters(total, ok_count, ng_count)

    def show_error(
        self,
        message: str,
        total: int,
        ok_count: int,
        ng_count: int,
    ) -> None:
        self._set_state(
            background=self.COLOR_ERROR,
            foreground="#FFFFFF",
            status="ERRO",
            detail=message,
        )
        self._set_counters(total, ok_count, ng_count)

    def _set_counters(
        self,
        total: int,
        ok_count: int,
        ng_count: int,
    ) -> None:
        total = max(0, int(total))
        ok_count = max(0, int(ok_count))
        ng_count = max(0, int(ng_count))

        self.total_value_label.configure(text=str(total))
        self.ok_value_label.configure(text=str(ok_count))
        self.ng_value_label.configure(text=str(ng_count))
        self.counter_label.configure(
            text=f"TOTAL {total}    OK {ok_count}    NG {ng_count}"
        )

    def _set_state(
        self,
        background: str,
        foreground: str,
        status: str,
        detail: str,
    ) -> None:
        for widget in (
            self.analysis_panel,
            self.brand_label,
            self.mode_label,
            self.status_frame,
            self.status_label,
            self.detail_label,
            self.led_summary_label,
            self.metrics_frame,
            self.counter_label,
        ):
            widget.configure(bg=background)

        status_font_size = self.STATUS_FONT_SIZES.get(status, 36)
        self.status_label.configure(
            text=status,
            font=("DejaVu Sans", status_font_size, "bold"),
            fg=foreground,
        )
        self.detail_label.configure(text=detail, fg=foreground)
        self.brand_label.configure(fg=foreground)
        self.mode_label.configure(
            fg=foreground if foreground == "#111827" else "#CBD5E1"
        )
        self.led_summary_label.configure(fg=foreground)
        self.root.update_idletasks()

    def _handle_trigger(self, _event=None) -> str:
        self.on_trigger()
        return "break"

    def _handle_close(self, _event=None) -> str:
        self.on_close()
        return "break"
