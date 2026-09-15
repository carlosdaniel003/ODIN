from __future__ import annotations

"""Reconcilia presença física do F3 por separação relativa EMPTY x PLACA.

A classificação global de H1/BLUE/USB/AUX/OFF pode ficar ambígua porque todas
essas referências contêm a mesma placa ocupando o suporte. Essa ambiguidade não
pode virar ambiguidade de PRESENÇA.

Esta camada responde primeiro à pergunta física mais simples:

    o suporte está VAZIO ou existe uma PLACA ocupando o suporte?

Para isso, quando necessário, compara a referência EMPTY contra a melhor cena que
contém placa (OFF + qualquer CHECK). Só depois a autoridade de energia decide se
a placa presente está DESLIGADA ou LIGADA. A identidade do CHECK continua sendo
responsabilidade das máscaras do CHECK lógico atual.

Casos reais que motivaram a correção:

1) placa retirada durante BLUE:
   EMPTY=0.5867 e melhor cena com placa=0.4130 -> suporte vazio;
2) programa reiniciado com placa desligada já no suporte:
   melhor cena com placa=H1 0.8089, OFF=0.7879 e EMPTY=0.4089 -> placa presente,
   mesmo com H1/BLUE separados por apenas 0.0087 e o classificador global ficando
   UNKNOWN por ambiguidade entre referências que TODAS contêm placa.

Não altera OK/NG, sequência de CHECKS, câmera, timers, debounce de CHECK nem F2.
"""

from copy import deepcopy

import src.platform.display_f3_debug_clarity_fix as debug_clarity_module
import src.platform.display_f3_power_authority as power_module
import src.platform.display_f3_power_visual_coherence as coherence_module
import src.platform.display_f3_operational_status as operational_module
import src.platform.display_f3_runtime_contract_fix as contract_module


F3_RELATIVE_EMPTY_PRESENCE_SOURCE = "f3_relative_empty_presence_authority"
F3_RELATIVE_BOARD_PRESENCE_SOURCE = "f3_relative_board_presence_authority"
F3_RELATIVE_PRESENCE_SOURCE = "f3_relative_scene_presence_authority"

# O fallback relativo é deliberadamente conservador e simétrico: tanto EMPTY
# quanto PLACA precisam de score mínimo + separação clara da hipótese oposta.
F3_RELATIVE_PRESENCE_MIN_SCORE = 0.40
F3_RELATIVE_PRESENCE_MIN_MARGIN = 0.12
F3_RELATIVE_PRESENCE_MIN_RATIO = 1.50
F3_RELATIVE_PRESENCE_STRONG_MARGIN = 0.16

# Aliases mantidos para compatibilidade com testes/imports anteriores.
F3_RELATIVE_EMPTY_MIN_SCORE = F3_RELATIVE_PRESENCE_MIN_SCORE
F3_RELATIVE_EMPTY_MIN_MARGIN = F3_RELATIVE_PRESENCE_MIN_MARGIN
F3_RELATIVE_EMPTY_MIN_RATIO = F3_RELATIVE_PRESENCE_MIN_RATIO
F3_RELATIVE_EMPTY_STRONG_MARGIN = F3_RELATIVE_PRESENCE_STRONG_MARGIN


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


def _separation_confirmed(winner_score: float, loser_score: float) -> tuple[bool, float, float]:
    margin = float(winner_score - loser_score)
    ratio = float(winner_score / max(loser_score, 1e-6))
    confirmed = bool(
        winner_score >= F3_RELATIVE_PRESENCE_MIN_SCORE
        and margin >= F3_RELATIVE_PRESENCE_MIN_MARGIN
        and (
            ratio >= F3_RELATIVE_PRESENCE_MIN_RATIO
            or margin >= F3_RELATIVE_PRESENCE_STRONG_MARGIN
        )
    )
    return confirmed, margin, ratio


