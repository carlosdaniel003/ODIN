from __future__ import annotations

import unicodedata
from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk

from src.ui.main_window import ODINView
from src.ui.desktop_operation_window import DesktopOperationWindow


# ---------------------------------------------------------------------------
# Identidade visual exclusiva da branch display
# ---------------------------------------------------------------------------
# O amarelo continua sendo a assinatura do ODIN, mas não ocupa todos os
# elementos. Fundos, cartões e bordas usam uma escala grafite; azul, violeta,
# verde e vermelho comunicam contexto e estado.
DISPLAY_YELLOW = "#F5C518"
DISPLAY_YELLOW_DARK = "#C99700"
DISPLAY_YELLOW_SOFT = "#FFE27A"
DISPLAY_BLUE = "#2596BE"
DISPLAY_BLUE_LIGHT = "#7DD3FC"
DISPLAY_BLUE_DARK = "#102C3A"
DISPLAY_PURPLE = "#8B5CF6"
DISPLAY_PURPLE_LIGHT = "#C4B5FD"
DISPLAY_PURPLE_DARK = "#271E3A"
DISPLAY_SUCCESS = "#22C55E"
DISPLAY_SUCCESS_LIGHT = "#86EFAC"
DISPLAY_SUCCESS_DARK = "#102F22"
DISPLAY_DANGER = "#EF4444"
DISPLAY_DANGER_LIGHT = "#FCA5A5"
DISPLAY_DANGER_DARK = "#35181B"
DISPLAY_WARNING = "#F59E0B"

DISPLAY_DARK = "#0B0F14"
DISPLAY_DARK_ALT = "#101720"
DISPLAY_DARK_CARD = "#151D27"
DISPLAY_DARK_RAISED = "#1C2633"
DISPLAY_DARK_HOVER = "#243140"
DISPLAY_BORDER = "#2B3746"
DISPLAY_BORDER_STRONG = "#3A485A"
DISPLAY_MUTED = "#9AA7B6"
DISPLAY_INK = "#17130A"
DISPLAY_WHITE = "#F5F7FA"

# Nomes antigos preservados para imports já existentes.
DISPLAY_BLUE_DEEP = DISPLAY_DARK


_DARK_BACKGROUND_MAP = {
    "#030712": DISPLAY_DARK,
    "#050b14": DISPLAY_DARK_ALT,
    "#020617": DISPLAY_DARK,
    "#07111f": DISPLAY_DARK_CARD,
    "#0b1220": DISPLAY_DARK_CARD,
    "#0b1626": DISPLAY_DARK_RAISED,
    "#0f172a": DISPLAY_DARK_ALT,
    "#111827": DISPLAY_DARK_ALT,
    "#122033": DISPLAY_DARK_RAISED,
    "#172033": DISPLAY_BORDER,
    "#1e293b": DISPLAY_DARK_RAISED,
    "#334155": DISPLAY_DARK_HOVER,
    "#374151": DISPLAY_DARK_HOVER,
    "#475569": DISPLAY_BORDER_STRONG,
    "#1e3a5f": DISPLAY_BLUE_DARK,
    "#1e3a8a": DISPLAY_BLUE_DARK,
    "#1d4ed8": DISPLAY_BLUE_DARK,
    "#1c7898": DISPLAY_BLUE_DARK,
    "#104a60": DISPLAY_DARK,
}

_BACKGROUND_ACCENT_MAP = {
    "#38bdf8": DISPLAY_BLUE_DARK,
    "#22d3ee": DISPLAY_BLUE_DARK,
    "#2563eb": DISPLAY_BLUE_DARK,
    "#2596be": DISPLAY_BLUE_DARK,
    "#fbbf24": DISPLAY_YELLOW_DARK,
    "#f59e0b": DISPLAY_YELLOW_DARK,
    "#d7a900": DISPLAY_YELLOW_DARK,
}

