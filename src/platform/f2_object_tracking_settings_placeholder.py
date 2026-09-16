from __future__ import annotations

"""Placeholder visual para o futuro rastreamento automático de objetos do F2.

Nesta etapa a opção existe somente na janela de Configurações. Ela fica
explicitamente desabilitada e não altera configuração, câmera, análise, fluxo
produtivo ou persistência. A funcionalidade será ligada em uma etapa futura.
"""

import tkinter as tk

from src.ui.main_window import ODINView


F2_OBJECT_TRACKING_OPTION_TEXT = "Ativar rastreamento automático de objetos"
F2_OBJECT_TRACKING_SECTION_TITLE = "Produção F2"
F2_OBJECT_TRACKING_NOT_IMPLEMENTED_TEXT = (
    "Opção reservada exclusivamente ao modo PRODUÇÃO F2. "
    "O rastreamento automático de objetos ainda será implementado."
)


def _percorrer_widgets(widget):
    for filho in widget.winfo_children():
        yield filho
        yield from _percorrer_widgets(filho)


def _encontrar_conteudo_sistema(janela: tk.Toplevel):
    """Localiza o container rolável da aba Sistema sem acoplar ao F3."""
    for widget in _percorrer_widgets(janela):
        if not isinstance(widget, tk.Label):
            continue
        try:
            texto = str(widget.cget("text"))
        except tk.TclError:
            continue
        if texto != "Armazenamento":
            continue

        card_armazenamento = widget.master
        return getattr(card_armazenamento, "master", None)
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


def adicionar_opcao_rastreamento_automatico_f2(self, janela: tk.Toplevel) -> bool:
    """Adiciona somente a opção visual; nenhum comportamento é conectado."""
    if _opcao_ja_existe(janela):
        return False

    parent = _encontrar_conteudo_sistema(janela)
    if parent is None:
        return False

    card = tk.Frame(
        parent,
        bg=self.COR_CARD_2,
        highlightthickness=1,
        highlightbackground=self.COR_BORDA,
    )
    card.pack(fill=tk.X, padx=(0, 8), pady=(0, 14))

    tk.Label(
        card,
        text=F2_OBJECT_TRACKING_SECTION_TITLE,
        font=("Segoe UI", 11, "bold"),
        fg=self.COR_TEXTO,
        bg=self.COR_CARD_2,
        anchor="w",
    ).pack(fill=tk.X, padx=14, pady=(12, 6))

    tk.Frame(
        card,
        bg="#172033",
        height=1,
    ).pack(fill=tk.X, padx=14, pady=(0, 10))

    tk.Label(
        card,
        text=F2_OBJECT_TRACKING_NOT_IMPLEMENTED_TEXT,
        font=("Segoe UI", 9),
        fg=self.COR_TEXTO_2,
        bg=self.COR_CARD_2,
        wraplength=600,
        justify=tk.LEFT,
        anchor="w",
    ).pack(fill=tk.X, padx=14, pady=(0, 8))

    valor_rastreamento = tk.BooleanVar(master=janela, value=False)
    check = tk.Checkbutton(
        card,
        text=F2_OBJECT_TRACKING_OPTION_TEXT,
        variable=valor_rastreamento,
        state=tk.DISABLED,
        font=("Segoe UI", 10, "bold"),
        fg=self.COR_TEXTO,
        disabledforeground=self.COR_TEXTO_2,
        bg=self.COR_CARD_2,
        activebackground=self.COR_CARD_2,
        activeforeground=self.COR_TEXTO,
        selectcolor=self.COR_CARD,
        anchor="w",
    )
    check.pack(fill=tk.X, padx=12, pady=(0, 4))

    tk.Label(
        card,
        text="Funcionalidade ainda não implementada.",
        font=("Segoe UI", 8),
        fg=self.COR_TEXTO_3,
        bg=self.COR_CARD_2,
        anchor="w",
    ).pack(fill=tk.X, padx=14, pady=(0, 12))

    # Mantém a variável Tcl viva enquanto a janela existir. Não é lida nem salva.
    janela._odin_f2_object_tracking_placeholder_var = valor_rastreamento
    janela._odin_f2_object_tracking_placeholder_check = check
    return True


def instalar_opcao_rastreamento_automatico_f2() -> None:
    """Envolve somente a abertura de Configurações para inserir o placeholder."""
    current = ODINView.abrir_janela_configuracoes
    if bool(getattr(current, "_odin_f2_object_tracking_settings_placeholder", False)):
        return

    previous = current

    def abrir(self, *args, **kwargs):
        janelas_antes = {
            widget
            for widget in self.root.winfo_children()
            if isinstance(widget, tk.Toplevel)
        }

        resultado = previous(self, *args, **kwargs)

        novas_janelas = [
            widget
            for widget in self.root.winfo_children()
            if isinstance(widget, tk.Toplevel)
            and widget not in janelas_antes
            and widget.winfo_exists()
        ]
        if novas_janelas:
            janela = novas_janelas[-1]
            adicionar_opcao_rastreamento_automatico_f2(self, janela)
            try:
                janela.update_idletasks()
            except tk.TclError:
                pass

        return resultado

    abrir._odin_f2_object_tracking_settings_placeholder = True
    abrir._odin_f2_object_tracking_settings_placeholder_base = previous
    ODINView.abrir_janela_configuracoes = abrir
