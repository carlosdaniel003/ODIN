from __future__ import annotations

import base64
import tkinter as tk
from collections.abc import Callable

import cv2


class OperationWindow:
    """Tela de produção leve com prévia persistente da câmera."""

    COLOR_WAITING = "#111827"
    COLOR_POSITIONING = "#1D4ED8"
    COLOR_WAITING_REMOVAL = "#334155"
    COLOR_PROCESSING = "#F59E0B"
    COLOR_OK = "#16A34A"
    COLOR_NG = "#DC2626"
    COLOR_ERROR = "#7F1D1D"
    PREVIEW_BACKGROUND = "#020617"
    PREVIEW_BORDER = "#334155"
    PREVIEW_GUIDE = "#22D3EE"
    PREVIEW_BOARD_GUIDE = "#FBBF24"

    STATUS_FONT_SIZES = {
        "OK": 88,
        "NG": 88,
        "ERRO": 60,
        "AGUARDANDO": 44,
        "POSICIONANDO": 40,
        "PROCESSANDO": 42,
        "RETIRE A PLACA": 38,
        "PREPARANDO": 42,
    }

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
        self.preview_width = max(160, int(preview_width))
        self.preview_height = max(120, int(preview_height))
        self._preview_tk = None
        self._preview_image_item = None
        self._preview_guide_signature = None
        self._preview_use_ppm = True
        self._configured_led_count = 0
        self._has_led_result = False

        self.container = tk.Frame(
            root,
            bg=self.COLOR_WAITING,
            highlightthickness=0,
            takefocus=True,
        )
        self.container.grid_rowconfigure(1, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        self.brand_label = tk.Label(
            self.container,
            text="ODIN",
            font=("DejaVu Sans", 28, "bold"),
            bg=self.COLOR_WAITING,
            fg="#FFFFFF",
            anchor="center",
            justify="center",
        )
        self.brand_label.grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(28, 8),
        )

        self.status_frame = tk.Frame(
            self.container,
            bg=self.COLOR_WAITING,
            highlightthickness=0,
        )
        self.status_frame.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=(24, 16),
            pady=16,
        )
        self.status_frame.grid_rowconfigure(0, weight=1)
        self.status_frame.grid_columnconfigure(0, weight=1)

        self.status_label = tk.Label(
            self.status_frame,
            text="AGUARDANDO",
            font=("DejaVu Sans", 44, "bold"),
            bg=self.COLOR_WAITING,
            fg="#FFFFFF",
            anchor="center",
            justify="center",
            wraplength=0,
        )
        self.status_label.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=4,
        )

        self.detail_label = tk.Label(
            self.status_frame,
            text="Insira uma placa para iniciar",
            font=("DejaVu Sans", 18),
            bg=self.COLOR_WAITING,
            fg="#FFFFFF",
            anchor="center",
            justify="center",
            wraplength=620,
        )
        self.detail_label.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=8,
            pady=(0, 8),
        )

        self.led_summary_label = tk.Label(
            self.status_frame,
            text="LEDS CONFIGURADOS: 0",
            font=("DejaVu Sans", 17, "bold"),
            bg=self.COLOR_WAITING,
            fg="#FFFFFF",
            anchor="center",
            justify="center",
            wraplength=0,
        )
        self.led_summary_label.grid(
            row=2,
            column=0,
            sticky="ew",
            padx=8,
            pady=(0, 14),
        )

        self.preview_frame = tk.Frame(
            self.container,
            bg=self.PREVIEW_BACKGROUND,
            highlightbackground=self.PREVIEW_BORDER,
            highlightthickness=2,
            width=self.preview_width + 28,
            height=self.preview_height + 78,
        )
        self.preview_frame.grid(
            row=1,
            column=1,
            sticky="e",
            padx=(0, 24),
            pady=16,
        )
        self.preview_frame.grid_propagate(False)

        self.preview_title = tk.Label(
            self.preview_frame,
            text="CÂMERA AO VIVO",
            font=("DejaVu Sans", 12, "bold"),
            bg=self.PREVIEW_BACKGROUND,
            fg="#E2E8F0",
            anchor="center",
            justify="center",
        )
        self.preview_title.pack(fill="x", pady=(10, 6))

        self.preview_canvas = tk.Canvas(
            self.preview_frame,
            width=self.preview_width,
            height=self.preview_height,
            bg=self.PREVIEW_BACKGROUND,
            highlightthickness=0,
            bd=0,
        )
        self.preview_canvas.pack()

        self.preview_status = tk.Label(
            self.preview_frame,
            text="Aguardando câmera",
            font=("DejaVu Sans", 10),
            bg=self.PREVIEW_BACKGROUND,
            fg="#94A3B8",
            anchor="center",
            justify="center",
        )
        self.preview_status.pack(fill="x", pady=(7, 8))

        self.counter_label = tk.Label(
            self.container,
            text="TOTAL 0    OK 0    NG 0",
            font=("DejaVu Sans", 16, "bold"),
            bg=self.COLOR_WAITING,
            fg="#FFFFFF",
            anchor="center",
            justify="center",
        )
        self.counter_label.grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(4, 10),
        )

        self.footer_label = tk.Label(
            self.container,
            text="F1 ou ESC: parametrização",
            font=("DejaVu Sans", 12),
            bg=self.COLOR_WAITING,
            fg="#FFFFFF",
            anchor="center",
            justify="center",
        )
        self.footer_label.grid(
            row=3,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(0, 14),
        )

        self.container.bind("<Return>", self._handle_trigger)
        self.container.bind("<KP_Enter>", self._handle_trigger)
        self.container.bind("<F1>", self._handle_close)
        self.container.bind("<Escape>", self._handle_close)

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
        self._raise_preview()
        self.container.focus_force()

    def hide(self) -> None:
        self.container.place_forget()

    def update_preview(self, frame, leds=()) -> bool:
        if frame is None or getattr(frame, "size", 0) == 0:
            self.set_preview_status("Sem imagem da câmera", "#FCA5A5")
            return False

        frame_height, frame_width = frame.shape[:2]
        if frame_width <= 0 or frame_height <= 0:
            return False

        preview = cv2.resize(
            frame,
            (self.preview_width, self.preview_height),
            interpolation=cv2.INTER_AREA,
        )
        image_tk = self._create_preview_image(preview)
        if image_tk is None:
            self.set_preview_status(
                "Falha ao renderizar prévia",
                "#FCA5A5",
            )
            return False

        self._preview_tk = image_tk

        if self._preview_image_item is None:
            self._preview_image_item = self.preview_canvas.create_image(
                0,
                0,
                image=image_tk,
                anchor=tk.NW,
                tags=("preview_image",),
            )
        else:
            self.preview_canvas.itemconfigure(
                self._preview_image_item,
                image=image_tk,
            )

        self._update_guides(
            leds=leds,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        self._raise_preview()
        self.set_preview_status("Ao vivo • 1 FPS", "#86EFAC")
        return True

    def _create_preview_image(self, preview):
        if self._preview_use_ppm:
            try:
                rgb = cv2.cvtColor(preview, cv2.COLOR_BGR2RGB)
                header = (
                    f"P6\n{self.preview_width} "
                    f"{self.preview_height}\n255\n"
                ).encode("ascii")
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

    def set_preview_status(self, message: str, color: str) -> None:
        self.preview_status.configure(text=message, fg=color)

    def set_preview_paused(self, paused: bool) -> None:
        if paused:
            self.set_preview_status(
                "Imagem mantida • processando",
                "#FDE68A",
            )
        else:
            self.set_preview_status("Ao vivo • 1 FPS", "#86EFAC")
        self._raise_preview()

    def clear_preview(self, message: str = "Aguardando câmera") -> None:
        self._preview_tk = None
        self._preview_image_item = None
        self._preview_guide_signature = None
        self.preview_canvas.delete("all")
        self.set_preview_status(message, "#94A3B8")

    def _raise_preview(self) -> None:
        try:
            self.preview_frame.lift()
            if self._preview_image_item is not None:
                self.preview_canvas.tag_lower("preview_image")
            self.preview_canvas.tag_raise("preview_guide")
        except tk.TclError:
            pass

    def _update_guides(
        self,
        leds,
        frame_width: int,
        frame_height: int,
    ) -> None:
        led_list = list(leds or ())
        signature = (
            frame_width,
            frame_height,
            tuple(
                (
                    str(getattr(led, "id", "")),
                    int(getattr(led, "centro_x", 0)),
                    int(getattr(led, "centro_y", 0)),
                    int(getattr(led, "raio", 0)),
                )
                for led in led_list
            ),
        )
        if signature == self._preview_guide_signature:
            return

        self._preview_guide_signature = signature
        self.preview_canvas.delete("preview_guide")

        if not led_list:
            return

        scale_x = self.preview_width / frame_width
        scale_y = self.preview_height / frame_height
        radius_scale = min(scale_x, scale_y)
        left = self.preview_width
        top = self.preview_height
        right = 0
        bottom = 0

        for led in led_list:
            center_x = int(getattr(led, "centro_x", 0) * scale_x)
            center_y = int(getattr(led, "centro_y", 0) * scale_y)
            radius = max(
                2,
                int(getattr(led, "raio", 1) * radius_scale),
            )
            left = min(left, center_x - radius)
            top = min(top, center_y - radius)
            right = max(right, center_x + radius)
            bottom = max(bottom, center_y + radius)

            self.preview_canvas.create_oval(
                center_x - radius,
                center_y - radius,
                center_x + radius,
                center_y + radius,
                outline=self.PREVIEW_GUIDE,
                width=1,
                tags=("preview_guide",),
            )

        margin = 8
        self.preview_canvas.create_rectangle(
            max(1, left - margin),
            max(1, top - margin),
            min(self.preview_width - 1, right + margin),
            min(self.preview_height - 1, bottom + margin),
            outline=self.PREVIEW_BOARD_GUIDE,
            width=2,
            dash=(6, 4),
            tags=("preview_guide",),
        )

    def show_preparing(
        self,
        detail: str = "Preparando câmera e parâmetros",
    ) -> None:
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

        if not self._has_led_result:
            self.led_summary_label.configure(
                text=f"LEDS CONFIGURADOS: {led_count}"
            )

        self._set_state(
            background=self.COLOR_WAITING,
            foreground="#FFFFFF",
            status="AGUARDANDO",
            detail=f"{led_count} LEDs preparados — insira uma placa",
        )
        self._set_counters(total, ok_count, ng_count)

    def show_positioning(
        self,
        delay_seconds: float,
        total: int,
        ok_count: int,
        ng_count: int,
    ) -> None:
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
        self.led_summary_label.configure(
            text=f"ACESOS: {lit_count}    APAGADOS: {off_count}"
        )

        if is_ok:
            detail = f"Tempo de inspeção: {elapsed_seconds:.3f} s"
        else:
            failed_text = ", ".join(failed_led_ids[:12])
            if len(failed_led_ids) > 12:
                failed_text += f" e mais {len(failed_led_ids) - 12}"
            detail = (
                f"LEDs apagados: {failed_text}"
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
            self.container,
            self.status_frame,
            self.brand_label,
            self.status_label,
            self.detail_label,
            self.led_summary_label,
            self.counter_label,
            self.footer_label,
        ):
            widget.configure(bg=background)

        status_font_size = self.STATUS_FONT_SIZES.get(status, 42)
        self.status_label.configure(
            text=status,
            font=("DejaVu Sans", status_font_size, "bold"),
            fg=foreground,
            anchor="center",
            justify="center",
            wraplength=0,
        )
        self.detail_label.configure(
            text=detail,
            fg=foreground,
            anchor="center",
            justify="center",
        )
        self.brand_label.configure(fg=foreground)
        self.led_summary_label.configure(fg=foreground)
        self.counter_label.configure(fg=foreground)
        self.footer_label.configure(fg=foreground)
        self._raise_preview()
        self.root.update_idletasks()

    def _handle_trigger(self, _event=None) -> str:
        self.on_trigger()
        return "break"

    def _handle_close(self, _event=None) -> str:
        self.on_close()
        return "break"