_FOREGROUND_ACCENT_MAP = {
    "#38bdf8": DISPLAY_BLUE_LIGHT,
    "#22d3ee": DISPLAY_BLUE_LIGHT,
    "#2563eb": DISPLAY_BLUE_LIGHT,
    "#2596be": DISPLAY_BLUE_LIGHT,
    "#bae6fd": DISPLAY_BLUE_LIGHT,
    "#e0f2fe": DISPLAY_BLUE_LIGHT,
    "#fbbf24": DISPLAY_YELLOW,
    "#fde68a": DISPLAY_YELLOW_SOFT,
    "#f59e0b": DISPLAY_YELLOW,
    "#d7a900": DISPLAY_YELLOW_DARK,
}

_MUTED_FOREGROUND_MAP = {
    "#cbd5e1": DISPLAY_WHITE,
    "#94a3b8": DISPLAY_MUTED,
    "#e2e8f0": DISPLAY_WHITE,
    "#f9fafb": DISPLAY_WHITE,
    "#bfdbfe": DISPLAY_BLUE_LIGHT,
    "#d9f3fc": DISPLAY_BLUE_LIGHT,
    "#64748b": "#718096",
}

_BORDER_OPTIONS = {
    "highlightbackground",
    "highlightcolor",
    "bordercolor",
    "lightcolor",
    "darkcolor",
}

_FOREGROUND_OPTIONS = {
    "foreground",
    "fg",
    "activeforeground",
    "disabledforeground",
    "insertbackground",
    "selectforeground",
}

_BACKGROUND_OPTIONS = {
    "background",
    "bg",
    "activebackground",
    "fieldbackground",
    "selectbackground",
    "troughcolor",
    "selectcolor",
}

_SECTION_TITLES = {
    "imagem principal · ao vivo",
    "imagem principal • ao vivo",
    "mapa de intensidade",
    "resultado geral",
    "imagem de teste · canal v",
    "máscara / roi",
    "roi ampliado",
    "debug técnico",
    "log produção",
    "histórico da sessão / leds analisados",
    "referências fixas",
    "leds fixos",
    "raio de seleção dos leds",
    "configurações de leds",
    "controles avançados da câmera",
}


@dataclass(frozen=True)
class ButtonStyle:
    background: str
    foreground: str
    activebackground: str
    activeforeground: str
    border: str


_BUTTON_STYLES = {
    "primary": ButtonStyle(
        DISPLAY_YELLOW_DARK,
        DISPLAY_INK,
        DISPLAY_YELLOW,
        DISPLAY_INK,
        DISPLAY_YELLOW,
    ),
    "secondary": ButtonStyle(
        DISPLAY_DARK_RAISED,
        DISPLAY_YELLOW_SOFT,
        DISPLAY_DARK_HOVER,
        DISPLAY_YELLOW,
        DISPLAY_YELLOW_DARK,
    ),
    "info": ButtonStyle(
        DISPLAY_BLUE_DARK,
        DISPLAY_BLUE_LIGHT,
        DISPLAY_BLUE,
        DISPLAY_WHITE,
        DISPLAY_BLUE,
    ),
    "selection": ButtonStyle(
        DISPLAY_PURPLE_DARK,
        DISPLAY_PURPLE_LIGHT,
        DISPLAY_PURPLE,
        DISPLAY_WHITE,
        DISPLAY_PURPLE,
    ),
    "success": ButtonStyle(
        DISPLAY_SUCCESS_DARK,
        DISPLAY_SUCCESS_LIGHT,
        DISPLAY_SUCCESS,
        DISPLAY_INK,
        DISPLAY_SUCCESS,
    ),
    "danger": ButtonStyle(
        DISPLAY_DANGER_DARK,
        DISPLAY_DANGER_LIGHT,
        DISPLAY_DANGER,
        DISPLAY_WHITE,
        DISPLAY_DANGER,
    ),
    "neutral": ButtonStyle(
        DISPLAY_DARK_RAISED,
        DISPLAY_WHITE,
        DISPLAY_DARK_HOVER,
        DISPLAY_WHITE,
        DISPLAY_BORDER_STRONG,
    ),
    "icon": ButtonStyle(
        DISPLAY_DARK_RAISED,
        DISPLAY_YELLOW,
        DISPLAY_DARK_HOVER,
        DISPLAY_YELLOW_SOFT,
        DISPLAY_BORDER,
    ),
    "tab": ButtonStyle(
        DISPLAY_DARK_RAISED,
        DISPLAY_MUTED,
        DISPLAY_BLUE_DARK,
        DISPLAY_BLUE_LIGHT,
        DISPLAY_BORDER,
    ),
}


