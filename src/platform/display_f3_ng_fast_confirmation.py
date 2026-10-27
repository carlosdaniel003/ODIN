"""Prova conservadora de NG rápido no primeiro CHECK do Display F3.

Somente a estabilidade temporal fica mais curta. A semântica continua sob a
autoridade híbrida CNN + aprendizado físico same-mask. Nenhuma classificação
é recalculada, nem a sequência/checks ou a captura são modificados.
"""
from __future__ import annotations


def assinatura_ng_h1_consenso(
    context: dict,
    analysis: dict,
    policy: dict,
    *,
    reference_gate: bool,
    tracking_snapshot: bool,
) -> tuple[str, ...]:
    """IDs das máscaras OFF anormais aptas a 3 frames independentes.

    Um H1 parcialmente aceso em transição não é NG rápido. A maioria das
    máscaras esperadas ON deve estar realmente ON no MESMO frame; todas as
    divergências precisam concordar entre CNN e fonte física local.
    """
    if (
        not reference_gate
        or not tracking_snapshot
        or bool(context.get("intermittent"))
        or analysis.get("neural_visual_authority") is not True
        or analysis.get("tracking_snapshot_explicit") is not True
        or analysis.get("ready") is not True
        or policy.get("decision") != "ng"
        or policy.get("confirmed_ng") is not True
        or policy.get("board_powered") is not True
    ):
        return ()

    rows = analysis.get("mask_results")
    if not isinstance(rows, (list, tuple)) or not rows:
        return ()
    if int(analysis.get("effective_uncertain_mask_count", 0) or 0) != 0:
        return ()

    expected_on = 0
    observed_on = 0
    failures = []
    for row in rows:
        if not isinstance(row, dict) or not str(row.get("mask_id") or ""):
            return ()
        if (
            row.get("semantic_certain") is not True
            or str(row.get("classified") or "") not in ("on", "off")
        ):
            return ()
        expected = str(row.get("expected") or "")
        classified = str(row.get("classified") or "")
        if expected == "on":
            expected_on += 1
            observed_on += int(classified == "on")
        elif expected != "off":
            return ()

        if expected == classified and row.get("matched") is True:
            continue
        if not (expected == "on" and classified == "off"
                and row.get("matched") is False):
            return ()

        # O mesmo segmento OFF deve ter dupla confirmação independente;
        # evidência incerta, class_pool ou desacordo não ganham atalho.
        if not (
            row.get("hybrid_resolution") == "neural_physical_consensus"
            and row.get("neural_certain") is True
            and row.get("neural_classified") == "off"
            and row.get("physical_evidence_available") is True
            and row.get("physical_local_authoritative") is True
            and row.get("physical_classified") == "off"
            and str(row.get("physical_reference_source") or "").startswith(
                "f3_check_photos_same_mask"
            )
        ):
            return ()
        failures.append(str(row["mask_id"]))

    if expected_on < 2 or observed_on <= expected_on // 2 or not failures:
        return ()
    confirmed = {str(mid) for mid in (
        analysis.get("effective_confirmed_failed_mask_ids") or ()
    ) if str(mid)}
    if confirmed != set(failures):
        return ()
    return tuple(sorted(failures))


