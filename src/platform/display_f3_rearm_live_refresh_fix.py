from __future__ import annotations

"""Fecha o handoff visual/físico do F3 após OK, NG ou SEGREGAR.

Dois sintomas podem aparecer juntos depois de um resultado terminal:

1. o frame atual já prova suporte vazio pela autoridade relativa de presença,
   mas o rearme dedicado ainda usa o detector histórico que exige EMPTY acima
   do threshold absoluto; com EMPTY ~= 0.59 ele pode ficar eternamente em
   ``waiting_empty``;
2. o guard terminal interrompe o processo automático antes da rotina que atualiza
   a segunda linha ``ANÁLISE VISUAL``. A câmera continua viva, porém o texto da UI
   pode permanecer congelado no último ``CHECK BLUE • 77%`` da placa descartada.

Esta camada reutiliza exatamente a autoridade relativa EMPTY x melhor cena com
placa já adotada pelo F3 e publica as duas linhas de status em cada frame de
rearme. Não cria timer, não lê uma segunda câmera, não altera OK/NG e não toca F2.
"""

from copy import deepcopy

import src.platform.display_f3_cycle_rearm_release_fix as rearm_module
import src.platform.display_f3_final_rearm_guard as final_guard_module
import src.platform.display_f3_operational_status as operational_module
import src.platform.display_visual_reference_status as visual_status_module
from src.platform.display_visual_reference_status import (
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
    DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
)


F3_REARM_LIVE_REFRESH_SOURCE = "f3_rearm_live_presence_refresh"


def _score_value(matcher, current_small, metadata: dict | None):
    try:
        candidate = operational_module._score_candidate(matcher, current_small, metadata)
    except Exception:
        return None
    if not isinstance(candidate, dict):
        return None
    try:
        return float(candidate.get("score"))
    except (TypeError, ValueError):
        return None


def _project_checks(repository, project_name: str) -> list[dict]:
    try:
        rows = repository.listar_checks(project_name)
    except Exception:
        rows = None
    if isinstance(rows, list):
        return [item for item in rows if isinstance(item, dict)]

    try:
        project = repository.carregar_projeto(project_name)
    except Exception:
        project = None
    if not isinstance(project, dict):
        return []
    return [item for item in (project.get("checks") or ()) if isinstance(item, dict)]


def estado_scores_presenca_rearme_f3(matcher, frame, project_name: str) -> dict:
    """Monta somente os scores necessários para presença durante o rearme."""
    try:
        current_small = visual_status_module._small_image(frame)
    except Exception:
        current_small = None
    if current_small is None:
        return {"kind": "unknown", "reference_scores": {}}

    repository = getattr(matcher, "repository", None)
    scores: dict[str, float] = {}
    board_complete = False

    try:
        project_refs = matcher.project_store.get_all(project_name)
    except Exception:
        project_refs = {}
    if isinstance(project_refs, dict):
        empty_meta = project_refs.get(DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT)
        off_meta = project_refs.get(DISPLAY_PROJECT_REFERENCE_BOARD_OFF)
        empty_score = _score_value(matcher, current_small, empty_meta)
        off_score = _score_value(matcher, current_small, off_meta)
        if empty_score is not None:
            scores["empty"] = empty_score
        if off_score is not None:
            scores["off"] = off_score
        board_complete = bool(empty_meta is not None and off_meta is not None)

    if repository is not None:
        for check in _project_checks(repository, project_name):
            check_id = str(check.get("id") or "").strip()
            if not check_id:
                continue
            try:
                metadata = matcher.check_store.get(project_name, check_id)
            except Exception:
                metadata = None
            score = _score_value(matcher, current_small, metadata)
            if score is not None:
                scores[f"check:{check_id}"] = score

    return {
        "kind": "unknown",
        "reference_scores": scores,
        "board_references_complete": board_complete,
        "rearm_presence_probe": True,
    }


def detectar_suporte_vazio_relativo_rearme_f3(
    matcher,
    frame,
    project_name: str,
) -> dict | None:
    """Confirma EMPTY no rearme pela mesma separação relativa do runtime final."""
    state = estado_scores_presenca_rearme_f3(matcher, frame, project_name)
    try:
        from src.platform.display_f3_presence_relative_empty_fix import (
            avaliar_suporte_vazio_relativo_f3,
        )

        evidence = avaliar_suporte_vazio_relativo_f3(state)
    except Exception:
        return None

    if not isinstance(evidence, dict) or not bool(evidence.get("empty_confirmed")):
        return None

    return {
        "kind": "empty",
        "text": "PLACA FORA DO SUPORTE",
        "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["empty"],
        "allow_auto": False,
        "physical_state_key": "empty:rearm_relative_presence",
        "board_references_complete": bool(state.get("board_references_complete")),
        "reference_scores": dict(state.get("reference_scores") or {}),
        "rearm_empty_probe": True,
        "rearm_empty_relative": True,
        "presence_authority_source": F3_REARM_LIVE_REFRESH_SOURCE,
        "board_presence_evidence": {
            "available": True,
            "board_present": False,
            "empty_confirmed": True,
            "presence_confirmed": True,
            "source": F3_REARM_LIVE_REFRESH_SOURCE,
            "decision_mode": evidence.get("decision_mode"),
            "reason": evidence.get("reason"),
            "empty_score": evidence.get("empty_score"),
            "best_board_reference": evidence.get("best_board_reference"),
            "best_board_score": evidence.get("best_board_score"),
            "empty_over_best_board_margin": evidence.get("empty_over_best_board_margin"),
            "empty_over_best_board_ratio": evidence.get("empty_over_best_board_ratio"),
        },
    }


