from __future__ import annotations

from copy import deepcopy

import src.platform.display_f3_check_transition_guard as transition_module
import src.platform.display_f3_operational_status as operational_module
from src.platform.display_auto_check_analyzer import DisplayAutomaticCheckAnalyzer
from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin


F3_TRANSIENT_DISPLAY_NAMES = frozenset({"BLUE", "BLUETOOTH", "BT"})
# O BLUE pisca fisicamente. Com preview a 45 ms, 12 frames seguram o estado por
# cerca de meio segundo, suficiente para atravessar a fase escura sem chamar a
# placa de desligada. Um novo CHECK real sempre substitui o hold imediatamente.
F3_TRANSIENT_HOLD_FRAMES = 12
# Suporte vazio é o estado de rearmamento do ciclo. Dois frames consecutivos
# evitam um falso vazio isolado, mas reduzem a latência frente ao debounce físico
# legado de três frames.
F3_EMPTY_STABLE_FRAMES = 2
F3_TERMINAL_EVENTS = frozenset({"plate_ok", "plate_ng", "plate_discarded"})

_LEGACY_PHYSICAL_STABILIZER = transition_module._estado_fisico_estavel


def _normalized_tokens(value: str) -> set[str]:
    normalized = " ".join(
        str(value or "").strip().upper().replace("-", " ").replace("_", " ").split()
    )
    return set(normalized.split())


def _is_transient_check_state(state: dict | None) -> bool:
    if not isinstance(state, dict) or str(state.get("kind") or "") != "check":
        return False
    name = str(state.get("check_name") or state.get("text") or "")
    return bool(_normalized_tokens(name).intersection(F3_TRANSIENT_DISPLAY_NAMES))


def _clear_transient_hold(app) -> None:
    app._display_f3_transient_hold_state = None
    app._display_f3_transient_hold_frames = 0


def _remember_immediate_check(app, raw_state: dict) -> dict:
    state = dict(raw_state)
    key = str(state.get("physical_state_key") or state.get("check_id") or "check")

    # CHECKs ligados não precisam do debounce físico de três frames: a própria
    # referência visual já confirmou o estado e a análise óptica ainda possui
    # seu debounce de OK/NG. Isto é essencial para H1 e para estados transitórios.
    app._display_f3_physical_stable_key = key
    app._display_f3_physical_stable_state = dict(state)
    app._display_f3_physical_pending_key = ""
    app._display_f3_physical_pending_frames = 0

    if _is_transient_check_state(state):
        app._display_f3_transient_hold_state = dict(state)
        app._display_f3_transient_hold_frames = F3_TRANSIENT_HOLD_FRAMES
    else:
        _clear_transient_hold(app)
    return state


def _stabilize_empty_fast(app, raw_state: dict) -> dict:
    state = dict(raw_state)
    key = str(state.get("physical_state_key") or "empty")
    stable_key = str(getattr(app, "_display_f3_physical_stable_key", "") or "")
    if key == stable_key:
        app._display_f3_physical_pending_key = ""
        app._display_f3_physical_pending_frames = 0
        app._display_f3_physical_stable_state = dict(state)
        return state

    pending_key = str(getattr(app, "_display_f3_physical_pending_key", "") or "")
    pending_frames = int(getattr(app, "_display_f3_physical_pending_frames", 0) or 0)
    pending_frames = pending_frames + 1 if pending_key == key else 1
    app._display_f3_physical_pending_key = key
    app._display_f3_physical_pending_frames = pending_frames

    if pending_frames < F3_EMPTY_STABLE_FRAMES:
        return {
            "kind": "unknown",
            "text": "IDENTIFICANDO...",
            "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"],
            "allow_auto": False,
            "board_references_complete": bool(
                state.get("board_references_complete")
            ),
            "physical_transition_pending": True,
            "pending_target": "empty",
        }

    app._display_f3_physical_stable_key = key
    app._display_f3_physical_stable_state = dict(state)
    app._display_f3_physical_pending_key = ""
    app._display_f3_physical_pending_frames = 0
    return state


