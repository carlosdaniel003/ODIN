from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import tkinter as tk

import src.platform.display_auto_check_runtime as runtime_module
import src.platform.display_f3_exact_check_template as exact_module
import src.platform.display_f3_operational_status as operational_module
import src.platform.display_f3_unknown_debug_fix as debug_module
from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin
from src.platform.display_f3_exact_check_template import F3ExactCheckTemplateAnalyzer
from src.platform.display_production_f3_window import DisplayProductionF3Window
from src.platform.display_visual_reference_status import (
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
    DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
    DISPLAY_PROJECT_REFERENCE_TYPES,
)


F3_LIVE_TRACE_MAX_FRAMES = 180
F3_LIVE_TRACE_DETAIL_FRAMES = 48
F3_LIVE_DEBUG_REFRESH_MS = 450
F3_EXACT_PROBE_SOURCE = "f3_expected_check_exact_live_probe"


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt(value, digits: int = 4) -> str:
    number = _safe_float(value)
    return "--" if number is None else f"{number:.{digits}f}"


def _bool(value) -> str:
    return "SIM" if bool(value) else "NÃO"


def _frame_token(app, frame):
    token = getattr(app, "camera_ultimo_frame_id", None)
    if isinstance(token, int) and token >= 0:
        return ("camera", int(token))
    return ("object", id(frame))


def _rotation(app) -> int:
    try:
        return int(app._obter_rotacao_visual_display_f3())
    except Exception:
        return int(getattr(app, "visual_rotation", 0) or 0)


def _context(app):
    try:
        value = app._display_auto_current_context()
    except Exception:
        value = None
    return deepcopy(value) if isinstance(value, dict) else None


def _project_name(app) -> str:
    repository = getattr(app, "display_project_repository", None)
    if repository is None:
        return ""
    try:
        return str(repository.obter_projeto_ativo() or "")
    except Exception:
        return ""


def _reference_name_map(repository, project_name: str) -> dict[str, str]:
    names = {
        "empty": "SUPORTE_VAZIO",
        "off": "PLACA_DESLIGADA",
    }
    if repository is None or not project_name:
        return names
    try:
        checks = repository.listar_checks(project_name)
    except Exception:
        checks = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        check_id = str(check.get("id") or "")
        if not check_id:
            continue
        names[f"check:{check_id}"] = str(
            check.get("name") or check_id
        ).strip().upper()
    return names


def _reference_rows_full_roi(app, frame, project_name: str) -> list[dict]:
    """Scores técnicos usando o mesmo pipeline ROI-primeiro do gabarito exato."""
    repository = getattr(app, "display_project_repository", None)
    matcher = getattr(app, "_display_f3_operational_matcher", None)
    if repository is None or matcher is None or frame is None:
        return []

    candidates = exact_module._physical_candidates(matcher, project_name)
    rows = []
    for candidate in candidates:
        metadata = candidate.get("metadata")
        score = exact_module._score_reference_full_roi(frame, metadata)
        threshold = matcher._threshold(metadata) if isinstance(metadata, dict) else None
        rows.append(
            {
                "key": str(candidate.get("key") or ""),
                "name": str(candidate.get("name") or candidate.get("key") or ""),
                "configured": isinstance(metadata, dict),
                "score": _safe_float(score),
                "threshold": _safe_float(threshold),
                "matched": bool(
                    score is not None
                    and threshold is not None
                    and float(score) >= float(threshold)
                ),
                "comparison_mode": "full_resolution_roi_first",
                "roi": deepcopy((metadata or {}).get("roi")) if isinstance(metadata, dict) else None,
            }
        )
    return sorted(
        rows,
        key=lambda item: _safe_float(item.get("score"), -1.0),
        reverse=True,
    )


