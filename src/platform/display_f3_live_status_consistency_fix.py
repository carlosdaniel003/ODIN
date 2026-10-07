from __future__ import annotations

"""Mantém a faixa DIVERGÊNCIA coerente mesmo quando gates encerram cedo.

A faixa substitui completamente o antigo status operacional "ANÁLISE VISUAL".
Ela consome somente a análise semântica já produzida pelo CHECK atual e nunca
executa visão adicional, nunca decide OK/NG e nunca altera debounce/fluxo.
"""

from copy import deepcopy

import src.platform.display_f3_operational_status as operational_module
from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin
from src.platform.display_production_f3_window import DisplayProductionF3Window


F3_LIVE_STATUS_CONSISTENCY_SOURCE = "f3_live_divergence_status"
F3_LEGACY_REFERENCE_PLACEHOLDER = (
    "ANÁLISE VISUAL: aguardando referências do projeto"
)
F3_INITIAL_FRAME_PLACEHOLDER = (
    "DIVERGÊNCIA • NENHUMA • AGUARDANDO PRIMEIRA LEITURA"
)


def _current_context(app) -> dict:
    try:
        context = app._display_auto_current_context()
    except Exception:
        context = None
    return context if isinstance(context, dict) else {}


def resolver_status_visual_runtime_f3(
    app,
    current_text: str = "",
) -> tuple[str, str] | None:
    """Resolve a faixa DIVERGÊNCIA usando somente estado já calculado."""
    del current_text

    if bool(getattr(app, "_display_f3_waiting_new_board_after_empty", False)):
        state = operational_module.formatar_status_divergencia_f3(
            None,
            _current_context(app),
            waiting_reason="AGUARDANDO NOVA PLACA",
        )
    elif bool(getattr(app, "_display_f3_waiting_empty_rearm", False)):
        state = operational_module.formatar_status_divergencia_f3(
            None,
            _current_context(app),
            waiting_reason="AGUARDANDO RETIRADA DA PLACA",
        )
    else:
        state = operational_module.formatar_status_divergencia_f3(
            getattr(app, "_display_auto_last_analysis", None),
            _current_context(app),
        )

    return str(state["text"]), str(state["color"])


def publicar_status_visual_runtime_f3(app) -> dict | None:
    window = getattr(app, "display_f3_window", None)
    if window is None:
        return None

    # NG congelado já recebeu a divergência do snapshot exato antes do latch.
    if bool(getattr(app, "_display_f3_ng_evidence_frozen", False)):
        return None

    label = getattr(window, "visual_analysis_state_label", None)
    try:
        current_text = str(label.cget("text")) if label is not None else ""
    except Exception:
        current_text = ""

    resolved = resolver_status_visual_runtime_f3(app, current_text)
    if resolved is None:
        return None

    status_text, color = resolved
    try:
        window.set_visual_analysis_status(status_text, color)
    except Exception:
        return None

    snapshot = {
        "text": status_text,
        "color": color,
        "source": F3_LIVE_STATUS_CONSISTENCY_SOURCE,
        "previous_text": current_text,
    }
    app._display_f3_live_status_consistency = deepcopy(snapshot)
    return snapshot


def corrigir_placeholder_inicial_f3(window) -> bool:
    """Converte somente o placeholder legado ainda criado por adapters antigos."""
    label = getattr(window, "visual_analysis_state_label", None)
    if label is None:
        return False
    try:
        current = str(label.cget("text"))
    except Exception:
        return False
    if str(current).strip() != F3_LEGACY_REFERENCE_PLACEHOLDER:
        return False
    try:
        label.configure(text=F3_INITIAL_FRAME_PLACEHOLDER)
    except Exception:
        return False
    return True


def _install_window_placeholder_fix() -> None:
    cls = DisplayProductionF3Window
    current_init = cls.__init__
    if bool(getattr(current_init, "_odin_f3_live_status_placeholder_fix", False)):
        return

    previous_init = current_init

    def init(self, *args, **kwargs):
        previous_init(self, *args, **kwargs)
        corrigir_placeholder_inicial_f3(self)

    init._odin_f3_live_status_placeholder_fix = True
    init._odin_f3_live_status_placeholder_base = previous_init
    cls.__init__ = init


def _install_process_refresh() -> None:
    cls = DisplayAutomaticCheckF3Mixin
    current_process = cls._process_display_auto_check
    if bool(getattr(current_process, "_odin_f3_live_status_consistency", False)):
        return

    previous_process = current_process

    def process(self):
        try:
            return previous_process(self)
        finally:
            if bool(getattr(self, "display_f3_ativo", False)):
                publicar_status_visual_runtime_f3(self)

    process._odin_f3_live_status_consistency = True
    process._odin_f3_live_status_consistency_base = previous_process
    cls._process_display_auto_check = process


def instalar_consistencia_status_live_display_f3() -> None:
    """Instala refresh final da faixa DIVERGÊNCIA por fora dos gates."""
    _install_window_placeholder_fix()
    _install_process_refresh()
    DisplayAutomaticCheckF3Mixin._display_f3_live_status_consistency_installed = True
