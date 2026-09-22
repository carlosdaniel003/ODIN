from __future__ import annotations


DISPLAY_F3_RESULT_HOLD_MS = 2000

# O canvas continua exibindo os pixels reais da câmera sem qualquer tint.
# Apenas o fundo/letterbox ao redor da imagem acompanha o resultado anterior.
DISPLAY_F3_VISUAL_THEMES = {
    "neutral": {
        "window_bg": "#020617",
        "panel_bg": "#0F172A",
        "panel_border": "#1E293B",
        "surface_bg": "#0B1220",
        "surface_border": "#334155",
        "preview_bg": "#07111F",
        "preview_border": "#334155",
        "camera_surround_bg": "#020617",
        "footer_bg": "#020617",
        "text": "#FFFFFF",
        "muted": "#CBD5E1",
        "soft_text": "#94A3B8",
        "action_bg": "#0E7490",
        "action_active": "#0891B2",
        "pending_bg": "#172033",
        "pending_border": "#475569",
        "current_bg": "#3B3205",
        "current_border": "#D6A900",
        "current_fg": "#FDE68A",
        "completed_bg": "#166534",
        "completed_border": "#22C55E",
    },
    "ok_result": {
        "window_bg": "#071A0F",
        "panel_bg": "#16A34A",
        "panel_border": "#86EFAC",
        "surface_bg": "#14532D",
        "surface_border": "#4ADE80",
        "preview_bg": "#0B2E1A",
        "preview_border": "#4ADE80",
        "camera_surround_bg": "#0C3B20",
        "footer_bg": "#071A0F",
        "text": "#FFFFFF",
        "muted": "#DCFCE7",
        "soft_text": "#BBF7D0",
        "action_bg": "#15803D",
        "action_active": "#166534",
        "pending_bg": "#0F3D24",
        "pending_border": "#4ADE80",
        "current_bg": "#14532D",
        "current_border": "#86EFAC",
        "current_fg": "#FFFFFF",
        "completed_bg": "#14532D",
        "completed_border": "#86EFAC",
    },
    "ok_waiting": {
        "window_bg": "#071A0F",
        "panel_bg": "#14532D",
        "panel_border": "#22C55E",
        "surface_bg": "#0F3D24",
        "surface_border": "#2F8550",
        "preview_bg": "#0B2517",
        "preview_border": "#2F8550",
        "camera_surround_bg": "#081C11",
        "footer_bg": "#071A0F",
        "text": "#FFFFFF",
        "muted": "#DCFCE7",
        "soft_text": "#BBF7D0",
        "action_bg": "#166534",
        "action_active": "#15803D",
        "pending_bg": "#12351F",
        "pending_border": "#2F6F46",
        "current_bg": "#443806",
        "current_border": "#FACC15",
        "current_fg": "#FEF08A",
        "completed_bg": "#166534",
        "completed_border": "#4ADE80",
    },
    "ng_result": {
        "window_bg": "#260909",
        "panel_bg": "#DC2626",
        "panel_border": "#FCA5A5",
        "surface_bg": "#7F1D1D",
        "surface_border": "#F87171",
        "preview_bg": "#3B1111",
        "preview_border": "#F87171",
        "camera_surround_bg": "#4A1111",
        "footer_bg": "#260909",
        "text": "#FFFFFF",
        "muted": "#FEE2E2",
        "soft_text": "#FECACA",
        "action_bg": "#B91C1C",
        "action_active": "#991B1B",
        "pending_bg": "#4A1616",
        "pending_border": "#F87171",
        "current_bg": "#641B1B",
        "current_border": "#FCA5A5",
        "current_fg": "#FFFFFF",
        "completed_bg": "#7F1D1D",
        "completed_border": "#FCA5A5",
    },
    "ng_waiting": {
        "window_bg": "#1F0808",
        "panel_bg": "#7F1D1D",
        "panel_border": "#EF4444",
        "surface_bg": "#3B1111",
        "surface_border": "#991B1B",
        "preview_bg": "#2A0D0D",
        "preview_border": "#991B1B",
        "camera_surround_bg": "#250B0B",
        "footer_bg": "#1F0808",
        "text": "#FFFFFF",
        "muted": "#FEE2E2",
        "soft_text": "#FECACA",
        "action_bg": "#991B1B",
        "action_active": "#B91C1C",
        "pending_bg": "#321313",
        "pending_border": "#7F1D1D",
        "current_bg": "#443806",
        "current_border": "#FACC15",
        "current_fg": "#FEF08A",
        "completed_bg": "#166534",
        "completed_border": "#4ADE80",
    },
}


