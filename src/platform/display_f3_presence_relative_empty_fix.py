from __future__ import annotations

"""Reconhece suporte vazio no F3 quando a referência absoluta cai abaixo do limiar.

O classificador físico continua preferindo a confirmação absoluta das referências.
Esta camada trata somente o caso em que ele retorna UNKNOWN, mas a foto de
PLACA FORA DO SUPORTE é a melhor referência por uma separação relativa forte
contra TODAS as referências que contêm placa (OFF + CHECKS).

Motivação observada em produção:
- EMPTY = 0.5867, abaixo do threshold absoluto 0.72;
- melhor referência com placa = H1 0.4130;
- margem = 0.1737;
- a análise visual relativa já identificava corretamente PLACA FORA DO SUPORTE,
  enquanto a autoridade operacional permanecia em IDENTIFICANDO.

A correção não altera OK/NG, sequência de CHECKS, debounce do CHECK, câmera nem F2.
Ela também não transforma ausência de placa em "display desligado": sem placa,
energia não é avaliada e o gate produtivo permanece bloqueado.
"""

from copy import deepcopy

import src.platform.display_f3_debug_clarity_fix as debug_clarity_module
import src.platform.display_f3_power_authority as power_module
import src.platform.display_f3_power_visual_coherence as coherence_module
import src.platform.display_f3_operational_status as operational_module
import src.platform.display_f3_runtime_contract_fix as contract_module


F3_RELATIVE_EMPTY_PRESENCE_SOURCE = "f3_relative_empty_presence_authority"

# Mantemos a mesma filosofia conservadora já usada pelo diagnóstico visual:
# o fallback só existe quando a melhor referência é EMPTY, há score mínimo e
# separação clara em relação à melhor cena que contém placa.
F3_RELATIVE_EMPTY_MIN_SCORE = 0.40
F3_RELATIVE_EMPTY_MIN_MARGIN = 0.12
F3_RELATIVE_EMPTY_MIN_RATIO = 1.50
F3_RELATIVE_EMPTY_STRONG_MARGIN = 0.16


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _occupied_scores(reference_scores: dict) -> list[tuple[str, float]]:
    rows: list[tuple[str, float]] = []
    for key, value in reference_scores.items():
        name = str(key or "")
        if name != "off" and not name.startswith("check:"):
            continue
        score = _safe_float(value)
        if score is not None:
            rows.append((name, float(score)))
    rows.sort(key=lambda item: item[1], reverse=True)
    return rows


def avaliar_suporte_vazio_relativo_f3(state: dict | None) -> dict:
    """Confirma EMPTY por separação relativa apenas quando o físico ficou UNKNOWN."""
    data = state if isinstance(state, dict) else {}
    kind = str(data.get("kind") or "unknown").strip().lower()
    scores = (
        dict(data.get("reference_scores") or {})
        if isinstance(data.get("reference_scores"), dict)
        else {}
    )
    empty_score = _safe_float(scores.get("empty"))
    occupied = _occupied_scores(scores)
    best_key = occupied[0][0] if occupied else None
    best_score = occupied[0][1] if occupied else None

    result = {
        "available": bool(empty_score is not None and best_score is not None),
        "source": F3_RELATIVE_EMPTY_PRESENCE_SOURCE,
        "empty_confirmed": False,
        "presence_confirmed": False,
        "board_present": False,
        "decision_mode": "relative_empty_not_confirmed",
        "physical_kind_before": kind,
        "empty_score": empty_score,
        "best_board_reference": best_key,
        "best_board_score": best_score,
        "minimum_empty_score": F3_RELATIVE_EMPTY_MIN_SCORE,
        "minimum_margin": F3_RELATIVE_EMPTY_MIN_MARGIN,
        "minimum_ratio": F3_RELATIVE_EMPTY_MIN_RATIO,
        "strong_margin": F3_RELATIVE_EMPTY_STRONG_MARGIN,
    }

    # Se a autoridade física absoluta já confirmou EMPTY, apenas tornamos essa
    # proveniência explícita para status/debug.
    if kind == "empty":
        result.update(
            {
                "available": True,
                "empty_confirmed": True,
                "presence_confirmed": True,
                "decision_mode": "absolute_empty_reference",
                "reason": "suporte_vazio_confirmado_pela_referencia_absoluta",
            }
        )
        return result

    # Nunca substituímos um OFF/CHECK/POWERED explícito por inferência relativa.
    if kind != "unknown":
        result["reason"] = "estado_fisico_explicito_nao_sobrescrito"
        return result

    if empty_score is None or best_score is None:
        result["reason"] = "scores_de_presenca_incompletos"
        return result

    margin = float(empty_score - best_score)
    ratio = float(empty_score / max(best_score, 1e-6))
    result["empty_over_best_board_margin"] = round(margin, 4)
    result["empty_over_best_board_ratio"] = round(ratio, 4)

    score_ok = empty_score >= F3_RELATIVE_EMPTY_MIN_SCORE
    separation_ok = bool(
        margin >= F3_RELATIVE_EMPTY_MIN_MARGIN
        and (
            ratio >= F3_RELATIVE_EMPTY_MIN_RATIO
            or margin >= F3_RELATIVE_EMPTY_STRONG_MARGIN
        )
    )
    confirmed = bool(score_ok and separation_ok)

    result.update(
        {
            "empty_confirmed": confirmed,
            "presence_confirmed": confirmed,
            "decision_mode": (
                "relative_empty_strong_separation"
                if confirmed
                else "relative_empty_insufficient_separation"
            ),
            "reason": (
                "suporte_vazio_confirmado_por_separacao_relativa"
                if confirmed
                else "separacao_relativa_insuficiente_para_confirmar_suporte_vazio"
            ),
        }
    )
    return result