def avaliar_presenca_relativa_f3(state: dict | None) -> dict:
    """Decide somente VAZIO x OCUPADO; nunca decide qual CHECK está ativo."""
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
        "source": F3_RELATIVE_PRESENCE_SOURCE,
        "empty_confirmed": False,
        "presence_confirmed": False,
        "board_present": False,
        "decision_mode": "relative_presence_not_confirmed",
        "physical_kind_before": kind,
        "empty_score": empty_score,
        "best_board_reference": best_key,
        "best_board_score": best_score,
        "minimum_score": F3_RELATIVE_PRESENCE_MIN_SCORE,
        "minimum_margin": F3_RELATIVE_PRESENCE_MIN_MARGIN,
        "minimum_ratio": F3_RELATIVE_PRESENCE_MIN_RATIO,
        "strong_margin": F3_RELATIVE_PRESENCE_STRONG_MARGIN,
    }

    # Um estado físico já explícito continua tendo prioridade. Aqui apenas
    # transformamos sua semântica em PRESENÇA, sem reaproveitar o nome do CHECK.
    if kind == "empty":
        result.update(
            {
                "available": True,
                "source": F3_RELATIVE_EMPTY_PRESENCE_SOURCE,
                "empty_confirmed": True,
                "presence_confirmed": True,
                "board_present": False,
                "decision_mode": "absolute_empty_reference",
                "reason": "suporte_vazio_confirmado_pela_referencia_absoluta",
            }
        )
        return result

    if kind in {"off", "check", "powered"}:
        result.update(
            {
                "available": True,
                "source": F3_RELATIVE_BOARD_PRESENCE_SOURCE,
                "empty_confirmed": False,
                "presence_confirmed": True,
                "board_present": True,
                "decision_mode": "absolute_board_scene_reference",
                "reason": "placa_confirmada_por_estado_fisico_explicito",
            }
        )
        return result

    if kind not in {"unknown", "unavailable"}:
        result["reason"] = "estado_fisico_nao_elegivel_para_fallback_relativo"
        return result

    if empty_score is None or best_score is None:
        result["reason"] = "scores_de_presenca_incompletos"
        return result

    board_confirmed, board_margin, board_ratio = _separation_confirmed(
        best_score,
        empty_score,
    )
    empty_confirmed, empty_margin, empty_ratio = _separation_confirmed(
        empty_score,
        best_score,
    )

    result.update(
        {
            "board_over_empty_margin": round(board_margin, 4),
            "board_over_empty_ratio": round(board_ratio, 4),
            "empty_over_best_board_margin": round(empty_margin, 4),
            "empty_over_best_board_ratio": round(empty_ratio, 4),
        }
    )

    if board_confirmed:
        result.update(
            {
                "source": F3_RELATIVE_BOARD_PRESENCE_SOURCE,
                "presence_confirmed": True,
                "board_present": True,
                "empty_confirmed": False,
                "decision_mode": "relative_board_strong_separation",
                "reason": "placa_confirmada_por_separacao_relativa_do_suporte_vazio",
            }
        )
        return result

    if empty_confirmed:
        result.update(
            {
                "source": F3_RELATIVE_EMPTY_PRESENCE_SOURCE,
                "presence_confirmed": True,
                "board_present": False,
                "empty_confirmed": True,
                "decision_mode": "relative_empty_strong_separation",
                "reason": "suporte_vazio_confirmado_por_separacao_relativa",
            }
        )
        return result

    result.update(
        {
            "decision_mode": "relative_presence_insufficient_separation",
            "reason": "separacao_relativa_insuficiente_para_confirmar_presenca",
        }
    )
    return result


def avaliar_suporte_vazio_relativo_f3(state: dict | None) -> dict:
    """API histórica: mantém foco em EMPTY, usando a autoridade simétrica nova."""
    result = avaliar_presenca_relativa_f3(state)
    kind = str((state or {}).get("kind") or "unknown").strip().lower() if isinstance(state, dict) else "unknown"
    if kind in {"off", "check", "powered"}:
        result["empty_confirmed"] = False
        result["reason"] = "estado_fisico_explicito_nao_sobrescrito"
    return result


def resolver_presenca_global_relativa_f3(
    state: dict | None,
    legacy_presence: dict | None = None,
) -> dict:
    """Produz a única resposta de presença consumida pela autoridade de energia."""
    base = deepcopy(legacy_presence) if isinstance(legacy_presence, dict) else {}
    evidence = avaliar_presenca_relativa_f3(state)
    base["relative_presence_diagnostic"] = deepcopy(evidence)

    if not bool(evidence.get("presence_confirmed")):
        return base

    base.update(
        {
            "available": True,
            "board_present": bool(evidence.get("board_present")),
            "empty_confirmed": bool(evidence.get("empty_confirmed")),
            "presence_confirmed": True,
            "source": str(evidence.get("source") or F3_RELATIVE_PRESENCE_SOURCE),
            "reason": str(evidence.get("reason") or ""),
            "decision_mode": str(evidence.get("decision_mode") or ""),
            "empty_score": evidence.get("empty_score"),
            "best_board_reference": evidence.get("best_board_reference"),
            "best_board_score": evidence.get("best_board_score"),
            "board_over_empty_margin": evidence.get("board_over_empty_margin"),
            "board_over_empty_ratio": evidence.get("board_over_empty_ratio"),
            "empty_over_best_board_margin": evidence.get("empty_over_best_board_margin"),
            "empty_over_best_board_ratio": evidence.get("empty_over_best_board_ratio"),
        }
    )
    return base