def obter_tema_visual_display_f3(nome: str | None) -> dict:
    chave = str(nome or "neutral").strip().lower()
    return dict(DISPLAY_F3_VISUAL_THEMES.get(chave, DISPLAY_F3_VISUAL_THEMES["neutral"]))


def obter_feedback_espera_display_f3(snapshot: dict | None):
    """Retorna o último resultado somente enquanto aguarda o primeiro CHECK."""
    data = dict(snapshot or {})
    try:
        current_index = int(data.get("current_index", 0) or 0)
    except (TypeError, ValueError):
        current_index = 0

    completed_ids = tuple(data.get("completed_ids", ()) or ())
    if current_index != 0 or completed_ids:
        return None

    last_result = str(data.get("last_result") or "").strip().upper()
    if last_result == "OK":
        return (
            "OK",
            "Última placa: OK • aguardando H1 da próxima placa",
        )
    if last_result == "NG":
        return (
            "NG",
            "Última placa: NG • aguardando H1 da próxima placa",
        )
    return None


def _configure(widget, **kwargs) -> None:
    if widget is None:
        return
    try:
        widget.configure(**kwargs)
    except Exception:
        pass


def _estilizar_metricas(window, tema: dict) -> None:
    for value_label in (
        getattr(window, "total_value_label", None),
        getattr(window, "ok_value_label", None),
        getattr(window, "ng_value_label", None),
    ):
        if value_label is None:
            continue
        card = getattr(value_label, "master", None)
        _configure(
            card,
            bg=tema["surface_bg"],
            highlightbackground=tema["surface_border"],
        )
        try:
            children = card.winfo_children()
        except Exception:
            children = ()
        for child in children:
            texto = ""
            try:
                texto = str(child.cget("text"))
            except Exception:
                pass
            _configure(
                child,
                bg=tema["surface_bg"],
                fg=(
                    tema["soft_text"]
                    if texto in ("TOTAL", "OK", "NG")
                    else tema["text"]
                ),
            )


def _estilizar_cards_checks(
    window,
    snapshot: dict | None,
    tema: dict,
    force_all_completed: bool = False,
) -> None:
    data = dict(snapshot or {})
    checks = list(data.get("checks", []) or [])
    try:
        cards = list(window.check_flow_frame.winfo_children())
    except Exception:
        return

    for card, check in zip(cards, checks):
        state = "completed" if force_all_completed else str(check.get("state", "pending"))
        if state == "completed":
            bg = tema["completed_bg"]
            border = tema["completed_border"]
            status_fg = tema["text"]
        elif state == "current":
            bg = tema["current_bg"]
            border = tema["current_border"]
            status_fg = tema["current_fg"]
        else:
            bg = tema["pending_bg"]
            border = tema["pending_border"]
            status_fg = tema["soft_text"]

        _configure(
            card,
            bg=bg,
            highlightbackground=border,
        )
        try:
            children = list(card.winfo_children())
        except Exception:
            children = []
        for indice, child in enumerate(children):
            _configure(
                child,
                bg=bg,
                fg=(status_fg if indice in (0, 2) else tema["text"]),
            )


