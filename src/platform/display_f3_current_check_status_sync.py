from __future__ import annotations

"""Sincroniza o status visual do Display F3 com o CHECK óptico atual.

A memória física do F3 existe para atravessar transições em que o classificador de
cena inteira volta temporariamente para OFF/UNKNOWN. Ela não pode, porém, manter o
nome do CHECK anterior depois que o analisador produtivo confirmou integralmente o
CHECK lógico atual.

Esta camada é somente de apresentação/memória de status. Não registra resultado,
não avança CHECK, não altera debounce e não muda os campos de autoridade física.
Funciona para qualquer CHECK atual ou futuro, sem nomes especiais.

Depois desta camada ser instalada, o instalador acopla por fora dela o contrato
`display_f3_final_check_stability`, que fecha a estabilidade produtiva usando o
estado FINAL já reconciliado. Assim nenhum wrapper interno que ainda tenha visto
OFF pode zerar a confirmação de um CHECK que terminou o frame 100% aprovado.
"""

from copy import deepcopy

import src.platform.display_f3_operational_status as operational_module
import src.platform.display_f3_physical_status_memory as memory_module
from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin


F3_CURRENT_CHECK_STATUS_SYNC_SOURCE = "f3_current_check_full_mask_status_sync"

_STALE_MEMORY_FIELDS = (
    "physical_status_memory_evidence",
    "physical_status_memory_override",
    "physical_status_memory_underlying_kind",
    "physical_status_memory_check_id",
    "physical_status_memory_check_name",
    "physical_status_memory_source",
)


def _current_context(app) -> dict | None:
    try:
        context = app._display_auto_current_context()
    except Exception:
        return None
    return context if isinstance(context, dict) else None


def _analysis_matches_context(analysis: dict | None, context: dict | None) -> bool:
    return bool(
        isinstance(analysis, dict)
        and isinstance(context, dict)
        and str(analysis.get("project_name") or "")
        == str(context.get("project_name") or "")
        and str(analysis.get("check_id") or "")
        == str(context.get("check_id") or "")
    )


def analise_confirma_check_atual_integralmente_f3(
    analysis: dict | None,
    context: dict | None,
) -> bool:
    """Aceita somente o CHECK atual aprovado com todas as máscaras ativas conformes."""
    if not _analysis_matches_context(analysis, context):
        return False
    if not bool(analysis.get("ready")) or analysis.get("approved") is not True:
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


def sincronizar_status_check_atual_f3(app) -> bool:
    """Publica o CHECK atual assim que a análise produtiva confirma 100% das máscaras.

    Deliberadamente preserva kind/allow_auto/physical_state_key e o gate de decisão
    existentes. Portanto corrige o texto/memória visuais sem criar uma nova autoridade
    para OK/NG ou avanço de sequência.
    """
    if not bool(getattr(app, "display_f3_ativo", False)):
        return False
    if bool(
        getattr(app, "_display_f3_waiting_empty_rearm", False)
        or getattr(app, "_display_f3_waiting_new_board_after_empty", False)
    ):
        return False
    if getattr(app, "display_f3_result_after_id", None) is not None:
        return False

    context = _current_context(app)
    analysis = getattr(app, "_display_auto_last_analysis", None)
    if not analise_confirma_check_atual_integralmente_f3(analysis, context):
        return False

    if bool((context or {}).get("intermittent", False)):
        try:
            temporal_ready, _seen, _total = (
                app._display_auto_update_intermittent_evidence(
                    context,
                    analysis,
                )
            )
        except Exception:
            temporal_ready = False
        if not temporal_ready:
            return False

    state = getattr(app, "_display_f3_operational_state", None)
    if not isinstance(state, dict):
        return False
    if str(state.get("kind") or "unknown").strip().lower() in {"empty", "unavailable"}:
        return False

    project_name = str((context or {}).get("project_name") or "").strip()
    check_id = str((context or {}).get("check_id") or "").strip()
    check_name = str((context or {}).get("check_name") or check_id or "CHECK").strip().upper()
    if not project_name or not check_id:
        return False

    # A memória passa a acompanhar o CHECK efetivamente observado, e não o último
    # CHECK que já terminou o debounce/registro. Isto é apresentação, não decisão.
    memory_module.lembrar_check_fisico_confirmado_f3(
        app,
        {
            "project_name": project_name,
            "check_id": check_id,
            "check_name": check_name,
        },
    )
    app._display_f3_physical_status_memory_reason = "check_atual_confirmado_100pct_mascaras"

    synchronized = deepcopy(state)
    for key in _STALE_MEMORY_FIELDS:
        synchronized.pop(key, None)

    # Não tocamos nos campos kind/allow_auto/physical_state_key/decision_allowed.
    synchronized["text"] = f"PLACA NO SUPORTE • LIGADA • DISPLAY EM {check_name}"
    synchronized["color"] = operational_module.F3_OPERATIONAL_STATUS_COLORS["check"]
    synchronized["current_check_status_sync"] = True
    synchronized["current_check_status_sync_check_id"] = check_id
    synchronized["current_check_status_sync_check_name"] = check_name
    synchronized["current_check_status_sync_source"] = F3_CURRENT_CHECK_STATUS_SYNC_SOURCE
    app._display_f3_operational_state = synchronized

    window = getattr(app, "display_f3_window", None)
    if window is not None:
        try:
            window.set_operational_reference_status(
                synchronized["text"],
                synchronized["color"],
            )
        except Exception:
            pass
    return True


