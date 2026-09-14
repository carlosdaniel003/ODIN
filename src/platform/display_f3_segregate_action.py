from __future__ import annotations

from src.platform.display_production_f3_window import DisplayProductionF3Window


SEGREGATE_BUTTON_TEXT = "SEGREGAR PLACA  [1]"
SEGREGATE_FOOTER_TEXT = "1: SEGREGAR PLACA  •  F3 ou ESC: voltar ao ODIN"
SEGREGATE_RESULT_TEXT = "PLACA SEGREGADA"
SEGREGATE_RESULT_DETAIL = (
    "Retire a placa do suporte. A próxima placa começará pelo primeiro CHECK."
)


_INSTALLED = False


def instalar_acao_segregar_placa_display_f3() -> None:
    """Troca a nomenclatura operacional para SEGREGAR sem alterar o contrato interno.

    ``discarded``/``on_discard`` permanecem como nomes internos de compatibilidade.
    A interface produtiva, porém, fala somente em SEGREGAR PLACA.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    cls = DisplayProductionF3Window
    original_init = cls.__init__
    original_show_plate_result = cls.show_plate_result

    def init(self, *args, **kwargs) -> None:
        original_init(self, *args, **kwargs)
        try:
            self.discard_button.configure(text=SEGREGATE_BUTTON_TEXT)
        except Exception:
            pass
        try:
            self.footer_label.configure(text=SEGREGATE_FOOTER_TEXT)
        except Exception:
            pass

    def show_plate_result(
        self,
        is_ok: bool,
        snapshot: dict,
        discarded: bool = False,
    ) -> None:
        original_show_plate_result(
            self,
            is_ok=is_ok,
            snapshot=snapshot,
            discarded=discarded,
        )
        if not bool(discarded):
            return
        try:
            self.status_label.configure(text=SEGREGATE_RESULT_TEXT)
        except Exception:
            pass
        try:
            self.detail_label.configure(text=SEGREGATE_RESULT_DETAIL)
        except Exception:
            pass

    cls.__init__ = init
    cls.show_plate_result = show_plate_result
    cls._odin_display_f3_segregate_action = True
    _INSTALLED = True