def _merge_presence(result: dict, evidence: dict) -> dict:
    presence = (
        deepcopy(result.get("board_presence_evidence"))
        if isinstance(result.get("board_presence_evidence"), dict)
        else {}
    )
    presence["relative_presence_diagnostic"] = deepcopy(evidence)
    if bool(evidence.get("presence_confirmed")):
        presence.update(
            {
                "available": True,
                "board_present": bool(evidence.get("board_present")),
                "empty_confirmed": bool(evidence.get("empty_confirmed")),
                "presence_confirmed": True,
                "source": str(evidence.get("source") or ""),
                "reason": str(evidence.get("reason") or ""),
                "decision_mode": str(evidence.get("decision_mode") or ""),
                "empty_score": evidence.get("empty_score"),
                "best_board_reference": evidence.get("best_board_reference"),
                "best_board_score": evidence.get("best_board_score"),
                "board_over_empty_margin": evidence.get("board_over_empty_margin"),
                "board_over_empty_ratio": evidence.get("board_over_empty_ratio"),
                "empty_over_best_board_margin": evidence.get("empty_over_best_board_margin"),
                "empty_over_best_board_ratio": evidence.get("empty_over_best_board_ratio"),
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

    if not bool(presence.get("presence_confirmed")):
        return base

    board_present = bool(presence.get("board_present"))
    empty_confirmed = bool(presence.get("empty_confirmed"))
    lines = str(base).splitlines()
    patched: list[str] = []
    inserted = False

    if board_present:
        margin = _safe_float(presence.get("board_over_empty_margin"))
    else:
        margin = _safe_float(presence.get("empty_over_best_board_margin"))
    margin_text = "--" if margin is None else f"{margin * 100.0:.1f} p.p."

    for line in lines:
        if line.startswith("ESTADO DA PLACA:"):
            if empty_confirmed:
                patched.append("ESTADO DA PLACA: FORA DO SUPORTE • CONFIRMADA")
            elif board_present:
                patched.append("ESTADO DA PLACA: PRESENTE • CONFIRMADA")
            else:
                patched.append(line)

            if not inserted:
                patched.append(
                    "PRESENÇA: "
                    f"melhor_com_placa={presence.get('best_board_reference', '--')} "
                    f"{_pct(presence.get('best_board_score'))} • "
                    f"EMPTY={_pct(presence.get('empty_score'))} • "
                    f"margem={margin_text} • "
                    f"modo={presence.get('decision_mode', '--')}"
                )
                inserted = True
            continue

        if empty_confirmed and line.startswith("ENERGIA DO DISPLAY:"):
            patched.append("ENERGIA DO DISPLAY: NÃO APLICÁVEL • SUPORTE VAZIO")
            continue
        if empty_confirmed and line.startswith("MOTIVO:"):
            patched.append("MOTIVO: suporte vazio confirmado; gate produtivo bloqueado")
            continue
        patched.append(line)
    return "\n".join(patched)


_INSTALLED = False


def instalar_presenca_relativa_suporte_vazio_display_f3() -> None:
    """Instala autoridade simétrica de presença depois da energia unificada."""
    global _INSTALLED
    if _INSTALLED:
        return

    # A energia deve receber uma resposta de presença baseada em VAZIO x PLACA,
    # e não na disputa entre H1/BLUE/USB/AUX. A função v2 resolve este nome em
    # tempo de execução, portanto o patch é suficiente sem criar novo loop.
    previous_presence = power_module._presence_from_global_scores

    def presence(state: dict | None) -> dict:
        legacy = previous_presence(state)
        return resolver_presenca_global_relativa_f3(state, legacy)

    power_module._presence_from_global_scores = presence
    power_module._display_f3_relative_scene_presence_installed = True

    previous_authority = power_module.aplicar_autoridade_energia_ao_estado_f3

    def apply(app, state, frame, project_name: str, context: dict | None):
        result = previous_authority(app, state, frame, project_name, context)
        if not isinstance(result, dict):
            return result

        evidence = avaliar_presenca_relativa_f3(result)
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
