from __future__ import annotations

from copy import deepcopy

import src.platform.display_f3_operational_status as operational_module
import src.platform.display_f3_physical_learning_policy as physical_policy_module
from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin


F3_FAST_EXPECTED_GATE_SOURCE = "f3_expected_check_exact_template_fast_path"
F3_FAST_EXPECTED_BLOCKING_KINDS = frozenset({"off", "empty", "unavailable"})


def contexto_exige_captura_rapida_f3(context: dict | None) -> bool:
    """H1 e CHECKS transitórios podem usar o caminho rápido do F3."""
    if not isinstance(context, dict):
        return False

    try:
        if DisplayAutomaticCheckF3Mixin._display_auto_is_reference_gate(context):
            return True
    except Exception:
        pass

    try:
        return bool(
            DisplayAutomaticCheckF3Mixin._display_auto_is_transient_check(context)
        )
    except Exception:
        return False


def _estado_tem_evidencia_fisica_ligada_f3(state: dict | None) -> bool:
    """Fast path só existe depois de alguma evidência positiva de display ligado.

    OFF, suporte vazio e indisponível são autoridades absolutas. Um estado
    UNKNOWN também não libera análise por si só: ele só pode liberar quando o
    UNKNOWN existe exclusivamente por debounce de uma transição cujo candidato
    físico bruto já é algum CHECK ligado (``check:<id>``).
    """
    if not isinstance(state, dict):
        return False

    kind = str(state.get("kind") or "unknown").strip().lower()
    if kind in F3_FAST_EXPECTED_BLOCKING_KINDS:
        return False
    if kind == "check":
        return True
    if kind != "unknown":
        return False

    if not bool(state.get("physical_transition_pending")):
        return False

    pending_key = str(state.get("pending_physical_state_key") or "").strip()
    return bool(pending_key.startswith("check:"))


def liberar_gate_fisico_para_check_rapido_f3(
    state: dict | None,
    context: dict | None,
) -> dict:
    """Acelera H1/BLUE sem jamais transformar placa apagada em display ligado.

    O fast path não aprova nenhum CHECK. Ele apenas permite que o gabarito exato
    do CHECK esperado examine imediatamente um frame quando já existe evidência
    física de que algum estado ligado está presente. Isso preserva a captura de
    BLUE transitório, mas torna OFF/EMPTY estados invioláveis.
    """
    result = deepcopy(state) if isinstance(state, dict) else {}
    if bool(result.get("allow_auto")):
        return result
    if not contexto_exige_captura_rapida_f3(context):
        return result
    if not _estado_tem_evidencia_fisica_ligada_f3(result):
        return result

    result["allow_auto"] = True
    result["fast_expected_check_gate"] = True
    result["fast_expected_check_source"] = F3_FAST_EXPECTED_GATE_SOURCE
    return result


def _anexar_candidato_fisico_pendente_f3(self, state: dict | None) -> dict:
    """Expõe ao fast path qual candidato bruto está aguardando debounce."""
    result = deepcopy(state) if isinstance(state, dict) else {}
    if str(result.get("kind") or "").strip().lower() != "unknown":
        return result
    if not bool(result.get("physical_transition_pending")):
        return result

    pending_key = str(
        getattr(self, "_display_f3_physical_pending_key", "") or ""
    ).strip()
    if pending_key:
        result["pending_physical_state_key"] = pending_key
    return result


_INSTALLED = False


