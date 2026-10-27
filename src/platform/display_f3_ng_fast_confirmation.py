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
