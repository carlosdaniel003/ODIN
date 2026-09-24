from __future__ import annotations

from copy import deepcopy
import time

import src.platform.display_f3_operational_status as operational_module
import src.platform.display_f3_power_authority as power_module
import src.platform.display_f3_power_authority_v2 as power_v2_module
import src.platform.display_f3_runtime_contract_fix as contract_module


F3_STABLE_PRESENCE_SOURCE = "f3_best_occupied_vs_empty_presence_stability"
F3_PRESENCE_MIN_OCCUPIED_SCORE = power_module.F3_POWERED_MIN_BOARD_SCENE_SCORE
F3_PRESENCE_MIN_MARGIN = power_module.F3_POWERED_MIN_OFF_OVER_EMPTY_MARGIN
F3_PRESENCE_AMBIGUOUS_HOLD_FRAMES = 3
F3_INTERMITTENT_POWER_HOLD_S = 2.5


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _occupied_rows(scores: dict) -> list[tuple[str, float]]:
    rows = []
    for key, value in scores.items():
        name = str(key or "")
        if name != "off" and not name.startswith("check:"):
            continue
        score = _safe_float(value)
        if score is not None:
            rows.append((name, float(score)))
    rows.sort(key=lambda item: item[1], reverse=True)
    return rows


def avaliar_presenca_melhor_ocupado_f3(state: dict | None) -> dict:
    data = state if isinstance(state, dict) else {}
    kind = str(data.get("kind") or "unknown").strip().lower()
    scores = data.get("reference_scores") if isinstance(data.get("reference_scores"), dict) else {}
    empty_score = _safe_float(scores.get("empty"))
    occupied = _occupied_rows(scores)
    best_key = occupied[0][0] if occupied else None
    best_score = occupied[0][1] if occupied else None

    result = {
        "available": bool(empty_score is not None and best_score is not None),
        "source": F3_STABLE_PRESENCE_SOURCE,
        "board_present": False,
        "presence_confirmed": False,
        "empty_confirmed": False,
        "empty_score": empty_score,
        "best_occupied_reference": best_key,
        "best_occupied_score": best_score,
    }

    if kind == "empty":
        result.update(
            available=True,
            empty_confirmed=True,
            presence_confirmed=True,
            reason="suporte_vazio_confirmado",
        )
        return result

    if empty_score is not None and best_score is not None:
        margin = float(best_score - empty_score)
        present = bool(
            best_score >= F3_PRESENCE_MIN_OCCUPIED_SCORE
            and margin >= F3_PRESENCE_MIN_MARGIN
        )
        result.update(
            board_present=present,
            presence_confirmed=present,
            occupied_over_empty_margin=round(margin, 4),
            reason=(
                "melhor_cena_com_placa_supera_empty"
                if present
                else "separacao_ocupado_vs_empty_insuficiente"
            ),
        )
        return result

    explicit_present = kind in {"off", "check", "powered"}
    result.update(
        available=explicit_present,
        board_present=explicit_present,
        presence_confirmed=explicit_present,
        reason=(
            "estado_explicito_com_placa"
            if explicit_present
            else "scores_de_presenca_indisponiveis"
        ),
    )
    return result


def _hold_presence(app, evidence: dict) -> dict:
    result = deepcopy(evidence)
    if result.get("empty_confirmed"):
        app._display_f3_presence_stability_latch = None
        return result
    if result.get("board_present") and result.get("presence_confirmed"):
        app._display_f3_presence_stability_latch = {
            "frames": 0,
            "evidence": deepcopy(result),
        }
        return result

    latch = getattr(app, "_display_f3_presence_stability_latch", None)
    if not isinstance(latch, dict):
        return result
    frames = int(latch.get("frames", 0) or 0) + 1
    if frames > F3_PRESENCE_AMBIGUOUS_HOLD_FRAMES:
        app._display_f3_presence_stability_latch = None
        return result
    latch["frames"] = frames
    app._display_f3_presence_stability_latch = latch
    result.update(
        available=True,
        board_present=True,
        presence_confirmed=True,
        held_from_previous_frame=True,
        held_ambiguous_frames=frames,
        reason="presenca_mantida_durante_ambiguidade_curta",
    )
    return result


