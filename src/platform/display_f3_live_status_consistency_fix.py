from __future__ import annotations

"""Mantém as linhas de status do F3 coerentes mesmo quando um gate encerra cedo.

O pipeline F3 possui guards externos que podem encerrar ``_process_display_auto_check``
antes do wrapper histórico responsável por publicar a segunda linha ``ANÁLISE
VISUAL``. O caso mais importante é o gate final de energia: com a placa presente,
mas todos os segmentos esperados ON ainda apagados, ele bloqueia corretamente a
decisão produtiva e retorna sem chamar o pipeline interno. Antes desta correção a
primeira linha já dizia PLACA DESLIGADA, enquanto a segunda podia continuar no
placeholder criado ao abrir a janela: ``aguardando referências do projeto``.

Esta camada é somente de apresentação. Ela reutiliza o estado operacional e a
autoridade de energia já calculados no MESMO ciclo. Não lê a câmera novamente,
não executa uma segunda análise, não muda OK/NG, CHECK, debounce, sequência ou F2.
"""

from copy import deepcopy

import src.platform.display_f3_operational_status as operational_module
import src.platform.display_f3_power_authority as power_module
from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin
from src.platform.display_production_f3_window import DisplayProductionF3Window


F3_LIVE_STATUS_CONSISTENCY_SOURCE = "f3_live_status_consistency"
F3_LEGACY_REFERENCE_PLACEHOLDER = "ANÁLISE VISUAL: aguardando referências do projeto"
F3_INITIAL_FRAME_PLACEHOLDER = "ANÁLISE VISUAL: aguardando primeira leitura da câmera"


def _rearm_active(app) -> bool:
    return bool(
        getattr(app, "_display_f3_waiting_empty_rearm", False)
        or getattr(app, "_display_f3_waiting_new_board_after_empty", False)
    )


def _current_check_name(app) -> str:
    try:
        context = app._display_auto_current_context()
    except Exception:
        context = None
    if not isinstance(context, dict):
        return "CHECK"
    return str(context.get("check_name") or context.get("check_id") or "CHECK").strip().upper()


def _is_placeholder(text: str) -> bool:
    value = str(text or "").strip().lower()
    return bool(
        not value
        or "aguardando referências do projeto" in value
        or "aguardando referencias do projeto" in value
        or "aguardando primeira leitura" in value
    )


def resolver_status_visual_runtime_f3(app, current_text: str = "") -> tuple[str, str] | None:
    """Resolve somente estados já conhecidos, sem recalcular visão computacional."""
    if _rearm_active(app):
        # O rearme possui sua própria apresentação detalhada (1/2, suporte vazio,
        # aguardando nova placa) e não deve ser sobrescrito por esta camada.
        return None

    placeholder = _is_placeholder(current_text)
    status = getattr(app, "_display_f3_power_authority_status", None)
    if isinstance(status, dict):
        presence = status.get("presence") if isinstance(status.get("presence"), dict) else {}
        board_present = bool(status.get("board_present"))
        empty_confirmed = bool(status.get("empty_confirmed") or presence.get("empty_confirmed"))
        evidence = status.get("energy") if isinstance(status.get("energy"), dict) else {}
        energy_state = str(
            evidence.get("energy_state") or power_module.F3_POWER_STATE_UNCONFIRMED
        ).strip().lower()

        if empty_confirmed and not board_present:
            return (
                "ANÁLISE VISUAL: PLACA FORA DO SUPORTE",
                operational_module.F3_OPERATIONAL_STATUS_COLORS["empty"],
            )

        if board_present and energy_state == power_module.F3_POWER_STATE_OFF:
            return (
                "ANÁLISE VISUAL: PLACA DESLIGADA NO SUPORTE • energia pelas máscaras",
                operational_module.F3_OPERATIONAL_STATUS_COLORS["off"],
            )

        if board_present and energy_state == power_module.F3_POWER_STATE_UNCONFIRMED:
            return (
                "ANÁLISE VISUAL: PLACA PRESENTE • ENERGIA NÃO CONFIRMADA",
                operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"],
            )

        # Com energia confirmada, o pipeline normal continua livre para mostrar a
        # análise global informativa. Só substituímos um placeholder que claramente
        # não representa o runtime atual.
        if (
            board_present
            and energy_state == power_module.F3_POWER_STATE_POWERED
            and placeholder
        ):
            return (
                f"ANÁLISE VISUAL: DISPLAY LIGADO • analisando {_current_check_name(app)}",
                operational_module.F3_OPERATIONAL_STATUS_COLORS["check"],
            )

    # Fallback semântico: usa o estado operacional já calculado. Só é aceito se o
    # próprio runtime confirma que as referências físicas estão configuradas; uma
    # configuração realmente incompleta continua sendo mostrada pelos builders
    # históricos, sem ser mascarada por este fix.
    state = getattr(app, "_display_f3_operational_state", None)
    if not isinstance(state, dict) or not bool(state.get("board_references_complete")):
        return None

    kind = str(state.get("kind") or "unknown").strip().lower()
    if kind == "empty":
        return (
            "ANÁLISE VISUAL: PLACA FORA DO SUPORTE",
            operational_module.F3_OPERATIONAL_STATUS_COLORS["empty"],
        )
    if kind == "off":
        return (
            "ANÁLISE VISUAL: PLACA DESLIGADA NO SUPORTE",
            operational_module.F3_OPERATIONAL_STATUS_COLORS["off"],
        )
    if kind in {"check", "powered"} and placeholder:
        name = str(state.get("check_name") or _current_check_name(app)).strip().upper()
        return (
            f"ANÁLISE VISUAL: DISPLAY LIGADO • analisando {name or 'CHECK'}",
            operational_module.F3_OPERATIONAL_STATUS_COLORS["check"],
        )
    if kind == "unknown" and placeholder:
        return (
            "ANÁLISE VISUAL: identificando estado atual...",
            operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"],
        )
    return None


def publicar_status_visual_runtime_f3(app) -> dict | None:
    window = getattr(app, "display_f3_window", None)
    if window is None:
        return None

    label = getattr(window, "visual_analysis_state_label", None)
    try:
        current_text = str(label.cget("text")) if label is not None else ""
    except Exception:
        current_text = ""

    resolved = resolver_status_visual_runtime_f3(app, current_text)
    if resolved is None:
        return None

    text, color = resolved
    try:
        window.set_visual_analysis_status(text, color)
    except Exception:
        return None

    snapshot = {
        "text": text,
        "color": color,
        "source": F3_LIVE_STATUS_CONSISTENCY_SOURCE,
        "previous_text": current_text,
    }
    app._display_f3_live_status_consistency = deepcopy(snapshot)
    return snapshot


def corrigir_placeholder_inicial_f3(window) -> bool:
    """O texto inicial descreve espera pelo primeiro frame, não falta de referência."""
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
    """Instala refresh visual final por fora de gates que podem retornar cedo."""
    _install_window_placeholder_fix()
    _install_process_refresh()
    DisplayAutomaticCheckF3Mixin._display_f3_live_status_consistency_installed = True
