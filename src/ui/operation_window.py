from __future__ import annotations

import tkinter as tk
from collections.abc import Callable


class OperationWindow:
    """Tela de produção leve exibida sobre a parametrização."""

    COLOR_WAITING = "#111827"
    COLOR_PROCESSING = "#F59E0B"
    COLOR_OK = "#16A34A"
    COLOR_NG = "#DC2626"
    COLOR_ERROR = "#7F1D1D"

    def __init__(
        self,
        root: tk.Tk,
        on_trigger: Callable[[], None],
        on_close: Callable[[], None],
    ) -> None:
        self.root = root
        self.on_trigger = on_trigger
        self.on_close = on_close
        self._blink_after_ids: list[str] = []

        self.container = tk.Frame(
            root,
            bg=self.COLOR_WAITING,
            highlightthickness=0,
        )

        self.brand_label = tk.Label(
            self.container,
            text="ODIN",
            font=("DejaVu Sans", 28, "bold"),
            bg=self.COLOR_WAITING,
            fg="#D1D5DB",
        )
        self.brand_label.pack(pady=(42, 0))

        self.status_label = tk.Label(
            self.container,
            text="AGUARDANDO",
            font=("DejaVu Sans", 86, "bold"),
            bg=self.COLOR_WAITING,
            fg="#FFFFFF",
            justify="center",
        )
        self.status_label.pack(expand=True)

        self.detail_label = tk.Label(
            self.container,
            text="Pressione ENTER para inspecionar",
            font=("DejaVu Sans", 20),
            bg=self.COLOR_WAITING,
            fg="#E5E7EB",
            justify="center",
        )
        self.detail_label.pack(pady=(0, 24))

        self.counter_label = tk.Label(
            self.container,
            text="TOTAL 0    OK 0    NG 0",
            font=("DejaVu Sans", 16, "bold"),
            bg=self.COLOR_WAITING,
            fg="#D1D5DB",
        )
        self.counter_label.pack(pady=(0, 16))

        self.footer_label = tk.Label(
            self.container,
            text="F1 ou ESC: parametrização",
            font=("DejaVu Sans", 12),
            bg=self.COLOR_WAITING,
            fg="#9CA3AF",
        )
        self.footer_label.pack(pady=(0, 18))

        root.bind("<Return>", self._handle_trigger, add="+")
        root.bind("<KP_Enter>", self._handle_trigger, add="+")
        root.bind("<F1>", self._handle_close, add="+")
        root.bind("<Escape>", self._handle_close, add="+")

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
        self.container.focus_set()

    def hide(self) -> None:
        self._cancel_blink()
        self.container.place_forget()

    def show_preparing(self, detail: str = "Preparando câmera e parâmetros") -> None:
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
        self._set_state(
            background=self.COLOR_WAITING,
            foreground="#FFFFFF",
            status="AGUARDANDO",
            detail=f"{led_count} LEDs preparados — pressione ENTER",
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
        self._blink_result(background)

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
        self._cancel_blink()
        self._apply_background(background)
        self.status_label.configure(text=status, fg=foreground)
        self.detail_label.configure(text=detail, fg=foreground)
        self.brand_label.configure(fg=foreground)
        self.counter_label.configure(fg=foreground)
        self.footer_label.configure(fg=foreground)
        self.root.update_idletasks()

    def _blink_result(self, result_color: str) -> None:
        sequence = (
            (120, self.COLOR_WAITING),
            (240, result_color),
            (360, self.COLOR_WAITING),
            (480, result_color),
        )
        for delay_ms, color in sequence:
            after_id = self.root.after(
                delay_ms,
                lambda selected_color=color: self._apply_background(
                    selected_color
                ),
            )
            self._blink_after_ids.append(after_id)

    def _apply_background(self, background: str) -> None:
        for widget in (
            self.container,
            self.brand_label,
            self.status_label,
            self.detail_label,
            self.counter_label,
            self.footer_label,
        ):
            widget.configure(bg=background)

    def _cancel_blink(self) -> None:
        for after_id in self._blink_after_ids:
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass
        self._blink_after_ids.clear()

    def _handle_trigger(self, _event=None):
        if self.visible:
            self.on_trigger()
            return "break"
        return None

    def _handle_close(self, _event=None):
        if self.visible:
            self.on_close()
            return "break"
        return None
