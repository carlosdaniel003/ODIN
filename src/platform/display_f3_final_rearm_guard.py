from __future__ import annotations

"""Autoridade final do handoff entre placas na Produção Display F3.

As camadas históricas do F3 compõem vários wrappers sobre o estado físico e o
processo automático. O rearme terminal precisa ficar literalmente por fora de
todas elas: depois de APROVADA/NG/SEGREGADA, nenhuma leitura de H1 pode iniciar
outro ciclo até o suporte vazio ser confirmado e uma nova placa entrar.

Este módulo não classifica CHECK, não altera máscaras e não toca no F2. Ele só
mantém o bloqueio terminal visível e impede que um wrapper interno reative a
análise produtiva enquanto o handoff físico ainda está pendente.
"""

import src.platform.display_f3_operational_status as operational_module
from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin
from src.platform.display_f3_cycle_rearm_release_fix import (
    instalar_rearme_fisico_final_display_f3,
)


F3_FINAL_REARM_GUARD_SOURCE = "f3_final_terminal_rearm_guard"
F3_REARM_PHASE_WAIT_EMPTY = "waiting_empty"
F3_REARM_PHASE_WAIT_NEW_BOARD = "waiting_new_board"


def fase_rearme_terminal_f3(app) -> str:
    if bool(getattr(app, "_display_f3_waiting_empty_rearm", False)):
        return F3_REARM_PHASE_WAIT_EMPTY
    if bool(getattr(app, "_display_f3_waiting_new_board_after_empty", False)):
        return F3_REARM_PHASE_WAIT_NEW_BOARD
    return ""


def estado_visivel_rearme_terminal_f3(state: dict | None, phase: str) -> dict:
    """Torna explícito que reconhecer H1 não significa poder avançar o ciclo."""
    result = dict(state or {})
    result["rearm_underlying_kind"] = str(result.get("kind") or "unknown")
    result["rearm_underlying_text"] = str(result.get("text") or "")
    result["kind"] = "unknown"
    result["allow_auto"] = False
    result["_display_f3_physical_decision_allowed"] = False
    result["final_rearm_guard"] = True
    result["final_rearm_guard_source"] = F3_FINAL_REARM_GUARD_SOURCE
    result["color"] = operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"]

    if phase == F3_REARM_PHASE_WAIT_NEW_BOARD:
        result["text"] = "SUPORTE VAZIO CONFIRMADO • AGUARDANDO NOVA PLACA"
        result["cycle_rearm_waiting"] = False
        result["cycle_rearmed_waiting_new_board"] = True
        result["final_rearm_reason"] = "aguardando_nova_placa"
    else:
        result["text"] = "SEGREGAÇÃO/RESULTADO CONCLUÍDO • RETIRE A PLACA DO SUPORTE"
        result["cycle_rearm_waiting"] = True
        result["cycle_rearmed_waiting_new_board"] = False
        result["final_rearm_reason"] = "aguardando_suporte_vazio"
    return result


def _publicar_estado_rearme(self, state: dict) -> None:
    self._display_f3_operational_state = dict(state)
    window = getattr(self, "display_f3_window", None)
    if window is not None:
        try:
            window.set_operational_reference_status(
                str(state.get("text") or "IDENTIFICANDO..."),
                str(
                    state.get("color")
                    or operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"]
                ),
            )
        except Exception:
            pass


def _atualizar_rearme_terminal_f3(self) -> str:
    """Deixa o builder final consumir EMPTY/nova placa sem executar o CHECK."""
    frame = getattr(self, "camera_frame_atual", None)
    repository = getattr(self, "display_project_repository", None)
    if frame is None or getattr(frame, "size", 0) == 0 or repository is None:
        return fase_rearme_terminal_f3(self)

    try:
        project_name = str(repository.obter_projeto_ativo() or "")
    except Exception:
        project_name = ""
    if not project_name:
        return fase_rearme_terminal_f3(self)

    try:
        context = self._display_auto_current_context()
    except Exception:
        context = None

    try:
        state = operational_module._build_operational_state(
            self,
            frame,
            project_name,
            context,
        )
    except Exception:
        state = dict(getattr(self, "_display_f3_operational_state", {}) or {})

    phase_after = fase_rearme_terminal_f3(self)
    if phase_after:
        state = estado_visivel_rearme_terminal_f3(state, phase_after)
        _publicar_estado_rearme(self, state)
    else:
        # O builder acabou de confirmar a nova placa. Publicamos o estado já
        # liberado e deixamos o pipeline produtivo executar no mesmo preview.
        if isinstance(state, dict):
            _publicar_estado_rearme(self, state)
    return phase_after


def instalar_guard_rearme_terminal_final_display_f3() -> None:
    """Instala o bloqueio terminal por fora de todo o pipeline automático F3."""
    # Reaplica primeiro o builder dedicado sobre a composição atualmente ativa.
    instalar_rearme_fisico_final_display_f3()

    cls = DisplayAutomaticCheckF3Mixin
    current_process = cls._process_display_auto_check
    if bool(getattr(current_process, "_odin_f3_final_terminal_rearm_guard", False)):
        cls._display_f3_final_terminal_rearm_guard_installed = True
        return

    previous_process = current_process

    def process(self):
        if not bool(getattr(self, "display_f3_ativo", False)):
            return previous_process(self)

        phase = fase_rearme_terminal_f3(self)
        if not phase:
            return previous_process(self)

        phase = _atualizar_rearme_terminal_f3(self)
        if not phase:
            return previous_process(self)

        try:
            self._reset_display_auto_stability(transition=False)
        except Exception:
            pass

        try:
            if phase == F3_REARM_PHASE_WAIT_NEW_BOARD:
                self._display_auto_set_preview_status(
                    "AUTO • suporte vazio confirmado • aguardando NOVA PLACA",
                    "#FDE68A",
                )
            else:
                self._display_auto_set_preview_status(
                    "AUTO • ciclo encerrado • RETIRE A PLACA DO SUPORTE",
                    "#FDE68A",
                )
        except Exception:
            pass
        return None

    process._odin_f3_final_terminal_rearm_guard = True
    process._odin_f3_final_terminal_rearm_base = previous_process
    cls._process_display_auto_check = process
    cls._display_f3_final_terminal_rearm_guard_installed = True