def estabilizar_estado_fisico_rapido_f3(app, raw_state: dict) -> dict:
    """Debounce físico assimétrico para o Display.

    - CHECK ligado: entra imediatamente para a análise não perder H1/BLUE.
    - BLUE/BT: mantém o último estado durante a fase escura do pisca.
    - EMPTY: confirma em dois frames e nunca é mascarado pelo hold.
    - OFF normal: preserva o debounce legado de três frames.
    """
    state = dict(raw_state or {})
    kind = str(state.get("kind") or "unknown")

    if kind == "check":
        return _remember_immediate_check(app, state)

    if kind == "empty":
        # Retirar a placa é o evento que rearma um novo ciclo. Cancelamos a
        # memória do BLUE e confirmamos o suporte vazio com apenas dois frames.
        _clear_transient_hold(app)
        return _stabilize_empty_fast(app, state)

    hold_frames = int(getattr(app, "_display_f3_transient_hold_frames", 0) or 0)
    hold_state = getattr(app, "_display_f3_transient_hold_state", None)
    if kind in {"off", "unknown", "unavailable"} and hold_frames > 0 and isinstance(
        hold_state, dict
    ):
        app._display_f3_transient_hold_frames = hold_frames - 1
        held = deepcopy(hold_state)
        held["transient_hold"] = True
        held["raw_kind_during_hold"] = kind
        held["hold_frames_remaining"] = hold_frames - 1
        return held

    if hold_frames <= 0:
        _clear_transient_hold(app)
    return _LEGACY_PHYSICAL_STABILIZER(app, state)


def promover_suporte_vazio_rapido_f3(
    matcher,
    frame,
    project_name: str,
    fallback_state: dict,
) -> dict:
    """Resolve EMPTY contra a referência física OFF antes dos CHECKs.

    A referência de suporte vazio não precisa vencer cada estado ligado do
    Display. Se ela está acima do próprio threshold e vence diretamente a
    referência de placa presente/desligada no mesmo domínio, não há placa no
    suporte. Isso remove o caso em que CHECKs antigos deixavam o F3 preso em
    IDENTIFICANDO mesmo com o suporte fisicamente vazio.
    """
    state = dict(fallback_state or {})
    if str(state.get("kind") or "") != "unknown":
        return state

    try:
        import src.platform.display_f3_physical_state_fix as physical_module

        prepared, observed, board_complete = physical_module._prepare_candidates(
            matcher,
            frame,
            project_name,
        )
    except Exception:
        return state

    if observed is None:
        return state
    by_key = {str(item.get("key") or ""): item for item in prepared}
    empty = by_key.get("empty")
    off = by_key.get("off")
    if not isinstance(empty, dict) or not bool(empty.get("matched")):
        return state
    if not isinstance(off, dict):
        return state

    try:
        comparison = physical_module.comparar_referencias_no_mesmo_dominio_f3(
            observed,
            empty["reference"],
            off["reference"],
            empty["metadata"],
            off["metadata"],
        )
    except Exception:
        return state

    if str(comparison.get("winner") or "") != "left":
        return state

    promoted = physical_module._state_from_candidate(
        empty,
        board_complete,
        len(prepared),
    )
    promoted["fast_empty"] = True
    promoted["empty_vs_off"] = dict(comparison)
    return promoted


def armar_rearme_por_suporte_vazio_f3(app) -> None:
    """Bloqueia uma nova placa até a câmera confirmar suporte vazio."""
    app._display_f3_waiting_empty_rearm = True
    app._display_f3_last_recognized_check_id = ""
    app._display_f3_last_recognized_check_name = ""
    app._display_f3_physical_stable_key = ""
    app._display_f3_physical_stable_state = None
    app._display_f3_physical_pending_key = ""
    app._display_f3_physical_pending_frames = 0
    app._display_f3_overlay_analysis_cache_key = None
    app._display_f3_overlay_analysis_cache = None
    _clear_transient_hold(app)

    clear_gate = getattr(app, "_display_auto_clear_manual_entry_gate", None)
    if callable(clear_gate):
        try:
            clear_gate()
        except Exception:
            pass
    reset = getattr(app, "_reset_display_auto_stability", None)
    if callable(reset):
        try:
            reset(transition=False)
        except TypeError:
            try:
                reset()
            except Exception:
                pass
        except Exception:
            pass