def _normalizar_cor(valor) -> str:
    return str(valor or "").strip().lower()


def _normalizar_texto(valor) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(letra for letra in texto if not unicodedata.combining(letra))
    return " ".join(texto.lower().replace("\n", " ").split())


def mapear_cor_display(opcao: str, valor):
    """Converte a paleta antiga para o novo sistema visual da display."""
    nome = str(opcao or "").lower()
    cor = _normalizar_cor(valor)
    if not cor.startswith("#"):
        return valor

    if nome in _BORDER_OPTIONS:
        if cor in _DARK_BACKGROUND_MAP:
            return DISPLAY_BORDER
        if cor in _FOREGROUND_ACCENT_MAP:
            return _FOREGROUND_ACCENT_MAP[cor]
        return valor

    if nome in _FOREGROUND_OPTIONS:
        if cor in _FOREGROUND_ACCENT_MAP:
            return _FOREGROUND_ACCENT_MAP[cor]
        if cor in _MUTED_FOREGROUND_MAP:
            return _MUTED_FOREGROUND_MAP[cor]
        return valor

    if nome in _BACKGROUND_OPTIONS:
        if cor in _DARK_BACKGROUND_MAP:
            return _DARK_BACKGROUND_MAP[cor]
        if cor in _BACKGROUND_ACCENT_MAP:
            return _BACKGROUND_ACCENT_MAP[cor]
        return valor

    return valor


def classificar_acao_botao(texto: str) -> str:
    """Classifica um botão pela intenção para criar hierarquia visual."""
    normalizado = _normalizar_texto(texto)

    if normalizado in {"⚙", "odin"}:
        return "icon"
    if normalizado in {"sistema", "camera"}:
        return "tab"
    if any(
        termo in normalizado
        for termo in ("remover", "excluir", "apagar", "limpar selecao")
    ):
        return "danger"
    if normalizado in {"hora on"}:
        return "success"
    if normalizado in {"hora off", "fechar", "cancelar", "renomear"}:
        return "neutral"
    if any(
        termo in normalizado
        for termo in (
            "selecionar leds",
            "detectar leds",
            "configurar leds",
            "adicionar",
            "mover para cima",
            "mover para baixo",
        )
    ):
        return "selection"
    if any(
        termo in normalizado
        for termo in (
            "tela ao vivo",
            "carregar imagem",
            "camera",
        )
    ):
        return "info"
    if any(
        termo in normalizado
        for termo in (
            "analisar",
            "producao",
            "salvar",
            "carregar projeto",
            "ok",
        )
    ):
        return "primary"
    if any(
        termo in normalizado
        for termo in (
            "carregar leds",
            "carregar refs",
            "ref. aceso",
            "ref. apagado",
        )
    ):
        return "secondary"
    return "neutral"


def obter_estilo_botao_display(texto: str) -> ButtonStyle:
    return _BUTTON_STYLES[classificar_acao_botao(texto)]


