from __future__ import annotations

from src.platform.display_auto_check_analyzer import DISPLAY_AUTO_CLASS_LOW_LIGHT
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
)


DISPLAY_AUTO_DECISION_OK = "ok"
DISPLAY_AUTO_DECISION_NG = "ng"
DISPLAY_AUTO_DECISION_SEARCHING = "searching"

# O ReferenceLedClassifier já calibra a confiança entre 0.50 e 0.99.
# O F3 não adiciona um limiar mais rígido do que o modo normal, para que uma
# leitura que é aceita fora do F3 também possa ser aceita aqui.
DISPLAY_AUTO_MIN_CONFIDENCE = 0.50


def _confidence(result: dict) -> float:
    try:
        return float(result.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def decidir_analise_display_f3(
    analysis: dict | None,
    *,
    reference_gate: bool = False,
) -> dict:
    """Converte classificação óptica em OK, NG confirmado ou busca contínua.

    Regras operacionais:
    - H1/primeiro CHECK é o referencial de entrada: nunca gera NG automático;
      só avança quando estiver conforme.
    - Depois de H1, ausência de evidência não é defeito: continua buscando.
    - POUCA LUZ em uma máscara esperada ACESA/APAGADA é inconsistência.
    - ACESO onde era esperado APAGADO é inconsistência positiva.
    - APAGADO onde era esperado ACESO só é defeito quando existe, no mesmo
      frame, pelo menos outro segmento reconhecido como ACESO. Isso confirma
      que o Display está ligado antes de declarar um segmento apagado.
    """
    data = dict(analysis or {})
    if not bool(data.get("ready")):
        return {
            "decision": DISPLAY_AUTO_DECISION_SEARCHING,
            "reason": str(data.get("reason") or "analise_indisponivel"),
            "confirmed_ng": False,
            "board_powered": False,
        }

    results = [
        item
        for item in (data.get("mask_results") or [])
        if isinstance(item, dict)
    ]
    if not results:
        # Compatibilidade com testes/stubs antigos que fornecem apenas o OK.
        # Sem detalhes de máscara, nunca aceitamos um NG automático.
        if data.get("approved") is True:
            return {
                "decision": DISPLAY_AUTO_DECISION_OK,
                "reason": "check_conforme_compatibilidade",
                "confirmed_ng": False,
                "board_powered": False,
            }
        return {
            "decision": DISPLAY_AUTO_DECISION_SEARCHING,
            "reason": "sem_resultados_de_mascara",
            "confirmed_ng": False,
            "board_powered": False,
        }

    confident_results = [
        item
        for item in results
        if _confidence(item) >= DISPLAY_AUTO_MIN_CONFIDENCE
    ]
    board_powered = any(
        str(item.get("classified")) == DISPLAY_CHECK_STATE_ON
        for item in confident_results
    )

    all_matched = all(bool(item.get("matched")) for item in results)
    all_confident = len(confident_results) == len(results)

    # O H1/primeiro CHECK só pode ser OK quando a própria leitura comprova que
    # existe pelo menos um segmento ACESO. Uma placa totalmente apagada nunca
    # valida o referencial, mesmo que alguma camada anterior marque "approved".
    if reference_gate and not board_powered:
        return {
            "decision": DISPLAY_AUTO_DECISION_SEARCHING,
            "reason": "aguardando_evidencia_placa_ligada",
            "confirmed_ng": False,
            "board_powered": False,
        }

    if all_matched and all_confident:
        return {
            "decision": DISPLAY_AUTO_DECISION_OK,
            "reason": "check_conforme_confirmado",
            "confirmed_ng": False,
            "board_powered": bool(board_powered),
        }

    # O H1 é a referência que confirma que a placa entrou no fluxo correto.
    # Até ele ficar OK, qualquer leitura diferente é tratada como transição ou
    # ausência da condição esperada, nunca como NG automático.
    if reference_gate:
        return {
            "decision": DISPLAY_AUTO_DECISION_SEARCHING,
            "reason": "aguardando_referencia_h1",
            "confirmed_ng": False,
            "board_powered": bool(board_powered),
        }

    certain_mismatches = [
        item
        for item in confident_results
        if not bool(item.get("matched"))
    ]

    # POUCA LUZ é uma evidência explícita de estado intermediário anormal.
    for item in certain_mismatches:
        if str(item.get("classified")) == DISPLAY_AUTO_CLASS_LOW_LIGHT:
            return {
                "decision": DISPLAY_AUTO_DECISION_NG,
                "reason": "pouca_luz_confirmada",
                "confirmed_ng": True,
                "board_powered": bool(board_powered),
                "failed_mask_id": str(item.get("mask_id") or ""),
            }

    # Um segmento aceso quando deveria estar apagado já comprova atividade no
    # Display e é uma inconsistência direta do CHECK atual.
    for item in certain_mismatches:
        if (
            str(item.get("expected")) == DISPLAY_CHECK_STATE_OFF
            and str(item.get("classified")) == DISPLAY_CHECK_STATE_ON
        ):
            return {
                "decision": DISPLAY_AUTO_DECISION_NG,
                "reason": "aceso_quando_deveria_apagado",
                "confirmed_ng": True,
                "board_powered": True,
                "failed_mask_id": str(item.get("mask_id") or ""),
            }

    # Não declare APAGADO apenas porque tudo parece escuro. Primeiro deve haver
    # outro segmento ACESO no mesmo frame para confirmar que a placa está ligada.
    if board_powered:
        for item in certain_mismatches:
            if (
                str(item.get("expected")) == DISPLAY_CHECK_STATE_ON
                and str(item.get("classified")) == DISPLAY_CHECK_STATE_OFF
            ):
                return {
                    "decision": DISPLAY_AUTO_DECISION_NG,
                    "reason": "apagado_com_placa_ligada",
                    "confirmed_ng": True,
                    "board_powered": True,
                    "failed_mask_id": str(item.get("mask_id") or ""),
                }

    if not all_confident:
        reason = "classificacao_incerta"
    elif any(
        str(item.get("expected")) == DISPLAY_CHECK_STATE_ON
        and str(item.get("classified")) == DISPLAY_CHECK_STATE_OFF
        for item in certain_mismatches
    ):
        reason = "aguardando_evidencia_placa_ligada"
    else:
        reason = "aguardando_estado_do_check"

    return {
        "decision": DISPLAY_AUTO_DECISION_SEARCHING,
        "reason": reason,
        "confirmed_ng": False,
        "board_powered": bool(board_powered),
    }