def _presence_scores_full_roi(matcher, frame, project_name: str) -> dict:
    """Corrige o fallback UNKNOWN->OFF: nunca usa miniatura antes da ROI."""
    references = matcher.project_store.get_all(project_name)
    board_complete = all(kind in references for kind in DISPLAY_PROJECT_REFERENCE_TYPES)
    off_metadata = references.get(DISPLAY_PROJECT_REFERENCE_BOARD_OFF)
    empty_metadata = references.get(DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT)
    off_score = exact_module._score_reference_full_roi(frame, off_metadata)
    empty_score = exact_module._score_reference_full_roi(frame, empty_metadata)
    return {
        "board_references_complete": board_complete,
        "off_score": _safe_float(off_score),
        "off_threshold": (
            _safe_float(matcher._threshold(off_metadata))
            if isinstance(off_metadata, dict)
            else None
        ),
        "empty_score": _safe_float(empty_score),
        "empty_threshold": (
            _safe_float(matcher._threshold(empty_metadata))
            if isinstance(empty_metadata, dict)
            else None
        ),
        "comparison_mode": "full_resolution_roi_first",
    }


def _probe_analyzer(app):
    repository = getattr(app, "display_project_repository", None)
    analyzer = getattr(app, "_display_f3_live_probe_analyzer", None)
    if analyzer is None or getattr(analyzer, "repository", None) is not repository:
        analyzer = F3ExactCheckTemplateAnalyzer(repository) if repository is not None else None
        app._display_f3_live_probe_analyzer = analyzer
    return analyzer


def _probe_expected_check(app, frame, context: dict | None) -> dict | None:
    if not isinstance(context, dict):
        return None
    analyzer = _probe_analyzer(app)
    if analyzer is None:
        return None
    try:
        return analyzer.analyze(
            frame=frame,
            project_name=str(context.get("project_name") or ""),
            check_id=str(context.get("check_id") or ""),
            visual_rotation=_rotation(app),
        )
    except Exception as exc:
        return {
            "ready": False,
            "approved": None,
            "reason": "erro_sonda_gabarito_exato",
            "error": f"{type(exc).__name__}: {exc}",
            "mask_results": [],
            "reference_authority": F3_EXACT_PROBE_SOURCE,
        }


def _probe_required_frames(app, context: dict | None) -> int:
    if not isinstance(context, dict):
        return 2
    try:
        if app._display_auto_is_transient_check(context):
            return 1
    except Exception:
        pass
    return 2


def _update_positive_probe_stability(app, context: dict | None, analysis: dict | None) -> dict:
    signature = None
    if isinstance(context, dict):
        signature = (
            str(context.get("project_name") or ""),
            str(context.get("check_id") or ""),
        )
    approved = bool(isinstance(analysis, dict) and analysis.get("approved") is True)
    if approved and bool((context or {}).get("intermittent", False)):
        try:
            intermittent_ready, _seen, _total = (
                app._display_auto_update_intermittent_evidence(
                    context,
                    analysis,
                )
            )
        except Exception:
            intermittent_ready = False
        approved = bool(intermittent_ready)

    previous_signature = getattr(app, "_display_f3_live_probe_signature", None)
    frames = int(getattr(app, "_display_f3_live_probe_ok_frames", 0) or 0)

    if signature is None or not approved:
        app._display_f3_live_probe_signature = signature
        app._display_f3_live_probe_ok_frames = 0
        return {
            "approved": approved,
            "frames": 0,
            "required": _probe_required_frames(app, context),
            "confirm": False,
        }

    frames = frames + 1 if previous_signature == signature else 1
    app._display_f3_live_probe_signature = signature
    app._display_f3_live_probe_ok_frames = frames
    required = _probe_required_frames(app, context)
    return {
        "approved": True,
        "frames": frames,
        "required": required,
        "confirm": frames >= required,
    }


