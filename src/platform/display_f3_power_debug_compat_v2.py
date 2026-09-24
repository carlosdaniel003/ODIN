from __future__ import annotations

"""Compatibilidade final para consumidores históricos de evidência de energia.

A API antiga não recebe ``app`` nem a geometria móvel do tracker. Para
DEBUG/guards históricos ela usa o classificador ON/OFF por mesma máscara no
domínio mestre bruto (rotation=0). O resultado é somente diagnóstico por CHECK;
a decisão produtiva de energia continua global e pertence à autoridade unificada
instalada no runtime F3.
"""

from copy import deepcopy

import src.platform.display_f3_physical_learning_policy as physical_policy_module
from src.platform.display_f3_same_mask_reference_fix import F3SameMaskReferenceAnalyzer
from src.platform.display_f3_power_authority_v2 import (
    F3_UNIFIED_POWER_SOURCE,
    resumir_energia_por_analise_bruta_f3,
)


def avaliar_evidencia_energia_unificada_compat_f3(
    *,
    repository,
    matcher,
    frame,
    project_name: str,
    check_id: str,
) -> dict:
    analyzer = F3SameMaskReferenceAnalyzer(repository)
    try:
        analysis = analyzer.analyze(
            frame=frame,
            project_name=str(project_name or ""),
            check_id=str(check_id or ""),
            visual_rotation=0,
        )
    except Exception as exc:
        return {
            "available": False,
            "off_confirmed": False,
            "powered_confirmed": False,
            "energy_state": "unconfirmed",
            "reason": f"analise_bruta_indisponivel:{type(exc).__name__}:{exc}",
            "source": F3_UNIFIED_POWER_SOURCE,
            "diagnostic_only": True,
            "decision_authority": False,
        }

    evidence = resumir_energia_por_analise_bruta_f3(analysis, {})
    details = []
    for item in evidence.get("details") or ():
        row = deepcopy(item)
        winner = str(row.get("winner") or "tie")
        row["winner_semantic"] = winner
        if winner == "powered":
            row["winner"] = "check"
        row["distance_off"] = None
        row["distance_check"] = None
        row["reference_span"] = None
        row["separation"] = None
        details.append(row)

    return {
        "available": bool(evidence.get("available")),
        "off_confirmed": bool(evidence.get("off_confirmed")),
        "powered_confirmed": bool(evidence.get("powered_confirmed")),
        "energy_state": str(evidence.get("energy_state") or "unconfirmed"),
        "check_id": str(check_id or ""),
        "expected_on_mask_count": int(evidence.get("expected_on_mask_count", 0) or 0),
        "off_votes": int(evidence.get("off_votes", 0) or 0),
        "powered_votes": int(evidence.get("powered_votes", 0) or 0),
        "tie_votes": int(evidence.get("tie_votes", 0) or 0),
        "valid_votes": int(evidence.get("valid_votes", 0) or 0),
        "same_mask_comparison": True,
        "same_coordinate_system": True,
        "coordinate_domain": "master_raw_equivalent",
        "source": F3_UNIFIED_POWER_SOURCE,
        "primary_authority": evidence.get("primary_authority"),
        "secondary_guard": evidence.get("secondary_guard"),
        "legacy_power_evidence_used": False,
        "diagnostic_only": True,
        "decision_authority": False,
        "details": details,
    }


_INSTALLED = False


def instalar_compatibilidade_energia_unificada_debug_f3() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    physical_policy_module.avaliar_evidencia_energia_check_pelas_mascaras_f3 = (
        avaliar_evidencia_energia_unificada_compat_f3
    )
    try:
        import src.platform.display_f3_power_deadlock_fix as deadlock_module

        deadlock_module.avaliar_evidencia_energia_check_pelas_mascaras_f3 = (
            avaliar_evidencia_energia_unificada_compat_f3
        )
    except Exception:
        pass

    physical_policy_module._display_f3_unified_power_debug_compat_installed = True
    _INSTALLED = True
