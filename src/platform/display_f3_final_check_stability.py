from __future__ import annotations

"""Contrato final de estabilidade dos CHECKS produtivos do Display F3.

Algumas camadas históricas do F3 conciliam o falso OFF do matcher global com a
análise das máscaras. Em determinados encadeamentos, o frame termina corretamente
como CHECK atual + análise 100% aprovada, porém `_display_auto_stable_frames` já
foi zerado por uma camada interna que ainda enxergou o estado físico anterior.

Esta camada é instalada POR ÚLTIMO e trabalha somente com o resultado produtivo
final daquele frame. Ela não analisa imagem novamente e não possui nomes especiais
de CHECK: vale para USB, AUX e qualquer CHECK futuro.
"""

from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin


F3_FINAL_STABILITY_SOURCE = "f3_final_current_check_stability"


def _context(app) -> dict | None:
    try:
        value = app._display_auto_current_context()
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _signature(context: dict | None) -> tuple[str, str] | None:
    if not isinstance(context, dict):
        return None
    project = str(context.get("project_name") or "").strip()
    check_id = str(context.get("check_id") or "").strip()
    if not project or not check_id:
        return None
    return project, check_id


def _analysis_matches(analysis: dict | None, context: dict | None) -> bool:
    if not isinstance(analysis, dict):
        return False
    expected = _signature(context)
    if expected is None:
        return False
    return expected == (
        str(analysis.get("project_name") or "").strip(),
        str(analysis.get("check_id") or "").strip(),
    )


def _analysis_fully_approved(analysis: dict | None, context: dict | None) -> bool:
    if not _analysis_matches(analysis, context):
        return False
    if not bool(analysis.get("ready")) or analysis.get("approved") is not True:
        return False

    try:
        active = int(analysis.get("active_mask_count", 0) or 0)
        matched = int(analysis.get("matched_mask_count", 0) or 0)
    except (TypeError, ValueError):
        active = 0
        matched = 0

    if active > 0:
        return matched >= active

    results = [
        item
        for item in (analysis.get("mask_results") or [])
        if isinstance(item, dict)
        and str(item.get("expected") or "").strip().lower() != "ignore"
    ]
    return bool(results) and all(bool(item.get("matched")) for item in results)


def _decision_allowed(app, context: dict | None) -> bool:
    state = getattr(app, "_display_f3_operational_state", None)
    if not isinstance(state, dict):
        return False

    kind = str(state.get("kind") or "unknown").strip().lower()
    if kind in {"empty", "unavailable", "off"}:
        return False

    check_id = str((context or {}).get("check_id") or "").strip()
    if kind == "check":
        physical_check_id = str(state.get("check_id") or "").strip()
        physical_key = str(state.get("physical_state_key") or "").strip()
        if physical_check_id and physical_check_id != check_id:
            return False
        if physical_key.startswith("check:") and physical_key != f"check:{check_id}":
            return False

    return bool(
        state.get(
            "_display_f3_physical_decision_allowed",
            state.get("allow_auto", False),
        )
    )


def _frame_token(app):
    try:
        frame = getattr(app, "camera_frame_atual", None)
        return app._display_auto_frame_token(frame)
    except Exception:
        frame_id = getattr(app, "camera_ultimo_frame_id", None)
        if isinstance(frame_id, int):
            return ("camera", frame_id)
        return None


def _clear(app, reason: str = "") -> None:
    app._display_f3_final_stability_signature = None
    app._display_f3_final_stability_frames = 0
    app._display_f3_final_stability_last_frame = None
    app._display_f3_final_stability_reason = str(reason or "")


def _required_frames(app, context: dict) -> int:
    try:
        if app._display_auto_is_transient_check(context):
            return 1
    except Exception:
        pass
    try:
        return max(1, int(app.DISPLAY_AUTO_OK_STABLE_FRAMES))
    except Exception:
        return 2


