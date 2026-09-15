from __future__ import annotations

"""Substitui a sonda histórica de energia do F3 pela comparação mesma-máscara.

A API antiga é preservada porque o DEBUG TÉCNICO e alguns guards históricos a
consultam. A implementação, porém, não usa mais o vetor de features global que
gerava distâncias ~1170 quase empatadas entre OFF e CHECK.

OFF, LIVE e ON são normalizados para a mesma resolução mestre e a mesma máscara
física. O runtime final usa a versão rotacionada em ``display_f3_power_authority``;
esta compatibilidade opera no domínio mestre bruto, matematicamente equivalente
porque as três imagens e a geometria permanecem no mesmo sistema de coordenadas.
"""

import cv2

import src.platform.display_f3_physical_learning_policy as physical_policy_module
from src.platform.display_auto_check_analyzer import display_mask_to_analysis_selection
from src.platform.display_f3_exact_check_template import _read_reference_full
from src.platform.display_f3_power_authority import (
    F3_POWER_AUTHORITY_SOURCE,
    _mask_optical_signature,
    classificar_posicao_relativa_energia_f3,
    resumir_votos_energia_f3,
)
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_ON,
    normalizar_resolucao_display,
)
from src.platform.display_visual_reference_status import (
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
)


def _prepare_master(frame, resolution):
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    width, height = int(resolution[0]), int(resolution[1])
    image = frame
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.ndim == 3 and image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    elif image.ndim != 3 or image.shape[2] != 3:
        return None
    if image.shape[:2] != (height, width):
        interpolation = (
            cv2.INTER_AREA
            if image.shape[1] > width or image.shape[0] > height
            else cv2.INTER_LINEAR
        )
        image = cv2.resize(image, (width, height), interpolation=interpolation)
    return image


def avaliar_evidencia_energia_mesma_mascara_compat_f3(
    *,
    repository,
    matcher,
    frame,
    project_name: str,
    check_id: str,
) -> dict:
    project = repository.carregar_projeto(project_name)
    check = repository.carregar_check(project_name, check_id)
    if not isinstance(project, dict) or not isinstance(check, dict):
        return {
            "available": False,
            "off_confirmed": False,
            "powered_confirmed": False,
            "reason": "contexto_invalido",
            "source": F3_POWER_AUTHORITY_SOURCE,
        }

    resolution = normalizar_resolucao_display(project.get("master_resolution"))
    if resolution is None:
        return {
            "available": False,
            "off_confirmed": False,
            "powered_confirmed": False,
            "reason": "resolucao_ausente",
            "source": F3_POWER_AUTHORITY_SOURCE,
        }

    states = check.get("mask_states") if isinstance(check.get("mask_states"), dict) else {}
    on_masks = [
        mask
        for mask in (project.get("masks") or [])
        if isinstance(mask, dict)
        and states.get(str(mask.get("id") or "")) == DISPLAY_CHECK_STATE_ON
    ]
    if not on_masks:
        return {
            "available": False,
            "off_confirmed": False,
            "powered_confirmed": False,
            "reason": "check_sem_mascara_acesa",
            "source": F3_POWER_AUTHORITY_SOURCE,
        }

    project_refs = matcher.project_store.get_all(project_name)
    off_metadata = project_refs.get(DISPLAY_PROJECT_REFERENCE_BOARD_OFF)
    on_metadata = matcher.check_store.get(project_name, check_id)
    off = _prepare_master(_read_reference_full(off_metadata), resolution)
    on = _prepare_master(_read_reference_full(on_metadata), resolution)
    live = _prepare_master(frame, resolution)
    if any(image is None or getattr(image, "size", 0) == 0 for image in (off, on, live)):
        return {
            "available": False,
            "off_confirmed": False,
            "powered_confirmed": False,
            "reason": "referencias_energia_indisponiveis",
            "source": F3_POWER_AUTHORITY_SOURCE,
        }

    details = []
    for mask in on_masks:
        mask_id = str(mask.get("id") or "")
        try:
            selection = display_mask_to_analysis_selection(mask)
        except (TypeError, ValueError):
            continue

        live_signature = _mask_optical_signature(live, selection)
        off_signature = _mask_optical_signature(off, selection)
        on_signature = _mask_optical_signature(on, selection)
        if not all(isinstance(item, dict) for item in (live_signature, off_signature, on_signature)):
            continue

        relative = classificar_posicao_relativa_energia_f3(
            live_signature,
            off_signature,
            on_signature,
        )
        details.append(
            {
                "mask_id": mask_id,
                **relative,
                # Nomes antigos permanecem para o relatório existente, agora em
                # escala normalizada e semanticamente coerente.
                "distance_off": relative.get("distance_off"),
                "distance_check": relative.get("distance_on"),
                "reference_span": relative.get("reference_distance"),
                "separation": (
                    None
                    if relative.get("power_position") is None
                    else round(abs(float(relative["power_position"]) - 0.5) * 2.0, 4)
                ),
                "live_v_mean": round(float(live_signature.get("v_mean", 0.0)), 2),
                "off_v_mean": round(float(off_signature.get("v_mean", 0.0)), 2),
                "on_v_mean": round(float(on_signature.get("v_mean", 0.0)), 2),
            }
        )

    summary = resumir_votos_energia_f3(details, len(on_masks))
    # Compatibilidade textual: a implementação antiga chamava o voto positivo
    # de "check"; o novo runtime usa "powered". Mantemos ambos explícitos.
    legacy_details = []
    for item in details:
        row = dict(item)
        if row.get("winner") == "powered":
            row["winner"] = "check"
            row["winner_semantic"] = "powered"
        else:
            row["winner_semantic"] = row.get("winner")
        legacy_details.append(row)

    return {
        "available": bool(details),
        "off_confirmed": bool(summary.get("off_confirmed")),
        "powered_confirmed": bool(summary.get("powered_confirmed")),
        "energy_state": summary.get("energy_state"),
        "check_id": str(check_id),
        "expected_on_mask_count": int(summary.get("expected_on_mask_count", 0)),
        "off_votes": int(summary.get("off_votes", 0)),
        "powered_votes": int(summary.get("powered_votes", 0)),
        "tie_votes": int(summary.get("tie_votes", 0)),
        "valid_votes": int(summary.get("valid_votes", 0)),
        "same_mask_comparison": True,
        "same_coordinate_system": True,
        "coordinate_domain": "master_raw_equivalent",
        "source": F3_POWER_AUTHORITY_SOURCE,
        "details": legacy_details,
    }


_INSTALLED = False


def instalar_evidencia_energia_mesma_mascara_display_f3() -> None:
    """Redireciona todos os consumidores históricos para a nova sonda."""
    global _INSTALLED
    if _INSTALLED:
        return

    physical_policy_module.avaliar_evidencia_energia_check_pelas_mascaras_f3 = (
        avaliar_evidencia_energia_mesma_mascara_compat_f3
    )

    # display_f3_power_deadlock_fix importou a função antiga por valor.
    try:
        import src.platform.display_f3_power_deadlock_fix as deadlock_module

        deadlock_module.avaliar_evidencia_energia_check_pelas_mascaras_f3 = (
            avaliar_evidencia_energia_mesma_mascara_compat_f3
        )
    except Exception:
        pass

    physical_policy_module._display_f3_same_mask_power_evidence_installed = True
    _INSTALLED = True