def aplicar_gate_rearme_ciclo_f3(app, state: dict) -> dict:
    """Só rearma o automático depois de PLACA FORA DO SUPORTE confirmado."""
    result = dict(state or {})
    if not bool(getattr(app, "_display_f3_waiting_empty_rearm", False)):
        return result

    kind = str(result.get("kind") or "unknown")
    if kind == "empty":
        app._display_f3_waiting_empty_rearm = False
        app._display_f3_last_recognized_check_id = ""
        app._display_f3_last_recognized_check_name = ""
        result["cycle_rearmed"] = True
        result["allow_auto"] = False
        reset = getattr(app, "_reset_display_auto_stability", None)
        if callable(reset):
            try:
                reset(transition=False)
            except TypeError:
                try:
                    reset()
                except Exception:
                    pass
            except Exception:
                pass

        release_ng = getattr(app, "_liberar_evidencia_ng_display_f3", None)
        if callable(release_ng):
            try:
                release_ng()
            except Exception:
                pass
        return result

    # Mesmo que a placa analisada continue mostrando exatamente H1/BLUE/etc.,
    # nenhuma análise oficial pode começar novamente antes de EMPTY.
    result["allow_auto"] = False
    result["cycle_rearm_waiting"] = True
    return result


def _analysis_matches_context(analysis, context: dict) -> bool:
    return bool(
        isinstance(analysis, dict)
        and str(analysis.get("project_name") or "")
        == str(context.get("project_name") or "")
        and str(analysis.get("check_id") or "")
        == str(context.get("check_id") or "")
    )


def atualizar_classificacao_overlay_f3(app):
    """Atualiza apenas as cores da ROI, sem poder avançar/reprovar um CHECK.

    O gate físico decide se o CHECK pode ser registrado. A classificação óptica
    das máscaras é independente e continua rodando para manter verde/vermelho/
    amarelo na câmera ao vivo mesmo quando o gate está bloqueado.
    """
    if not bool(getattr(app, "display_f3_ativo", False)):
        return None

    try:
        if bool(app._display_auto_configuration_open()):
            return None
    except Exception:
        pass

    frame = getattr(app, "camera_frame_atual", None)
    if frame is None or getattr(frame, "size", 0) == 0:
        return None

    try:
        context = app._display_auto_current_context()
    except Exception:
        context = None
    if not isinstance(context, dict):
        return None

    current_analysis = getattr(app, "_display_auto_last_analysis", None)
    if _analysis_matches_context(current_analysis, context):
        return current_analysis

    try:
        frame_token = app._display_auto_frame_token(frame)
    except Exception:
        frame_token = ("object", id(frame))
    cache_key = (
        str(context.get("project_name") or ""),
        str(context.get("check_id") or ""),
        frame_token,
    )
    cached_key = getattr(app, "_display_f3_overlay_analysis_cache_key", None)
    cached_analysis = getattr(app, "_display_f3_overlay_analysis_cache", None)
    if cache_key == cached_key and _analysis_matches_context(cached_analysis, context):
        # O gate pode limpar _display_auto_last_analysis a cada frame bloqueado.
        # Reaproveitamos a classificação do mesmo frame sem recalcular tudo.
        app._display_auto_last_analysis = cached_analysis
        return cached_analysis

    repository = getattr(app, "display_project_repository", None)
    if repository is None:
        return None
    analyzer = getattr(app, "_display_auto_analyzer", None)
    if analyzer is None or getattr(analyzer, "repository", None) is not repository:
        # Não usa _rebuild_display_auto_analyzer(), pois esse método também
        # reinicia o debounce oficial. Aqui queremos somente classificação.
        analyzer = DisplayAutomaticCheckAnalyzer(repository)
        app._display_auto_analyzer = analyzer

    try:
        rotation = int(app._obter_rotacao_visual_display_f3())
    except Exception:
        rotation = 0

    analysis = analyzer.analyze(
        frame=frame,
        project_name=str(context.get("project_name") or ""),
        check_id=str(context.get("check_id") or ""),
        visual_rotation=rotation,
    )
    if not isinstance(analysis, dict):
        return None

    app._display_f3_overlay_analysis_cache_key = cache_key
    app._display_f3_overlay_analysis_cache = analysis
    app._display_auto_last_analysis = analysis
    return analysis


def atualizar_rearme_durante_resultado_f3(app):
    """Continua procurando EMPTY durante o card final de OK/NG/descartada."""
    if not bool(getattr(app, "_display_f3_waiting_empty_rearm", False)):
        return None
    if getattr(app, "display_f3_result_after_id", None) is None:
        return None

    frame = getattr(app, "camera_frame_atual", None)
    repository = getattr(app, "display_project_repository", None)
    window = getattr(app, "display_f3_window", None)
    if frame is None or getattr(frame, "size", 0) == 0 or repository is None:
        return None

    try:
        project_name = str(repository.obter_projeto_ativo() or "")
    except Exception:
        project_name = ""
    if not project_name:
        return None

    try:
        context = app._display_auto_current_context()
        state = operational_module._build_operational_state(
            app,
            frame,
            project_name,
            context,
        )
    except Exception:
        return None

    app._display_f3_operational_state = dict(state)
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
    return state