def _advance_positive_probe_if_needed(
    app,
    context_before: dict | None,
    analysis: dict | None,
    stability: dict,
) -> dict | None:
    if not bool(stability.get("confirm")) or not isinstance(context_before, dict):
        return None

    context_after = _context(app)
    if not isinstance(context_after, dict):
        return None
    if str(context_after.get("check_id") or "") != str(context_before.get("check_id") or ""):
        return {
            "advanced": False,
            "reason": "core_ja_avancou_check",
        }

    try:
        event = app.registrar_resultado_check_display_f3(True)
    except Exception as exc:
        return {
            "advanced": False,
            "reason": "erro_registrar_check_probe",
            "error": f"{type(exc).__name__}: {exc}",
        }

    app._display_f3_live_probe_ok_frames = 0
    app._display_f3_live_probe_signature = None

    try:
        if str((event or {}).get("event") or "") == "check_advanced":
            app._display_auto_arm_manual_entry_gate(context_before, event)
            app._display_auto_signature = None
            app._display_auto_transition_frames = app.DISPLAY_AUTO_TRANSITION_FRAMES
        else:
            app._display_auto_clear_manual_entry_gate()
            app._reset_display_auto_stability()
    except Exception:
        pass

    # O gabarito exato é evidência física positiva mais forte que um UNKNOWN/OFF
    # global. Atualizamos apenas o status informativo; o avanço já ocorreu pela
    # comparação exata das máscaras, nunca por heurística de cena inteira.
    state = {
        "kind": "check",
        "text": (
            "PLACA NO SUPORTE • LIGADA • DISPLAY EM "
            + str(context_before.get("check_name") or context_before.get("check_id") or "CHECK").strip().upper()
        ),
        "allow_auto": True,
        "check_id": str(context_before.get("check_id") or ""),
        "check_name": str(context_before.get("check_name") or "").strip().upper(),
        "physical_state_key": f"check:{context_before.get('check_id')}",
        "source": F3_EXACT_PROBE_SOURCE,
        "exact_probe_confirmed": True,
    }
    app._display_f3_operational_state = state
    window = getattr(app, "display_f3_window", None)
    if window is not None:
        try:
            window.set_operational_reference_status(
                str(state["text"]),
                operational_module.F3_OPERATIONAL_STATUS_COLORS["check"],
            )
        except Exception:
            pass

    return {
        "advanced": True,
        "event": deepcopy(event) if isinstance(event, dict) else event,
        "source": F3_EXACT_PROBE_SOURCE,
    }


def _mask_snapshot(item: dict) -> dict:
    return {
        "mask_id": str(item.get("mask_id", item.get("id", ""))),
        "expected": item.get("expected"),
        "classified": item.get("classified"),
        "matched": bool(item.get("matched")),
        "confidence": _safe_float(item.get("confidence")),
        "template_similarity": _safe_float(item.get("template_similarity")),
        "template_threshold": _safe_float(item.get("template_threshold")),
        "pixel_similarity": _safe_float(item.get("pixel_similarity")),
        "energy_similarity": _safe_float(item.get("energy_similarity")),
        "reference_v_mean": _safe_float(item.get("reference_v_mean")),
        "current_v_mean": _safe_float(item.get("current_v_mean")),
    }


def _record_live_frame(
    app,
    *,
    token,
    context: dict | None,
    analysis: dict | None,
    analysis_source: str,
    stability: dict,
    advance: dict | None,
) -> None:
    history = getattr(app, "_display_f3_live_trace", None)
    if not isinstance(history, deque):
        history = deque(maxlen=F3_LIVE_TRACE_MAX_FRAMES)
        app._display_f3_live_trace = history

    state = getattr(app, "_display_f3_operational_state", None)
    state_data = deepcopy(state) if isinstance(state, dict) else {}
    mask_results = [
        _mask_snapshot(item)
        for item in (analysis or {}).get("mask_results", [])
        if isinstance(item, dict)
    ] if isinstance(analysis, dict) else []
    similarities = [
        value
        for value in (_safe_float(item.get("template_similarity")) for item in mask_results)
        if value is not None
    ]

    record = {
        "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds"),
        "token": token,
        "frame_id": getattr(app, "camera_ultimo_frame_id", None),
        "rotation": _rotation(app),
        "context": deepcopy(context) if isinstance(context, dict) else None,
        "physical": {
            key: deepcopy(state_data.get(key))
            for key in (
                "kind",
                "text",
                "allow_auto",
                "source",
                "physical_state_key",
                "score",
                "best_score",
                "ambiguous",
                "physical_transition_pending",
                "pending_physical_state_key",
                "fast_expected_check_gate",
                "comparison_mode",
            )
        },
        "reference_scores": deepcopy(state_data.get("reference_scores") or {}),
        "analysis_source": str(analysis_source),
        "probe": {
            "ready": (analysis or {}).get("ready") if isinstance(analysis, dict) else None,
            "approved": (analysis or {}).get("approved") if isinstance(analysis, dict) else None,
            "reason": (analysis or {}).get("reason") if isinstance(analysis, dict) else None,
            "matched": int((analysis or {}).get("matched_mask_count", 0) or 0) if isinstance(analysis, dict) else 0,
            "active": int((analysis or {}).get("active_mask_count", 0) or 0) if isinstance(analysis, dict) else 0,
            "similarity_min": min(similarities) if similarities else None,
            "similarity_avg": (sum(similarities) / len(similarities)) if similarities else None,
            "similarity_max": max(similarities) if similarities else None,
            "stable_frames": int(stability.get("frames", 0) or 0),
            "required_frames": int(stability.get("required", 0) or 0),
        },
        "advance": deepcopy(advance) if isinstance(advance, dict) else advance,
        "masks": mask_results,
    }
    history.append(record)
    app._display_f3_live_trace_last_token = token
    app._display_f3_live_probe_last_analysis = deepcopy(analysis) if isinstance(analysis, dict) else None


