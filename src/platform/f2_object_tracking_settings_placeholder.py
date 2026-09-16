from __future__ import annotations

"""Placeholder visual para o futuro rastreamento automático de objetos do F2.

A opção deve aparecer dentro do card ``Produção F2`` que já é criado por
``f2_automatic_analysis``. Nesta etapa ela é somente visual, fica desabilitada e
não altera configuração, câmera, análise, fluxo produtivo ou persistência.
"""

import tkinter as tk

import src.platform.f2_automatic_analysis as f2_auto_module


F2_OBJECT_TRACKING_OPTION_TEXT = "Ativar rastreamento automático de objetos"
F2_OBJECT_TRACKING_SECTION_TITLE = "Produção F2"
F2_OBJECT_TRACKING_NOT_IMPLEMENTED_TEXT = (
    "Funcionalidade em desenvolvimento. A opção pertence somente ao modo "
    "Produção F2 e ainda não executa rastreamento."
)


def _percorrer_widgets(widget):
    for filho in widget.winfo_children():
        yield filho
        yield from _percorrer_widgets(filho)


def _encontrar_card_producao_f2(janela: tk.Toplevel):
    """Encontra o card real criado por F2AutomaticAnalysisMixin."""
    for widget in _percorrer_widgets(janela):
        if not isinstance(widget, tk.Label):
            continue
        try:
            if str(widget.cget("text")) == F2_OBJECT_TRACKING_SECTION_TITLE:
                return widget.master
        except tk.TclError:
            continue
    return None


def _opcao_ja_existe(janela: tk.Toplevel) -> bool:
    for widget in _percorrer_widgets(janela):
        if not isinstance(widget, tk.Checkbutton):
            continue
        try:
            if str(widget.cget("text")) == F2_OBJECT_TRACKING_OPTION_TEXT:
                return True
        except tk.TclError:
            continue
    return False


def adicionar_opcao_rastreamento_automatico_f2(app, janela: tk.Toplevel) -> bool:
    """Insere a opção no card Produção F2 existente, sem conectar comportamento."""
    if _opcao_ja_existe(janela):
        return False

    card = _encontrar_card_producao_f2(janela)
    if card is None:
        return False

    view = app.view

    # Pequena separação interna: continua sendo o mesmo card Produção F2.
    tk.Frame(
        card,
        bg="#172033",
        height=1,
    ).pack(fill=tk.X, padx=14, pady=(2, 9))

    valor_rastreamento = tk.BooleanVar(master=janela, value=False)
    check = tk.Checkbutton(
        card,
        text=F2_OBJECT_TRACKING_OPTION_TEXT,
        variable=valor_rastreamento,
        state=tk.DISABLED,
        font=("Segoe UI", 10, "bold"),
        fg=view.COR_TEXTO,
        disabledforeground=view.COR_TEXTO_2,
        bg=view.COR_CARD_2,
        activebackground=view.COR_CARD_2,
        activeforeground=view.COR_TEXTO,
        selectcolor=view.COR_CARD,
        anchor="w",
    )
    check.pack(fill=tk.X, padx=14, pady=(0, 4))

    tk.Label(
        card,
        text=F2_OBJECT_TRACKING_NOT_IMPLEMENTED_TEXT,
        font=("Segoe UI", 8),
        fg=view.COR_TEXTO_3,
        bg=view.COR_CARD_2,
        anchor="w",
        justify=tk.LEFT,
        wraplength=650,
    ).pack(fill=tk.X, padx=14, pady=(0, 12))

    # Mantém a variável Tcl viva enquanto a janela existir. Não é lida nem salva.
    janela._odin_f2_object_tracking_placeholder_var = valor_rastreamento
    janela._odin_f2_object_tracking_placeholder_check = check
    janela._odin_f2_object_tracking_placeholder_added = True

    try:
        janela.update_idletasks()
    except tk.TclError:
        pass
    return True


def instalar_opcao_rastreamento_automatico_f2() -> None:
    """Envolve o criador real do card F2, em vez da janela genérica de Configurações."""
    current = f2_auto_module._add_auto_analysis_setting
    if bool(getattr(current, "_odin_f2_object_tracking_settings_placeholder", False)):
        return

    previous = current

    def adicionar_setting_f2(app, settings_window):
        resultado = previous(app, settings_window)
        adicionar_opcao_rastreamento_automatico_f2(app, settings_window)
        return resultado

    adicionar_setting_f2._odin_f2_object_tracking_settings_placeholder = True
    adicionar_setting_f2._odin_f2_object_tracking_settings_placeholder_base = previous
    f2_auto_module._add_auto_analysis_setting = adicionar_setting_f2
