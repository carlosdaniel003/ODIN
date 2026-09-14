from __future__ import annotations

import src.platform.display_f3_live_runtime_fix as live_module
import src.platform.display_f3_operational_status as operational_module


F3_REARM_EMPTY_STABLE_FRAMES = 2
F3_NEW_BOARD_STABLE_FRAMES = 2


def detectar_suporte_vazio_exclusivo_rearme_f3(
    matcher,
    frame,
    project_name: str,
) -> dict | None:
    """Detecta EMPTY para rearmamento sem deixar CHECKs concorrerem com o vazio.

    Depois de um resultado terminal não precisamos descobrir qual CHECK está na
    imagem: precisamos somente confirmar que a placa saiu fisicamente do suporte.
    Por isso a decisão usa apenas a referência de suporte vazio contra a referência
    de placa presente/desligada, no mesmo domínio visual já usado pelo F3.
    """
    fallback = {
        "kind": "unknown",
        "text": "IDENTIFICANDO...",
        "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"],
        "allow_auto": False,
    }
    try:
        state = live_module.promover_suporte_vazio_rapido_f3(
            matcher,
            frame,
            project_name,
            fallback,
        )
    except Exception:
        return None

    if str((state or {}).get("kind") or "") != "empty":
        return None

    result = dict(state)
    result["rearm_empty_probe"] = True
    result["allow_auto"] = False
    return result


def _reset_auto_after_physical_transition(app) -> None:
    app._display_f3_overlay_analysis_cache_key = None
    app._display_f3_overlay_analysis_cache = None
    app._display_f3_last_recognized_check_id = ""
    app._display_f3_last_recognized_check_name = ""

    # O último CHECK aprovado pertence à placa anterior. Ele permanece válido
    # durante o card final e enquanto a mesma placa continua no suporte, mas deve
    # desaparecer assim que EMPTY foi confirmado e o ciclo físico realmente mudou.
    app._display_f3_physical_status_memory_project = ""
    app._display_f3_physical_status_memory_check_id = ""
    app._display_f3_physical_status_memory_check_name = ""
    app._display_f3_physical_status_memory_reason = "suporte_vazio_confirmado"

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


def _concluir_passagem_por_suporte_vazio_f3(app) -> None:
    """Prepara um ciclo realmente novo depois que EMPTY foi confirmado."""
    app._display_f3_rearm_empty_frames = 0
    app._display_f3_waiting_new_board_after_empty = True
    app._display_f3_new_board_frames = 0
    app._display_f3_physical_stable_key = "empty"
    app._display_f3_physical_stable_state = {
        "kind": "empty",
        "physical_state_key": "empty",
        "allow_auto": False,
    }
    app._display_f3_physical_pending_key = ""
    app._display_f3_physical_pending_frames = 0

    runtime = getattr(app, "display_check_runtime", None)
    restart = getattr(runtime, "reiniciar_placa", None)
    if callable(restart):
        try:
            restart()
        except Exception:
            pass

    _reset_auto_after_physical_transition(app)


def aplicar_rearme_fisico_dedicado_f3(
    app,
    matcher,
    frame,
    project_name: str,
    fallback_state: dict,
) -> dict:
    """Executa o handoff terminal -> EMPTY -> nova placa sem reusar a anterior."""
    state = dict(fallback_state or {})

    if bool(getattr(app, "_display_f3_waiting_empty_rearm", False)):
        empty = detectar_suporte_vazio_exclusivo_rearme_f3(
            matcher,
            frame,
            project_name,
        )
        if empty is None:
            app._display_f3_rearm_empty_frames = 0
            state["allow_auto"] = False
            state["cycle_rearm_waiting"] = True
            return state

        frames = int(getattr(app, "_display_f3_rearm_empty_frames", 0) or 0) + 1
        app._display_f3_rearm_empty_frames = frames
        if frames < F3_REARM_EMPTY_STABLE_FRAMES:
            return {
                "kind": "unknown",
                "text": (
                    "CONFIRMANDO PLACA FORA DO SUPORTE • "
                    f"{frames}/{F3_REARM_EMPTY_STABLE_FRAMES}"
                ),
                "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"],
                "allow_auto": False,
                "board_references_complete": bool(
                    empty.get("board_references_complete")
                ),
                "cycle_rearm_waiting": True,
                "rearm_empty_pending": True,
                "rearm_empty_pending_frames": frames,
            }

        confirmed = dict(empty)
        confirmed["rearm_empty_confirmed"] = True
        confirmed["rearm_empty_frames"] = frames
        result = live_module.aplicar_gate_rearme_ciclo_f3(app, confirmed)
        if not bool(getattr(app, "_display_f3_waiting_empty_rearm", False)):
            _concluir_passagem_por_suporte_vazio_f3(app)
        return result

    if bool(getattr(app, "_display_f3_waiting_new_board_after_empty", False)):
        empty = detectar_suporte_vazio_exclusivo_rearme_f3(
            matcher,
            frame,
            project_name,
        )
        if empty is not None:
            app._display_f3_new_board_frames = 0
            held = dict(empty)
            held["allow_auto"] = False
            held["cycle_rearmed_waiting_new_board"] = True
            return held

        frames = int(getattr(app, "_display_f3_new_board_frames", 0) or 0) + 1
        app._display_f3_new_board_frames = frames
        if frames < F3_NEW_BOARD_STABLE_FRAMES:
            return {
                "kind": "unknown",
                "text": (
                    "CONFIRMANDO NOVA PLACA • "
                    f"{frames}/{F3_NEW_BOARD_STABLE_FRAMES}"
                ),
                "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"],
                "allow_auto": False,
                "board_references_complete": bool(
                    state.get("board_references_complete")
                ),
                "cycle_rearmed_waiting_new_board": True,
            }

        app._display_f3_waiting_new_board_after_empty = False
        app._display_f3_new_board_frames = 0
        _reset_auto_after_physical_transition(app)
        state["cycle_new_board_confirmed"] = True
        return state

    app._display_f3_rearm_empty_frames = 0
    app._display_f3_new_board_frames = 0
    return state


