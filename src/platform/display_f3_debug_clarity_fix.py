from __future__ import annotations

"""Torna o DEBUG TÉCNICO do F3 legível sem alterar qualquer decisão produtiva.

O relatório histórico mistura duas coisas diferentes:

* decisão produtiva do CHECK atual (foto do CHECK + máscaras + mask_states);
* análise visual informativa das referências de presença.

Quando várias fotos globais ficam visualmente parecidas, a segunda pode escrever
"referências muito próximas" mesmo com o CHECK produtivo 100% conforme. Este
módulo deixa essa separação explícita e também corrige no snapshot o nome do
atributo usado para registrar o rearme terminal.
"""

import src.platform.display_f3_manual_snapshot_debug as manual_module


F3_DEBUG_CLARITY_SOURCE = "f3_debug_productive_authority_clarity"
SUMMARY_MARKER = "[RESUMO OPERACIONAL - LEIA PRIMEIRO]"


def _context(snapshot: dict) -> dict:
    value = snapshot.get("logical_context")
    return dict(value) if isinstance(value, dict) else {}


def _runtime(snapshot: dict) -> dict:
    value = snapshot.get("runtime_at_click")
    return dict(value) if isinstance(value, dict) else {}


def _analysis_matches_context(analysis: dict | None, context: dict) -> bool:
    if not isinstance(analysis, dict):
        return False
    return bool(
        str(analysis.get("project_name") or "") == str(context.get("project_name") or "")
        and str(analysis.get("check_id") or "") == str(context.get("check_id") or "")
    )


def _productive_analysis(snapshot: dict) -> dict | None:
    context = _context(snapshot)
    runtime = _runtime(snapshot)
    live = runtime.get("last_auto_analysis")
    if _analysis_matches_context(live, context):
        return dict(live)

    current_id = str(context.get("check_id") or "")
    for row in snapshot.get("check_analyses") or ():
        if not isinstance(row, dict) or str(row.get("check_id") or "") != current_id:
            continue
        for key in ("exact_template", "check_photo_learning"):
            analysis = row.get(key)
            if isinstance(analysis, dict):
                return dict(analysis)
    return None


def _productive_counts(analysis: dict | None) -> tuple[int, int]:
    if not isinstance(analysis, dict):
        return 0, 0
    try:
        active = int(analysis.get("active_mask_count", 0) or 0)
        matched = int(analysis.get("matched_mask_count", 0) or 0)
    except (TypeError, ValueError):
        return 0, 0
    return max(0, matched), max(0, active)