def instalar_gate_rapido_check_esperado_display_f3() -> None:
    """Instala captura rápida e as últimas políticas exclusivas do F3."""
    global _INSTALLED
    if _INSTALLED:
        return

    original_physical_builder = physical_policy_module._build_physical_operational_state
    original_operational_builder = operational_module._build_operational_state

    def physical_builder(self, frame, project_name: str, context: dict | None):
        state = original_physical_builder(self, frame, project_name, context)
        state = _anexar_candidato_fisico_pendente_f3(self, state)
        return liberar_gate_fisico_para_check_rapido_f3(state, context)

    physical_policy_module._build_physical_operational_state = physical_builder

    if original_operational_builder is original_physical_builder:
        operational_module._build_operational_state = physical_builder
    else:
        def operational_builder(self, frame, project_name: str, context: dict | None):
            state = original_operational_builder(self, frame, project_name, context)
            state = _anexar_candidato_fisico_pendente_f3(self, state)
            return liberar_gate_fisico_para_check_rapido_f3(state, context)

        operational_module._build_operational_state = operational_builder

    DisplayAutomaticCheckF3Mixin._display_f3_fast_expected_gate_installed = True

    # Uma única camada é responsável pelo workspace. A antiga extensão
    # display_f3_responsive_config não é mais instalada porque disputava geometria
    # e maximização com o workspace final.
    from src.platform.display_f3_workspace_ui import (
        instalar_workspace_telas_display_f3,
    )

    instalar_workspace_telas_display_f3()

    # O editor de referências usa segmento como geometria nativa. Esta camada
    # impede que a ROI visível seja descartada no OK e gere "Uma máscara necessária".
    from src.platform.display_f3_reference_mask_save_fix import (
        instalar_correcao_salvamento_mascara_referencia_display_f3,
    )

    instalar_correcao_salvamento_mascara_referencia_display_f3()

    from src.platform.display_f3_unknown_debug_fix import (
        instalar_correcao_unknown_e_debug_display_f3,
    )

    instalar_correcao_unknown_e_debug_display_f3()

    from src.platform.display_f3_live_diagnostic_trace import (
        instalar_rastreio_ao_vivo_debug_display_f3,
    )

    instalar_rastreio_ao_vivo_debug_display_f3()

    from src.platform.display_f3_debug_toggle import (
        instalar_toggle_debug_tecnico_display_f3,
    )

    instalar_toggle_debug_tecnico_display_f3()

    from src.platform.display_f3_h1_single_frame_probe import (
        instalar_captura_h1_um_frame_display_f3,
    )

    instalar_captura_h1_um_frame_display_f3()

    from src.platform.display_f3_probe_rearm_guard import (
        instalar_guard_sonda_rearme_display_f3,
    )

    instalar_guard_sonda_rearme_display_f3()

    from src.platform.display_f3_runtime_performance_guard import (
        instalar_guard_performance_runtime_display_f3,
    )

    instalar_guard_performance_runtime_display_f3()

    from src.platform.display_f3_zero_cost_debug_runtime import (
        instalar_runtime_debug_off_custo_zero_display_f3,
    )

    instalar_runtime_debug_off_custo_zero_display_f3()

    from src.platform.display_f3_reference_preview_rotation import (
        instalar_rotacao_preview_referencias_display_f3,
    )

    instalar_rotacao_preview_referencias_display_f3()

    # Performance deve ficar por fora dos wrappers históricos.
    from src.platform.display_f3_final_performance import (
        instalar_performance_final_display_f3,
    )

    instalar_performance_final_display_f3()

    # Contrato operacional permanece por fora das otimizações de runtime.
    from src.platform.display_f3_runtime_contract_fix import (
        instalar_contrato_runtime_display_f3,
    )

    instalar_contrato_runtime_display_f3()

    # A decisão física final separa presença de placa da conformidade do CHECK.
    # UNKNOWN/falso OFF pode virar PLACA LIGADA quando OFF x EMPTY confirma placa
    # no suporte e as máscaras do mesmo CHECK já mostram energia real. Isso não
    # aprova H1/BLUE/USB/AUX; apenas libera o analisador sem ficar preso no SSIM.
    from src.platform.display_f3_physical_powered_gate import (
        instalar_gate_placa_ligada_display_f3,
    )

    instalar_gate_placa_ligada_display_f3()

    # Quebra o caso circular em que OFF bloqueava o analisador que o gate acima
    # precisava consultar. A sonda direta CHECK x OFF só responde se há energia.
    from src.platform.display_f3_power_deadlock_fix import (
        instalar_correcao_deadlock_energia_display_f3,
    )

    instalar_correcao_deadlock_energia_display_f3()

    # Última camada visual/diagnóstica: remove o toggle OFF/ON e o debug ao vivo
    # da interface. ANALISAR congela um frame e processa só o CHECK atual;
    # DEBUG TÉCNICO gera a auditoria completa daquele mesmo frame sob demanda,
    # sem interferir no sequenciador produtivo.
    from src.platform.display_f3_manual_snapshot_debug import (
        instalar_analise_manual_snapshot_display_f3,
    )

    instalar_analise_manual_snapshot_display_f3()

    # A janela final de debug é maximizada como os workspaces F3 e não renderiza
    # milhares de linhas. O relatório completo fica somente no botão COPIAR DEBUG.
    from src.platform.display_f3_snapshot_debug_lightweight_ui import (
        instalar_debug_snapshot_leve_display_f3,
    )

    instalar_debug_snapshot_leve_display_f3()

    # A sonda exata de H1/BLUE já calcula a classificação de cada máscara. Publica
    # essa mesma análise no overlay para que um CHECK reconhecido nunca permaneça
    # cinza apenas porque o gate físico bloqueou o analisador produtivo naquele frame.
    from src.platform.display_f3_probe_visual_sync import (
        instalar_sincronia_visual_sonda_display_f3,
    )

    instalar_sincronia_visual_sonda_display_f3()

    # Última autoridade do ciclo físico: se a sonda exata confirmou integralmente
    # o H1, ela pode liberar o registro daquele CHECK mesmo quando a comparação de
    # cena ainda prefere OFF. Após H1, a placa permanece LIGADA/AGUARDANDO até
    # EMPTY/rearme, sem liberar OK/NG dos CHECKS seguintes por memória de estado.
    from src.platform.display_f3_powered_cycle_latch import (
        instalar_latch_ciclo_energizado_display_f3,
    )

    instalar_latch_ciclo_energizado_display_f3()

    # Autoridade final apenas de APRESENTAÇÃO: se o analisador produtivo confirmou
    # 100% das máscaras do CHECK lógico atual, o status não pode continuar exibindo
    # o CHECK anterior memorizado. Vale para USB, AUX e qualquer CHECK futuro sem
    # nomes/índices especiais e não altera gate, debounce ou registro de resultado.
    from src.platform.display_f3_current_check_status_sync import (
        instalar_sincronia_status_check_atual_display_f3,
    )

    instalar_sincronia_status_check_atual_display_f3()
    _INSTALLED = True