def _obter_matcher_operacional(app):
    repository = getattr(app, "display_project_repository", None)
    if repository is None:
        return None
    matcher = getattr(app, "_display_f3_operational_matcher", None)
    if matcher is None or getattr(matcher, "repository", None) is not repository:
        try:
            matcher = operational_module.DisplayVisualReferenceMatcher(repository)
        except Exception:
            return None
        app._display_f3_operational_matcher = matcher
    return matcher


def _instalar_wrapper_operacional_rearme_f3() -> None:
    """Mantém o rearme como camada externa mesmo após outros builders F3.

    O instalador histórico guardava apenas um booleano global. Se uma camada
    posterior substituísse ``_build_operational_state`` (como o gabarito exato),
    o booleano continuava True e o rearme nunca era reinstalado. O resultado era
    exatamente um ciclo visualmente em H1, porém ainda bloqueado internamente pelo
    latch de rearme da placa anterior.
    """
    base_build = operational_module._build_operational_state
    if bool(getattr(base_build, "_odin_f3_dedicated_cycle_rearm_release", False)):
        operational_module._display_f3_dedicated_cycle_rearm_release_installed = True
        return

    def build(self, frame, project_name: str, context: dict | None):
        was_waiting_empty = bool(
            getattr(self, "_display_f3_waiting_empty_rearm", False)
        )
        state = base_build(self, frame, project_name, context)

        # Um gate interno pode ter reconhecido EMPTY sozinho. Nesse caso apenas
        # finalizamos o reset do ciclo e passamos a aguardar a nova placa.
        if was_waiting_empty and not bool(
            getattr(self, "_display_f3_waiting_empty_rearm", False)
        ):
            _concluir_passagem_por_suporte_vazio_f3(self)
            return state

        needs_dedicated_gate = bool(
            getattr(self, "_display_f3_waiting_empty_rearm", False)
            or getattr(self, "_display_f3_waiting_new_board_after_empty", False)
        )
        if not needs_dedicated_gate:
            return state

        matcher = _obter_matcher_operacional(self)
        if matcher is None:
            state = dict(state or {})
            state["allow_auto"] = False
            state["cycle_rearm_waiting"] = True
            return state

        return aplicar_rearme_fisico_dedicado_f3(
            self,
            matcher,
            frame,
            project_name,
            state,
        )

    build._odin_f3_dedicated_cycle_rearm_release = True
    build._odin_f3_dedicated_cycle_rearm_base = base_build
    operational_module._build_operational_state = build
    operational_module._display_f3_dedicated_cycle_rearm_release_installed = True


def _instalar_patch_no_instalador_principal() -> None:
    if bool(
        getattr(live_module, "_display_f3_cycle_rearm_release_patch_installed", False)
    ):
        return

    original_install_cycle_gate = live_module._install_cycle_rearm_gate
    original_arm = live_module.armar_rearme_por_suporte_vazio_f3

    def arm(app) -> None:
        app._display_f3_rearm_empty_frames = 0
        app._display_f3_waiting_new_board_after_empty = False
        app._display_f3_new_board_frames = 0
        original_arm(app)

    def install_cycle_gate() -> None:
        original_install_cycle_gate()
        _instalar_wrapper_operacional_rearme_f3()

    live_module.armar_rearme_por_suporte_vazio_f3 = arm
    live_module._install_cycle_rearm_gate = install_cycle_gate
    live_module._display_f3_cycle_rearm_release_patch_installed = True

    # Compatibilidade com processos que importem esta extensão depois de o
    # instalador principal já ter sido executado.
    if bool(getattr(operational_module, "_display_f3_cycle_rearm_gate_installed", False)):
        _instalar_wrapper_operacional_rearme_f3()


def instalar_rearme_fisico_final_display_f3() -> None:
    """Reaplica o handoff EMPTY -> nova placa sobre o builder F3 atualmente ativo."""
    _instalar_patch_no_instalador_principal()
    _instalar_wrapper_operacional_rearme_f3()


_instalar_patch_no_instalador_principal()