def instalar_paleta_display() -> None:
    """Atualiza as constantes antes da criação das telas do ODIN."""
    ODINView.COR_FUNDO_APP = DISPLAY_DARK
    ODINView.COR_TOPO = DISPLAY_DARK_ALT
    ODINView.COR_CARD = DISPLAY_DARK_CARD
    ODINView.COR_CARD_2 = DISPLAY_DARK_RAISED
    ODINView.COR_BORDA = DISPLAY_BORDER
    ODINView.COR_TEXTO = DISPLAY_WHITE
    ODINView.COR_TEXTO_2 = DISPLAY_WHITE
    ODINView.COR_TEXTO_3 = DISPLAY_MUTED
    ODINView.COR_AZUL = DISPLAY_BLUE_LIGHT
    ODINView.COR_AMARELO = DISPLAY_YELLOW
    ODINView.COR_NEUTRO = DISPLAY_DARK_HOVER
    # Mantém verde para resultado OK, mas a marca do ODIN passa a ser âmbar.
    ODINView.COR_VERDE_CLARO = DISPLAY_YELLOW

    DesktopOperationWindow.COLOR_WAITING = DISPLAY_DARK_ALT
    DesktopOperationWindow.COLOR_POSITIONING = DISPLAY_BLUE_DARK
    DesktopOperationWindow.COLOR_WAITING_REMOVAL = DISPLAY_DARK
    DesktopOperationWindow.COLOR_PROCESSING = DISPLAY_YELLOW_DARK
    DesktopOperationWindow.PREVIEW_BACKGROUND = DISPLAY_DARK
    DesktopOperationWindow.PREVIEW_PANEL = DISPLAY_DARK_CARD
    DesktopOperationWindow.PREVIEW_BORDER = DISPLAY_BORDER
    DesktopOperationWindow.PREVIEW_GUIDE = DISPLAY_YELLOW
    DesktopOperationWindow.PREVIEW_BOARD_GUIDE = DISPLAY_BLUE_LIGHT
    DesktopOperationWindow.PREVIEW_FAILED = DISPLAY_DANGER
    DesktopOperationWindow.PREVIEW_TEXT = DISPLAY_WHITE
    DesktopOperationWindow.PREVIEW_MUTED = DISPLAY_MUTED

    # A janela F2 derivada preserva o mesmo contrato visual.
    try:
        from src.platform.blue_operation_window import BlueOperationWindow

        BlueOperationWindow.PREVIEW_FAILED = DISPLAY_DANGER
    except Exception:
        pass


def _texto_tematizado(texto: str) -> str:
    return (
        str(texto)
        .replace("CÍRCULO AZUL", "CÍRCULO VERMELHO")
        .replace("Círculo azul", "Círculo vermelho")
        .replace("Marcados em azul", "Marcados em vermelho")
        .replace("marcados em azul", "marcados em vermelho")
        .replace("CÍRCULO AMARELO", "CÍRCULO VERMELHO")
        .replace("Círculo amarelo", "Círculo vermelho")
        .replace("Marcados em amarelo", "Marcados em vermelho")
        .replace("marcados em amarelo", "marcados em vermelho")
    )


def _configurar(widget, **opcoes) -> None:
    if not opcoes:
        return
    try:
        widget.configure(**opcoes)
    except Exception:
        pass


def _obter(widget, opcao: str):
    try:
        return widget.cget(opcao)
    except Exception:
        return None


def _classe_widget(widget) -> str:
    try:
        return str(widget.winfo_class())
    except Exception:
        return type(widget).__name__


def _tematizar_itens_canvas(canvas) -> None:
    try:
        itens = canvas.find_all()
    except Exception:
        return

    for item in itens:
        for opcao in ("fill", "outline"):
            try:
                atual = canvas.itemcget(item, opcao)
            except Exception:
                continue
            novo = mapear_cor_display(
                "foreground" if opcao == "fill" else "highlightbackground",
                atual,
            )
            if novo == atual:
                novo = mapear_cor_display("background", atual)
            if novo != atual:
                try:
                    canvas.itemconfigure(item, **{opcao: novo})
                except Exception:
                    pass