def _merge_presence(result: dict, evidence: dict) -> dict:
    presence = (
        deepcopy(result.get("board_presence_evidence"))
        if isinstance(result.get("board_presence_evidence"), dict)
        else {}
    )
    presence["relative_empty_diagnostic"] = deepcopy(evidence)
    if bool(evidence.get("empty_confirmed")):
        presence.update(
            {
                "available": True,
                "board_present": False,
                "empty_confirmed": True,
                "presence_confirmed": True,
                "source": F3_RELATIVE_EMPTY_PRESENCE_SOURCE,
                "reason": str(evidence.get("reason") or ""),
                "decision_mode": str(evidence.get("decision_mode") or ""),
                "empty_score": evidence.get("empty_score"),
                "best_board_reference": evidence.get("best_board_reference"),
                "best_board_score": evidence.get("best_board_score"),
                "empty_over_best_board_margin": evidence.get(
                    "empty_over_best_board_margin"
                ),
                "empty_over_best_board_ratio": evidence.get(
                    "empty_over_best_board_ratio"
                ),
            }
        )
    return presence


def aplicar_suporte_vazio_confirmado_f3(app, result: dict, evidence: dict) -> dict:
    """Converte UNKNOWN em EMPTY sem tocar no CHECK lógico nem gerar resultado."""
    output = deepcopy(result)
    presence = _merge_presence(output, evidence)
    output["board_presence_evidence"] = presence

    if not bool(evidence.get("empty_confirmed")):
        return output

    output.update(
        {
            "kind": "empty",
            "text": "PLACA FORA DO SUPORTE",
            "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["empty"],
            "allow_auto": False,
            "physical_state_key": "empty:relative_presence",
            "powered_board_confirmed": False,
            "power_gate_blocked": True,
            "power_gate_reason": "suporte_vazio_confirmado_por_referencia_relativa",
            "presence_authority_source": F3_RELATIVE_EMPTY_PRESENCE_SOURCE,
            contract_module.F3_DECISION_ALLOWED_KEY: False,
            contract_module.F3_MASK_LIVE_KEY: True,
        }
    )

    # Sem placa, qualquer evidência de energia do frame anterior deixa de ter
    # significado. Não apagamos análise bruta global; apenas chaves operacionais.
    for key in (
        "power_evidence",
        "power_mask_evidence_v2",
        "powered_mask_evidence",
        "current_check_power_mask_evidence",
    ):
        output.pop(key, None)

    previous_status = getattr(app, "_display_f3_power_authority_status", None)
    status = deepcopy(previous_status) if isinstance(previous_status, dict) else {}
    status.update(
        {
            "presence_authority_source": F3_RELATIVE_EMPTY_PRESENCE_SOURCE,
            "board_present": False,
            "empty_confirmed": True,
            "presence": deepcopy(presence),
            "energy": None,
            "decision_allowed": False,
            "reason": output["power_gate_reason"],
        }
    )
    app._display_f3_power_authority_status = status
    return output