def tokens_corrobacao_fisica_h1(
    analysis: dict,
    failed_mask_ids: tuple[str, ...],
    observations: list[dict] | tuple[dict, ...] | None,
    *,
    snapshot_token,
    required: int = 3,
    diagnostics: dict | None = None,
) -> tuple[tuple[str, int], ...]:
    """Obtém IDs de frames RAW físicos que corroboram um NG H1 híbrido.

    A CNN decide a divergência no RAW congelado. Esta função só verifica se a
    mesma leitura persiste nos frames físicos já coletados pelo proprietário
    de energia. Não executa CNN, tracking ou matching adicional.
    """
    # Observabilidade D-096: registrar onde o quórum físico parou, sem
    # calcular outro voto, modificar a seleção ou relaxar o gate temporal.
    debug = diagnostics if isinstance(diagnostics, dict) else None
    if debug is not None:
        debug.clear()
        debug.update({
            "snapshot_token": snapshot_token,
            "history_count": len(observations) if isinstance(observations, (list, tuple)) else 0,
            "history_frame_tokens": tuple(
                item.get("frame_token") if isinstance(item, dict) else None
                for item in (observations or ())[-18:]
            ) if isinstance(observations, (list, tuple)) else (),
            "accepted_tokens": (),
        })

    def note(reason: str, *, frame_token=None, details=None):
        if debug is not None:
            debug["stop_reason"] = reason
            if frame_token is not None:
                debug["stop_frame_token"] = frame_token
            if details is not None:
                debug["stop_details"] = details

    if (
        not failed_mask_ids
        or not isinstance(snapshot_token, (list, tuple))
        or len(snapshot_token) < 2
        or snapshot_token[0] != "camera"
        or not isinstance(observations, (list, tuple))
    ):
        note("invalid_snapshot_or_history")
        return ()
    try:
        snapshot_id = int(snapshot_token[1])
    except (TypeError, ValueError):
        note("invalid_snapshot_frame_id")
        return ()

    expected = {}
    for row in analysis.get("mask_results") or ():
        if not isinstance(row, dict):
            note("invalid_semantic_mask_row")
            return ()
        mid = str(row.get("mask_id") or "")
        state = str(row.get("expected") or "")
        if not mid or state not in ("on", "off") or mid in expected:
            note("invalid_semantic_mask_states")
            return ()
        expected[mid] = state
    if not set(failed_mask_ids).issubset(expected):
        note("failed_mask_not_in_semantic_expected")
        return ()

    seen = set()
    valid_tokens: list[tuple[str, int]] = []
    for item in reversed(observations):
        if not isinstance(item, dict):
            note("invalid_history_entry")
            break
        token = item.get("frame_token")
        if not isinstance(token, (list, tuple)) or len(token) < 2 or token[0] != "camera":
            note("invalid_history_frame_token", frame_token=token)
            break
        try:
            frame_id = int(token[1])
        except (TypeError, ValueError):
            note("invalid_history_frame_id", frame_token=token)
            break
        if frame_id <= snapshot_id:
            note("history_not_newer_than_semantic", frame_token=token)
            break
        # H1 dura aproximadamente 3 segundos; nunca herdar votos
        # indefinidamente de outra fase da placa.
        if frame_id - snapshot_id > 45:
            note("history_exceeds_45_frame_window", frame_token=token,
                 details={"frame_gap": frame_id - snapshot_id})
            break
        if frame_id in seen:
            continue
        seen.add(frame_id)

        failed_gates = tuple(
            field for field in (
                "powered_confirmed", "decision_allowed", "board_present",
                "spatial_alignment_ready", "same_mask_comparison",
            ) if item.get(field) is not True
        )
        if failed_gates:
            note("physical_authority_gate_blocked", frame_token=token,
                 details={"failed_gates": failed_gates})
            break
        states = item.get("mask_classifications")
        if not isinstance(states, dict):
            note("physical_mask_classifications_missing", frame_token=token)
            break
        mismatched_failed = tuple(mid for mid in failed_mask_ids if states.get(mid) != "off")
        if mismatched_failed:
            note("failed_masks_not_off_in_physical", frame_token=token,
                 details={"mask_ids": mismatched_failed})
            break
        # Nenhum outro ON esperado pode ficar apagado e nenhum OFF
        # esperado pode acender: um CHECK diferente não valida H1.
        for mid, state in states.items():
            if mid in expected and str(state) != (
                "off" if mid in failed_mask_ids else expected[mid]
            ):
                note("other_mask_diverges_from_h1", frame_token=token,
                     details={"mask_id": mid, "observed": str(state),
                              "expected": "off" if mid in failed_mask_ids else expected[mid]})
                break
        else:
            expected_on = [
                mid for mid, state in expected.items()
                if state == "on" and mid not in failed_mask_ids
            ]
            if expected_on and all(states.get(mid) == "on" for mid in expected_on):
                valid_tokens.append(("camera", frame_id))
                if len(valid_tokens) >= required:
                    note("quorum_reached", frame_token=token)
                    if debug is not None:
                        debug["accepted_tokens"] = tuple(valid_tokens)
                    return tuple(valid_tokens)
                continue
            missing_healthy = tuple(mid for mid in expected_on if states.get(mid) != "on")
            note("healthy_on_masks_not_confirmed", frame_token=token,
                 details={"mask_ids": missing_healthy})
        break
    if debug is not None:
        debug["accepted_tokens"] = tuple(valid_tokens)
        if "stop_reason" not in debug:
            note("history_exhausted_before_quorum")
    return tuple(valid_tokens)