def _aplicar_estado_hover(widget, estilo: ButtonStyle, ativo: bool) -> None:
    try:
        if str(widget.cget("state")) == tk.DISABLED:
            return
    except Exception:
        pass

    if ativo:
        _configurar(
            widget,
            background=estilo.activebackground,
            foreground=estilo.activeforeground,
        )
    else:
        _configurar(
            widget,
            background=estilo.background,
            foreground=estilo.foreground,
        )


def _instalar_hover_botao(widget, estilo: ButtonStyle) -> None:
    try:
        widget._display_button_style = estilo
    except Exception:
        return

    if getattr(widget, "_display_hover_instalado", False):
        return

    try:
        widget.bind(
            "<Enter>",
            lambda _evento, botao=widget: _aplicar_estado_hover(
                botao,
                botao._display_button_style,
                True,
            ),
            add="+",
        )
        widget.bind(
            "<Leave>",
            lambda _evento, botao=widget: _aplicar_estado_hover(
                botao,
                botao._display_button_style,
                False,
            ),
            add="+",
        )
        widget._display_hover_instalado = True
    except Exception:
        pass


def _aplicar_estilo_botao(widget, texto: str) -> None:
    estilo = obter_estilo_botao_display(texto)
    _configurar(
        widget,
        background=estilo.background,
        foreground=estilo.foreground,
        activebackground=estilo.activebackground,
        activeforeground=estilo.activeforeground,
        highlightbackground=estilo.border,
        highlightcolor=estilo.border,
        highlightthickness=1,
        relief=tk.FLAT,
        bd=0,
    )
    _instalar_hover_botao(widget, estilo)


def aplicar_tema_widget(widget) -> None:
    """Aplica o tema dark/âmbar, preservando significado e hierarquia."""
    classe = _classe_widget(widget)
    alteracoes = {}

    for opcao in (
        "background",
        "foreground",
        "activebackground",
        "activeforeground",
        "highlightbackground",
        "highlightcolor",
        "insertbackground",
        "selectbackground",
        "selectforeground",
        "troughcolor",
        "selectcolor",
        "disabledforeground",
    ):
        atual = _obter(widget, opcao)
        if atual is None:
            continue
        novo = mapear_cor_display(opcao, atual)
        if novo != atual:
            alteracoes[opcao] = novo

    texto = _obter(widget, "text")
    texto_original = str(texto) if texto is not None else ""
    if texto is not None:
        novo_texto = _texto_tematizado(texto_original)
        if novo_texto != texto_original:
            alteracoes["text"] = novo_texto

    _configurar(widget, **alteracoes)

    if classe in {"Button", "Menubutton"}:
        _aplicar_estilo_botao(widget, texto_original)
    elif classe in {"Checkbutton", "Radiobutton"}:
        _configurar(
            widget,
            background=DISPLAY_DARK_RAISED,
            foreground=DISPLAY_WHITE,
            activebackground=DISPLAY_DARK_RAISED,
            activeforeground=DISPLAY_YELLOW,
            selectcolor=DISPLAY_DARK,
            highlightbackground=DISPLAY_BORDER,
        )
    elif classe in {"Entry", "Text", "Spinbox"}:
        _configurar(
            widget,
            background=DISPLAY_DARK,
            foreground=DISPLAY_WHITE,
            insertbackground=DISPLAY_YELLOW,
            selectbackground=DISPLAY_BLUE,
            selectforeground=DISPLAY_WHITE,
            highlightbackground=DISPLAY_BORDER,
            highlightcolor=DISPLAY_YELLOW_DARK,
        )
    elif classe == "Listbox":
        _configurar(
            widget,
            background=DISPLAY_DARK,
            foreground=DISPLAY_WHITE,
            selectbackground=DISPLAY_BLUE_DARK,
            selectforeground=DISPLAY_BLUE_LIGHT,
            highlightbackground=DISPLAY_BORDER,
            highlightcolor=DISPLAY_BLUE,
        )
    elif classe == "Label":
        texto_normalizado = _normalizar_texto(texto_original)
        if texto_normalizado == "odin":
            _configurar(widget, foreground=DISPLAY_YELLOW)
        elif texto_original.strip().lower() in _SECTION_TITLES:
            _configurar(widget, foreground=DISPLAY_YELLOW_SOFT)

    if classe == "Canvas":
        _tematizar_itens_canvas(widget)


