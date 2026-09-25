from __future__ import annotations

"""Contrato final do runtime Display F3.

Esta camada corrige regras operacionais que não podem ser quebradas por
otimizações posteriores:

1. As máscaras do CHECK atual são diagnóstico óptico contínuo e nunca ficam
   inativas por causa do estado físico da placa. O estado físico pode bloquear
   avanço/NG, mas não pode impedir classificação ou overlay.
2. Um falso OFF do classificador global pode ser reconciliado pelo CHECK lógico
   atual somente quando a própria análise aprovada comprova segmento ACESO. Isso
   vale para qualquer CHECK presente ou futuro, sem regras por nome/posição.
3. A janela Configurar deve conservar o contrato explícito de construtor
   ``root/repository/frame_provider/on_change/on_close`` mesmo após o lazy-load.

O módulo é exclusivo do F3 e é instalado depois da camada final de performance.
"""

from copy import deepcopy

import src.platform.display_f3_operational_status as operational_module
import src.platform.display_f3_physical_learning_policy as physical_policy_module


F3_MASK_CONFIRMED_SOURCE = "f3_current_check_confirmed_by_live_masks"
F3_DECISION_ALLOWED_KEY = "_display_f3_physical_decision_allowed"
F3_MASK_LIVE_KEY = "mask_analysis_active"
F3_MASK_CONFIRMABLE_KINDS = frozenset({"unknown", "powered", "off"})


def preparar_estado_para_mascaras_ativas_f3(state: dict | None) -> dict:
    """Libera somente o caminho óptico e preserva a autoridade física real."""
    result = deepcopy(state) if isinstance(state, dict) else {}
    decision_allowed = bool(result.get("allow_auto"))
    result[F3_DECISION_ALLOWED_KEY] = decision_allowed
    result[F3_MASK_LIVE_KEY] = True

    # O wrapper físico legado usa allow_auto como condição para entrar no
    # analisador. Aqui ele significa apenas "pode executar a leitura óptica".
    # Ao final do ciclo o valor público é restaurado para decision_allowed.
    result["allow_auto"] = True
    return result


def restaurar_autoridade_fisica_f3(state: dict | None) -> dict:
    result = deepcopy(state) if isinstance(state, dict) else {}
    if F3_DECISION_ALLOWED_KEY in result:
        result["allow_auto"] = bool(result.get(F3_DECISION_ALLOWED_KEY))
    result[F3_MASK_LIVE_KEY] = True
    return result


def _analysis_matches_context(analysis: dict | None, context: dict | None) -> bool:
    if not isinstance(analysis, dict) or not isinstance(context, dict):
        return False
    return (
        str(analysis.get("project_name") or "")
        == str(context.get("project_name") or "")
        and str(analysis.get("check_id") or "")
        == str(context.get("check_id") or "")
    )


def _analysis_confirms_current_check(app) -> tuple[bool, dict | None]:
    try:
        context = app._display_auto_current_context()
    except Exception:
        context = None
    analysis = getattr(app, "_display_auto_last_analysis", None)
    confirmed = bool(
        _analysis_matches_context(analysis, context)
        and analysis.get("ready")
        and analysis.get("approved") is True
    )
    return confirmed, context


