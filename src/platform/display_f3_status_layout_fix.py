from __future__ import annotations

import tkinter as tk

import src.platform.display_visual_reference_status as visual_status_module
from src.platform.display_production_f3_window import DisplayProductionF3Window
from src.platform.display_visual_reference_status import (
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
    DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
    display_check_cards_structure_key,
)


F3_CHECK_CARD_HEIGHT = 46
F3_STATUS_FONT = ("DejaVu Sans", 28, "bold")
F3_DETAIL_FONT = ("DejaVu Sans", 12)


def format_display_status_f3(result: dict | None) -> tuple[str, str]:
    data = dict(result or {})
    configured = int(data.get("configured_count", 0) or 0)
    if configured <= 0:
        return "STATUS DO DISPLAY: REFERÊNCIAS NÃO CONFIGURADAS", "#94A3B8"
    if not bool(data.get("camera", True)):
        return "STATUS DO DISPLAY: AGUARDANDO CÂMERA", "#94A3B8"
    if bool(data.get("ambiguous")):
        return "STATUS DO DISPLAY: IDENTIFICANDO...", "#FDE68A"

    best = data.get("best") if isinstance(data.get("best"), dict) else None
    if bool(data.get("matched")) and best is not None:
        name = str(best.get("name") or "CHECK").strip().upper()
        return f"STATUS DO DISPLAY: {name}", "#7DD3FC"

    return "STATUS DO DISPLAY: NÃO IDENTIFICADO", "#FDE68A"


def format_board_status_f3(result: dict | None) -> tuple[str, str]:
    data = dict(result or {})
    configured = int(data.get("configured_count", 0) or 0)
    required = int(data.get("required_count", 2) or 2)
    if configured < required:
        return "STATUS DA PLACA: REFERÊNCIAS NÃO CONFIGURADAS", "#94A3B8"
    if not bool(data.get("camera", True)):
        return "STATUS DA PLACA: AGUARDANDO CÂMERA", "#94A3B8"
    if bool(data.get("ambiguous")):
        return "STATUS DA PLACA: IDENTIFICANDO...", "#FDE68A"

    best = data.get("best") if isinstance(data.get("best"), dict) else None
    if bool(data.get("matched")) and best is not None:
        kind = str(best.get("kind") or "")
        if kind == DISPLAY_PROJECT_REFERENCE_BOARD_OFF:
            # Esta referência confirma presença física. O estado ligado/desligado
            # é mostrado separadamente pelo status do CHECK (H1/BLUE/USB/etc.).
            return "STATUS DA PLACA: PLACA NO SUPORTE", "#86EFAC"
        if kind == DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT:
            return "STATUS DA PLACA: PLACA FORA DO SUPORTE", "#CBD5E1"

    return "STATUS DA PLACA: IDENTIFICANDO...", "#FDE68A"


def _set_state_f3_without_reflow(
    self,
    background: str,
    foreground: str,
    status: str,
    detail: str,
) -> None:
    """Atualiza resultado sem alterar a geometria do painel esquerdo."""
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

    self.status_label.configure(
        text=str(status),
        font=F3_STATUS_FONT,
        height=1,
        fg=foreground,
    )
    self.detail_label.configure(
        text=str(detail),
        font=F3_DETAIL_FONT,
        height=2,
        fg=foreground,
    )
    self.brand_label.configure(fg=foreground)
    self.mode_label.configure(
        fg=foreground if foreground == "#111827" else "#CBD5E1"
    )
    self.led_summary_label.configure(fg=foreground)


