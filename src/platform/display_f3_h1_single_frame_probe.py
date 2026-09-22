from __future__ import annotations

import src.platform.display_auto_check_runtime as runtime_module
import src.platform.display_f3_live_diagnostic_trace as trace_module
import src.platform.display_f3_live_runtime_fix as live_runtime_module
from src.platform.display_auto_check_analyzer import (
    DisplayAutomaticCheckAnalyzer as LearnedDisplayAutomaticCheckAnalyzer,
)
from src.platform.display_f3_exact_check_template import F3_EXACT_TEMPLATE_SOURCE
from src.platform.display_project_repository import DISPLAY_CHECK_STATE_ON


# Mantido apenas para compatibilidade com imports históricos. A sonda produtiva
# não usa mais a regra "somente segmentos esperados ACESOS" para aprovar H1/BLUE.
F3_POSITIVE_PROBE_MODE_ON_MASKS = "expected_on_exact_template"
F3_POSITIVE_PROBE_MODE_FULL_MASKS = "full_check_mask_conformity"


def frames_necessarios_sonda_positiva_f3(app, context: dict | None) -> int:
    """H1 exige estabilidade; BLUE continua rápido por ser transitório.

    O falso positivo real AUX->H1 mostrou que um único frame não é margem segura
    para o CHECK de referência. H1 e CHECKS estáveis usam dois frames positivos
    consecutivos. BLUE/BT continua em um frame porque é fisicamente transitório.
    """
    if not isinstance(context, dict):
        return 2

    try:
        if app._display_auto_is_transient_check(context):
            return 1
    except Exception:
        pass

    return 2


def _contexto_sonda_positiva_rapida_f3(app, context: dict | None) -> bool:
    if not isinstance(context, dict):
        return False

    try:
        if app._display_auto_is_reference_gate(context):
            return True
    except Exception:
        pass

    try:
        return bool(app._display_auto_is_transient_check(context))
    except Exception:
        return False


def avaliar_sonda_positiva_f3(
    app,
    context: dict | None,
    analysis: dict | None,
) -> dict:
    """A sonda positiva só confirma quando o CHECK inteiro está conforme.

    Antes, H1/BLUE podiam ser aprovados apenas porque TODAS as máscaras esperadas
    ACESAS estavam acesas, ignorando máscaras que deveriam estar APAGADAS. Isso é
    inseguro quando outro estado é um superconjunto do H1. No caso real AUX,
    todos os 7 segmentos ACESOS do H1 também estavam acesos, mas vários segmentos
    que H1 esperava APAGADOS estavam ACESOS. O antigo gate aprovava mesmo assim.

    Agora a sonda preserva a análise completa: ``approved=True`` somente quando
    todas as máscaras configuradas ACESO/APAGADO do CHECK coincidem. O contador de
    segmentos ACESOS permanece apenas como telemetria de debug.
    """
    if not isinstance(analysis, dict) or not bool(analysis.get("ready")):
        return {
            "approved": False,
            "mode": "unavailable",
            "on_total": 0,
            "on_matched": 0,
            "off_template_mismatches": 0,
            "full_mask_conformity": False,
        }

    original_approved = analysis.get("approved") is True
    intermittent_ready = True
    intermittent_seen = 0
    intermittent_total = 0
    if bool((context or {}).get("intermittent", False)):
        try:
            intermittent_ready, intermittent_seen, intermittent_total = (
                app._display_auto_update_intermittent_evidence(
                    context,
                    analysis,
                )
            )
        except Exception:
            intermittent_ready = False

    probe_approved = bool(original_approved and intermittent_ready)
    exact_probe = (
        str(analysis.get("reference_authority") or "")
        == F3_EXACT_TEMPLATE_SOURCE
    )
    fast_context = _contexto_sonda_positiva_rapida_f3(app, context)

    results = [
        item
        for item in (analysis.get("mask_results") or [])
        if isinstance(item, dict)
    ]
    on_results = [
        item
        for item in results
        if str(item.get("expected") or "") == DISPLAY_CHECK_STATE_ON
    ]
    on_matched = sum(1 for item in on_results if bool(item.get("matched")))
    off_template_mismatches = sum(
        1
        for item in results
        if str(item.get("expected") or "") != DISPLAY_CHECK_STATE_ON
        and not bool(item.get("matched"))
    )

    mode = (
        F3_POSITIVE_PROBE_MODE_FULL_MASKS
        if exact_probe and fast_context
        else "full_analysis"
    )

    return {
        "approved": bool(probe_approved),
        "mode": mode,
        "on_total": len(on_results),
        "on_matched": int(on_matched),
        "off_template_mismatches": int(off_template_mismatches),
        "exact_probe": bool(exact_probe),
        "fast_context": bool(fast_context),
        "original_approved": bool(original_approved),
        "full_mask_conformity": bool(probe_approved),
        "intermittent_ready": bool(intermittent_ready),
        "intermittent_seen_on": int(intermittent_seen),
        "intermittent_expected_on": int(intermittent_total),
    }