def _geometry_lines(app, project_name: str, context: dict | None) -> list[str]:
    repository = getattr(app, "display_project_repository", None)
    if repository is None or not project_name:
        return ["geometria_indisponivel"]
    try:
        project = repository.carregar_projeto(project_name)
        check = repository.carregar_check(project_name, str((context or {}).get("check_id") or ""))
    except Exception:
        return ["erro_ao_carregar_geometria"]
    if not isinstance(project, dict):
        return ["projeto_invalido"]
    states = check.get("mask_states", {}) if isinstance(check, dict) and isinstance(check.get("mask_states"), dict) else {}
    lines = []
    for mask in project.get("masks", []) or []:
        if not isinstance(mask, dict):
            continue
        mask_id = str(mask.get("id") or "")
        fields = []
        for key in ("type", "cx", "cy", "radius", "x", "y", "width", "height", "angle", "length", "thickness", "points"):
            if key in mask:
                fields.append(f"{key}={mask.get(key)}")
        lines.append(
            f"id={mask_id} | expected={states.get(mask_id, '--')} | " + " | ".join(fields)
        )
    return lines or ["nenhuma_mascara"]


def _append_live_trace_debug(app, base: str) -> str:
    history = getattr(app, "_display_f3_live_trace", None)
    records = list(history) if isinstance(history, deque) else []
    project_name = _project_name(app)
    context = _context(app)
    name_map = _reference_name_map(
        getattr(app, "display_project_repository", None),
        project_name,
    )

    lines = [base.rstrip(), "", "[DEBUG AO VIVO]", "modo=ATIVO", f"frames_retidos={len(records)}", f"limite_frames={F3_LIVE_TRACE_MAX_FRAMES}", f"refresh_janela_ms={F3_LIVE_DEBUG_REFRESH_MS}", "pipeline_scores=ROI_PRIMEIRO_EM_RESOLUCAO_ORIGINAL", ""]

    lines.append("[GEOMETRIA / ESTADO CONFIGURADO DAS MÁSCARAS]")
    lines.extend(_geometry_lines(app, project_name, context))
    lines.append("")

    current_probe = getattr(app, "_display_f3_live_probe_last_analysis", None)
    lines.append("[MÁSCARAS AO VIVO - ÚLTIMO FRAME ANALISADO]")
    if not isinstance(current_probe, dict):
        lines.append("sem_sonda_exata_ate_agora")
    else:
        lines.append(
            " | ".join(
                (
                    f"check={current_probe.get('check_name', current_probe.get('check_id', '--'))}",
                    f"ready={_bool(current_probe.get('ready'))}",
                    f"approved={current_probe.get('approved', '--')}",
                    f"matched={current_probe.get('matched_mask_count', '--')}/{current_probe.get('active_mask_count', '--')}",
                    f"reason={current_probe.get('reason', '--')}",
                )
            )
        )
        for item in current_probe.get("mask_results", []) or []:
            if not isinstance(item, dict):
                continue
            lines.append(
                "mask "
                + " | ".join(
                    (
                        f"id={item.get('mask_id', '--')}",
                        f"expected={item.get('expected', '--')}",
                        f"classified={item.get('classified', '--')}",
                        f"matched={_bool(item.get('matched'))}",
                        f"similarity={_fmt(item.get('template_similarity'))}",
                        f"threshold={_fmt(item.get('template_threshold'))}",
                        f"pixel={_fmt(item.get('pixel_similarity'))}",
                        f"energy={_fmt(item.get('energy_similarity'))}",
                        f"v_ref={_fmt(item.get('reference_v_mean'), 2)}",
                        f"v_live={_fmt(item.get('current_v_mean'), 2)}",
                        f"confidence={_fmt(item.get('confidence'))}",
                    )
                )
            )
    lines.append("")

    lines.append("[HISTÓRICO AO VIVO - RESUMO POR FRAME]")
    if not records:
        lines.append("sem_historico")
    for record in records:
        ctx = record.get("context") or {}
        physical = record.get("physical") or {}
        probe = record.get("probe") or {}
        scores = record.get("reference_scores") or {}
        score_text = ",".join(
            f"{name_map.get(str(key), str(key))}={_fmt(value)}"
            for key, value in sorted(scores.items())
        ) or "--"
        advance = record.get("advance")
        advance_text = "SIM" if isinstance(advance, dict) and advance.get("advanced") else "NÃO"
        lines.append(
            " | ".join(
                (
                    f"t={record.get('ts', '--')}",
                    f"frame={record.get('frame_id', '--')}",
                    f"logical={ctx.get('check_name', ctx.get('check_id', '--'))}",
                    f"physical={physical.get('kind', '--')}",
                    f"source={physical.get('source', '--')}",
                    f"allow={physical.get('allow_auto', '--')}",
                    f"probe={probe.get('matched', '--')}/{probe.get('active', '--')}",
                    f"probe_ok={probe.get('approved', '--')}",
                    f"probe_stable={probe.get('stable_frames', '--')}/{probe.get('required_frames', '--')}",
                    f"sim_min={_fmt(probe.get('similarity_min'))}",
                    f"sim_avg={_fmt(probe.get('similarity_avg'))}",
                    f"refs={score_text}",
                    f"advance={advance_text}",
                )
            )
        )
    lines.append("")

    lines.append(f"[HISTÓRICO DETALHADO DE MÁSCARAS - ÚLTIMOS {F3_LIVE_TRACE_DETAIL_FRAMES} FRAMES]")
    for record in records[-F3_LIVE_TRACE_DETAIL_FRAMES:]:
        ctx = record.get("context") or {}
        lines.append(
            f"FRAME {record.get('frame_id', '--')} | {record.get('ts', '--')} | CHECK={ctx.get('check_name', ctx.get('check_id', '--'))} | SOURCE={record.get('analysis_source', '--')}"
        )
        masks = record.get("masks") or []
        if not masks:
            lines.append("  sem_resultados_de_mascara")
            continue
        for item in masks:
            lines.append(
                "  mask "
                + " | ".join(
                    (
                        f"id={item.get('mask_id', '--')}",
                        f"expected={item.get('expected', '--')}",
                        f"classified={item.get('classified', '--')}",
                        f"matched={_bool(item.get('matched'))}",
                        f"sim={_fmt(item.get('template_similarity'))}",
                        f"pixel={_fmt(item.get('pixel_similarity'))}",
                        f"energy={_fmt(item.get('energy_similarity'))}",
                        f"v_ref={_fmt(item.get('reference_v_mean'), 2)}",
                        f"v_live={_fmt(item.get('current_v_mean'), 2)}",
                        f"confidence={_fmt(item.get('confidence'))}",
                    )
                )
            )
    lines.append("")
    lines.append("Copie todo o conteúdo acima; o histórico preserva H1/BLUE mesmo que o display já tenha mudado de função.")
    return "\n".join(lines)


