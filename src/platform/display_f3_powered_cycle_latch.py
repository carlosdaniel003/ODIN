from __future__ import annotations

"""Fecha o ciclo físico entre a sonda exata e a sequência produtiva do Display F3.

Há dois estados diferentes que não podem ser confundidos:

1. o classificador global pode continuar parecido com a foto de PLACA DESLIGADA,
   porque quase toda a cena permanece igual quando apenas segmentos do display mudam;
2. o gabarito exato do CHECK pode, no mesmo frame, confirmar todas as máscaras.

Quando o CHECK atual foi confirmado integralmente pela sonda exata, essa evidência é
forte o bastante para liberar SOMENTE o registro daquele CHECK. Depois que o H1 é
registrado, o ciclo fica marcado como energizado até EMPTY/rearme/resultado. Durante
as transições seguintes, um falso OFF global passa a significar "placa ligada,
aguardando o próximo CHECK" e nunca volta a derrubar visualmente a placa para
DESLIGADA.

O latch não aprova BLUE/USB/AUX. Ele mantém as máscaras vivas, mas conserva a
autoridade de decisão bloqueada até o CHECK atual possuir evidência própria.
"""

from copy import deepcopy

import src.platform.display_auto_check_runtime as runtime_module
import src.platform.display_f3_live_diagnostic_trace as trace_module
import src.platform.display_f3_operational_status as operational_module
import src.platform.display_f3_physical_learning_policy as physical_policy_module
import src.platform.display_f3_runtime_contract_fix as contract_module
from src.platform.display_production_f3 import DisplayProductionF3Mixin


F3_EXACT_DECISION_BRIDGE_SOURCE = "f3_exact_probe_decision_bridge"
F3_POWERED_CYCLE_SOURCE = "f3_h1_powered_cycle_latch"
F3_POWERED_CYCLE_KEY = "check:powered_cycle"


def _context_signature(context: dict | None) -> tuple[str, str] | None:
    if not isinstance(context, dict):
        return None
    project_name = str(context.get("project_name") or "").strip()
    check_id = str(context.get("check_id") or "").strip()
    if not project_name or not check_id:
        return None
    return project_name, check_id


def _current_context(app) -> dict | None:
    try:
        context = app._display_auto_current_context()
    except Exception:
        return None
    return context if isinstance(context, dict) else None


def _event_type(event: dict | None) -> str:
    if not isinstance(event, dict):
        return ""
    return str(event.get("event") or "").strip()


def _rearm_active(app) -> bool:
    return bool(
        getattr(app, "_display_f3_waiting_empty_rearm", False)
        or getattr(app, "_display_f3_waiting_new_board_after_empty", False)
    )


def _is_reference_gate(app, context: dict | None) -> bool:
    if not isinstance(context, dict):
        return False
    try:
        return bool(app._display_auto_is_reference_gate(context))
    except Exception:
        pass
    try:
        if int(context.get("current_index", -1)) == 0:
            return True
    except (TypeError, ValueError):
        pass
    return str(context.get("check_name") or "").strip().upper() == "H1"


def analise_confirma_check_integralmente_f3(analysis: dict | None) -> bool:
    """Exige confirmação positiva integral, não apenas semelhança parcial."""
    if not isinstance(analysis, dict):
        return False
    if not bool(analysis.get("ready")) or analysis.get("approved") is not True:
        return False

    # A sonda rápida de H1/BLUE preserva explicitamente o resultado do gabarito
    # completo antes de eventualmente aplicar a regra positiva apenas aos ON.
    exact_all = analysis.get("exact_all_masks_approved")
    if exact_all is False:
        return False

    try:
        active = int(analysis.get("active_mask_count", 0) or 0)
        matched = int(analysis.get("matched_mask_count", 0) or 0)
    except (TypeError, ValueError):
        active = 0
        matched = 0

    if active > 0:
        return matched >= active

    results = [
        item
        for item in (analysis.get("mask_results") or [])
        if isinstance(item, dict)
        and str(item.get("expected") or "").strip().lower() != "ignore"
    ]
    return bool(results) and all(bool(item.get("matched")) for item in results)