def atualizar_estabilidade_sonda_positiva_f3(
    app,
    context: dict | None,
    analysis: dict | None,
) -> dict:
    """Debounce da sonda positiva sem relaxar a decisão completa do CHECK."""
    signature = None
    if isinstance(context, dict):
        signature = (
            str(context.get("project_name") or ""),
            str(context.get("check_id") or ""),
        )

    evidence = avaliar_sonda_positiva_f3(app, context, analysis)
    approved = bool(evidence.get("approved"))

    if isinstance(analysis, dict):
        # Nunca sobrescrevemos analysis['approved'] nem analysis['reason'] aqui.
        # Esses dois campos pertencem ao analisador completo foto+mask_states.
        analysis["exact_all_masks_approved"] = bool(
            evidence.get("approved")
        )
        analysis["positive_probe_approved"] = approved
        analysis["positive_probe_mode"] = str(evidence.get("mode") or "")
        analysis["positive_probe_requires_full_mask_conformity"] = True
        analysis["positive_on_mask_count"] = int(evidence.get("on_total", 0) or 0)
        analysis["positive_on_matched_count"] = int(
            evidence.get("on_matched", 0) or 0
        )
        analysis["off_template_mismatch_count"] = int(
            evidence.get("off_template_mismatches", 0) or 0
        )
        analysis["positive_probe_reason"] = (
            "check_completo_conforme"
            if approved
            else "check_completo_nao_conforme"
        )

    previous_signature = getattr(app, "_display_f3_live_probe_signature", None)
    frames = int(getattr(app, "_display_f3_live_probe_ok_frames", 0) or 0)
    required = frames_necessarios_sonda_positiva_f3(app, context)

    if signature is None or not approved:
        app._display_f3_live_probe_signature = signature
        app._display_f3_live_probe_ok_frames = 0
        return {
            "approved": approved,
            "frames": 0,
            "required": required,
            "confirm": False,
            "mode": evidence.get("mode"),
            "on_total": evidence.get("on_total", 0),
            "on_matched": evidence.get("on_matched", 0),
            "off_template_mismatches": evidence.get("off_template_mismatches", 0),
        }

    frames = frames + 1 if previous_signature == signature else 1
    app._display_f3_live_probe_signature = signature
    app._display_f3_live_probe_ok_frames = frames
    return {
        "approved": True,
        "frames": frames,
        "required": required,
        "confirm": frames >= required,
        "mode": evidence.get("mode"),
        "on_total": evidence.get("on_total", 0),
        "on_matched": evidence.get("on_matched", 0),
        "off_template_mismatches": evidence.get("off_template_mismatches", 0),
    }


def restaurar_analisador_semantico_runtime_f3() -> None:
    """Restaura o analisador semântico nos aliases históricos do runtime."""
    runtime_module.DisplayAutomaticCheckAnalyzer = LearnedDisplayAutomaticCheckAnalyzer
    live_runtime_module.DisplayAutomaticCheckAnalyzer = LearnedDisplayAutomaticCheckAnalyzer


_INSTALLED = False


def instalar_captura_h1_um_frame_display_f3() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    trace_module._probe_required_frames = frames_necessarios_sonda_positiva_f3
    trace_module._update_positive_probe_stability = (
        atualizar_estabilidade_sonda_positiva_f3
    )
    restaurar_analisador_semantico_runtime_f3()
    _INSTALLED = True