def _install_roi_first_debug_sources() -> None:
    debug_module._presence_scores = _presence_scores_full_roi

    def rows(app, frame, project_name: str):
        return _reference_rows_full_roi(app, frame, project_name)

    debug_module._reference_debug_rows = rows


def _install_live_trace_runtime() -> None:
    cls = runtime_module.DisplayAutomaticCheckF3Mixin
    if bool(getattr(cls, "_display_f3_live_diagnostic_trace_installed", False)):
        return
    original_process = cls._process_display_auto_check

    def process(self):
        if not bool(getattr(self, "display_f3_ativo", False)):
            return original_process(self)

        frame = getattr(self, "camera_frame_atual", None)
        if frame is None or getattr(frame, "size", 0) == 0:
            return original_process(self)

        token = _frame_token(self, frame)
        context_before = _context(self)
        result = original_process(self)

        if not isinstance(context_before, dict):
            return result
        if getattr(self, "_display_f3_live_trace_last_token", None) == token:
            return result

        # Se o core já analisou este mesmo frame, reaproveitamos o resultado para
        # não duplicar custo. Se o gate físico bloqueou o core, executamos uma
        # sonda positiva invisível com o gabarito exato do CHECK esperado.
        core_token = getattr(self, "_display_auto_last_frame_token", None)
        core_analysis = getattr(self, "_display_auto_last_analysis", None)
        if (
            core_token == token
            and isinstance(core_analysis, dict)
            and str(core_analysis.get("check_id") or "") == str(context_before.get("check_id") or "")
        ):
            analysis = deepcopy(core_analysis)
            analysis_source = "core_auto_analysis"
        else:
            analysis = _probe_expected_check(self, frame, context_before)
            analysis_source = "hidden_exact_probe"

        stability = _update_positive_probe_stability(self, context_before, analysis)
        advance = _advance_positive_probe_if_needed(
            self,
            context_before,
            analysis,
            stability,
        )
        _record_live_frame(
            self,
            token=token,
            context=context_before,
            analysis=analysis,
            analysis_source=analysis_source,
            stability=stability,
            advance=advance,
        )

        window = getattr(self, "display_f3_window", None)
        if window is not None:
            try:
                window.set_technical_debug_provider(
                    lambda owner=self: debug_module.montar_debug_tecnico_display_f3(owner)
                )
            except Exception:
                pass
        return result

    cls._process_display_auto_check = process
    cls._display_f3_live_diagnostic_trace_installed = True


