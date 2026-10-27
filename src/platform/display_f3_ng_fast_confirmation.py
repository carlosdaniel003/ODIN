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


def contar_corrobacoes_fisicas_h1(
    analysis: dict,
    failed_mask_ids: tuple[str, ...],
    observations: list[dict] | tuple[dict, ...] | None,
    *,
    snapshot_token,
    required: int = 3,
) -> int:
    """Confirma NG de snapshot híbrido com leituras físicas de frames NOVOS.

    A CNN decide a divergência no RAW congelado. Esta função só verifica se a
    mesma leitura persiste nos frames físicos já coletados pelo proprietário
    de energia. Não executa CNN, tracking ou matching adicional.
    """
    if (
        not failed_mask_ids
        or not isinstance(snapshot_token, (list, tuple))
        or len(snapshot_token) < 2
        or snapshot_token[0] != "camera"
        or not isinstance(observations, (list, tuple))
    ):
        return 0
    try:
        snapshot_id = int(snapshot_token[1])
    except (TypeError, ValueError):
        return 0

    expected = {}
    for row in analysis.get("mask_results") or ():
        if not isinstance(row, dict):
            return 0
        mid = str(row.get("mask_id") or "")
        state = str(row.get("expected") or "")
        if not mid or state not in ("on", "off") or mid in expected:
            return 0
        expected[mid] = state
    if not set(failed_mask_ids).issubset(expected):
        return 0

    seen = set()
    consecutive = 0
    for item in reversed(observations):
        if not isinstance(item, dict):
            break
        token = item.get("frame_token")
        if not isinstance(token, (list, tuple)) or len(token) < 2 or token[0] != "camera":
            break
        try:
            frame_id = int(token[1])
        except (TypeError, ValueError):
            break
        if frame_id <= snapshot_id:
            break
        # H1 dura aproximadamente 3 segundos; nunca herdar votos
        # indefinidamente de outra fase da placa.
        if frame_id - snapshot_id > 45:
            break
        if frame_id in seen:
            continue
        seen.add(frame_id)

        if (
            item.get("powered_confirmed") is not True
            or item.get("decision_allowed") is not True
            or item.get("board_present") is not True
            or item.get("spatial_alignment_ready") is not True
            or item.get("same_mask_comparison") is not True
        ):
            break
        states = item.get("mask_classifications")
        if not isinstance(states, dict):
            break
        if not all(states.get(mid) == "off" for mid in failed_mask_ids):
            break
        # Nenhum outro ON esperado pode ficar apagado e nenhum OFF
        # esperado pode acender: um CHECK diferente não valida H1.
        for mid, state in states.items():
            if mid in expected and str(state) != (
                "off" if mid in failed_mask_ids else expected[mid]
            ):
                break
        else:
            expected_on = [
                mid for mid, state in expected.items()
                if state == "on" and mid not in failed_mask_ids
            ]
            if expected_on and all(states.get(mid) == "on" for mid in expected_on):
                consecutive += 1
                if consecutive >= required:
                    return required
                continue
        break
    return consecutive