def _clear_powered_cycle_latch(app, reason: str) -> None:
    app._display_f3_powered_cycle_latched = False
    app._display_f3_powered_cycle_project = ""
    app._display_f3_powered_cycle_reference_check = ""
    app._display_f3_powered_cycle_clear_reason = str(reason or "")


def _mark_powered_cycle_latch(app, context: dict | None) -> None:
    signature = _context_signature(context)
    if signature is None:
        return
    project_name, check_id = signature
    app._display_f3_powered_cycle_latched = True
    app._display_f3_powered_cycle_project = project_name
    app._display_f3_powered_cycle_reference_check = check_id
    app._display_f3_powered_cycle_clear_reason = ""


def _latch_matches_project(app, project_name: str) -> bool:
    return bool(
        getattr(app, "_display_f3_powered_cycle_latched", False)
        and str(getattr(app, "_display_f3_powered_cycle_project", "") or "")
        == str(project_name or "")
    )


def preparar_gate_decisao_sonda_exata_f3(
    app,
    context: dict | None,
    analysis: dict | None,
    stability: dict | None,
) -> bool:
    """Libera o registrar somente quando a sonda confirmou o CHECK integralmente."""
    info = {
        "used": False,
        "context": deepcopy(context) if isinstance(context, dict) else context,
        "stability_confirmed": bool((stability or {}).get("confirm")),
        "analysis_fully_confirmed": analise_confirma_check_integralmente_f3(analysis),
    }
    app._display_f3_exact_decision_bridge_last = info

    # O bridge histórico nunca recebe autoridade sobre o primeiro CHECK neural.
    # Isso vale inclusive antes de F3RuntimeAuthorities ser instalado.
    if (
        _is_reference_gate(app, context)
        and bool(
            getattr(
                runtime_module,
                "_display_f3_h1_neural_authority",
                False,
            )
        )
    ):
        info["blocked_reason"] = "h1_neural_owns_check_decision"
        return False

    # No produto final a decisão pertence ao F3CheckAnalyzerAuthority. Este
    # bridge continua apenas para composições legadas/testes sem a autoridade
    # canônica e nunca pode promover estado ou registrar CHECK em paralelo.
    if bool(getattr(app, "_display_f3_runtime_authorities_installed", False)):
        info["blocked_reason"] = "autoridade_canonica_runtime_ativa"
        return False

    if not bool(getattr(app, "display_f3_ativo", False)):
        info["blocked_reason"] = "f3_inativo"
        return False
    if _rearm_active(app):
        info["blocked_reason"] = "aguardando_rearme_fisico"
        return False
    if getattr(app, "display_f3_result_after_id", None) is not None:
        info["blocked_reason"] = "resultado_em_exibicao"
        return False
    if not bool((stability or {}).get("confirm")):
        info["blocked_reason"] = "sonda_ainda_sem_estabilidade"
        return False
    if not info["analysis_fully_confirmed"]:
        info["blocked_reason"] = "check_nao_confirmado_integralmente"
        return False

    expected_signature = _context_signature(context)
    if expected_signature is None or _context_signature(_current_context(app)) != expected_signature:
        info["blocked_reason"] = "contexto_logico_mudou"
        return False

    state = getattr(app, "_display_f3_operational_state", None)
    state = deepcopy(state) if isinstance(state, dict) else {}
    kind = str(state.get("kind") or "unknown").strip().lower()
    if kind in {"empty", "unavailable"}:
        info["blocked_reason"] = f"estado_fisico_absoluto:{kind}"
        return False

    project_name, check_id = expected_signature
    check_name = str((context or {}).get("check_name") or check_id).strip().upper()

    # Se o classificador físico já reconheceu explicitamente OUTRO CHECK, não o
    # escondemos. O bridge é destinado a OFF/UNKNOWN/POWERED ou ao próprio CHECK.
    if kind == "check":
        physical_check_id = str(state.get("check_id") or "").strip()
        if physical_check_id and physical_check_id != check_id:
            info["blocked_reason"] = "outro_check_fisico_confirmado"
            return False

    previous_kind = kind
    previous_key = str(state.get("physical_state_key") or "")
    state.update(
        {
            "kind": "check",
            "text": f"PLACA NO SUPORTE • LIGADA • DISPLAY EM {check_name}",
            "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["check"],
            "allow_auto": True,
            "check_id": check_id,
            "check_name": check_name,
            "physical_state_key": f"check:{check_id}",
            "physical_matches_expected_check": True,
            "exact_probe_confirmed": True,
            "exact_probe_decision_bridge": True,
            "physical_reference_kind_before_bridge": previous_kind,
            "physical_reference_key_before_bridge": previous_key,
            "source": F3_EXACT_DECISION_BRIDGE_SOURCE,
            contract_module.F3_DECISION_ALLOWED_KEY: True,
            contract_module.F3_MASK_LIVE_KEY: True,
        }
    )
    app._display_f3_operational_state = state
    info.update(
        {
            "used": True,
            "project_name": project_name,
            "check_id": check_id,
            "check_name": check_name,
            "previous_kind": previous_kind,
            "previous_physical_state_key": previous_key,
        }
    )
    return True


