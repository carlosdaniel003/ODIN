from __future__ import annotations

"""Mantém o overlay de máscaras sincronizado com a sonda exata H1/BLUE.

A sonda exata existe para não perder H1/BLUE quando o classificador físico global
fica preso em OFF/UNKNOWN. Antes desta correção, a sonda podia reconhecer 28/28
máscaras e atualizar o estado operacional, mas `_display_auto_last_analysis`
continuava vazio. Como o overlay ao vivo lê esse atributo, todas as ROIs eram
renderizadas em cinza mesmo com o CHECK reconhecido.

Esta camada é compatibilidade para composições legadas. Quando
`F3RuntimeAuthorities` está instalado, a sonda permanece somente diagnóstica:
não substitui `_display_auto_last_analysis`, não muda o overlay e não participa
de OK/NG. Assim a UI sempre reflete a análise canônica com geometria rastreada.
"""

import src.platform.display_f3_live_diagnostic_trace as trace_module


F3_PROBE_VISUAL_SOURCE = "f3_exact_probe_visual_sync"
F3_PROBE_BLOCKED_EVENT = "physical_gate_blocked"


def _context_signature(context: dict | None) -> tuple[str, str] | None:
    if not isinstance(context, dict):
        return None
    project_name = str(context.get("project_name") or "").strip()
    check_id = str(context.get("check_id") or "").strip()
    if not project_name or not check_id:
        return None
    return project_name, check_id


def _current_context(app) -> dict | None:
    try:
        context = app._display_auto_current_context()
    except Exception:
        return None
    return context if isinstance(context, dict) else None


def _runtime_blocks_visual_probe(app) -> bool:
    # D-008/D-015: debug/sonda não pode sobrescrever a autoridade canônica.
    if bool(getattr(app, "_display_f3_runtime_authorities_installed", False)):
        return True
    if not bool(getattr(app, "display_f3_ativo", False)):
        return True
    if getattr(app, "display_f3_result_after_id", None) is not None:
        return True
    if bool(getattr(app, "_display_f3_waiting_empty_rearm", False)):
        return True
    if bool(getattr(app, "_display_f3_waiting_new_board_after_empty", False)):
        return True
    try:
        if bool(app._display_auto_configuration_open()):
            return True
    except Exception:
        pass
    return False


def publicar_analise_visual_sonda_f3(
    app,
    context: dict | None,
    analysis: dict | None,
) -> bool:
    """Publica a análise já calculada para overlay/status, sem recalcular frame."""
    if _runtime_blocks_visual_probe(app):
        return False
    expected_signature = _context_signature(context)
    if expected_signature is None or not isinstance(analysis, dict):
        return False
    if not bool(analysis.get("ready")):
        return False
    if not any(isinstance(item, dict) for item in (analysis.get("mask_results") or [])):
        return False

    current = _current_context(app)
    if _context_signature(current) != expected_signature:
        return False

    project_name, check_id = expected_signature
    analysis_check_id = str(analysis.get("check_id") or check_id).strip()
    analysis_project = str(analysis.get("project_name") or project_name).strip()
    if analysis_check_id != check_id or analysis_project != project_name:
        return False

    # Cópia rasa: a sonda já construiu mask_results e não precisamos duplicar as
    # estruturas pesadas. Apenas completamos os campos de contexto usados pelo
    # overlay e pelo status de máscaras.
    visual = dict(analysis)
    visual.setdefault("project_name", project_name)
    visual.setdefault("check_id", check_id)
    visual.setdefault("check_name", str((context or {}).get("check_name") or check_id))
    visual["visual_analysis_source"] = F3_PROBE_VISUAL_SOURCE

    app._display_auto_last_analysis = visual

    frame = getattr(app, "camera_frame_atual", None)
    try:
        token = app._display_auto_frame_token(frame) if frame is not None else None
    except Exception:
        token = ("object", id(frame)) if frame is not None else None

    cache_key = (project_name, check_id, token)
    app._display_f3_overlay_analysis_cache_key = cache_key
    app._display_f3_overlay_analysis_cache = visual
    app._display_f3_probe_visual_analysis_signature = cache_key
    return True


def corrigir_retorno_avanco_bloqueado_f3(
    result,
    *,
    visual_published: bool,
):
    """Não chama de avanço um registro que o gate físico recusou."""
    if not isinstance(result, dict):
        return result
    event = result.get("event")
    event_type = str((event or {}).get("event") or "") if isinstance(event, dict) else ""
    if event_type != F3_PROBE_BLOCKED_EVENT:
        return result

    corrected = dict(result)
    corrected["advanced"] = False
    corrected["reason"] = "physical_gate_blocked_after_exact_probe"
    corrected["visual_analysis_published"] = bool(visual_published)
    return corrected


def executar_avanco_sonda_com_sincronia_visual_f3(
    previous_advance,
    app,
    context_before: dict | None,
    analysis: dict | None,
    stability: dict,
):
    """Colore o CHECK no mesmo ciclo óptico e preserva o gate de decisão."""
    published = publicar_analise_visual_sonda_f3(app, context_before, analysis)
    result = previous_advance(app, context_before, analysis, stability)

    # O caminho legado limpa `_display_auto_last_analysis` quando o registro foi
    # recusado. Se continuamos no mesmo CHECK, republicamos somente para o
    # overlay/status. No próximo frame o runtime produtivo pode usar essa leitura
    # como evidência de placa energizada e assumir a decisão normalmente.
    if _context_signature(_current_context(app)) == _context_signature(context_before):
        published = publicar_analise_visual_sonda_f3(
            app,
            context_before,
            analysis,
        ) or published

    return corrigir_retorno_avanco_bloqueado_f3(
        result,
        visual_published=published,
    )


def _install_physical_status_memory() -> None:
    # O status físico precisa sobreviver à troca do CHECK lógico e ao rearme
    # terminal sem virar uma nova autoridade de OK/NG. A extensão é genérica e
    # usa o último CHECK realmente aprovado, qualquer que seja o seu nome.
    from src.platform.display_f3_physical_status_memory import (
        instalar_memoria_status_fisico_display_f3,
    )

    instalar_memoria_status_fisico_display_f3()


_INSTALLED = False


def instalar_sincronia_visual_sonda_display_f3() -> None:
    """Instala a sincronização por fora das sondas/guards existentes do F3."""
    global _INSTALLED
    if _INSTALLED:
        _install_physical_status_memory()
        return
    if bool(getattr(trace_module, "_display_f3_probe_visual_sync_installed", False)):
        _install_physical_status_memory()
        _INSTALLED = True
        return

    previous_advance = trace_module._advance_positive_probe_if_needed

    def advance(app, context_before, analysis, stability):
        return executar_avanco_sonda_com_sincronia_visual_f3(
            previous_advance,
            app,
            context_before,
            analysis,
            stability,
        )

    trace_module._advance_positive_probe_if_needed = advance
    trace_module._display_f3_probe_visual_sync_installed = True
    _install_physical_status_memory()
    _INSTALLED = True