def _apply_final_presence(app, result: dict, frame, project_name: str, context: dict | None) -> dict:
    output = deepcopy(result)
    if str(output.get("kind") or "").strip().lower() == "empty":
        app._display_f3_presence_stability_latch = None
        app._display_f3_intermittent_power_latch = None
        return output

    presence = _hold_presence(app, avaliar_presenca_melhor_ocupado_f3(output))
    output["board_presence_evidence"] = deepcopy(presence)
    if not presence.get("board_present"):
        return output

    evidence = output.get("power_evidence")
    if not isinstance(evidence, dict):
        evidence = power_v2_module.avaliar_evidencia_energia_unificada_display_f3(
            app, frame, project_name, context
        )
        output["power_evidence"] = deepcopy(evidence)

    check_id = str((context or {}).get("check_id") or "")
    check_name = str((context or {}).get("check_name") or check_id or "CHECK").strip().upper()
    intermittent = bool((context or {}).get("intermittent", False))
    signature = (str(project_name or ""), check_id)
    now = time.monotonic()

    if evidence.get("powered_confirmed"):
        if intermittent:
            app._display_f3_intermittent_power_latch = {
                "signature": signature,
                "powered_at_s": now,
                "evidence": deepcopy(evidence),
            }
    elif intermittent:
        latch = getattr(app, "_display_f3_intermittent_power_latch", None)
        if isinstance(latch, dict) and tuple(latch.get("signature") or ()) == signature:
            age = now - float(latch.get("powered_at_s", 0.0) or 0.0)
            if 0.0 <= age <= F3_INTERMITTENT_POWER_HOLD_S:
                held = deepcopy(evidence)
                held.update(
                    {
                        "intermittent_phase_hold": True,
                        "intermittent_live_energy_state": str(
                            evidence.get("energy_state") or "unconfirmed"
                        ),
                        "intermittent_hold_age_ms": int(round(age * 1000.0)),
                        "energy_state": power_module.F3_POWER_STATE_POWERED,
                        "powered_confirmed": True,
                        "off_confirmed": False,
                    }
                )
                evidence = held
                output["power_evidence"] = deepcopy(evidence)
            elif age > F3_INTERMITTENT_POWER_HOLD_S:
                app._display_f3_intermittent_power_latch = None
    else:
        app._display_f3_intermittent_power_latch = None

    if evidence.get("powered_confirmed"):
        output.update(
            kind="powered",
            text=(
                f"PLACA NO SUPORTE • LIGADA • {check_name} • FASE OFF INTERMITENTE"
                if bool(evidence.get("intermittent_phase_hold"))
                else f"PLACA NO SUPORTE • LIGADA • ANALISANDO {check_name}"
            ),
            color=operational_module.F3_OPERATIONAL_STATUS_COLORS["check"],
            allow_auto=True,
            physical_state_key="check:powered_by_stable_presence",
            expected_check_id=check_id,
            powered_board_confirmed=True,
            power_gate_blocked=False,
            power_gate_reason="presenca_estavel_e_energia_confirmada",
        )
        output[contract_module.F3_DECISION_ALLOWED_KEY] = True
        decision_allowed = True
    else:
        is_off = bool(evidence.get("off_confirmed"))
        output.update(
            kind="off" if is_off else "unknown",
            text=(
                "PLACA NO SUPORTE • DESLIGADA • AGUARDANDO DISPLAY LIGADO"
                if is_off
                else "PLACA NO SUPORTE • ENERGIA DO DISPLAY NÃO CONFIRMADA"
            ),
            color=operational_module.F3_OPERATIONAL_STATUS_COLORS["off" if is_off else "unknown"],
            allow_auto=False,
            physical_state_key="off:stable_presence" if is_off else "power:unconfirmed",
            powered_board_confirmed=False,
            power_gate_blocked=True,
            power_gate_reason=(
                "placa_presente_e_todos_on_esperados_apagados"
                if is_off
                else "placa_presente_mas_energia_nao_confirmada"
            ),
        )
        output[contract_module.F3_DECISION_ALLOWED_KEY] = False
        decision_allowed = False

    output[contract_module.F3_MASK_LIVE_KEY] = True
    app._display_f3_power_authority_status = {
        "source": F3_STABLE_PRESENCE_SOURCE,
        "board_present": True,
        "presence": deepcopy(presence),
        "energy": deepcopy(evidence),
        "decision_allowed": decision_allowed,
        "reason": str(output.get("power_gate_reason") or ""),
    }
    return output


def instalar_estabilidade_presenca_placa_display_f3() -> None:
    if getattr(power_module, "_display_f3_presence_stability_installed", False):
        return

    power_module._presence_from_global_scores = avaliar_presenca_melhor_ocupado_f3
    previous_authority = power_module.aplicar_autoridade_energia_ao_estado_f3

    def apply(app, state, frame, project_name: str, context: dict | None):
        result = previous_authority(app, state, frame, project_name, context)
        if not isinstance(result, dict):
            return result
        return _apply_final_presence(app, result, frame, project_name, context)

    power_module.aplicar_autoridade_energia_ao_estado_f3 = apply
    power_module._display_f3_presence_stability_installed = True