def aplicar_status_visual_suporte_vazio_f3(
    state: dict | None,
    status: dict | None,
) -> dict | None:
    """Faz as duas linhas de status concordarem quando EMPTY foi confirmado."""
    if not isinstance(state, dict) or not isinstance(status, dict):
        return state

    presence = status.get("presence")
    if not isinstance(presence, dict) or not bool(presence.get("empty_confirmed")):
        return state

    result = deepcopy(state)
    raw_text = str(result.get("status_text_raw") or result.get("status_text") or result.get("text") or "")
    if raw_text and not result.get("status_text_raw"):
        result["status_text_raw"] = raw_text

    text = "ANÁLISE VISUAL: PLACA FORA DO SUPORTE • presença confirmada"
    result.update(
        {
            "text": text,
            "status_text": text,
            "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["empty"],
            "status_color": operational_module.F3_OPERATIONAL_STATUS_COLORS["empty"],
            "result_kind": "empty_support",
            "selected_reference": "empty_support",
            "selected_kind": "empty_support",
            "selected_name": "PLACA FORA DO SUPORTE",
            "decision_mode": "relative_empty_presence_authority",
            "effective_status_authority": F3_RELATIVE_EMPTY_PRESENCE_SOURCE,
            "global_visual_diagnostic_only": True,
            "uses_masks_for_effective_status": False,
        }
    )
    return result


def _pct(value) -> str:
    number = _safe_float(value)
    return "--" if number is None else f"{number * 100.0:.1f}%"


def _patch_debug_summary(base: str, snapshot: dict) -> str:
    runtime = snapshot.get("runtime_at_click") if isinstance(snapshot, dict) else None
    runtime = runtime if isinstance(runtime, dict) else {}
    status = runtime.get("power_authority")
    status = status if isinstance(status, dict) else {}
    presence = status.get("presence")
    presence = presence if isinstance(presence, dict) else {}

    if not bool(presence.get("empty_confirmed")):
        return base

    lines = str(base).splitlines()
    patched: list[str] = []
    inserted = False
    for line in lines:
        if line.startswith("ESTADO DA PLACA:"):
            patched.append("ESTADO DA PLACA: FORA DO SUPORTE • CONFIRMADA")
            if not inserted:
                margin = _safe_float(presence.get("empty_over_best_board_margin"))
                margin_text = "--" if margin is None else f"{margin * 100.0:.1f} p.p."
                patched.append(
                    "PRESENÇA: "
                    f"EMPTY={_pct(presence.get('empty_score'))} • "
                    f"melhor_com_placa={presence.get('best_board_reference', '--')} "
                    f"{_pct(presence.get('best_board_score'))} • "
                    f"margem={margin_text} • "
                    f"modo={presence.get('decision_mode', '--')}"
                )
                inserted = True
            continue
        if line.startswith("ENERGIA DO DISPLAY:"):
            patched.append("ENERGIA DO DISPLAY: NÃO APLICÁVEL • SUPORTE VAZIO")
            continue
        if line.startswith("MOTIVO:"):
            patched.append("MOTIVO: suporte vazio confirmado; gate produtivo bloqueado")
            continue
        patched.append(line)
    return "\n".join(patched)


_INSTALLED = False


def instalar_presenca_relativa_suporte_vazio_display_f3() -> None:
    """Instala a última autoridade de presença, depois da energia unificada."""
    global _INSTALLED
    if _INSTALLED:
        return

    previous_authority = power_module.aplicar_autoridade_energia_ao_estado_f3

    def apply(app, state, frame, project_name: str, context: dict | None):
        result = previous_authority(app, state, frame, project_name, context)
        if not isinstance(result, dict):
            return result

        evidence = avaliar_suporte_vazio_relativo_f3(result)
        result = deepcopy(result)
        result["board_presence_evidence"] = _merge_presence(result, evidence)
        if not bool(evidence.get("empty_confirmed")):
            return result
        return aplicar_suporte_vazio_confirmado_f3(app, result, evidence)

    power_module.aplicar_autoridade_energia_ao_estado_f3 = apply
    power_module._display_f3_relative_empty_presence_installed = True

    # Os wrappers de status instalados anteriormente resolvem esta função no
    # módulo em tempo de execução; substituí-la aqui mantém uma única apresentação.
    previous_visual = coherence_module.aplicar_coerencia_estado_visual_com_energia_f3

    def visual(state: dict | None, status: dict | None):
        result = previous_visual(state, status)
        return aplicar_status_visual_suporte_vazio_f3(result, status)

    coherence_module.aplicar_coerencia_estado_visual_com_energia_f3 = visual
    coherence_module._display_f3_relative_empty_visual_status_installed = True

    previous_report = debug_clarity_module._report_summary_block

    def report(snapshot: dict) -> str:
        return _patch_debug_summary(previous_report(snapshot), snapshot)

    debug_clarity_module._report_summary_block = report
    power_module._report_summary_power = report
    debug_clarity_module._display_f3_relative_empty_debug_installed = True

    _INSTALLED = True
