from __future__ import annotations

"""Coerência final entre energia física, ANÁLISE VISUAL e overlay do F3.

A autoridade de energia já é resolvida antes da decisão produtiva. Esta camada
faz a apresentação respeitar essa autoridade:

* se a placa está presente e a energia foi confirmada como OFF, o status visual
  efetivo mostra PLACA DESLIGADA, mesmo que a comparação global de fotos tenha
  H1/BLUE/USB/AUX com score ligeiramente maior;
* se a energia ainda não foi confirmada, o status não anuncia um CHECK;
* enquanto não houver energia produtivamente confirmada, classificações brutas
  não pintam divergências em amarelo. A preview mostra somente as guias neutras
  das máscaras, preservando a geometria sem chamar ausência de energia de defeito;
* os scores globais e o texto original continuam preservados no Debug Técnico
  como diagnóstico, sem autoridade operacional.

Isso é importante porque a análise bruta de uma placa totalmente desligada pode
classificar alguma máscara esperada OFF como ON por diferença de foto/template.
Esse artefato não pode ser usado como ``has_any_on`` para habilitar amarelo em
todas as máscaras esperadas ON.

Módulo exclusivo do F3. Não altera OK/NG, debounce, sequência, câmera ou F2.
"""

from copy import deepcopy

import src.platform.display_f3_operational_status as operational_module
import src.platform.display_f3_power_authority as power_module
import src.platform.display_f3_snapshot_debug_lightweight_ui as debug_ui
import src.platform.display_live_roi_overlay as overlay_module


F3_POWER_VISUAL_COHERENCE_SOURCE = "f3_power_visual_coherence"
F3_OVERLAY_MODE_SEMANTIC = "semantic_powered"
F3_OVERLAY_MODE_NEUTRAL = "neutral_guides_no_power"


def _power_status(app) -> dict | None:
    """Retorna a última autoridade física publicada no mesmo runtime F3."""
    status = getattr(app, "_display_f3_power_authority_status", None)
    if isinstance(status, dict):
        return status

    # Fallback somente para apresentação caso o status dedicado ainda não tenha
    # sido anexado, mas o estado operacional final já exista.
    state = getattr(app, "_display_f3_operational_state", None)
    if not isinstance(state, dict):
        return None
    evidence = state.get("power_evidence")
    presence = state.get("board_presence_evidence")
    if not isinstance(evidence, dict) and not isinstance(presence, dict):
        return None
    return {
        "source": str(state.get("power_authority_source") or ""),
        "board_present": bool((presence or {}).get("board_present")),
        "presence": deepcopy(presence) if isinstance(presence, dict) else None,
        "energy": deepcopy(evidence) if isinstance(evidence, dict) else None,
        "decision_allowed": bool(state.get("allow_auto")),
        "reason": str(state.get("power_gate_reason") or ""),
    }


def _energy_state(status: dict | None) -> str:
    evidence = status.get("energy") if isinstance(status, dict) else None
    if not isinstance(evidence, dict):
        return power_module.F3_POWER_STATE_UNCONFIRMED
    return str(
        evidence.get("energy_state")
        or power_module.F3_POWER_STATE_UNCONFIRMED
    ).strip().lower()


def _semantic_overlay_allowed(status: dict | None) -> bool:
    if not isinstance(status, dict):
        return False
    return bool(
        status.get("board_present")
        and status.get("decision_allowed")
        and _energy_state(status) == power_module.F3_POWER_STATE_POWERED
    )


def aplicar_coerencia_overlay_com_energia_f3(
    context: dict | None,
    status: dict | None,
) -> dict | None:
    """Suprime cores semânticas quando não há energia confirmada.

    Geometria/resolução/estado esperado permanecem no contexto. Assim o renderer
    de guias de início continua desenhando o contorno neutro das máscaras.
    """
    if not isinstance(context, dict):
        return context

    result = deepcopy(context)
    if not isinstance(status, dict):
        return result

    state = _energy_state(status)
    allowed = _semantic_overlay_allowed(status)
    result["power_energy_state"] = state
    result["power_decision_allowed"] = bool(status.get("decision_allowed"))
    result["power_board_present"] = bool(status.get("board_present"))
    result["power_visual_coherence_source"] = F3_POWER_VISUAL_COHERENCE_SOURCE

    if allowed:
        result["semantic_overlay_allowed"] = True
        result["semantic_overlay_mode"] = F3_OVERLAY_MODE_SEMANTIC
        return result

    # Sem energia não existe defeito de segmento. Não reutilizamos classificação
    # bruta/stale para acender amarelo. As máscaras continuam visíveis como guia
    # neutra pela camada display_f3_mask_visibility_ui.
    result["classifications"] = {}
    result["failed_mask_ids"] = ()
    result["failed_masks"] = {}
    result["has_any_on"] = False
    result["semantic_overlay_allowed"] = False
    result["semantic_overlay_suppressed"] = True
    result["semantic_overlay_mode"] = F3_OVERLAY_MODE_NEUTRAL
    result["semantic_overlay_reason"] = str(
        status.get("reason")
        or "energia_produtiva_nao_confirmada"
    )
    return result


