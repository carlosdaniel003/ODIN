from __future__ import annotations

import tkinter as tk

from src.ui.operation_window import DesktopOperationWindow


def substituir_texto_marcacao_azul(texto: str) -> str:
    return str(texto).replace(
        "Marcados em vermelho na câmera",
        "Marcados em azul na câmera",
    )


def texto_placa_analisada_f2(is_ok: bool) -> str:
    """Mensagem curta e determinística para caber ao lado da preview F2."""
    if bool(is_ok):
        return "PLACA OK\nINSIRA UMA NOVA PLACA"
    return "PLACA NG\nPONTOS APAGADOS\nDESTACADOS NA CÂMERA"


class BlueOperationWindow(DesktopOperationWindow):
    """Tela F2 com todas as referências visuais de NG em azul."""

    PREVIEW_FAILED = "#2563EB"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.preview_legend.configure(
            text="CÍRCULO AZUL: LED APAGADO",
            fg=self.PREVIEW_FAILED,
        )

    def _widget_pertence_ao_painel(self, widget) -> bool:
        atual = widget
        while atual is not None:
            if atual is self.container:
                return True
            atual = getattr(atual, "master", None)
        return False

    def hide(self) -> None:
        if self._preview_resize_after_id is not None:
            try:
                self.root.after_cancel(self._preview_resize_after_id)
            except Exception:
                pass
            self._preview_resize_after_id = None

        try:
            widget_com_grab = self.root.grab_current()
            if (
                widget_com_grab is not None
                and self._widget_pertence_ao_painel(widget_com_grab)
            ):
                widget_com_grab.grab_release()
        except Exception:
            pass

        try:
            self.container.place_forget()
            self.container.lower()
        except tk.TclError:
            pass

        try:
            self.root.update_idletasks()
            self.root.focus_force()
        except tk.TclError:
            pass

    def show_result(
        self,
        is_ok: bool,
        elapsed_seconds: float,
        failed_led_ids: tuple[str, ...],
        total: int,
        ok_count: int,
        ng_count: int,
    ) -> None:
        super().show_result(
            is_ok=is_ok,
            elapsed_seconds=elapsed_seconds,
            failed_led_ids=failed_led_ids,
            total=total,
            ok_count=ok_count,
            ng_count=ng_count,
        )

        if not is_ok:
            texto = str(self.detail_label.cget("text"))
            self.detail_label.configure(
                text=substituir_texto_marcacao_azul(texto)
            )

    def show_waiting(
        self,
        led_count: int,
        total: int,
        ok_count: int,
        ng_count: int,
    ) -> None:
        """Mantém o texto pós-resultado legível no espaço restante da preview."""
        super().show_waiting(
            led_count=led_count,
            total=total,
            ok_count=ok_count,
            ng_count=ng_count,
        )

        if not (
            bool(getattr(self, "_has_led_result", False))
            and getattr(self, "_last_result_ok", None) is not None
        ):
            return

        # A miniatura do último frame ocupa a coluna esquerda do painel de
        # resultado. Não dependa do wraplength anterior (calculado quando essa
        # coluna ainda não existia): use linhas explícitas curtas e centralize
        # o texto dentro da coluna livre da direita.
        self.detail_label.configure(
            text=texto_placa_analisada_f2(bool(self._last_result_ok)),
            justify="center",
            anchor="center",
            wraplength=0,
        )