def aplicar_latch_ciclo_ligado_ao_estado_fisico_f3(
    app,
    state: dict | None,
    project_name: str,
    context: dict | None,
) -> dict:
    """Durante o mesmo ciclo, falso OFF vira LIGADA/AGUARDANDO sem liberar OK/NG."""
    result = deepcopy(state) if isinstance(state, dict) else {}

    if _rearm_active(app) or getattr(app, "display_f3_result_after_id", None) is not None:
        _clear_powered_cycle_latch(app, "rearme_ou_resultado")
        return result

    kind = str(result.get("kind") or "unknown").strip().lower()
    if kind == "empty":
        _clear_powered_cycle_latch(app, "suporte_vazio")
        return result

    if not _latch_matches_project(app, project_name):
        return result
    if kind not in {"off", "unknown"}:
        return result

    check_id = str((context or {}).get("check_id") or "").strip()
    check_name = str((context or {}).get("check_name") or check_id or "CHECK").strip().upper()
    previous_kind = kind
    previous_key = str(result.get("physical_state_key") or "")

    # allow_auto=True aqui é apenas a porta interna para manter as máscaras vivas.
    # O contrato F3 usa F3_DECISION_ALLOWED_KEY=False para impedir que essa memória
    # de energia, sozinha, gere OK ou NG do próximo CHECK.
    result.update(
        {
            "kind": "powered",
            "text": f"PLACA NO SUPORTE • LIGADA • AGUARDANDO {check_name}",
            "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["check"],
            "allow_auto": True,
            "physical_state_key": F3_POWERED_CYCLE_KEY,
            "expected_check_id": check_id,
            "physical_matches_expected_check": False,
            "powered_board_confirmed": True,
            "powered_cycle_latched": True,
            "latched_raw_kind": previous_kind,
            "latched_raw_physical_state_key": previous_key,
            "source": F3_POWERED_CYCLE_SOURCE,
            contract_module.F3_DECISION_ALLOWED_KEY: False,
            contract_module.F3_MASK_LIVE_KEY: True,
        }
    )
    return result