def estabilizar_check_final_f3(app, context_before: dict | None) -> dict:
    """Acumula somente frames finais, novos e integralmente aprovados.

    Retorna diagnóstico compacto para testes/debug. O registro só ocorre se o
    CHECK ainda for exatamente o mesmo depois de todo o pipeline interno.
    """
    result = {
        "source": F3_FINAL_STABILITY_SOURCE,
        "counted": False,
        "registered": False,
    }

    if not bool(getattr(app, "display_f3_ativo", False)):
        _clear(app, "f3_inativo")
        result["reason"] = "f3_inativo"
        return result
    if bool(
        getattr(app, "_display_f3_waiting_empty_rearm", False)
        or getattr(app, "_display_f3_waiting_new_board_after_empty", False)
    ):
        _clear(app, "rearme_ativo")
        result["reason"] = "rearme_ativo"
        return result
    if getattr(app, "display_f3_result_after_id", None) is not None:
        _clear(app, "resultado_em_exibicao")
        result["reason"] = "resultado_em_exibicao"
        return result

    context_after = _context(app)
    signature = _signature(context_after)
    if signature is None or signature != _signature(context_before):
        # O pipeline interno já avançou o CHECK. Não devemos registrar uma segunda vez.
        _clear(app, "contexto_ja_avancou")
        result["reason"] = "contexto_ja_avancou"
        return result

    analysis = getattr(app, "_display_auto_last_analysis", None)
    if not _analysis_fully_approved(analysis, context_after):
        _clear(app, "analise_nao_aprovada_integralmente")
        result["reason"] = "analise_nao_aprovada_integralmente"
        return result

    if bool(context_after.get("intermittent", False)):
        try:
            temporal_ready, temporal_seen, temporal_total = (
                app._display_auto_update_intermittent_evidence(
                    context_after,
                    analysis,
                )
            )
        except Exception:
            temporal_ready, temporal_seen, temporal_total = False, 0, 0
        result["intermittent_seen_on"] = int(temporal_seen)
        result["intermittent_expected_on"] = int(temporal_total)
        if not temporal_ready:
            _clear(app, "intermitente_aguardando_fase_acesa")
            result["reason"] = "intermitente_aguardando_fase_acesa"
            return result

    if not _decision_allowed(app, context_after):
        _clear(app, "autoridade_fisica_nao_liberada")
        result["reason"] = "autoridade_fisica_nao_liberada"
        return result

    token = _frame_token(app)
    if token is not None and token == getattr(
        app, "_display_f3_final_stability_last_frame", None
    ):
        result["reason"] = "mesmo_frame"
        result["frames"] = int(
            getattr(app, "_display_f3_final_stability_frames", 0) or 0
        )
        return result

    if getattr(app, "_display_f3_final_stability_signature", None) == signature:
        frames = int(getattr(app, "_display_f3_final_stability_frames", 0) or 0) + 1
    else:
        frames = 1

    app._display_f3_final_stability_signature = signature
    app._display_f3_final_stability_frames = frames
    app._display_f3_final_stability_last_frame = token
    app._display_f3_final_stability_reason = "acumulando"

    required = _required_frames(app, context_after)
    result.update(
        {
            "counted": True,
            "frames": frames,
            "required": required,
            "project_name": signature[0],
            "check_id": signature[1],
        }
    )

    # Espelha a contagem no campo legado apenas para diagnóstico visual. A fonte
    # de verdade desta correção permanece nos campos _display_f3_final_*.
    app._display_auto_last_decision = True
    app._display_auto_stable_frames = max(
        int(getattr(app, "_display_auto_stable_frames", 0) or 0),
        frames,
    )

    if frames < required:
        result["reason"] = "aguardando_estabilidade"
        return result

    # Confere novamente o contexto imediatamente antes de registrar.
    if _signature(_context(app)) != signature:
        _clear(app, "contexto_mudou_antes_registro")
        result["reason"] = "contexto_mudou_antes_registro"
        return result

    event = app.registrar_resultado_check_display_f3(True)
    event_type = str((event or {}).get("event") or "") if isinstance(event, dict) else ""
    result["register_event"] = event_type
    result["registered"] = event_type in {
        "check_advanced",
        "plate_ok",
        "plate_ng",
    }
    result["reason"] = "registrado" if result["registered"] else "registro_nao_avancou"
    app._display_f3_final_stability_last_event = dict(result)
    _clear(app, result["reason"])
    return result


_INSTALLED = False


def instalar_estabilidade_final_checks_display_f3() -> None:
    """Instala por fora de todas as demais camadas F3."""
    global _INSTALLED
    if _INSTALLED:
        return

    cls = DisplayAutomaticCheckF3Mixin
    previous_process = cls._process_display_auto_check

    def process(self):
        context_before = _context(self)
        result = previous_process(self)
        try:
            diagnostic = estabilizar_check_final_f3(self, context_before)
            self._display_f3_final_stability_last = diagnostic
        except Exception as exc:
            self._display_f3_final_stability_last = {
                "source": F3_FINAL_STABILITY_SOURCE,
                "counted": False,
                "registered": False,
                "reason": f"erro:{type(exc).__name__}",
            }
        return result

    cls._process_display_auto_check = process
    cls._display_f3_final_check_stability_installed = True
    _INSTALLED = True