def aplicar_tema_arvore(widget) -> None:
    aplicar_tema_widget(widget)
    try:
        filhos = tuple(widget.winfo_children())
    except Exception:
        filhos = ()
    for filho in filhos:
        aplicar_tema_arvore(filho)


def configurar_estilos_ttk_display(root) -> None:
    try:
        style = ttk.Style(root)
        style.theme_use("clam")
    except Exception:
        return

    configuracoes = {
        "TFrame": {
            "background": DISPLAY_DARK_CARD,
        },
        "TLabel": {
            "background": DISPLAY_DARK_CARD,
            "foreground": DISPLAY_WHITE,
        },
        "TButton": {
            "background": DISPLAY_DARK_RAISED,
            "foreground": DISPLAY_WHITE,
            "bordercolor": DISPLAY_BORDER,
            "focuscolor": DISPLAY_YELLOW_DARK,
            "padding": (10, 7),
        },
        "TCheckbutton": {
            "background": DISPLAY_DARK_CARD,
            "foreground": DISPLAY_WHITE,
            "focuscolor": DISPLAY_YELLOW_DARK,
        },
        "TRadiobutton": {
            "background": DISPLAY_DARK_CARD,
            "foreground": DISPLAY_WHITE,
            "focuscolor": DISPLAY_YELLOW_DARK,
        },
        "TNotebook": {
            "background": DISPLAY_DARK,
            "bordercolor": DISPLAY_BORDER,
            "tabmargins": (2, 4, 2, 0),
        },
        "TNotebook.Tab": {
            "background": DISPLAY_DARK_RAISED,
            "foreground": DISPLAY_MUTED,
            "padding": (14, 8),
        },
        "Treeview": {
            "background": DISPLAY_DARK,
            "fieldbackground": DISPLAY_DARK,
            "foreground": DISPLAY_WHITE,
            "bordercolor": DISPLAY_BORDER,
            "rowheight": 27,
        },
        "Treeview.Heading": {
            "background": DISPLAY_DARK_RAISED,
            "foreground": DISPLAY_YELLOW_SOFT,
            "bordercolor": DISPLAY_BORDER,
            "relief": "flat",
        },
        "TEntry": {
            "fieldbackground": DISPLAY_DARK,
            "foreground": DISPLAY_WHITE,
            "insertcolor": DISPLAY_YELLOW,
            "bordercolor": DISPLAY_BORDER,
            "lightcolor": DISPLAY_BORDER,
            "darkcolor": DISPLAY_BORDER,
        },
        "TCombobox": {
            "fieldbackground": DISPLAY_DARK,
            "background": DISPLAY_DARK_RAISED,
            "foreground": DISPLAY_WHITE,
            "arrowcolor": DISPLAY_YELLOW,
            "bordercolor": DISPLAY_BORDER,
        },
        "Vertical.TScrollbar": {
            "background": DISPLAY_DARK_RAISED,
            "troughcolor": DISPLAY_DARK,
            "bordercolor": DISPLAY_DARK,
            "arrowcolor": DISPLAY_YELLOW,
        },
        "Horizontal.TScrollbar": {
            "background": DISPLAY_DARK_RAISED,
            "troughcolor": DISPLAY_DARK,
            "bordercolor": DISPLAY_DARK,
            "arrowcolor": DISPLAY_YELLOW,
        },
        "TScale": {
            "background": DISPLAY_DARK_CARD,
            "troughcolor": DISPLAY_DARK,
        },
        "TProgressbar": {
            "background": DISPLAY_YELLOW_DARK,
            "troughcolor": DISPLAY_DARK,
            "bordercolor": DISPLAY_BORDER,
        },
    }

    for nome, opcoes in configuracoes.items():
        try:
            style.configure(nome, **opcoes)
        except Exception:
            pass

    try:
        style.map(
            "TButton",
            background=[
                ("pressed", DISPLAY_YELLOW_DARK),
                ("active", DISPLAY_DARK_HOVER),
            ],
            foreground=[
                ("pressed", DISPLAY_INK),
                ("active", DISPLAY_YELLOW_SOFT),
            ],
            bordercolor=[("focus", DISPLAY_YELLOW_DARK)],
        )
        style.map(
            "Treeview",
            background=[("selected", DISPLAY_BLUE_DARK)],
            foreground=[("selected", DISPLAY_BLUE_LIGHT)],
        )
        style.map(
            "TNotebook.Tab",
            background=[
                ("selected", DISPLAY_YELLOW_DARK),
                ("active", DISPLAY_DARK_HOVER),
            ],
            foreground=[
                ("selected", DISPLAY_INK),
                ("active", DISPLAY_WHITE),
            ],
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", DISPLAY_DARK)],
            selectbackground=[("readonly", DISPLAY_BLUE_DARK)],
            selectforeground=[("readonly", DISPLAY_BLUE_LIGHT)],
        )
    except Exception:
        pass