_INSTALLED = False


def instalar_sincronia_status_check_atual_display_f3() -> None:
    """Instala status, estabilidade final e aprovação positiva em um frame."""
    global _INSTALLED
    if _INSTALLED:
        return

    cls = DisplayAutomaticCheckF3Mixin
    previous_process = cls._process_display_auto_check

    def process(self):
        result = previous_process(self)
        try:
            sincronizar_status_check_atual_f3(self)
        except Exception:
            # Status visual nunca pode interromper o fluxo produtivo.
            pass
        return result

    cls._process_display_auto_check = process
    cls._display_f3_current_check_status_sync_installed = True
    _INSTALLED = True

    # Deve ser literalmente a camada mais externa. Ela enxerga o estado já
    # reconciliado por todas as políticas anteriores e acumula estabilidade sem
    # depender do nome/posição do CHECK.
    from src.platform.display_f3_final_check_stability import (
        instalar_estabilidade_final_checks_display_f3,
    )

    instalar_estabilidade_final_checks_display_f3()

    # Contrato final de aprovação positiva: um único frame válido para qualquer
    # CHECK atual ou futuro. NG mantém seu debounce conservador independente.
    from src.platform.display_f3_single_frame_approval import (
        instalar_aprovacao_um_frame_display_f3,
    )

    instalar_aprovacao_um_frame_display_f3()

    # A análise visual de presença continua informativa, mas passa a aceitar um
    # vencedor relativo forte quando a iluminação derruba ambos os scores abaixo
    # do threshold absoluto. A mesma decisão é publicada no Debug Técnico.
    from src.platform.display_f3_visual_analysis_relative_fallback import (
        instalar_fallback_relativo_analise_visual_display_f3,
    )

    instalar_fallback_relativo_analise_visual_display_f3()

    # Desempate exclusivamente visual: cada CHECK é comparado, dentro da própria
    # ROI desenhada, contra sua foto e contra a foto da placa desligada. Se OFF
    # vencer claramente na mesma região, o CHECK sai apenas da disputa do status
    # ANÁLISE VISUAL. Não usa máscaras e não altera qualquer decisão produtiva.
    from src.platform.display_f3_visual_roi_disambiguation import (
        instalar_desambiguacao_roi_analise_visual_display_f3,
    )

    instalar_desambiguacao_roi_analise_visual_display_f3()

    # Autoridade final do handoff físico entre placas. O builder operacional pode
    # ser substituído pelas camadas de gabarito/fast path; por isso o rearme é
    # reaplicado aqui, já sobre a composição final, impedindo que a segunda placa
    # fique visualmente em H1 enquanto o latch da placa anterior continua ativo.
    from src.platform.display_f3_cycle_rearm_release_fix import (
        instalar_rearme_fisico_final_display_f3,
    )

    instalar_rearme_fisico_final_display_f3()

    # Nomenclatura produtiva: a ação manual é SEGREGAR PLACA. Os identificadores
    # internos antigos são mantidos apenas para compatibilidade com o runtime.
    from src.platform.display_f3_segregate_action import (
        instalar_acao_segregar_placa_display_f3,
    )

    instalar_acao_segregar_placa_display_f3()
