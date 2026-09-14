from __future__ import annotations

"""Corrige somente a ANÁLISE VISUAL informativa do Display F3.

Depois da troca do ROI retangular pela união das máscaras do projeto, as fotos de
H1/BLUE/USB/AUX e PLACA DESLIGADA passaram a produzir scores altos e próximos.
A regra visual reutilizava a margem rígida do classificador físico e, por isso,
respondia ``referências muito próximas`` mesmo quando uma foto de CHECK era a
melhor correspondência do frame.

Esta camada não muda a autoridade produtiva. Quando o resolvedor visual já tem
várias referências acima do limiar e a MELHOR delas é um CHECK, o CHECK vencedor
continua sendo mostrado como a melhor correspondência visual. A proximidade fica
registrada como diagnóstico, em vez de apagar o nome do CHECK.

Ambiguidade entre as duas referências físicas (SUPORTE VAZIO x PLACA DESLIGADA)
continua conservadora. Nada deste módulo registra OK/NG, avança CHECK, rearma
ciclo ou altera a Produção F2.
"""

from copy import deepcopy

import src.platform.display_f3_visual_analysis_relative_fallback as visual_module


F3_VISUAL_BEST_CHECK_MIN_EDGE = 1e-6
F3_VISUAL_BEST_CHECK_SOURCE = "f3_visual_best_matched_check"


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def resolver_melhor_check_visual_f3(
    candidates: dict | None,
    decision: dict | None,
) -> dict | None:
    """Mantém o melhor CHECK visível quando a única dúvida é margem pequena.

    O resolvedor base continua responsável por thresholds, fallback relativo e
    casos realmente não identificados. Aqui só tratamos o caso em que ele já
    encontrou referências absolutas válidas, marcou ``ambiguous`` pela margem de
    3%, e a referência de maior score é uma foto de CHECK.
    """
    if not isinstance(decision, dict):
        return decision
    if str(decision.get("result_kind") or "") != "ambiguous":
        return decision

    source = candidates if isinstance(candidates, dict) else {}
    best_key = str(decision.get("best_reference") or "")
    best = source.get(best_key)
    if (
        not best_key.startswith("check:")
        or not isinstance(best, dict)
        or str(best.get("kind") or "") != "check"
        or not bool(best.get("matched"))
    ):
        return decision

    best_score = _safe_float(best.get("score"))
    if best_score is None:
        return decision

    rival_scores = []
    for key, item in source.items():
        if str(key) == best_key or not isinstance(item, dict):
            continue
        score = _safe_float(item.get("score"))
        if score is not None:
            rival_scores.append(score)
    rival_score = max(rival_scores) if rival_scores else None

    # Empate numérico real continua ambíguo. Uma diferença positiva, mesmo menor
    # que a margem física de 3%, é suficiente para a leitura INFORMATIVA apontar
    # qual foto foi a melhor correspondência sem conceder qualquer autoridade.
    if (
        rival_score is not None
        and best_score - rival_score <= F3_VISUAL_BEST_CHECK_MIN_EDGE
    ):
        return decision

    result = deepcopy(decision)
    result.update(
        {
            "result_kind": "check",
            "selected_reference": best_key,
            "decision_mode": "best_matched_check_close_references",
            "relative_fallback": False,
            "check_id": str(best.get("check_id") or ""),
            "check_name": str(best.get("check_name") or best.get("name") or ""),
            "selected_name": str(best.get("name") or best.get("check_name") or ""),
            "selected_kind": "check",
            "close_references": True,
            "close_references_original_margin": decision.get("score_margin"),
            "best_check_visual_source": F3_VISUAL_BEST_CHECK_SOURCE,
            "informational_only": True,
            "affects_result": False,
        }
    )
    return result


_INSTALLED = False


def instalar_melhor_correspondencia_visual_display_f3() -> None:
    """Aplica o desempate por melhor CHECK somente ao resolvedor visual F3."""
    global _INSTALLED
    if _INSTALLED:
        return

    if bool(getattr(visual_module, "_display_f3_visual_best_match_fix", False)):
        _INSTALLED = True
        return

    original = visual_module.resolver_analise_visual_candidatos_f3

    def resolve(candidates):
        decision = original(candidates)
        return resolver_melhor_check_visual_f3(candidates, decision)

    visual_module.resolver_analise_visual_candidatos_f3 = resolve
    visual_module._display_f3_visual_best_match_fix = True
    _INSTALLED = True