def _safe_probability(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not (0.0 <= number <= 1.0):
        return None
    return number


def _fmt_probability(value) -> str:
    number = _safe_probability(value)
    return "--" if number is None else f"{number:.4f}"


def _neural_diagnostics(analysis: dict | None) -> dict:
    """Resume a CNN sem transformar diagnóstico em segunda autoridade.

    O relatório deve permitir distinguir três situações muito diferentes:
    modelo ausente, inferência neural incerta e divergência neural certa.
    Também publica a direção bruta por argmax apenas como instrumento de
    calibração; esse valor nunca participa de OK/NG.
    """
    if not isinstance(analysis, dict) or analysis.get("neural_visual_authority") is not True:
        return {"active": False}

    rows = [
        item
        for item in (analysis.get("mask_results") or ())
        if isinstance(item, dict) and str(item.get("mask_id") or "")
    ]
    model = analysis.get("neural_model")
    model = dict(model) if isinstance(model, dict) else {}

    uncertain_ids = []
    raw_mismatch_ids = []
    raw_matches = 0
    expected_on_probabilities = []
    expected_off_probabilities = []

    for item in rows:
        mask_id = str(item.get("mask_id") or "")
        expected = str(item.get("expected") or "").strip().lower()
        classified = str(item.get("classified") or "").strip().lower()
        certain = bool(item.get("neural_certain") is True)
        if not certain or classified == "uncertain":
            uncertain_ids.append(mask_id)

        probabilities = item.get("neural_probabilities")
        probabilities = probabilities if isinstance(probabilities, dict) else {}
        p_on = _safe_probability(probabilities.get("on"))
        p_off = _safe_probability(probabilities.get("off"))
        if p_on is None or p_off is None:
            continue

        if expected == "on":
            expected_on_probabilities.append(p_on)
        elif expected == "off":
            expected_off_probabilities.append(p_on)

        raw_state = "on" if p_on >= p_off else "off"
        if expected in ("on", "off"):
            if raw_state == expected:
                raw_matches += 1
            else:
                raw_mismatch_ids.append(mask_id)

    def stats(values):
        if not values:
            return {"min": None, "mean": None, "max": None}
        return {
            "min": min(values),
            "mean": sum(values) / float(len(values)),
            "max": max(values),
        }

    on_stats = stats(expected_on_probabilities)
    off_stats = stats(expected_off_probabilities)
    gap = None
    midpoint = None
    if on_stats["min"] is not None and off_stats["max"] is not None:
        gap = float(on_stats["min"]) - float(off_stats["max"])
        midpoint = (float(on_stats["min"]) + float(off_stats["max"])) / 2.0

    return {
        "active": True,
        "authority": str(analysis.get("reference_authority") or ""),
        "reason": str(analysis.get("reason") or ""),
        "approved": analysis.get("approved"),
        "active_mask_count": len(rows),
        "matched_mask_count": int(analysis.get("matched_mask_count", 0) or 0),
        "uncertain_count": len(uncertain_ids),
        "uncertain_mask_ids": tuple(uncertain_ids),
        "raw_argmax_match_count": int(raw_matches),
        "raw_argmax_mismatch_ids": tuple(raw_mismatch_ids),
        "expected_on_p_on": on_stats,
        "expected_off_p_on": off_stats,
        "diagnostic_separation_gap": gap,
        "diagnostic_midpoint": midpoint,
        "model_ready": bool(model.get("ready")),
        "model_reason": str(model.get("reason") or ""),
        "model_path": str(model.get("model_path") or ""),
        "input_size": model.get("input_size"),
        "on_min_on_probability": _safe_probability(
            model.get("on_min_on_probability")
        ),
        "off_max_on_probability": _safe_probability(
            model.get("off_max_on_probability")
        ),
        "load_count": model.get("load_count"),
        "batch_size": model.get("batch_size"),
        "inference_count": model.get("inference_count"),
        "conventional_visual_authority_used": bool(
            analysis.get("conventional_visual_authority_used")
        ),
    }


def construir_resumo_operacional_debug_f3(snapshot: dict) -> dict:
    context = _context(snapshot)
    runtime = _runtime(snapshot)
    state = runtime.get("operational_state")
    state = dict(state) if isinstance(state, dict) else {}
    analysis = _productive_analysis(snapshot)
    matched, active = _productive_counts(analysis)

    ready = bool(isinstance(analysis, dict) and analysis.get("ready"))
    approved = bool(ready and analysis.get("approved") is True)
    fully_matched = bool(approved and active > 0 and matched >= active)
    neural = _neural_diagnostics(analysis)

    waiting_empty = bool(runtime.get("waiting_empty_rearm"))
    waiting_new = bool(runtime.get("waiting_new_board_after_empty"))
    cycle_waiting = bool(state.get("cycle_rearm_waiting"))
    cycle_waiting_new = bool(state.get("cycle_rearmed_waiting_new_board"))

    blocked = bool(waiting_empty or waiting_new or cycle_waiting or cycle_waiting_new)
    if waiting_empty or cycle_waiting:
        flow_reason = "aguardando retirar a placa anterior e confirmar PLACA FORA DO SUPORTE"
    elif waiting_new or cycle_waiting_new:
        flow_reason = "suporte vazio confirmado; aguardando NOVA PLACA"
    else:
        flow_reason = "livre para o fluxo produtivo"

    check_name = str(context.get("check_name") or context.get("check_id") or "CHECK")
    if fully_matched:
        productive_text = f"{check_name} CONFORME {matched}/{active} máscaras"
    elif bool(neural.get("active")) and ready and int(neural.get("uncertain_count", 0) or 0) > 0:
        productive_text = (
            f"{check_name} INDETERMINADO • "
            f"{int(neural.get('uncertain_count', 0) or 0)}/{active} máscaras incertas"
        )
    elif ready:
        productive_text = f"{check_name} NÃO CONFORME {matched}/{active} máscaras"
    else:
        productive_text = f"{check_name} sem decisão produtiva pronta"

    return {
        "source": F3_DEBUG_CLARITY_SOURCE,
        "check_name": check_name,
        "check_id": str(context.get("check_id") or ""),
        "ready": ready,
        "approved": approved,
        "fully_matched": fully_matched,
        "matched_mask_count": matched,
        "active_mask_count": active,
        "productive_text": productive_text,
        "flow_blocked": blocked,
        "flow_reason": flow_reason,
        "waiting_empty_rearm": waiting_empty,
        "waiting_new_board_after_empty": waiting_new,
        "cycle_rearm_waiting": cycle_waiting,
        "cycle_rearmed_waiting_new_board": cycle_waiting_new,
        "neural": neural,
    }


def aplicar_clareza_snapshot_debug_f3(snapshot: dict, app) -> dict:
    if not isinstance(snapshot, dict):
        return snapshot

    runtime = snapshot.get("runtime_at_click")
    if not isinstance(runtime, dict):
        runtime = {}
        snapshot["runtime_at_click"] = runtime

    # O relatório antigo consultava _display_auto_waiting_empty_rearm, atributo
    # que não é a fonte real do ciclo. A autoridade correta usa prefixo _display_f3.
    runtime["waiting_empty_rearm"] = bool(
        getattr(app, "_display_f3_waiting_empty_rearm", False)
    )
    runtime["waiting_new_board_after_empty"] = bool(
        getattr(app, "_display_f3_waiting_new_board_after_empty", False)
    )
    runtime["rearm_empty_frames"] = int(
        getattr(app, "_display_f3_rearm_empty_frames", 0) or 0
    )
    runtime["new_board_frames"] = int(
        getattr(app, "_display_f3_new_board_frames", 0) or 0
    )

    summary = construir_resumo_operacional_debug_f3(snapshot)
    snapshot["operational_summary"] = summary

    visual = snapshot.get("visual_analysis")
    if isinstance(visual, dict):
        raw_status = str(visual.get("status_text") or "")
        visual["status_text_raw"] = raw_status
        visual["productive_authority_note"] = (
            "A análise visual é somente informativa e não decide OK/NG nem avanço."
        )
        if summary.get("flow_blocked"):
            visual["status_text"] = (
                f"CHECK PRODUTIVO: {summary.get('productive_text')} • "
                f"FLUXO BLOQUEADO: {summary.get('flow_reason')}"
            )
        elif summary.get("fully_matched"):
            visual["status_text"] = (
                f"CHECK PRODUTIVO: {summary.get('productive_text')} • "
                "análise visual abaixo é somente informativa"
            )
        elif str(visual.get("result_kind") or "") == "ambiguous":
            visual["status_text"] = (
                "VISUAL INFORMATIVO: referências parecidas • "
                "isso NÃO bloqueia o CHECK produtivo"
            )

    return snapshot


def _report_summary_block(snapshot: dict) -> str:
    summary = snapshot.get("operational_summary")
    if not isinstance(summary, dict):
        summary = construir_resumo_operacional_debug_f3(snapshot)

    visual = snapshot.get("visual_analysis")
    visual = visual if isinstance(visual, dict) else {}
    raw_visual = str(visual.get("status_text_raw") or visual.get("status_text") or "--")

    lines = [
        SUMMARY_MARKER,
        f"CHECK ATUAL: {summary.get('check_name', '--')}",
        f"DECISÃO PRODUTIVA: {summary.get('productive_text', '--')}",
        (
            "FLUXO: BLOQUEADO • " + str(summary.get("flow_reason") or "--")
            if bool(summary.get("flow_blocked"))
            else "FLUXO: LIBERADO PARA O CHECK PRODUTIVO"
        ),
        (
            "REARME: "
            f"waiting_empty={summary.get('waiting_empty_rearm', False)} • "
            f"waiting_new_board={summary.get('waiting_new_board_after_empty', False)} • "
            f"cycle_waiting={summary.get('cycle_rearm_waiting', False)}"
        ),
    ]

    neural = summary.get("neural")
    neural = neural if isinstance(neural, dict) else {}
    if bool(neural.get("active")):
        on_stats = neural.get("expected_on_p_on")
        on_stats = on_stats if isinstance(on_stats, dict) else {}
        off_stats = neural.get("expected_off_p_on")
        off_stats = off_stats if isinstance(off_stats, dict) else {}
        mismatch_ids = tuple(neural.get("raw_argmax_mismatch_ids") or ())
        gap = neural.get("diagnostic_separation_gap")
        midpoint = neural.get("diagnostic_midpoint")
        active = int(neural.get("active_mask_count", 0) or 0)
        raw_matches = int(neural.get("raw_argmax_match_count", 0) or 0)
        lines.extend(
            [
                "AUTORIDADE VISUAL PRODUTIVA: IA NEURAL H1 (CNN/ONNX)",
                (
                    "MODELO IA: "
                    f"ready={neural.get('model_ready', False)} • "
                    f"reason={neural.get('model_reason') or '--'} • "
                    f"input={neural.get('input_size') or '--'} • "
                    f"batch={neural.get('batch_size') or '--'} • "
                    f"load_count={neural.get('load_count') or '--'} • "
                    f"inference_count={neural.get('inference_count') or '--'}"
                ),
                (
                    "LIMIARES IA PRODUTIVOS: "
                    f"OFF se P(ON)≤{_fmt_probability(neural.get('off_max_on_probability'))} • "
                    f"ON se P(ON)≥{_fmt_probability(neural.get('on_min_on_probability'))} • "
                    "entre os dois = INCERTO"
                ),
                (
                    "DECISÃO IA: "
                    f"reason={neural.get('reason') or '--'} • "
                    f"matched={neural.get('matched_mask_count', 0)}/{active} • "
                    f"incertos={neural.get('uncertain_count', 0)}/{active}"
                ),
                (
                    "DIREÇÃO BRUTA IA (DIAGNÓSTICO; NÃO DECIDE): "
                    f"argmax={raw_matches}/{active} compatíveis"
                    + (
                        f" • divergentes={','.join(mismatch_ids)}"
                        if mismatch_ids
                        else " • divergentes=nenhuma"
                    )
                ),
                (
                    "P(ON) NAS MÁSCARAS ESPERADAS ON: "
                    f"min={_fmt_probability(on_stats.get('min'))} • "
                    f"média={_fmt_probability(on_stats.get('mean'))} • "
                    f"max={_fmt_probability(on_stats.get('max'))}"
                ),
                (
                    "P(ON) NAS MÁSCARAS ESPERADAS OFF: "
                    f"min={_fmt_probability(off_stats.get('min'))} • "
                    f"média={_fmt_probability(off_stats.get('mean'))} • "
                    f"max={_fmt_probability(off_stats.get('max'))}"
                ),
                (
                    "SEPARAÇÃO LIVE IA (DIAGNÓSTICO; NÃO DECIDE): "
                    f"gap={('--' if gap is None else f'{float(gap):+.4f}')} • "
                    f"midpoint={_fmt_probability(midpoint)}"
                ),
                (
                    "AUTORIDADE CONVENCIONAL DE ON/OFF USADA: "
                    + ("SIM" if neural.get("conventional_visual_authority_used") else "NÃO")
                ),
                f"MODELO IA PATH: {neural.get('model_path') or '--'}",
            ]
        )

    lines.extend(
        [
            (
                "ANÁLISE VISUAL GLOBAL: SOMENTE PRESENÇA/INFORMATIVA • "
                "não altera OK/NG, máscaras ou avanço do fluxo"
            ),
            f"TEXTO VISUAL ORIGINAL: {raw_visual}",
        ]
    )
    return "\n".join(lines)


_INSTALLED = False


def instalar_clareza_debug_tecnico_display_f3() -> None:
    """Instala resumo legível e corrige telemetria de rearme do snapshot."""
    global _INSTALLED
    if _INSTALLED:
        return

    previous_capture = manual_module.capturar_snapshot_debug_display_f3
    previous_report = manual_module.montar_relatorio_snapshot_display_f3

    def capture(app):
        snapshot = previous_capture(app)
        try:
            return aplicar_clareza_snapshot_debug_f3(snapshot, app)
        except Exception:
            return snapshot

    def report(snapshot):
        base = previous_report(snapshot)
        if SUMMARY_MARKER in str(base):
            return base
        try:
            block = _report_summary_block(snapshot)
        except Exception:
            return base
        return f"{block}\n\n{base}"

    manual_module.capturar_snapshot_debug_display_f3 = capture
    manual_module.montar_relatorio_snapshot_display_f3 = report
    manual_module._display_f3_debug_clarity_installed = True
    _INSTALLED = True