def status_visual_rearme_f3(state: dict | None) -> tuple[str, str] | None:
    data = state if isinstance(state, dict) else {}
    waiting_new = bool(data.get("cycle_rearmed_waiting_new_board"))
    underlying_kind = str(
        data.get("rearm_underlying_kind") or data.get("kind") or ""
    ).strip().lower()
    empty_confirmed = bool(
        waiting_new
        or data.get("rearm_empty_confirmed")
        or data.get("rearm_empty_relative")
        or underlying_kind == "empty"
    )
    if empty_confirmed:
        return (
            "ANÁLISE VISUAL: PLACA FORA DO SUPORTE • suporte vazio confirmado",
            operational_module.F3_OPERATIONAL_STATUS_COLORS["empty"],
        )

    if bool(data.get("rearm_empty_pending")):
        frames = int(data.get("rearm_empty_pending_frames", 0) or 0)
        total = int(getattr(rearm_module, "F3_REARM_EMPTY_STABLE_FRAMES", 2) or 2)
        return (
            f"ANÁLISE VISUAL: confirmando PLACA FORA DO SUPORTE • {frames}/{total}",
            operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"],
        )

    if bool(data.get("cycle_rearm_waiting")) or bool(data.get("final_rearm_guard")):
        return (
            "ANÁLISE VISUAL: ciclo encerrado • aguardando retirada da placa anterior",
            operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"],
        )
    return None


def _publish_empty_power_status(app, state: dict) -> None:
    visual = status_visual_rearme_f3(state)
    if visual is None or "PLACA FORA DO SUPORTE" not in visual[0]:
        return

    presence = state.get("board_presence_evidence")
    if not isinstance(presence, dict):
        presence = {
            "available": True,
            "board_present": False,
            "empty_confirmed": True,
            "presence_confirmed": True,
            "source": F3_REARM_LIVE_REFRESH_SOURCE,
        }
    else:
        presence = deepcopy(presence)
        presence.update(
            board_present=False,
            empty_confirmed=True,
            presence_confirmed=True,
        )

    app._display_f3_power_authority_status = {
        "source": F3_REARM_LIVE_REFRESH_SOURCE,
        "board_present": False,
        "empty_confirmed": True,
        "presence": presence,
        "energy": None,
        "decision_allowed": False,
        "reason": "suporte_vazio_confirmado_durante_rearme",
    }
    app._display_auto_last_analysis = None
    app._display_f3_overlay_analysis_cache_key = None
    app._display_f3_overlay_analysis_cache = None


def instalar_correcao_rearme_status_live_display_f3() -> None:
    """Instala detector relativo no rearme e impede status visual congelado."""
    if bool(getattr(rearm_module, "_display_f3_rearm_live_refresh_installed", False)):
        return

    previous_detector = rearm_module.detectar_suporte_vazio_exclusivo_rearme_f3

    def detector(matcher, frame, project_name: str):
        direct = previous_detector(matcher, frame, project_name)
        if isinstance(direct, dict):
            direct = dict(direct)
            direct.setdefault("presence_authority_source", F3_REARM_LIVE_REFRESH_SOURCE)
            return direct
        return detectar_suporte_vazio_relativo_rearme_f3(
            matcher,
            frame,
            project_name,
        )

    rearm_module.detectar_suporte_vazio_exclusivo_rearme_f3 = detector
    rearm_module._display_f3_rearm_live_refresh_installed = True

    previous_publish = final_guard_module._publicar_estado_rearme

    def publish(app, state: dict) -> None:
        previous_publish(app, state)
        _publish_empty_power_status(app, state)

        visual = status_visual_rearme_f3(state)
        if visual is None:
            return
        window = getattr(app, "display_f3_window", None)
        if window is None:
            return
        try:
            window.set_visual_analysis_status(visual[0], visual[1])
        except Exception:
            pass
        app._display_f3_rearm_visual_status = {
            "text": visual[0],
            "color": visual[1],
            "source": F3_REARM_LIVE_REFRESH_SOURCE,
        }

    final_guard_module._publicar_estado_rearme = publish
    final_guard_module._display_f3_rearm_live_visual_refresh_installed = True