def aplicar_coerencia_estado_visual_com_energia_f3(
    state: dict | None,
    status: dict | None,
) -> dict | None:
    """Faz o texto efetivo respeitar energia e preserva o match global bruto."""
    if not isinstance(state, dict):
        return state

    result = deepcopy(state)
    if not isinstance(status, dict):
        return result

    energy = _energy_state(status)
    board_present = bool(status.get("board_present"))
    result["power_visual_coherence_source"] = F3_POWER_VISUAL_COHERENCE_SOURCE
    result["power_energy_state"] = energy
    result["power_board_present"] = board_present

    # Preserva o diagnóstico de imagem inteira para suporte, mas ele deixa de ser
    # a frase principal quando contradiz a autoridade física das máscaras.
    raw_text = str(result.get("status_text") or result.get("text") or "")
    if raw_text and not result.get("status_text_raw"):
        result["status_text_raw"] = raw_text
    result.setdefault("global_visual_result_kind_raw", result.get("result_kind"))
    result.setdefault("global_visual_selected_reference_raw", result.get("selected_reference"))
    result.setdefault("global_visual_best_reference_raw", result.get("best_reference"))
    result.setdefault("global_visual_decision_mode_raw", result.get("decision_mode"))

    if board_present and energy == power_module.F3_POWER_STATE_OFF:
        text = "ANÁLISE VISUAL: PLACA DESLIGADA NO SUPORTE • energia pelas máscaras"
        result.update(
            {
                "text": text,
                "status_text": text,
                "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["off"],
                "status_color": operational_module.F3_OPERATIONAL_STATUS_COLORS["off"],
                "result_kind": "board_off",
                "selected_reference": "board_off",
                "selected_kind": "board_off",
                "selected_name": "PLACA DESLIGADA NO SUPORTE",
                "decision_mode": "power_authority_override_off",
                "effective_status_authority": "power_masks",
                "global_visual_diagnostic_only": True,
                "uses_masks_for_effective_status": True,
            }
        )
        return result

    if board_present and energy == power_module.F3_POWER_STATE_UNCONFIRMED:
        text = "ANÁLISE VISUAL: PLACA PRESENTE • ENERGIA NÃO CONFIRMADA"
        result.update(
            {
                "text": text,
                "status_text": text,
                "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"],
                "status_color": operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"],
                "result_kind": "power_unconfirmed",
                "selected_reference": None,
                "selected_kind": "unknown",
                "selected_name": "ENERGIA NÃO CONFIRMADA",
                "decision_mode": "power_authority_override_unconfirmed",
                "effective_status_authority": "power_masks",
                "global_visual_diagnostic_only": True,
                "uses_masks_for_effective_status": True,
            }
        )
        return result

    # Com energia confirmada, o match global continua apenas informativo e pode
    # mostrar qual foto ficou mais próxima. Não ganha autoridade de OK/NG.
    if energy == power_module.F3_POWER_STATE_POWERED:
        result["effective_status_authority"] = "global_visual_informational"
        result["global_visual_diagnostic_only"] = True
    return result


def _install_overlay_context_gate() -> None:
    if bool(getattr(overlay_module, "_display_f3_power_visual_overlay_installed", False)):
        return

    previous = overlay_module._overlay_context

    def build(window, visual_rotation: int):
        context = previous(window, visual_rotation)
        app = overlay_module._app_from_window(window)
        if app is None:
            return context
        return aplicar_coerencia_overlay_com_energia_f3(
            context,
            _power_status(app),
        )

    overlay_module._overlay_context = build
    overlay_module._display_f3_power_visual_overlay_installed = True


def _install_live_visual_status_gate() -> None:
    if bool(getattr(operational_module, "_display_f3_power_visual_status_installed", False)):
        return

    previous = operational_module._build_visual_analysis_state

    def build(app, frame, project_name: str):
        state = previous(app, frame, project_name)
        return aplicar_coerencia_estado_visual_com_energia_f3(
            state,
            _power_status(app),
        )

    operational_module._build_visual_analysis_state = build
    operational_module._display_f3_power_visual_status_installed = True


def _install_debug_visual_gate() -> None:
    if bool(getattr(debug_ui, "_display_f3_power_visual_debug_installed", False)):
        return

    previous_snapshot = debug_ui._build_visual_analysis_snapshot
    previous_report = debug_ui._visual_report_block

    def snapshot(app, frame, project_name: str):
        visual = previous_snapshot(app, frame, project_name)
        return aplicar_coerencia_estado_visual_com_energia_f3(
            visual,
            _power_status(app),
        )

    def report(snapshot_data: dict) -> str:
        base = previous_report(snapshot_data)
        visual = (
            snapshot_data.get("visual_analysis")
            if isinstance(snapshot_data, dict)
            else None
        )
        if not isinstance(visual, dict):
            return base
        raw = str(visual.get("status_text_raw") or "--")
        effective = str(visual.get("status_text") or visual.get("text") or "--")
        extra = (
            "\n[COERÊNCIA ENERGIA x APRESENTAÇÃO]"
            f"\neffective_status={effective}"
            f"\nglobal_status_raw={raw}"
            f"\npower_energy_state={visual.get('power_energy_state', '--')}"
            f"\neffective_status_authority={visual.get('effective_status_authority', '--')}"
            "\nglobal_visual_diagnostic_only=SIM"
        )
        return f"{base}{extra}" if base else extra.lstrip("\n")

    debug_ui._build_visual_analysis_snapshot = snapshot
    debug_ui._visual_report_block = report
    debug_ui._display_f3_power_visual_debug_installed = True


_INSTALLED = False


def instalar_coerencia_visual_energia_display_f3() -> None:
    """Instala a apresentação final depois da autoridade unificada de energia."""
    global _INSTALLED
    if _INSTALLED:
        return

    _install_overlay_context_gate()
    _install_live_visual_status_gate()
    _install_debug_visual_gate()

    operational_module._display_f3_power_visual_coherence_installed = True
    _INSTALLED = True
