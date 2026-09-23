from __future__ import annotations

"""Análise técnica manual do Display F3 sobre um único frame congelado.

O operador dispara ANALISAR quando quiser investigar o estado atual. O frame é
copiado imediatamente e todo o diagnóstico abaixo trabalha somente nessa cópia.
Nenhuma função deste módulo registra OK/NG, avança CHECK, rearma ciclo ou altera
estado da Produção F2.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import tkinter as tk

import cv2

from src.platform.display_f3_window_geometry import fit_f3_toplevel
import numpy as np

import src.platform.display_f3_exact_check_template as exact_module
import src.platform.display_f3_physical_learning_policy as physical_policy_module
import src.platform.display_f3_unknown_debug_fix as unknown_debug_module
from src.platform.display_f3_same_mask_reference_fix import F3SameMaskReferenceAnalyzer
from src.platform.display_f3_exact_check_template import F3ExactCheckTemplateAnalyzer
from src.platform.display_production_f3 import DisplayProductionF3Mixin
from src.platform.display_production_f3_window import DisplayProductionF3Window
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_IGNORE,
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
)
from src.platform.display_visual_reference_status import (
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
    DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
    DISPLAY_PROJECT_REFERENCE_TYPES,
    DisplayVisualReferenceMatcher,
)


F3_MANUAL_SNAPSHOT_SOURCE = "f3_manual_frozen_frame_diagnostic"

DEBUG_BG = "#07111F"
DEBUG_PANEL = "#0B1220"
DEBUG_BORDER = "#334155"
DEBUG_TEXT = "#E2E8F0"
DEBUG_MUTED = "#94A3B8"
DEBUG_ACTION = "#0E7490"
DEBUG_ACTION_ACTIVE = "#0891B2"


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt(value, digits: int = 4) -> str:
    number = _safe_float(value)
    return "--" if number is None else f"{number:.{digits}f}"


def _yes_no(value) -> str:
    return "SIM" if bool(value) else "NÃO"


def _safe_deepcopy(value):
    try:
        return deepcopy(value)
    except Exception:
        return value


def _ng_evidence_snapshot(app) -> dict | None:
    if not bool(getattr(app, "_display_f3_ng_evidence_frozen", False)):
        return None
    value = getattr(app, "_display_f3_ng_evidence_snapshot", None)
    return value if isinstance(value, dict) else {}


def _rotation(app) -> int:
    evidence = _ng_evidence_snapshot(app)
    if evidence is not None:
        try:
            value = int(evidence.get("rotation", 0) or 0)
        except Exception:
            value = 0
    else:
        try:
            value = int(app._obter_rotacao_visual_display_f3())
        except Exception:
            value = int(getattr(app, "visual_rotation", 0) or 0)
    value %= 360
    return value if value in (0, 90, 180, 270) else 0


def _current_context(app):
    evidence = _ng_evidence_snapshot(app)
    if evidence is not None:
        value = evidence.get("context")
        return _safe_deepcopy(value) if isinstance(value, dict) else None

    try:
        value = app._display_auto_current_context()
    except Exception:
        value = None
    return _safe_deepcopy(value) if isinstance(value, dict) else None


def _window_visual_state(app) -> dict:
    evidence = _ng_evidence_snapshot(app)
    if evidence is not None:
        value = evidence.get("visual_state")
        if isinstance(value, dict):
            return _safe_deepcopy(value)

    window = getattr(app, "display_f3_window", None)
    getter = getattr(window, "snapshot_debug_visual_state", None)
    if callable(getter):
        try:
            value = getter()
        except Exception:
            value = None
        if isinstance(value, dict):
            return _safe_deepcopy(value)
    return {}


def _runtime_state_at_frame(app) -> dict:
    evidence = _ng_evidence_snapshot(app)
    if evidence is not None:
        runtime_debug = (
            evidence.get("runtime_debug")
            if isinstance(evidence.get("runtime_debug"), dict)
            else {}
        )
        return {
            "display_f3_active": bool(getattr(app, "display_f3_ativo", False)),
            "diagnostic_source": "ng_evidence_frozen",
            "ng_evidence_frozen": True,
            "live_camera_ignored": True,
            "camera_frame_id": evidence.get("frame_id"),
            "logical_context": _current_context(app),
            "operational_state": _safe_deepcopy(
                evidence.get("operational_state")
            ),
            "last_auto_analysis": _safe_deepcopy(evidence.get("analysis")),
            "sequence": _safe_deepcopy(evidence.get("sequence")),
            "last_decision": _safe_deepcopy(runtime_debug.get("last_decision")),
            "stable_frames": _safe_deepcopy(runtime_debug.get("stable_frames")),
            "required_stable_frames": _safe_deepcopy(
                runtime_debug.get("required_stable_frames")
            ),
            "transition_frames": _safe_deepcopy(
                runtime_debug.get("transition_frames")
            ),
            "physical_stable_key": _safe_deepcopy(
                runtime_debug.get("physical_stable_key")
            ),
            "physical_pending_key": _safe_deepcopy(
                runtime_debug.get("physical_pending_key")
            ),
            "physical_pending_frames": _safe_deepcopy(
                runtime_debug.get("physical_pending_frames")
            ),
            "unknown_off_pending_frames": _safe_deepcopy(
                runtime_debug.get("unknown_off_pending_frames")
            ),
            "manual_entry_signature": _safe_deepcopy(
                runtime_debug.get("manual_entry_signature")
            ),
            "manual_entry_label": _safe_deepcopy(
                runtime_debug.get("manual_entry_label")
            ),
            "waiting_empty_rearm": _safe_deepcopy(
                runtime_debug.get("waiting_empty_rearm")
            ),
        }

    try:
        sequence = app.display_check_runtime.snapshot()
    except Exception:
        sequence = None
    return {
        "display_f3_active": bool(getattr(app, "display_f3_ativo", False)),
        "diagnostic_source": "live_camera_at_analyze_click",
        "ng_evidence_frozen": False,
        "live_camera_ignored": False,
        "camera_frame_id": getattr(app, "camera_ultimo_frame_id", None),
        "logical_context": _current_context(app),
        "operational_state": _safe_deepcopy(
            getattr(app, "_display_f3_operational_state", None)
        ),
        "last_auto_analysis": _safe_deepcopy(
            getattr(app, "_display_auto_last_analysis", None)
        ),
        "sequence": _safe_deepcopy(sequence),
        "last_decision": _safe_deepcopy(
            getattr(app, "_display_auto_last_decision", None)
        ),
        "stable_frames": _safe_deepcopy(
            getattr(app, "_display_auto_stable_frames", None)
        ),
        "required_stable_frames": None,
        "transition_frames": _safe_deepcopy(
            getattr(app, "_display_auto_transition_frames", None)
        ),
        "physical_stable_key": _safe_deepcopy(
            getattr(app, "_display_f3_physical_stable_key", None)
        ),
        "physical_pending_key": _safe_deepcopy(
            getattr(app, "_display_f3_physical_pending_key", None)
        ),
        "physical_pending_frames": _safe_deepcopy(
            getattr(app, "_display_f3_physical_pending_frames", None)
        ),
        "unknown_off_pending_frames": _safe_deepcopy(
            getattr(app, "_display_f3_unknown_off_pending_frames", None)
        ),
        "manual_entry_signature": _safe_deepcopy(
            getattr(app, "_display_auto_manual_entry_signature", None)
        ),
        "manual_entry_label": _safe_deepcopy(
            getattr(app, "_display_auto_manual_entry_label", None)
        ),
        "waiting_empty_rearm": _safe_deepcopy(
            getattr(app, "_display_auto_waiting_empty_rearm", None)
        ),
    }


def _camera_settings_at_frame(app) -> dict:
    """Ajuda a correlacionar foco/exposição/ganho/WB com o mesmo frame."""
    return {
        "backend": str(
            getattr(app, "_backend_atual", "")
            or getattr(app, "_backend_name", "")
            or ""
        ),
        "configured": _safe_deepcopy(
            getattr(app, "_configuracoes_camera", None)
        ),
        "hardware_values": _safe_deepcopy(
            getattr(app, "_camera_live_valores_hardware", None)
        ),
        "control_status": _safe_deepcopy(
            getattr(app, "_status_controles_camera", None)
        ),
    }


def _freeze_current_frame(app):
    """Seleciona a fonte autoritativa e devolve uma cópia imutável para o DEBUG.

    Durante NG congelado, a câmera ao vivo é deliberadamente ignorada. Ela
    continua rodando somente para o gate de PLACA FORA DO SUPORTE.
    """
    evidence = _ng_evidence_snapshot(app)
    if evidence is not None:
        source = getattr(app, "_display_f3_ng_evidence_frame", None)
        frame_id = evidence.get("frame_id")
        if source is None or getattr(source, "size", 0) == 0:
            return None, {
                "attempts": [],
                "frame_id": frame_id,
                "stable_frame_id": True,
                "reason": "ng_evidence_frame_missing",
                "source": "ng_evidence_frozen",
                "live_camera_ignored": True,
            }
        try:
            frozen = source.copy()
        except Exception:
            frozen = np.array(source, copy=True)
        return frozen, {
            "attempts": [
                {
                    "attempt": 1,
                    "frame_id_before": frame_id,
                    "frame_id_after": frame_id,
                    "stable": True,
                }
            ],
            "frame_id": frame_id,
            "stable_frame_id": True,
            "reason": "ok",
            "source": "ng_evidence_frozen",
            "live_camera_ignored": True,
        }

    """Copia um frame coerente e registra se o id da câmera mudou na captura."""
    attempts = []
    frozen = None
    selected_frame_id = None
    for attempt in range(1, 3):
        before = getattr(app, "camera_ultimo_frame_id", None)
        source = getattr(app, "camera_frame_atual", None)
        if source is None or getattr(source, "size", 0) == 0:
            return None, {
                "attempts": attempts,
                "frame_id": before,
                "stable_frame_id": False,
                "reason": "camera_sem_frame",
            }
        try:
            candidate = source.copy()
        except Exception:
            candidate = np.array(source, copy=True)
        after = getattr(app, "camera_ultimo_frame_id", None)
        stable = before == after
        attempts.append(
            {
                "attempt": attempt,
                "frame_id_before": before,
                "frame_id_after": after,
                "stable": bool(stable),
            }
        )
        frozen = candidate
        selected_frame_id = before if stable else after
        if stable:
            break
    return frozen, {
        "attempts": attempts,
        "frame_id": selected_frame_id,
        "stable_frame_id": bool(attempts and attempts[-1].get("stable")),
        "reason": "ok",
        "source": "live_camera_at_analyze_click",
        "live_camera_ignored": False,
    }


def _frame_statistics(frame) -> dict:
    if frame is None or getattr(frame, "size", 0) == 0:
        return {"available": False}
    image = np.asarray(frame)
    stats = {
        "available": True,
        "shape": [int(value) for value in image.shape],
        "dtype": str(image.dtype),
        "bytes": int(image.nbytes),
        "sha256_24": hashlib.sha256(image.tobytes()).hexdigest()[:24],
        "min": float(np.min(image)),
        "max": float(np.max(image)),
        "mean": round(float(np.mean(image)), 4),
        "std": round(float(np.std(image)), 4),
    }
    if image.ndim == 3 and image.shape[2] >= 3:
        bgr = image[:, :, :3]
        channels = {}
        for index, name in enumerate(("B", "G", "R")):
            channel = bgr[:, :, index]
            channels[name] = {
                "mean": round(float(np.mean(channel)), 4),
                "std": round(float(np.std(channel)), 4),
                "p05": round(float(np.percentile(channel, 5)), 4),
                "p50": round(float(np.percentile(channel, 50)), 4),
                "p95": round(float(np.percentile(channel, 95)), 4),
                "p99": round(float(np.percentile(channel, 99)), 4),
            }
        stats["channels_bgr"] = channels
        try:
            hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
            saturation = hsv[:, :, 1]
            value = hsv[:, :, 2]
            stats["hsv"] = {
                "s_mean": round(float(np.mean(saturation)), 4),
                "s_std": round(float(np.std(saturation)), 4),
                "v_mean": round(float(np.mean(value)), 4),
                "v_std": round(float(np.std(value)), 4),
                "v_p50": round(float(np.percentile(value, 50)), 4),
                "v_p95": round(float(np.percentile(value, 95)), 4),
                "v_p99": round(float(np.percentile(value, 99)), 4),
                "hot_235_pct": round(float(np.mean(value >= 235) * 100.0), 5),
                "hot_245_pct": round(float(np.mean(value >= 245) * 100.0), 5),
                "hot_250_pct": round(float(np.mean(value >= 250) * 100.0), 5),
            }
        except Exception as exc:
            stats["hsv_error"] = f"{type(exc).__name__}: {exc}"
    return stats


def _reference_rows(matcher, frame, project_name: str) -> list[dict]:
    rows = []
    try:
        candidates = exact_module._physical_candidates(matcher, project_name)
    except Exception as exc:
        return [{"error": f"{type(exc).__name__}: {exc}"}]

    for candidate in candidates:
        metadata = candidate.get("metadata")
        try:
            score = exact_module._score_reference_full_roi(frame, metadata)
        except Exception as exc:
            score = None
            error = f"{type(exc).__name__}: {exc}"
        else:
            error = None
        try:
            threshold = (
                float(matcher._threshold(metadata))
                if isinstance(metadata, dict)
                else None
            )
        except Exception:
            threshold = None
        score_float = _safe_float(score)
        row = {
            "key": str(candidate.get("key") or ""),
            "kind": str(candidate.get("kind") or ""),
            "name": str(candidate.get("name") or candidate.get("key") or ""),
            "check_id": str(candidate.get("check_id") or ""),
            "configured": isinstance(metadata, dict),
            "score": score_float,
            "threshold": threshold,
            "matched": bool(
                score_float is not None
                and threshold is not None
                and score_float >= threshold
            ),
            "margin_to_threshold": (
                None
                if score_float is None or threshold is None
                else round(score_float - threshold, 4)
            ),
            "comparison_mode": "full_resolution_roi_first",
            "image_path": str((metadata or {}).get("image_path") or "")
            if isinstance(metadata, dict)
            else "",
            "roi": _safe_deepcopy((metadata or {}).get("roi"))
            if isinstance(metadata, dict)
            else None,
        }
        if error:
            row["error"] = error
        rows.append(row)
    rows.sort(
        key=lambda item: _safe_float(item.get("score"), -1.0),
        reverse=True,
    )
    if rows:
        rows[0]["rank"] = 1
        for index, row in enumerate(rows[1:], start=2):
            row["rank"] = index
        if len(rows) >= 2:
            top = _safe_float(rows[0].get("score"))
            second = _safe_float(rows[1].get("score"))
            rows[0]["margin_to_second"] = (
                None if top is None or second is None else round(top - second, 4)
            )
    return rows


def _presence_summary_from_rows(rows: list[dict]) -> dict:
    by_key = {
        str(item.get("key") or ""): item
        for item in rows
        if isinstance(item, dict)
    }
    off = by_key.get("off", {})
    empty = by_key.get("empty", {})
    return {
        "board_references_complete": bool(off.get("configured") and empty.get("configured")),
        "off_score": _safe_float(off.get("score")),
        "off_threshold": _safe_float(off.get("threshold")),
        "empty_score": _safe_float(empty.get("score")),
        "empty_threshold": _safe_float(empty.get("threshold")),
        "comparison_mode": "full_resolution_roi_first",
    }


def _project_and_checks(repository, project_name: str):
    try:
        project = repository.carregar_projeto(project_name)
    except Exception:
        project = None
    try:
        checks = repository.listar_checks(project_name)
    except Exception:
        checks = []
    return (
        _safe_deepcopy(project) if isinstance(project, dict) else {},
        [_safe_deepcopy(item) for item in checks if isinstance(item, dict)],
    )


def _mask_geometry(mask: dict) -> dict:
    keys = (
        "id",
        "name",
        "type",
        "cx",
        "cy",
        "radius",
        "x",
        "y",
        "width",
        "height",
        "angle",
        "length",
        "thickness",
        "points",
    )
    return {key: _safe_deepcopy(mask.get(key)) for key in keys if key in mask}


def _configured_masks(project: dict, checks: list[dict]) -> list[dict]:
    rows = []
    for mask in project.get("masks", []) or []:
        if not isinstance(mask, dict):
            continue
        mask_id = str(mask.get("id") or "")
        states = {}
        for check in checks:
            check_id = str(check.get("id") or "")
            mask_states = check.get("mask_states", {})
            states[check_id] = (
                mask_states.get(mask_id)
                if isinstance(mask_states, dict)
                else None
            )
        rows.append(
            {
                "mask_id": mask_id,
                "geometry": _mask_geometry(mask),
                "states_by_check": states,
            }
        )
    return rows


def _check_configuration(check: dict, masks: list[dict]) -> dict:
    states = check.get("mask_states", {})
    states = states if isinstance(states, dict) else {}
    active_ids = [str(mask.get("id") or "") for mask in masks if isinstance(mask, dict)]
    counts = {
        DISPLAY_CHECK_STATE_ON: 0,
        DISPLAY_CHECK_STATE_OFF: 0,
        DISPLAY_CHECK_STATE_IGNORE: 0,
        "unconfigured": 0,
    }
    for mask_id in active_ids:
        state = states.get(mask_id)
        if state in counts:
            counts[state] += 1
        else:
            counts["unconfigured"] += 1
    return {
        "check_id": str(check.get("id") or ""),
        "check_name": str(check.get("name") or check.get("id") or ""),
        "mask_states": _safe_deepcopy(states),
        "counts": counts,
    }


def _run_check_analyses(
    repository,
    matcher,
    frame,
    project_name: str,
    checks: list[dict],
    rotation: int,
) -> list[dict]:
    exact = F3ExactCheckTemplateAnalyzer(repository)
    learned = F3SameMaskReferenceAnalyzer(repository)
    rows = []
    for check in checks:
        check_id = str(check.get("id") or "")
        if not check_id:
            continue
        row = {
            "check_id": check_id,
            "check_name": str(check.get("name") or check_id),
        }
        try:
            row["exact_template"] = _safe_deepcopy(
                exact.analyze(
                    frame=frame,
                    project_name=project_name,
                    check_id=check_id,
                    visual_rotation=rotation,
                )
            )
        except Exception as exc:
            row["exact_template"] = {
                "ready": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        try:
            row["check_photo_learning"] = _safe_deepcopy(
                learned.analyze(
                    frame=frame,
                    project_name=project_name,
                    check_id=check_id,
                    visual_rotation=rotation,
                )
            )
        except Exception as exc:
            row["check_photo_learning"] = {
                "ready": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        try:
            row["power_mask_evidence"] = _safe_deepcopy(
                physical_policy_module.avaliar_evidencia_energia_check_pelas_mascaras_f3(
                    repository=repository,
                    matcher=matcher,
                    frame=frame,
                    project_name=project_name,
                    check_id=check_id,
                )
            )
        except Exception as exc:
            row["power_mask_evidence"] = {
                "available": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        rows.append(row)
    return rows


def _physical_diagnostics(
    repository,
    matcher,
    frame,
    project_name: str,
    context: dict | None,
    reference_rows: list[dict],
) -> dict:
    result = {}
    current_check_id = str((context or {}).get("check_id") or "")
    try:
        raw = exact_module.classificar_estado_fisico_por_gabaritos_f3(
            matcher,
            frame,
            project_name,
        )
    except Exception as exc:
        raw = {
            "kind": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }
    result["raw_exact_reference_classifier"] = _safe_deepcopy(raw)

    corrected = _safe_deepcopy(raw)
    try:
        corrected = physical_policy_module.corrigir_falso_check_ligado_pelas_mascaras_f3(
            repository=repository,
            matcher=matcher,
            frame=frame,
            project_name=project_name,
            state=raw,
        )
    except Exception as exc:
        corrected = _safe_deepcopy(raw)
        corrected["power_correction_error"] = f"{type(exc).__name__}: {exc}"
    result["after_power_mask_correction"] = _safe_deepcopy(corrected)

    try:
        contextual = physical_policy_module.aplicar_contexto_ao_estado_fisico_f3(
            corrected,
            current_check_id=current_check_id,
        )
    except Exception as exc:
        contextual = _safe_deepcopy(corrected)
        contextual["context_error"] = f"{type(exc).__name__}: {exc}"
    result["for_current_logical_check"] = _safe_deepcopy(contextual)

    presence = _presence_summary_from_rows(reference_rows)
    result["presence_summary"] = presence
    if current_check_id:
        try:
            energy = physical_policy_module.avaliar_evidencia_energia_check_pelas_mascaras_f3(
                repository=repository,
                matcher=matcher,
                frame=frame,
                project_name=project_name,
                check_id=current_check_id,
            )
        except Exception as exc:
            energy = {
                "available": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        result["current_check_power_mask_evidence"] = _safe_deepcopy(energy)
        try:
            unknown_candidate = unknown_debug_module.resolver_unknown_com_evidencia_off_f3(
                contextual,
                evidence=energy,
                off_score=presence.get("off_score"),
                off_threshold=presence.get("off_threshold"),
                empty_score=presence.get("empty_score"),
                board_references_complete=bool(presence.get("board_references_complete")),
            )
        except Exception as exc:
            unknown_candidate = {
                "error": f"{type(exc).__name__}: {exc}",
            }
        result["unknown_to_off_candidate_without_debounce"] = _safe_deepcopy(
            unknown_candidate
        )
    return result


def capturar_snapshot_debug_display_f3(app) -> dict:
    """Executa diagnóstico completo sem alterar a sequência produtiva."""
    captured_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")
    frame, capture = _freeze_current_frame(app)
    snapshot = {
        "source": F3_MANUAL_SNAPSHOT_SOURCE,
        "captured_at": captured_at,
        "capture": capture,
        "errors": [],
    }
    if frame is None or getattr(frame, "size", 0) == 0:
        reason = str((capture or {}).get("reason") or "camera_sem_frame")
        snapshot["errors"].append(reason)
        snapshot["report_ready"] = False
        return snapshot

    snapshot["frame"] = _frame_statistics(frame)
    snapshot["rotation"] = _rotation(app)
    snapshot["logical_context"] = _current_context(app)

    # Tudo abaixo é capturado AGORA, antes de análises custosas. Assim textos,
    # cores, visor e contexto pertencem ao mesmo instante do frame.
    snapshot["runtime_at_click"] = _runtime_state_at_frame(app)
    snapshot["visual_state"] = _window_visual_state(app)
    snapshot["camera_settings_at_frame"] = _camera_settings_at_frame(app)

    repository = getattr(app, "display_project_repository", None)
    if repository is None:
        snapshot["errors"].append("repository_display_indisponivel")
        snapshot["report_ready"] = False
        return snapshot

    try:
        project_name = str(repository.obter_projeto_ativo() or "")
    except Exception as exc:
        project_name = ""
        snapshot["errors"].append(f"erro_projeto_ativo:{type(exc).__name__}:{exc}")
    snapshot["project_name"] = project_name
    snapshot["config_file"] = str(getattr(repository, "config_file", "--"))
    if not project_name:
        snapshot["errors"].append("projeto_display_ativo_ausente")
        snapshot["report_ready"] = False
        return snapshot

    project, checks = _project_and_checks(repository, project_name)
    masks = [
        item for item in (project.get("masks", []) or []) if isinstance(item, dict)
    ]
    snapshot["project"] = {
        "name": project_name,
        "master_resolution": _safe_deepcopy(project.get("master_resolution")),
        "mask_count": len(masks),
        "check_count": len(checks),
        "updated_at": project.get("updated_at"),
    }
    snapshot["check_configuration"] = [
        _check_configuration(check, masks) for check in checks
    ]
    snapshot["mask_configuration"] = _configured_masks(project, checks)

    matcher = DisplayVisualReferenceMatcher(repository)
    references = _reference_rows(matcher, frame, project_name)
    snapshot["reference_analysis"] = references
    snapshot["physical_analysis"] = _physical_diagnostics(
        repository,
        matcher,
        frame,
        project_name,
        snapshot.get("logical_context"),
        references,
    )
    snapshot["check_analyses"] = _run_check_analyses(
        repository,
        matcher,
        frame,
        project_name,
        checks,
        int(snapshot["rotation"]),
    )

    try:
        from src.platform.display_live_roi_overlay import (
            montar_contexto_overlay_snapshot_display_f3,
        )

        runtime_analysis = (
            snapshot.get("runtime_at_click", {}).get("last_auto_analysis")
        )
        logical_context = snapshot.get("logical_context") or {}
        overlay_context = montar_contexto_overlay_snapshot_display_f3(
            repository,
            project_name,
            str(logical_context.get("check_id") or ""),
            runtime_analysis if isinstance(runtime_analysis, dict) else None,
            int(snapshot.get("rotation", 0) or 0),
        )
    except Exception as exc:
        overlay_context = None
        snapshot["errors"].append(
            f"overlay_snapshot:{type(exc).__name__}:{exc}"
        )
    snapshot["overlay_context"] = _safe_deepcopy(overlay_context)

    snapshot["report_ready"] = True
    # O frame bruto não é persistido na estrutura textual; o hash identifica a
    # cópia usada em todos os cálculos desta execução.
    return snapshot


def _json(value) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(value)


def _append_analysis_summary(lines: list[str], title: str, analysis: dict | None) -> None:
    lines.append(title)
    data = analysis if isinstance(analysis, dict) else {}
    lines.append(
        " | ".join(
            (
                f"ready={data.get('ready', '--')}",
                f"approved={data.get('approved', '--')}",
                f"reason={data.get('reason', '--')}",
                f"authority={data.get('reference_authority', '--')}",
                f"matched={data.get('matched_mask_count', '--')}/{data.get('active_mask_count', '--')}",
                f"ignored={data.get('ignored_mask_count', '--')}",
            )
        )
    )
    presence = data.get("presence_reference")
    if isinstance(presence, dict):
        lines.append(
            "presence "
            + " | ".join(
                (
                    f"configured={presence.get('configured', '--')}",
                    f"available={presence.get('available', '--')}",
                    f"matched={presence.get('matched', '--')}",
                    f"score={_fmt(presence.get('score'))}",
                    f"threshold={_fmt(presence.get('threshold'))}",
                    f"role={presence.get('role', '--')}",
                )
            )
        )
    for item in data.get("mask_results", []) or []:
        if not isinstance(item, dict):
            continue
        distances = item.get("distances") if isinstance(item.get("distances"), dict) else {}
        features = item.get("features") if isinstance(item.get("features"), dict) else {}
        lines.append(
            "mask "
            + " | ".join(
                (
                    f"id={item.get('mask_id', '--')}",
                    f"expected={item.get('expected', '--')}",
                    f"classified={item.get('classified', '--')}",
                    f"matched={_yes_no(item.get('matched'))}",
                    f"confidence={_fmt(item.get('confidence'))}",
                    f"template_sim={_fmt(item.get('template_similarity'))}",
                    f"template_threshold={_fmt(item.get('template_threshold'))}",
                    f"pixel_sim={_fmt(item.get('pixel_similarity'))}",
                    f"energy_sim={_fmt(item.get('energy_similarity'))}",
                    f"v_ref={_fmt(item.get('reference_v_mean'), 2)}",
                    f"v_live={_fmt(item.get('current_v_mean'), 2)}",
                    f"d_on={_fmt(distances.get(DISPLAY_CHECK_STATE_ON))}",
                    f"d_off={_fmt(distances.get(DISPLAY_CHECK_STATE_OFF))}",
                    f"separation={_fmt(item.get('reference_separation'))}",
                    f"low_light_interp={_fmt(item.get('low_light_interpolation'))}",
                    f"v_mean={_fmt(features.get('v_mean'), 2)}",
                    f"v_p95={_fmt(features.get('v_p95'), 2)}",
                    f"v_p99={_fmt(features.get('v_p99'), 2)}",
                    f"glow={_fmt(features.get('glow_score'))}",
                    f"source={item.get('reference_source', '--')}",
                )
            )
        )
        if item.get("reference_checks") is not None:
            lines.append("  reference_checks=" + _json(item.get("reference_checks")).replace("\n", " "))
    lines.append("")


def montar_relatorio_snapshot_display_f3(snapshot: dict) -> str:
    """Texto estático: abrir/copiar nunca volta a consultar a câmera ao vivo."""
    lines = [
        "ODIN DISPLAY F3 - ANÁLISE MANUAL DE FRAME",
        f"source={snapshot.get('source', '--')}",
        f"capturado_em={snapshot.get('captured_at', '--')}",
        f"projeto={snapshot.get('project_name', '--')}",
        f"config_file={snapshot.get('config_file', '--')}",
        f"frame_id={((snapshot.get('capture') or {}).get('frame_id', '--'))}",
        f"frame_id_estavel={_yes_no((snapshot.get('capture') or {}).get('stable_frame_id'))}",
        f"frame_source={((snapshot.get('capture') or {}).get('source', '--'))}",
        f"live_camera_ignored={_yes_no((snapshot.get('capture') or {}).get('live_camera_ignored'))}",
        f"visual_rotation={snapshot.get('rotation', '--')}",
        f"frame_sha256_24={((snapshot.get('frame') or {}).get('sha256_24', '--'))}",
        "",
        "IMPORTANTE: todos os cálculos [FRAME], [REFERÊNCIAS], [ESTADO FÍSICO],",
        "[CHECKS] e [MÁSCARAS] abaixo foram executados sobre a MESMA cópia congelada.",
        (
            "Com NG congelado, essa cópia é o FRAME EXATO QUE ATESTOU O NG; a câmera "
            "ao vivo usada para detectar PLACA FORA DO SUPORTE é ignorada pelo DEBUG."
            if ((snapshot.get("capture") or {}).get("source") == "ng_evidence_frozen")
            else "Sem NG congelado, a cópia é o frame capturado ao clicar em ANALISAR."
        ),
        "Abrir DEBUG TÉCNICO não recalcula nada.",
        "",
    ]

    if snapshot.get("errors"):
        lines.append("[ERROS DE CAPTURA / CONTEXTO]")
        lines.extend(str(item) for item in snapshot.get("errors") or [])
        lines.append("")

    lines.append("[CAPTURA DO FRAME]")
    lines.append(_json(snapshot.get("capture")))
    lines.append("")

    lines.append("[ANÁLISE DA IMAGEM / FRAME CONGELADO]")
    lines.append(_json(snapshot.get("frame")))
    lines.append("")

    lines.append("[CHECK LÓGICO NO INSTANTE DO CLIQUE]")
    lines.append(_json(snapshot.get("logical_context")))
    lines.append("")

    lines.append("[PROJETO DISPLAY]")
    lines.append(_json(snapshot.get("project")))
    lines.append("")

    lines.append("[REFERÊNCIAS VISUAIS / PRESENÇA / SCORE - MESMO FRAME]")
    rows = snapshot.get("reference_analysis") or []
    if not rows:
        lines.append("sem_referencias_calculadas")
    for row in rows:
        if not isinstance(row, dict):
            continue
        lines.append(
            " | ".join(
                (
                    f"rank={row.get('rank', '--')}",
                    f"key={row.get('key', '--')}",
                    f"name={row.get('name', '--')}",
                    f"configured={_yes_no(row.get('configured'))}",
                    f"score={_fmt(row.get('score'))}",
                    f"threshold={_fmt(row.get('threshold'))}",
                    f"margin_threshold={_fmt(row.get('margin_to_threshold'))}",
                    f"matched={_yes_no(row.get('matched'))}",
                    f"margin_second={_fmt(row.get('margin_to_second'))}",
                    f"mode={row.get('comparison_mode', '--')}",
                    f"roi={row.get('roi', '--')}",
                    f"path={row.get('image_path', '--')}",
                    f"error={row.get('error', '--')}",
                )
            )
        )
    lines.append("")

    lines.append("[ANÁLISE FÍSICA - SEM DEBOUNCE / MESMO FRAME]")
    lines.append(_json(snapshot.get("physical_analysis")))
    lines.append("")

    lines.append("[CONFIGURAÇÃO DOS CHECKS]")
    for check in snapshot.get("check_configuration") or []:
        lines.append(
            f"CHECK {check.get('check_name', check.get('check_id', '--'))} | id={check.get('check_id', '--')} | counts={check.get('counts', {})}"
        )
        lines.append("mask_states=" + _json(check.get("mask_states")).replace("\n", " "))
    lines.append("")

    lines.append("[GEOMETRIA E ESTADO DE TODAS AS MÁSCARAS POR CHECK]")
    for item in snapshot.get("mask_configuration") or []:
        lines.append(
            f"mask={item.get('mask_id', '--')} | geometry={_json(item.get('geometry')).replace(chr(10), ' ')} | states={_json(item.get('states_by_check')).replace(chr(10), ' ')}"
        )
    lines.append("")

    lines.append("[COMPARAÇÃO DO MESMO FRAME CONTRA TODOS OS CHECKS]")
    for row in snapshot.get("check_analyses") or []:
        lines.append(
            f"===== CHECK {row.get('check_name', row.get('check_id', '--'))} | id={row.get('check_id', '--')} ====="
        )
        _append_analysis_summary(
            lines,
            "[GABARITO EXATO DA FOTO DO CHECK]",
            row.get("exact_template"),
        )
        _append_analysis_summary(
            lines,
            "[APRENDIZADO ACESO/APAGADO DAS FOTOS DOS CHECKS]",
            row.get("check_photo_learning"),
        )
        evidence = row.get("power_mask_evidence")
        lines.append("[EVIDÊNCIA DE ENERGIA: CHECK x PLACA DESLIGADA]")
        if isinstance(evidence, dict):
            lines.append(
                " | ".join(
                    (
                        f"available={_yes_no(evidence.get('available'))}",
                        f"off_confirmed={_yes_no(evidence.get('off_confirmed'))}",
                        f"expected_on={evidence.get('expected_on_mask_count', '--')}",
                        f"off_votes={evidence.get('off_votes', '--')}",
                        f"powered_votes={evidence.get('powered_votes', '--')}",
                        f"tie_votes={evidence.get('tie_votes', '--')}",
                        f"valid_votes={evidence.get('valid_votes', '--')}",
                        f"reason={evidence.get('reason', '--')}",
                        f"error={evidence.get('error', '--')}",
                    )
                )
            )
            for detail in evidence.get("details", []) or []:
                lines.append(
                    "power_mask "
                    + " | ".join(
                        (
                            f"id={detail.get('mask_id', '--')}",
                            f"winner={detail.get('winner', '--')}",
                            f"distance_off={_fmt(detail.get('distance_off'))}",
                            f"distance_check={_fmt(detail.get('distance_check'))}",
                            f"reference_span={_fmt(detail.get('reference_span'))}",
                            f"separation={_fmt(detail.get('separation'))}",
                        )
                    )
                )
        lines.append("")

    lines.append("[RUNTIME PRODUTIVO OBSERVADO NO MESMO CLIQUE]")
    lines.append(
        "Este bloco é apenas contexto do runtime. Ele NÃO é usado para recalcular o snapshot acima."
    )
    lines.append(_json(snapshot.get("runtime_at_click")))
    lines.append("")

    lines.append("[LEITURA RÁPIDA PARA SUPORTE]")
    physical = snapshot.get("physical_analysis") or {}
    raw = physical.get("raw_exact_reference_classifier") or {}
    corrected = physical.get("after_power_mask_correction") or {}
    contextual = physical.get("for_current_logical_check") or {}
    unknown_candidate = physical.get("unknown_to_off_candidate_without_debounce") or {}
    lines.append(f"physical_raw_kind={raw.get('kind', '--')}")
    lines.append(f"physical_raw_text={raw.get('text', '--')}")
    lines.append(f"physical_after_power_kind={corrected.get('kind', '--')}")
    lines.append(f"physical_for_logical_check_kind={contextual.get('kind', '--')}")
    lines.append(f"physical_for_logical_check_allow_auto={contextual.get('allow_auto', '--')}")
    lines.append(f"unknown_off_candidate_kind={unknown_candidate.get('kind', '--')}")
    if rows:
        lines.append(
            "best_reference="
            + str(rows[0].get("name", rows[0].get("key", "--")))
            + f" | score={_fmt(rows[0].get('score'))} | threshold={_fmt(rows[0].get('threshold'))}"
        )
    lines.append("")
    lines.append("Cole este bloco inteiro na conversa/chamado de debug do Display F3.")
    return "\n".join(lines)


def _set_button_text_temporarily(button, text: str, reset_text: str = "ANALISAR", delay_ms: int = 1200):
    try:
        button.configure(text=text)
        button.after(delay_ms, lambda: button.configure(text=reset_text))
    except Exception:
        pass


def _capture_from_window(window) -> dict | None:
    app = getattr(window, "_display_f3_manual_debug_owner", None)
    if app is None:
        app = getattr(window, "_display_f3_debug_owner", None)
    button = getattr(window, "f3_manual_analyze_button", None)
    debug_button = getattr(window, "f3_snapshot_debug_button", None)
    if app is None:
        if button is not None:
            _set_button_text_temporarily(button, "SEM CONTEXTO")
        return None

    try:
        if button is not None:
            button.configure(text="ANALISANDO...", state=tk.DISABLED, cursor="arrow")
            button.update_idletasks()
    except Exception:
        pass

    snapshot = capturar_snapshot_debug_display_f3(app)
    if not bool(snapshot.get("report_ready")):
        # Mesmo uma falha de contexto é preservada quando houve frame, pois pode
        # ser útil para suporte. Sem frame não habilitamos um relatório vazio.
        if (snapshot.get("frame") or {}).get("available"):
            report = montar_relatorio_snapshot_display_f3(snapshot)
            window._display_f3_manual_snapshot = _safe_deepcopy(snapshot)
            window._display_f3_manual_snapshot_report = report
            if debug_button is not None:
                try:
                    debug_button.configure(state=tk.NORMAL, cursor="hand2")
                except Exception:
                    pass
        if button is not None:
            try:
                button.configure(state=tk.NORMAL, cursor="hand2")
            except Exception:
                pass
            _set_button_text_temporarily(button, "ANÁLISE INCOMPLETA")
        return snapshot

    report = montar_relatorio_snapshot_display_f3(snapshot)
    window._display_f3_manual_snapshot = _safe_deepcopy(snapshot)
    window._display_f3_manual_snapshot_report = report
    window._display_f3_manual_snapshot_serial = int(
        getattr(window, "_display_f3_manual_snapshot_serial", 0) or 0
    ) + 1

    # Se havia um debug de snapshot anterior aberto, fecha para impedir que o
    # operador confunda o relatório velho com o novo frame.
    try:
        window.close_f3_snapshot_debug()
    except Exception:
        pass

    if debug_button is not None:
        try:
            debug_button.configure(state=tk.NORMAL, cursor="hand2")
        except Exception:
            pass
    if button is not None:
        try:
            button.configure(state=tk.NORMAL, cursor="hand2")
        except Exception:
            pass
        _set_button_text_temporarily(button, "ANALISADO")
    return snapshot


def _open_snapshot_debug(window):
    report = str(getattr(window, "_display_f3_manual_snapshot_report", "") or "")
    if not report:
        return None

    existing = getattr(window, "_display_f3_snapshot_debug_window", None)
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.deiconify()
                existing.lift()
                existing.focus_force()
                return existing
        except Exception:
            pass

    top = tk.Toplevel(window.root)
    window._display_f3_snapshot_debug_window = top
    top.title("ODIN • DISPLAY F3 • DEBUG DO FRAME ANALISADO")
    top.configure(bg=DEBUG_BG)
    fit_f3_toplevel(
        top,
        window.root,
        preferred_width=1080,
        preferred_height=700,
        min_width=760,
        min_height=520,
    )
    top.minsize(780, 500)

    shell = tk.Frame(top, bg=DEBUG_BG)
    shell.pack(fill="both", expand=True, padx=14, pady=14)

    tk.Label(
        shell,
        text="DEBUG TÉCNICO • FRAME ANALISADO",
        font=("DejaVu Sans", 12, "bold"),
        bg=DEBUG_BG,
        fg=DEBUG_TEXT,
        anchor="w",
    ).pack(fill="x")
    snapshot = getattr(window, "_display_f3_manual_snapshot", {}) or {}
    frame_id = (snapshot.get("capture") or {}).get("frame_id", "--")
    sha = (snapshot.get("frame") or {}).get("sha256_24", "--")
    tk.Label(
        shell,
        text=f"Frame {frame_id} • hash {sha} • conteúdo congelado no clique em ANALISAR",
        font=("DejaVu Sans", 9),
        bg=DEBUG_BG,
        fg=DEBUG_MUTED,
        anchor="w",
    ).pack(fill="x", pady=(2, 8))

    text_shell = tk.Frame(
        shell,
        bg=DEBUG_PANEL,
        highlightbackground=DEBUG_BORDER,
        highlightthickness=1,
    )
    text_shell.pack(fill="both", expand=True)
    text_shell.grid_rowconfigure(0, weight=1)
    text_shell.grid_columnconfigure(0, weight=1)

    text = tk.Text(
        text_shell,
        wrap="none",
        bg=DEBUG_PANEL,
        fg=DEBUG_TEXT,
        insertbackground=DEBUG_TEXT,
        selectbackground="#164E63",
        selectforeground="#FFFFFF",
        relief="flat",
        bd=0,
        font=("DejaVu Sans Mono", 9),
        padx=10,
        pady=10,
    )
    vertical = tk.Scrollbar(text_shell, orient="vertical", command=text.yview)
    horizontal = tk.Scrollbar(text_shell, orient="horizontal", command=text.xview)
    text.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    text.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal.grid(row=1, column=0, sticky="ew")
    text.insert("1.0", report)
    text.configure(state="disabled")
    window._display_f3_snapshot_debug_text = text

    actions = tk.Frame(shell, bg=DEBUG_BG)
    actions.pack(fill="x", pady=(10, 0))

    def copy_all():
        content = str(getattr(window, "_display_f3_manual_snapshot_report", "") or "")
        try:
            top.clipboard_clear()
            top.clipboard_append(content)
            top.update()
        except Exception:
            pass

    tk.Button(
        actions,
        text="COPIAR TUDO",
        command=copy_all,
        font=("DejaVu Sans", 9, "bold"),
        bg=DEBUG_ACTION,
        fg="#FFFFFF",
        activebackground=DEBUG_ACTION_ACTIVE,
        activeforeground="#FFFFFF",
        relief="flat",
        bd=0,
        padx=12,
        pady=7,
        cursor="hand2",
    ).pack(side="left")
    tk.Button(
        actions,
        text="FECHAR",
        command=window.close_f3_snapshot_debug,
        font=("DejaVu Sans", 9, "bold"),
        bg="#1E293B",
        fg=DEBUG_TEXT,
        activebackground="#334155",
        activeforeground="#FFFFFF",
        relief="flat",
        bd=0,
        padx=12,
        pady=7,
        cursor="hand2",
    ).pack(side="right")

    top.protocol("WM_DELETE_WINDOW", window.close_f3_snapshot_debug)
    top.bind("<Escape>", lambda _event: window.close_f3_snapshot_debug())
    return top


def _close_snapshot_debug(window):
    top = getattr(window, "_display_f3_snapshot_debug_window", None)
    window._display_f3_snapshot_debug_window = None
    window._display_f3_snapshot_debug_text = None
    if top is not None:
        try:
            top.destroy()
        except Exception:
            pass


def _destroy_widget(owner, attribute: str) -> None:
    widget = getattr(owner, attribute, None)
    if widget is not None:
        try:
            widget.destroy()
        except Exception:
            pass
    try:
        setattr(owner, attribute, None)
    except Exception:
        pass


def _install_owner_bridge() -> None:
    cls = DisplayProductionF3Mixin
    if bool(getattr(cls, "_display_f3_manual_snapshot_owner_bridge_installed", False)):
        return
    original_create = cls._criar_janela_producao_display_f3

    def create(self):
        window = original_create(self)
        window._display_f3_manual_debug_owner = self
        return window

    cls._criar_janela_producao_display_f3 = create
    cls._display_f3_manual_snapshot_owner_bridge_installed = True


def _install_window_controls() -> None:
    cls = DisplayProductionF3Window
    if bool(getattr(cls, "_display_f3_manual_snapshot_controls_installed", False)):
        return
    original_init = cls.__init__

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)

        # Remove o DEBUG ao vivo anterior e o toggle OFF/ON. O backend produtivo
        # permanece em modo debug-off/custo-zero; diagnóstico passa a ser apenas
        # manual e baseado em snapshot.
        _destroy_widget(self, "technical_debug_button")
        _destroy_widget(self, "technical_debug_toggle")
        try:
            self._display_f3_technical_debug_enabled = False
        except Exception:
            pass

        self._display_f3_manual_snapshot = None
        self._display_f3_manual_snapshot_report = ""
        self._display_f3_manual_snapshot_serial = 0
        self._display_f3_snapshot_debug_window = None
        self._display_f3_snapshot_debug_text = None

        analyze = tk.Button(
            self.project_frame,
            text="ANALISAR",
            command=lambda owner=self: owner.capture_f3_snapshot_analysis(),
            font=("DejaVu Sans", 8, "bold"),
            bg="#0E7490",
            fg="#FFFFFF",
            activebackground="#0891B2",
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=11,
            pady=6,
            cursor="hand2",
        )
        analyze.grid(
            row=0,
            column=2,
            rowspan=2,
            sticky="e",
            padx=(0, 8),
            pady=7,
        )
        self.f3_manual_analyze_button = analyze

        debug = tk.Button(
            self.project_frame,
            text="DEBUG TÉCNICO",
            command=lambda owner=self: owner.open_f3_snapshot_debug(),
            font=("DejaVu Sans", 8, "bold"),
            bg="#1E293B",
            fg="#94A3B8",
            activebackground="#334155",
            activeforeground="#FFFFFF",
            disabledforeground="#64748B",
            relief="flat",
            bd=0,
            padx=11,
            pady=6,
            cursor="arrow",
            state=tk.DISABLED,
        )
        debug.grid(
            row=0,
            column=3,
            rowspan=2,
            sticky="e",
            padx=(0, 10),
            pady=7,
        )
        self.f3_snapshot_debug_button = debug

    cls.capture_f3_snapshot_analysis = lambda self: _capture_from_window(self)
    cls.open_f3_snapshot_debug = lambda self: _open_snapshot_debug(self)
    cls.close_f3_snapshot_debug = lambda self: _close_snapshot_debug(self)
    cls.__init__ = init
    cls._display_f3_manual_snapshot_controls_installed = True


_INSTALLED = False


def instalar_analise_manual_snapshot_display_f3() -> None:
    """Instala ANALISAR + DEBUG TÉCNICO estático como última camada do F3."""
    global _INSTALLED
    if _INSTALLED:
        return
    _install_owner_bridge()
    _install_window_controls()
    _INSTALLED = True