def _install_physical_cycle_latch() -> None:
    if bool(
        getattr(
            physical_policy_module,
            "_display_f3_powered_cycle_latch_installed",
            False,
        )
    ):
        return

    previous_builder = physical_policy_module._build_physical_operational_state

    def physical_builder(self, frame, project_name: str, context: dict | None):
        state = previous_builder(self, frame, project_name, context)
        return aplicar_latch_ciclo_ligado_ao_estado_fisico_f3(
            self,
            state,
            project_name,
            context,
        )

    physical_policy_module._build_physical_operational_state = physical_builder
    physical_policy_module._display_f3_powered_cycle_latch_installed = True

    # Diagnósticos paralelos só são redirecionados se ainda apontavam exatamente
    # para o mesmo builder produtivo.
    if operational_module._build_operational_state is previous_builder:
        operational_module._build_operational_state = physical_builder


def _install_cycle_lifecycle_on_register() -> None:
    cls = DisplayProductionF3Mixin
    if bool(getattr(cls, "_display_f3_powered_cycle_register_installed", False)):
        return

    previous_register = cls.registrar_resultado_check_display_f3

    def register_result(self, aprovado: bool = True):
        context_before = _current_context(self)
        event = previous_register(self, aprovado)
        event_type = _event_type(event)

        if event_type == "check_advanced" and bool(aprovado) and _is_reference_gate(
            self, context_before
        ):
            _mark_powered_cycle_latch(self, context_before)
        elif event_type in {"plate_ok", "plate_ng", "plate_discarded"}:
            _clear_powered_cycle_latch(self, f"evento_terminal:{event_type}")

        bridge = getattr(self, "_display_f3_exact_decision_bridge_last", None)
        if isinstance(bridge, dict):
            bridge["register_event"] = event_type
            bridge["cycle_powered_latched"] = bool(
                getattr(self, "_display_f3_powered_cycle_latched", False)
            )
        return event

    cls.registrar_resultado_check_display_f3 = register_result
    cls._display_f3_powered_cycle_register_installed = True


def _install_session_lifecycle() -> None:
    cls = DisplayProductionF3Mixin
    if bool(getattr(cls, "_display_f3_powered_cycle_session_installed", False)):
        return

    previous_activate = cls._ativar_tela_producao_display_f3
    previous_close = cls.fechar_tela_producao_display_f3
    previous_discard = cls.descartar_placa_display_f3

    def activate(self):
        _clear_powered_cycle_latch(self, "nova_sessao_f3")
        return previous_activate(self)

    def close(self):
        _clear_powered_cycle_latch(self, "f3_fechado")
        return previous_close(self)

    def discard(self):
        result = previous_discard(self)
        _clear_powered_cycle_latch(self, "placa_descartada")
        return result

    cls._ativar_tela_producao_display_f3 = activate
    cls.fechar_tela_producao_display_f3 = close
    cls.descartar_placa_display_f3 = discard
    cls._display_f3_powered_cycle_session_installed = True


def _install_exact_probe_decision_bridge() -> None:
    if bool(getattr(trace_module, "_display_f3_exact_decision_bridge_installed", False)):
        return

    previous_advance = trace_module._advance_positive_probe_if_needed

    def advance(app, context_before, analysis, stability):
        used = preparar_gate_decisao_sonda_exata_f3(
            app,
            context_before,
            analysis,
            stability,
        )
        result = previous_advance(app, context_before, analysis, stability)
        if isinstance(result, dict):
            result = dict(result)
            result["exact_decision_bridge_used"] = bool(used)
            result["cycle_powered_latched"] = bool(
                getattr(app, "_display_f3_powered_cycle_latched", False)
            )
        return result

    trace_module._advance_positive_probe_if_needed = advance
    trace_module._display_f3_exact_decision_bridge_installed = True


_INSTALLED = False


def instalar_latch_ciclo_energizado_display_f3() -> None:
    """Instala a correção final, por fora de todos os gates históricos do F3."""
    global _INSTALLED
    if _INSTALLED:
        return
    _install_physical_cycle_latch()
    _install_cycle_lifecycle_on_register()
    _install_session_lifecycle()
    _install_exact_probe_decision_bridge()
    _INSTALLED = True