def _render_check_cards_f3_fixed(
    self,
    snapshot: dict,
    force_all_completed: bool = False,
    force_terminal_segregated: bool = False,
) -> None:
    checks = list(snapshot.get("checks", []) or [])
    structure_key = display_check_cards_structure_key(snapshot)
    cached_key = getattr(self, "_display_stable_cards_key", None)
    cards = getattr(self, "_display_stable_cards", None)

    if cached_key != structure_key or not isinstance(cards, list):
        for child in self.check_flow_frame.winfo_children():
            child.destroy()
        cards = []

        if not checks:
            label = tk.Label(
                self.check_flow_frame,
                text="Nenhum CHECK configurado no Projeto Display.",
                font=("DejaVu Sans", 11, "bold"),
                bg=self.COLOR_WAITING,
                fg="#FCA5A5",
                anchor="center",
                justify="center",
                height=2,
            )
            label.grid(row=0, column=0, sticky="nsew", pady=8)
            self._display_stable_cards = cards
            self._display_stable_cards_key = structure_key
            return

        for index, check in enumerate(checks):
            card = tk.Frame(
                self.check_flow_frame,
                height=F3_CHECK_CARD_HEIGHT,
                highlightthickness=2,
            )
            card.grid(row=index, column=0, sticky="ew", pady=(0, 5))
            card.grid_propagate(False)
            card.grid_columnconfigure(1, weight=1)
            self.check_flow_frame.grid_rowconfigure(
                index,
                minsize=F3_CHECK_CARD_HEIGHT,
            )

            number = tk.Label(card, width=3)
            number.grid(row=0, column=0, padx=(7, 3), pady=7)
            name = tk.Label(card, anchor="w")
            name.grid(row=0, column=1, sticky="ew", padx=4, pady=7)
            state_label = tk.Label(card, anchor="e")
            state_label.grid(row=0, column=2, padx=(6, 9), pady=7)
            cards.append(
                {
                    "frame": card,
                    "number": number,
                    "name": name,
                    "state": state_label,
                }
            )

        self._display_stable_cards = cards
        self._display_stable_cards_key = structure_key

    if not checks:
        return

    for index, check in enumerate(checks):
        state = "completed" if force_all_completed else str(check.get("state", "pending"))
        if force_terminal_segregated:
            bg = self.COLOR_NG
            border = self.DISPLAY_READOUT_NG_OUTLINE
            status_text = "SEGREGADO"
            fg = "#FFFFFF"
        elif state == "completed":
            bg = self.CHECK_COMPLETED
            border = "#22C55E"
            status_text = "CONCLUÍDO"
            fg = "#FFFFFF"
        elif state == "current":
            bg = "#3B3205"
            border = self.CHECK_CURRENT
            status_text = "AGUARDANDO"
            fg = "#FDE68A"
        else:
            bg = self.CHECK_PENDING
            border = self.CHECK_BORDER
            status_text = "PRÓXIMO"
            fg = "#94A3B8"

        widgets = cards[index]
        widgets["frame"].configure(
            bg=bg,
            highlightbackground=border,
            highlightthickness=2,
            height=F3_CHECK_CARD_HEIGHT,
        )
        widgets["number"].configure(
            text=str(index + 1),
            font=("DejaVu Sans", 10, "bold"),
            bg=bg,
            fg=fg,
        )
        widgets["name"].configure(
            text=str(check.get("name") or check.get("id") or "CHECK"),
            font=("DejaVu Sans", 11, "bold"),
            bg=bg,
            fg="#FFFFFF",
        )
        widgets["state"].configure(
            text=status_text,
            font=("DejaVu Sans", 8, "bold"),
            bg=bg,
            fg=fg,
        )


def _install_status_on_preview_right() -> None:
    cls = DisplayProductionF3Window
    if bool(getattr(cls, "_display_f3_fixed_status_layout_installed", False)):
        return

    original_init = cls.__init__

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)

        old_display_label = getattr(self, "visual_reference_state_label", None)
        old_status_box = getattr(old_display_label, "master", None)
        if old_status_box is not None and old_status_box is not self.preview_header:
            try:
                old_status_box.destroy()
            except Exception:
                pass

        status_box = tk.Frame(self.preview_header, bg=self.PREVIEW_PANEL)
        status_box.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(7, 0),
        )
        status_box.grid_columnconfigure(0, weight=1)
        self._display_reference_status_box = status_box

        self.board_reference_state_label = tk.Label(
            status_box,
            text="STATUS DA PLACA: IDENTIFICANDO...",
            font=("DejaVu Sans", 9, "bold"),
            bg=self.PREVIEW_PANEL,
            fg="#CBD5E1",
            anchor="w",
            justify="left",
        )
        self.board_reference_state_label.grid(
            row=0,
            column=0,
            sticky="ew",
        )

        self.visual_reference_state_label = tk.Label(
            status_box,
            text="STATUS DO DISPLAY: IDENTIFICANDO...",
            font=("DejaVu Sans", 9, "bold"),
            bg=self.PREVIEW_PANEL,
            fg="#CBD5E1",
            anchor="w",
            justify="left",
        )
        self.visual_reference_state_label.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(2, 0),
        )

        # Reserva alturas fixas para que AGUARDANDO, resultado de CHECK e
        # resultado geral não empurrem a pilha de CHECKS para cima/baixo.
        self.status_frame.grid_rowconfigure(0, weight=0, minsize=58)
        self.status_frame.grid_rowconfigure(1, weight=0, minsize=48)
        self.status_frame.grid_rowconfigure(2, weight=1)
        self.status_label.configure(font=F3_STATUS_FONT, height=1)
        self.detail_label.configure(font=F3_DETAIL_FONT, height=2)

    cls.__init__ = init
    cls._set_state = _set_state_f3_without_reflow
    cls._render_check_cards = _render_check_cards_f3_fixed
    cls._display_f3_fixed_status_layout_installed = True


def instalar_layout_status_f3_estavel() -> None:
    """Mantém CHECKS imóveis e status visuais no painel direito do F3."""
    visual_status_module._format_display_status = format_display_status_f3
    visual_status_module._format_board_status = format_board_status_f3
    _install_status_on_preview_right()


# O app importa este módulo somente depois de display_f3_live_runtime_fix estar
# completamente carregado. Isso evita ciclo de import e instala o gate físico
# terminal no momento seguro do bootstrap do F3.
import src.platform.display_f3_cycle_rearm_release_fix  # noqa: E402,F401