def _analysis_has_positive_on_evidence(analysis: dict | None) -> bool:
    """Confirma que o frame contém pelo menos um segmento esperado realmente ACESO.

    Esta prova adicional é obrigatória quando o matcher global chamou o frame de
    OFF. Assim um CHECK composto somente por segmentos APAGADOS nunca pode, por
    si só, contradizer a referência física de placa desligada.
    """
    if not isinstance(analysis, dict):
        return False

    try:
        if int(analysis.get("positive_on_matched_count", 0) or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass

    for item in analysis.get("mask_results") or []:
        if not isinstance(item, dict):
            continue
        expected = str(item.get("expected") or "").strip().lower()
        classified = str(item.get("classified") or "").strip().lower()
        if expected == "on" and classified == "on" and bool(item.get("matched")):
            return True
    return False


def _state_accepts_mask_confirmation(
    state: dict | None,
    analysis: dict | None = None,
) -> bool:
    """Resolve qualquer CHECK atual sem depender de H1/BLUE/USB/AUX.

    UNKNOWN e POWERED podem ser resolvidos por uma análise 100% conforme do
    CHECK lógico atual. OFF também pode ser reconciliado, mas somente quando a
    mesma análise possui evidência positiva de pelo menos um segmento ACESO.
    EMPTY e UNAVAILABLE permanecem absolutos e nunca são promovidos por máscara.
    """
    if not isinstance(state, dict):
        return False
    kind = str(state.get("kind") or "unknown").strip().lower()
    if kind not in F3_MASK_CONFIRMABLE_KINDS:
        return False
    if kind == "off":
        return _analysis_has_positive_on_evidence(analysis)
    return True


def _state_from_mask_confirmation(state: dict, context: dict) -> dict:
    result = deepcopy(state)
    check_id = str(context.get("check_id") or "")
    check_name = str(context.get("check_name") or check_id or "CHECK").strip().upper()
    result.update(
        {
            "kind": "check",
            "text": f"PLACA NO SUPORTE • LIGADA • DISPLAY EM {check_name}",
            "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["check"],
            "check_id": check_id,
            "check_name": check_name,
            "physical_state_key": f"check:{check_id}",
            "physical_matches_expected_check": True,
            "powered_board_confirmed": True,
            "allow_auto": True,
            F3_DECISION_ALLOWED_KEY: True,
            F3_MASK_LIVE_KEY: True,
            "source": F3_MASK_CONFIRMED_SOURCE,
            "mask_confirmed_physical_state": True,
        }
    )
    return result


def _blocked_preview_text(state: dict, context: dict | None) -> str:
    kind = str(state.get("kind") or "unknown").strip().lower()
    if kind == "off":
        return "AUTO • placa desligada • máscaras em leitura"
    if kind == "empty":
        return "AUTO • aguardando placa no suporte • máscaras em leitura"
    if kind == "powered":
        expected = str((context or {}).get("check_name") or "CHECK").strip().upper()
        return f"AUTO • placa ligada • aguardando {expected} • máscaras em leitura"
    if kind == "check":
        expected = str((context or {}).get("check_name") or "CHECK").strip().upper()
        actual = str(state.get("check_name") or "CHECK").strip().upper()
        return f"AUTO • aguardando {expected} • display físico em {actual} • máscaras em leitura"
    if kind == "unavailable":
        return "AUTO • referências físicas indisponíveis • máscaras em leitura"
    return "AUTO • identificando estado físico • máscaras em leitura"


def _install_configuration_constructor_contract() -> None:
    """Repara o TypeError introduzido pela combinação presença + lazy-load."""
    import src.platform.display_project_config as config_module
    import src.platform.display_production_f3 as production_module
    import src.platform.display_visual_reference_status as visual_module

    base_cls = config_module.DisplayProjectConfigWindow
    if not bool(getattr(base_cls, "_display_f3_explicit_init_contract_fixed", False)):
        current_init = base_cls.__init__

        def init(
            self,
            root,
            repository,
            frame_provider,
            heavy_executor=None,
            on_change=None,
            on_close=None,
        ):
            return current_init(
                self,
                root=root,
                repository=repository,
                frame_provider=frame_provider,
                heavy_executor=heavy_executor,
                on_change=on_change,
                on_close=on_close,
            )

        base_cls.__init__ = init
        base_cls._display_f3_explicit_init_contract_fixed = True

    presence_cls = visual_module.DisplayProjectConfigPresenceWindow
    if not bool(getattr(presence_cls, "_display_f3_on_change_contract_fixed", False)):
        current_presence_init = presence_cls.__init__

        def presence_init(
            self,
            root,
            repository,
            *,
            frame_provider=None,
            heavy_executor=None,
            on_change=None,
            on_close=None,
        ):
            current_presence_init(
                self,
                root,
                repository,
                frame_provider=frame_provider,
                heavy_executor=heavy_executor,
                on_close=on_close,
            )
            # O refresh inicial da camada de performance é executado por after(),
            # portanto on_change já está correto antes de qualquer callback.
            self.on_change = on_change

        presence_cls.__init__ = presence_init
        presence_cls._display_f3_on_change_contract_fixed = True

    # Garante que o botão CONFIGURAR resolve a classe corrigida, inclusive porque
    # display_production_f3 importou a classe original por valor.
    production_module.DisplayProjectConfigWindow = presence_cls


def _install_masks_always_live_gate() -> None:
    from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin
    from src.platform.display_production_f3 import DisplayProductionF3Mixin

    cls = DisplayAutomaticCheckF3Mixin
    if bool(getattr(cls, "_display_f3_masks_always_live_contract_fixed", False)):
        return

    original_builder = physical_policy_module._build_physical_operational_state

    def physical_builder(self, frame, project_name: str, context: dict | None):
        state = original_builder(self, frame, project_name, context)

        # Se o frame anterior confirmou integralmente o MESMO CHECK, reutilizamos
        # essa evidência já no início do frame seguinte. Isso é o que permite que
        # a estabilidade acumule 1/2 -> 2/2 em vez de o falso OFF zerá-la sempre.
        latch = getattr(self, "_display_f3_mask_confirmed_signature", None)
        expected_signature = (
            str(project_name or ""),
            str((context or {}).get("check_id") or ""),
        )
        analysis = getattr(self, "_display_auto_last_analysis", None)
        previous_confirmed = bool(
            latch == expected_signature
            and expected_signature[1]
            and _analysis_matches_context(analysis, context)
            and isinstance(analysis, dict)
            and analysis.get("ready")
            and analysis.get("approved") is True
            and _state_accepts_mask_confirmation(state, analysis)
        )
        if previous_confirmed:
            state = _state_from_mask_confirmation(state, context or {})
            self._display_f3_mask_confirmed_signature = None

        return preparar_estado_para_mascaras_ativas_f3(state)

    physical_policy_module._build_physical_operational_state = physical_builder

    # O builder operacional pode ser consultado por diagnósticos paralelos. Ele
    # permanece físico/verdadeiro; somente o gate interno recebe allow_auto=True
    # para não desligar o analisador das máscaras.

    original_register = DisplayProductionF3Mixin.registrar_resultado_check_display_f3

    def register_result(self, aprovado: bool = True):
        state = getattr(self, "_display_f3_operational_state", None)
        allowed = bool(
            isinstance(state, dict)
            and state.get(F3_DECISION_ALLOWED_KEY, state.get("allow_auto", False))
        )
        if allowed:
            return original_register(self, aprovado)

        # CHECK confirmado pelas próprias máscaras é evidência positiva válida.
        # A regra é genérica: nenhum nome ou índice de CHECK aparece aqui.
        kind = str((state or {}).get("kind") or "unknown").strip().lower()
        analysis = getattr(self, "_display_auto_last_analysis", None)
        confirmed, context = _analysis_confirms_current_check(self)
        if (
            _state_accepts_mask_confirmation(state, analysis)
            and confirmed
            and isinstance(context, dict)
        ):
            promoted = _state_from_mask_confirmation(state or {}, context)
            promoted["physical_kind_before_mask_confirmation"] = kind
            self._display_f3_operational_state = promoted
            return original_register(self, aprovado)

        runtime = getattr(self, "display_check_runtime", None)
        snapshot = runtime.snapshot() if runtime is not None else {}
        return {
            "event": "physical_gate_blocked",
            "snapshot": snapshot,
            "approved": bool(aprovado),
        }

    DisplayProductionF3Mixin.registrar_resultado_check_display_f3 = register_result

    original_process = cls._process_display_auto_check

    def process(self):
        result = original_process(self)
        state = getattr(self, "_display_f3_operational_state", None)
        if not isinstance(state, dict):
            return result

        decision_allowed = bool(
            state.get(F3_DECISION_ALLOWED_KEY, state.get("allow_auto", False))
        )
        analysis = getattr(self, "_display_auto_last_analysis", None)
        confirmed, context = _analysis_confirms_current_check(self)

        if (
            not decision_allowed
            and _state_accepts_mask_confirmation(state, analysis)
            and confirmed
            and isinstance(context, dict)
        ):
            previous_kind = str(state.get("kind") or "unknown").strip().lower()
            state = _state_from_mask_confirmation(state, context)
            state["physical_kind_before_mask_confirmation"] = previous_kind
            self._display_f3_mask_confirmed_signature = (
                str(context.get("project_name") or ""),
                str(context.get("check_id") or ""),
            )
            decision_allowed = True
            window = getattr(self, "display_f3_window", None)
            if window is not None:
                try:
                    window.set_operational_reference_status(
                        state.get("text", ""),
                        state.get("color", "#7DD3FC"),
                    )
                except Exception:
                    pass

        # Restaura a semântica pública do gate depois que o analisador rodou.
        state = restaurar_autoridade_fisica_f3(state)
        if confirmed and str(state.get("source") or "") == F3_MASK_CONFIRMED_SOURCE:
            state["allow_auto"] = True
            state[F3_DECISION_ALLOWED_KEY] = True
        self._display_f3_operational_state = state

        if not decision_allowed:
            # Nunca apaga _display_auto_last_analysis: overlay, contagem e status
            # das máscaras precisam continuar atualizados em OFF/EMPTY/UNKNOWN.
            self._display_auto_last_decision = None
            self._display_auto_stable_frames = 0
            try:
                self._display_auto_set_preview_status(
                    _blocked_preview_text(state, context),
                    "#FDE68A",
                )
            except Exception:
                pass
        return result

    cls._process_display_auto_check = process
    cls._display_f3_masks_always_live_contract_fixed = True


def instalar_contrato_runtime_display_f3() -> None:
    """Instala a última política F3 depois de performance e demais extensões."""
    _install_configuration_constructor_contract()
    _install_masks_always_live_gate()