def _install_debug_builder_extension() -> None:
    original_builder = debug_module.montar_debug_tecnico_display_f3
    if bool(getattr(debug_module, "_display_f3_live_trace_builder_installed", False)):
        return

    def builder(app):
        return _append_live_trace_debug(app, original_builder(app))

    debug_module.montar_debug_tecnico_display_f3 = builder
    debug_module._display_f3_live_trace_builder_installed = True


def _install_debug_live_refresh() -> None:
    cls = DisplayProductionF3Window
    if bool(getattr(cls, "_display_f3_debug_live_refresh_installed", False)):
        return

    original_open = cls.open_technical_debug
    original_close = cls.close_technical_debug

    def tick(self):
        self._display_f3_debug_live_after_id = None
        top = getattr(self, "_display_f3_debug_window", None)
        if top is None:
            return
        try:
            if not top.winfo_exists():
                return
        except Exception:
            return
        try:
            self.refresh_technical_debug()
        except Exception:
            pass
        try:
            self._display_f3_debug_live_after_id = top.after(
                F3_LIVE_DEBUG_REFRESH_MS,
                self._display_f3_debug_live_tick,
            )
        except Exception:
            self._display_f3_debug_live_after_id = None

    def open_debug(self):
        result = original_open(self)
        if getattr(self, "_display_f3_debug_live_after_id", None) is None:
            try:
                top = getattr(self, "_display_f3_debug_window", None)
                if top is not None:
                    self._display_f3_debug_live_after_id = top.after(
                        F3_LIVE_DEBUG_REFRESH_MS,
                        self._display_f3_debug_live_tick,
                    )
            except Exception:
                self._display_f3_debug_live_after_id = None
        return result

    def close_debug(self):
        after_id = getattr(self, "_display_f3_debug_live_after_id", None)
        top = getattr(self, "_display_f3_debug_window", None)
        if after_id is not None and top is not None:
            try:
                top.after_cancel(after_id)
            except Exception:
                pass
        self._display_f3_debug_live_after_id = None
        return original_close(self)

    cls._display_f3_debug_live_tick = tick
    cls.open_technical_debug = open_debug
    cls.close_technical_debug = close_debug
    cls._display_f3_debug_live_refresh_installed = True


_INSTALLED = False


def instalar_rastreio_ao_vivo_debug_display_f3() -> None:
    """Última camada F3: ROI correta, histórico por frame e debug ao vivo."""
    global _INSTALLED
    if _INSTALLED:
        return
    _install_roi_first_debug_sources()
    _install_debug_builder_extension()
    _install_debug_live_refresh()
    _install_live_trace_runtime()
    _INSTALLED = True