def aplicar_tema_visual_display_f3(
    window,
    nome_tema: str,
    snapshot: dict | None = None,
    force_all_completed: bool = False,
) -> None:
    """Aplica a identidade de estado à maior parte da janela sem tingir a câmera."""
    tema = obter_tema_visual_display_f3(nome_tema)

    _configure(window.container, bg=tema["window_bg"])
    _configure(window.body_frame, bg=tema["window_bg"])

    _configure(
        window.analysis_panel,
        bg=tema["panel_bg"],
        highlightbackground=tema["panel_border"],
    )
    for widget in (
        getattr(window, "brand_label", None),
        getattr(window, "status_frame", None),
        getattr(window, "status_label", None),
        getattr(window, "detail_label", None),
        getattr(window, "led_summary_label", None),
        getattr(window, "metrics_frame", None),
        getattr(window, "counter_label", None),
        getattr(window, "check_flow_frame", None),
    ):
        _configure(widget, bg=tema["panel_bg"])
    _configure(window.brand_label, fg=tema["text"])
    _configure(window.mode_label, bg=tema["panel_bg"], fg=tema["muted"])
    _configure(window.status_label, fg=tema["text"])
    _configure(window.detail_label, fg=tema["text"])

    _configure(
        getattr(window, "project_frame", None),
        bg=tema["surface_bg"],
        highlightbackground=tema["surface_border"],
    )
    _configure(
        getattr(window, "project_info_label", None),
        bg=tema["surface_bg"],
        fg=tema["text"],
    )
    _configure(
        getattr(window, "project_detail_label", None),
        bg=tema["surface_bg"],
        fg=tema["soft_text"],
    )
    _configure(
        getattr(window, "project_config_button", None),
        bg=tema["action_bg"],
        activebackground=tema["action_active"],
        fg=tema["text"],
        activeforeground=tema["text"],
    )

    _estilizar_metricas(window, tema)

    # DESCARTAR continua vermelho por semântica de segurança, mesmo após OK.
    _configure(
        getattr(window, "discard_button", None),
        bg="#7F1D1D",
        activebackground="#991B1B",
        fg="#FFFFFF",
        activeforeground="#FFFFFF",
    )

    _configure(
        window.preview_frame,
        bg=tema["preview_bg"],
        highlightbackground=tema["preview_border"],
    )
    _configure(window.preview_header, bg=tema["preview_bg"])
    _configure(
        window.preview_title,
        bg=tema["preview_bg"],
        fg=tema["text"],
    )
    _configure(
        window.preview_legend,
        bg=tema["preview_bg"],
        fg=tema["muted"],
    )
    _configure(
        window.preview_status,
        bg=tema["preview_bg"],
        fg=tema["muted"],
    )
    _configure(
        window.preview_canvas,
        bg=tema["camera_surround_bg"],
        highlightbackground=tema["preview_border"],
    )
    _configure(
        window.footer_label,
        bg=tema["footer_bg"],
        fg=tema["muted"],
    )

    _estilizar_cards_checks(
        window,
        snapshot=snapshot,
        tema=tema,
        force_all_completed=force_all_completed,
    )

    try:
        window.root.update_idletasks()
    except Exception:
        pass


def instalar_feedback_resultado_display_f3() -> None:
    """Replica no F3 a memória visual pós-resultado usada pela Produção F2."""
    from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin
    import src.platform.display_production_f3_window as window_module

    # O mixin automático vem antes do runtime F3 no MRO da aplicação. Definir
    # aqui mantém a alteração exclusiva do F3 e faz o agendamento oficial usar
    # dois segundos sem tocar no fluxo da Produção F2.
    DisplayAutomaticCheckF3Mixin.DISPLAY_F3_RESULT_HOLD_MS = DISPLAY_F3_RESULT_HOLD_MS

    cls = window_module.DisplayProductionF3Window
    if getattr(cls, "_odin_display_result_feedback", False):
        return

    original_set_check_sequence = cls.set_check_sequence
    original_show_plate_result = cls.show_plate_result

    def set_check_sequence(self, snapshot) -> None:
        original_set_check_sequence(self, snapshot)

        data = dict(snapshot or {})
        checks = list(data.get("checks", []) or [])
        current = data.get("current_check")

        if bool(getattr(self, "_display_ng_evidence_frozen", False)):
            aplicar_tema_visual_display_f3(
                self,
                "ng_waiting",
                snapshot=data,
            )
            return

        feedback = obter_feedback_espera_display_f3(data)

        if (
            feedback is None
            or not checks
            or not isinstance(current, dict)
            or not bool(getattr(self, "_camera_ready", False))
        ):
            aplicar_tema_visual_display_f3(
                self,
                "neutral",
                snapshot=data,
            )
            return

        result, detail = feedback
        background = (
            self.COLOR_WAITING_AFTER_OK
            if result == "OK"
            else self.COLOR_WAITING_AFTER_NG
        )
        name = str(current.get("name") or current.get("id") or "CHECK")
        self._set_state(
            background=background,
            foreground="#FFFFFF",
            status="PLACA JÁ ANALISADA\nCOLOQUE OUTRA PLACA",
            detail=detail,
        )
        # O layout estável do F3 usa height=1 para estados normais. Este aviso é
        # deliberadamente composto por duas linhas e precisa reservar duas linhas
        # reais no Tkinter; caso contrário as partes superior/inferior são cortadas.
        self.status_label.configure(
            font=("DejaVu Sans", 22, "bold"),
            height=2,
            pady=0,
        )
        aplicar_tema_visual_display_f3(
            self,
            "ok_waiting" if result == "OK" else "ng_waiting",
            snapshot=data,
        )

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
        aplicar_tema_visual_display_f3(
            self,
            "ok_result" if is_ok else "ng_result",
            snapshot=snapshot,
            force_all_completed=bool(is_ok),
        )

    cls.set_check_sequence = set_check_sequence
    cls.show_plate_result = show_plate_result
    cls._odin_display_result_feedback = True
    cls._odin_display_full_result_theme = True


instalar_feedback_resultado_display_f3()
