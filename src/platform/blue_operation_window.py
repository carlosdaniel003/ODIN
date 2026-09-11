from __future__ import annotations

from src.platform.raspberry_runtime_fixes import (
    StableRaspberryOperationWindow,
)


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


class BlueRaspberryOperationWindow(StableRaspberryOperationWindow):
    """Tela F2 com todas as referências visuais de NG em azul."""

    PREVIEW_FAILED = "#2563EB"

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