class DisplayThemeMixin:
    """Tema exclusivo da branch display, aplicado à interface inteira."""

    def __init__(self, *args, **kwargs) -> None:
        self._display_theme_after_id = None
        instalar_paleta_display()
        super().__init__(*args, **kwargs)
        self._instalar_tema_display_runtime()

    def _instalar_tema_display_runtime(self) -> None:
        root = getattr(self, "root", None)
        if root is None:
            return

        try:
            root.configure(bg=DISPLAY_DARK)
            root.option_add("*Background", DISPLAY_DARK_CARD)
            root.option_add("*Foreground", DISPLAY_WHITE)
            root.option_add("*Button.background", DISPLAY_DARK_RAISED)
            root.option_add("*Button.foreground", DISPLAY_WHITE)
            root.option_add("*Button.activeBackground", DISPLAY_DARK_HOVER)
            root.option_add("*Button.activeForeground", DISPLAY_YELLOW_SOFT)
            root.option_add("*Entry.background", DISPLAY_DARK)
            root.option_add("*Entry.foreground", DISPLAY_WHITE)
            root.option_add("*Listbox.background", DISPLAY_DARK)
            root.option_add("*Listbox.foreground", DISPLAY_WHITE)
        except Exception:
            pass

        configurar_estilos_ttk_display(root)
        self._aplicar_tema_display_agora()

        try:
            root.bind_all("<Map>", self._evento_map_tema_display, add="+")
        except Exception:
            pass

        for atraso in (0, 120, 500, 1200):
            try:
                root.after(atraso, self._aplicar_tema_display_agora)
            except Exception:
                break

    def _evento_map_tema_display(self, _evento=None) -> None:
        root = getattr(self, "root", None)
        if root is None or self._display_theme_after_id is not None:
            return
        try:
            self._display_theme_after_id = root.after_idle(
                self._aplicar_tema_display_pendente
            )
        except Exception:
            self._display_theme_after_id = None

    def _aplicar_tema_display_pendente(self) -> None:
        self._display_theme_after_id = None
        self._aplicar_tema_display_agora()

    def _aplicar_tema_display_agora(self) -> None:
        root = getattr(self, "root", None)
        if root is None:
            return
        configurar_estilos_ttk_display(root)
        aplicar_tema_arvore(root)

    def _criar_interface_selecao_tela_cheia(self):
        janela, canvas = super()._criar_interface_selecao_tela_cheia()
        aplicar_tema_arvore(janela)
        try:
            janela.after_idle(lambda: aplicar_tema_arvore(janela))
        except Exception:
            pass
        return janela, canvas