def _install_fast_empty_classifier() -> None:
    if bool(getattr(transition_module, "_display_f3_fast_empty_classifier_installed", False)):
        return

    base_classifier = transition_module.classificar_estado_fisico_referencias_f3

    def classifier(matcher, frame, project_name: str):
        fallback = base_classifier(matcher, frame, project_name)
        return promover_suporte_vazio_rapido_f3(
            matcher,
            frame,
            project_name,
            fallback,
        )

    transition_module.classificar_estado_fisico_referencias_f3 = classifier
    transition_module._display_f3_fast_empty_classifier_installed = True


def _install_cycle_rearm_gate() -> None:
    if bool(getattr(operational_module, "_display_f3_cycle_rearm_gate_installed", False)):
        return

    base_build = operational_module._build_operational_state

    def build(self, frame, project_name: str, context: dict | None):
        state = base_build(self, frame, project_name, context)
        return aplicar_gate_rearme_ciclo_f3(self, state)

    operational_module._build_operational_state = build
    operational_module._display_f3_cycle_rearm_gate_installed = True

    # O latch nasce somente em eventos terminais. check_advanced não rearma,
    # porque ainda é a mesma placa atravessando a sequência normal.
    from src.platform.display_production_f3 import DisplayProductionF3Mixin

    cls = DisplayProductionF3Mixin
    if bool(getattr(cls, "_display_f3_cycle_rearm_methods_installed", False)):
        return

    original_register = cls.registrar_resultado_check_display_f3
    original_discard = cls.descartar_placa_display_f3

    def register(self, aprovado: bool = True):
        event = original_register(self, aprovado)
        if isinstance(event, dict) and str(event.get("event") or "") in F3_TERMINAL_EVENTS:
            armar_rearme_por_suporte_vazio_f3(self)
        return event

    def discard(self):
        event = original_discard(self)
        if isinstance(event, dict) and str(event.get("event") or "") in F3_TERMINAL_EVENTS:
            armar_rearme_por_suporte_vazio_f3(self)
        return event

    cls.registrar_resultado_check_display_f3 = register
    cls.descartar_placa_display_f3 = discard
    cls._display_f3_cycle_rearm_methods_installed = True


_DISPLAY_F3_LIVE_RUNTIME_FIX_INSTALLED = False


def instalar_runtime_ao_vivo_display_f3() -> None:
    """Instala resposta rápida/overlay/rearmamento somente no Display F3."""
    global _DISPLAY_F3_LIVE_RUNTIME_FIX_INSTALLED
    if _DISPLAY_F3_LIVE_RUNTIME_FIX_INSTALLED:
        return

    # O guard operacional consulta esta função a cada preview. Ao substituir aqui,
    # CHECKs ligados entram imediatamente, BLUE ganha histerese e EMPTY confirma
    # mais rápido.
    transition_module._estado_fisico_estavel = estabilizar_estado_fisico_rapido_f3
    _install_fast_empty_classifier()
    _install_cycle_rearm_gate()

    cls = DisplayAutomaticCheckF3Mixin
    if not bool(getattr(cls, "_display_f3_live_runtime_fix_installed", False)):
        gated_process = cls._process_display_auto_check

        def process(self):
            # Durante o card final o runtime oficial pausa a análise, mas a câmera
            # continua verificando se o operador já retirou a placa.
            try:
                atualizar_rearme_durante_resultado_f3(self)
            except Exception:
                pass

            result = gated_process(self)

            if bool(getattr(self, "_display_f3_waiting_empty_rearm", False)):
                try:
                    self._display_auto_set_preview_status(
                        "AUTO • retire a placa • aguardando PLACA FORA DO SUPORTE",
                        "#FDE68A",
                    )
                except Exception:
                    pass

            try:
                atualizar_classificacao_overlay_f3(self)
            except Exception:
                # Overlay nunca pode derrubar o fluxo operacional.
                pass
            return result

        cls._process_display_auto_check = process
        cls._display_f3_live_runtime_fix_installed = True

    _DISPLAY_F3_LIVE_RUNTIME_FIX_INSTALLED = True
