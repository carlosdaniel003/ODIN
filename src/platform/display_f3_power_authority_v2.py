from __future__ import annotations

"""Autoridade final v2 de energia do Display F3.

Resolve duas inconsistências observadas em produção:

1. o gate de energia antigo reduzia cada máscara a brilho/V e pixels quentes;
   em displays claros/saturados OFF e ON podiam ficar praticamente idênticos;
2. o DEBUG TÉCNICO podia comparar vários CHECKs reutilizando analisadores/cache e
   mostrar resultados incompatíveis para o mesmo frame.

A autoridade fica única e hierárquica:

    PRESENÇA GLOBAL -> ENERGIA PELAS MÁSCARAS -> CHECK -> CONFORMIDADE

A energia primária é independente do CHECK lógico. O frame físico atual é lido
nas máscaras rastreadas e cada máscara disputa entre exemplos ON e OFF da própria
região, aprendidos das fotos reais dos CHECKS. O menor padrão energizado
configurado define quantos votos ON são necessários para provar energia.

A análise do CHECK lógico continua separada: ela decide conformidade e sequência,
mas não pode desligar o gate só porque a placa está fisicamente em BLUE/USB/AUX
enquanto o fluxo ainda aguarda H1. Projetos antigos sem pares locais ON/OFF usam
o caminho anterior apenas como fallback de compatibilidade.

Módulo exclusivo do F3. Não cria timer, não lê uma segunda câmera e não altera F2.
"""

from copy import deepcopy
import hashlib
from pathlib import Path

import src.platform.display_f3_debug_clarity_fix as debug_clarity_module
import src.platform.display_f3_manual_snapshot_debug as manual_debug_module
import src.platform.display_f3_operational_status as operational_module
import src.platform.display_f3_physical_learning_policy as physical_policy_module
import src.platform.display_f3_power_authority as power_module
import src.platform.display_f3_runtime_contract_fix as contract_module
from src.core.feature_extractor import extrair_features_selecao
from src.platform.display_auto_check_analyzer import (
    DISPLAY_AUTO_CLASS_LOW_LIGHT,
    display_mask_to_analysis_selection,
)
from src.platform.display_auto_check_policy import DISPLAY_AUTO_MIN_CONFIDENCE
from src.platform.display_check_presence_reference import DisplayCheckPresenceReferenceStore
from src.platform.display_f3_check_photo_learning import F3CheckPhotoLearningAnalyzer
import src.platform.display_f3_same_mask_reference_fix as same_mask_module
from src.platform.display_f3_exact_check_template import (
    F3_EXACT_MASK_AMBIGUOUS_BAND,
    comparar_mascara_com_gabarito_f3,
    _resize_visual_frame,
)
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
    normalizar_resolucao_display,
)
from src.platform.display_visual_rotation import preparar_check_visual_display


F3_UNIFIED_POWER_SOURCE = "f3_unified_live_mask_power_authority"
F3_POWER_PRIMARY_SOURCE = "same_physical_mask_on_off_learning"
F3_POWER_SECONDARY_SOURCE = "current_check_full_pixel_guard_fallback"
F3_POWER_VOTE_POLICY = "minimum_configured_check_majority_across_live_masks"


def _required_consensus_votes(expected_count: int) -> int:
    """Maioria estrita: ruído isolado nunca prova nem remove energia."""
    expected = max(0, int(expected_count or 0))
    return (expected // 2) + 1 if expected > 0 else 0


def _valid_image(frame) -> bool:
    return frame is not None and getattr(frame, "size", 0) > 0


def _safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _energy_authority_frame(app, frame):
    """Usa o frame fisico bruto para energia quando o tracker faz warp.

    O rastreamento pode substituir temporariamente camera_frame_atual por uma
    imagem alinhada a foto do CHECK para julgar conformidade. Esse warp e util
    para o CHECK, mas nao pode virar prova fisica de que um LED acendeu.
    """
    candidates = []

    if bool(getattr(app, "_display_f3_tracking_instance_frame_prepared", False)):
        candidates.append(
            (
                "tracking_raw_authority_frame",
                getattr(app, "_display_f3_tracking_raw_authority_frame", None),
            )
        )

    try:
        override_depth = int(
            getattr(app, "_display_f3_tracking_frame_override_depth", 0) or 0
        )
    except (TypeError, ValueError):
        override_depth = 0
    if override_depth > 0:
        candidates.append(
            (
                "tracking_raw_preview_frame",
                getattr(app, "_display_f3_tracking_raw_preview_frame", None),
            )
        )

    for source, candidate in candidates:
        if _valid_image(candidate):
            return candidate, source

    return frame, "pipeline_frame"


def _frame_token(app, frame):
    """Identifica a imagem real, não apenas o contador lógico da câmera.

    O contador camera_ultimo_frame_id pode voltar a valores já usados depois
    de reiniciar/reconfigurar a câmera. O DEBUG também congela uma cópia do frame
    mantendo o mesmo contador. Se o cache usar somente esse ID, uma evidência
    POWERED antiga pode ser reaproveitada sobre uma imagem fisicamente OFF.

    Mantemos o token lógico para rastreabilidade, mas acrescentamos a identidade
    da instância da câmera e do ndarray recebido. Assim o cache só é reutilizado
    quando a chamada aponta literalmente para o mesmo frame em memória.
    """
    try:
        logical_token = app._display_auto_frame_token(frame)
    except Exception:
        logical_token = ("object", id(frame))

    camera_service = getattr(app, "camera_service", None)
    return (
        logical_token,
        ("camera_service", id(camera_service) if camera_service is not None else None),
        ("frame_object", id(frame)),
    )


def _energy_live_mask_context(app, frame, project: dict, visual_rotation: int):
    """Retorna frame + máscaras no MESMO espaço físico usado para energia.

    Com tracking, as máscaras já foram projetadas para o frame RAW atual. Sem
    tracking, aplicamos apenas a rotação visual cardinal do projeto.
    """
    geometry = getattr(app, "_display_f3_tracking_live_geometry", None)
    if isinstance(geometry, dict) and bool(geometry.get("locked")):
        resolution = geometry.get("resolution")
        try:
            frame_h, frame_w = frame.shape[:2]
        except Exception:
            frame_h = frame_w = 0
        if (
            isinstance(resolution, (list, tuple))
            and len(resolution) >= 2
            and int(resolution[0]) == int(frame_w)
            and int(resolution[1]) == int(frame_h)
        ):
            masks = {
                str(mask.get("id") or ""): deepcopy(mask)
                for mask in (geometry.get("masks") or ())
                if isinstance(mask, dict) and str(mask.get("id") or "")
            }
            if masks:
                return (
                    frame,
                    masks,
                    "tracking_live_geometry_raw",
                    str(geometry.get("geometry_space") or ""),
                )

    resolution = normalizar_resolucao_display(project.get("master_resolution"))
    if resolution is None:
        return None, {}, "unavailable", ""

    project_masks = [
        deepcopy(mask)
        for mask in (project.get("masks") or ())
        if isinstance(mask, dict) and str(mask.get("id") or "")
    ]
    visual_frame, visual_resolution, visual_masks = preparar_check_visual_display(
        frame,
        resolution,
        project_masks,
        int(visual_rotation or 0) % 360,
    )
    visual_frame = _resize_visual_frame(visual_frame, visual_resolution)
    if not _valid_image(visual_frame):
        return None, {}, "unavailable", ""

    masks = {
        str(mask.get("id") or ""): mask
        for mask in visual_masks
        if isinstance(mask, dict) and str(mask.get("id") or "")
    }
    return visual_frame, masks, "project_visual_geometry", "project"


def _minimum_powered_votes_from_checks(repository, project_name: str, pair_ids: set[str]):
    """Menor padrão energizado configurado, limitado a máscaras discriminantes."""
    counts = []
    try:
        checks = repository.listar_checks(project_name)
    except Exception:
        checks = []

    for check in checks or ():
        if not isinstance(check, dict):
            continue
        states = (
            check.get("mask_states", {})
            if isinstance(check.get("mask_states"), dict)
            else {}
        )
        count = sum(
            1
            for mask_id in pair_ids
            if str(states.get(mask_id) or "") == DISPLAY_CHECK_STATE_ON
        )
        if count > 0:
            counts.append(int(count))

    if not counts:
        return 0, 0
    minimum = min(counts)
    return int(minimum), int(_required_consensus_votes(minimum))


def _generic_live_mask_energy(
    app,
    frame,
    project_name: str,
    context: dict,
) -> dict:
    """Decide somente se existe energia, sem perguntar qual CHECK está ativo.

    Cada máscara física é comparada com exemplos ON e OFF da PRÓPRIA máscara,
    extraídos das fotos reais dos CHECKS. Só máscaras que possuem o par local
    ON+OFF participam da autoridade de energia; fallback entre máscaras não
    pode energizar a placa.
    """
    repository = getattr(app, "display_project_repository", None)
    if repository is None or not _valid_image(frame):
        return {"available": False, "reason": "repository_ou_frame_ausente"}

    try:
        project = repository.carregar_projeto(project_name)
    except Exception:
        project = None
    if not isinstance(project, dict):
        return {"available": False, "reason": "projeto_display_inexistente"}

    try:
        rotation = int(app._obter_rotacao_visual_display_f3()) % 360
    except Exception:
        rotation = 0

    analyzer = getattr(app, "_display_f3_generic_power_analyzer", None)
    if (
        analyzer is None
        or getattr(analyzer, "repository", None) is not repository
        or not isinstance(analyzer, same_mask_module.F3SameMaskReferenceAnalyzer)
    ):
        analyzer = same_mask_module.F3SameMaskReferenceAnalyzer(repository)
        app._display_f3_generic_power_analyzer = analyzer

    project_masks = [
        mask
        for mask in (project.get("masks") or ())
        if isinstance(mask, dict) and str(mask.get("id") or "")
    ]
    try:
        learning = analyzer._check_photo_learning(
            project_name,
            project,
            project_masks,
            rotation,
        )
    except Exception:
        return {"available": False, "reason": "aprendizado_fotos_checks_indisponivel"}

    by_mask = learning.get("by_mask", {}) if isinstance(learning, dict) else {}
    local_pairs = {}
    for mask_id, profile in (by_mask.items() if isinstance(by_mask, dict) else ()):
        if not isinstance(profile, dict):
            continue
        on_refs = list(profile.get(DISPLAY_CHECK_STATE_ON, []) or ())
        off_refs = list(profile.get(DISPLAY_CHECK_STATE_OFF, []) or ())
        if on_refs and off_refs:
            local_pairs[str(mask_id)] = (on_refs, off_refs)

    if not local_pairs:
        return {"available": False, "reason": "sem_pares_locais_on_off"}

    live_frame, live_masks, geometry_source, geometry_space = _energy_live_mask_context(
        app,
        frame,
        project,
        rotation,
    )
    if not _valid_image(live_frame) or not live_masks:
        return {"available": False, "reason": "geometria_live_indisponivel"}

    minimum_on, required_powered = _minimum_powered_votes_from_checks(
        repository,
        project_name,
        set(local_pairs),
    )
    if required_powered <= 0:
        return {"available": False, "reason": "checks_sem_on_discriminante"}

    powered_votes = 0
    off_votes = 0
    tie_votes = 0
    details = []
    classifications = {}

    for mask_id, (on_refs, off_refs) in local_pairs.items():
        visual_mask = live_masks.get(mask_id)
        if not isinstance(visual_mask, dict):
            continue
        try:
            selection = display_mask_to_analysis_selection(visual_mask)
            features = extrair_features_selecao(live_frame, selection)
        except (TypeError, ValueError):
            continue
        if int(getattr(features, "area_pixels", 0) or 0) <= 0:
            continue

        try:
            classified = same_mask_module.classificar_mascara_por_referencias_locais_f3(
                current=features,
                on_references=on_refs,
                off_references=off_refs,
                detect_low_light=True,
            )
        except Exception:
            classified = None
        if not isinstance(classified, dict):
            continue

        state = str(classified.get("state") or "").strip().lower()
        confidence = _safe_float(classified.get("confidence"))
        confident = confidence >= DISPLAY_AUTO_MIN_CONFIDENCE
        vote = "tie"
        if confident and state in (DISPLAY_CHECK_STATE_ON, DISPLAY_AUTO_CLASS_LOW_LIGHT):
            powered_votes += 1
            vote = "powered"
        elif confident and state == DISPLAY_CHECK_STATE_OFF:
            off_votes += 1
            vote = "off"
        else:
            tie_votes += 1

        classifications[mask_id] = state
        details.append(
            {
                "mask_id": mask_id,
                "classified": state,
                "confidence": round(confidence, 4),
                "winner": vote,
                "distances": deepcopy(classified.get("distances") or {}),
                "reference_separation": classified.get("reference_separation"),
                "reference_source": classified.get("reference_source"),
                "local_on_reference_count": len(on_refs),
                "local_off_reference_count": len(off_refs),
            }
        )

    valid_votes = int(powered_votes + off_votes)
    powered_confirmed = bool(
        required_powered > 0 and powered_votes >= required_powered
    )
    off_confirmed = bool(
        not powered_confirmed
        and physical_policy_module.decidir_placa_desligada_por_votos_mascaras_f3(
            off_votes=off_votes,
            powered_votes=powered_votes,
            valid_votes=valid_votes,
        )
    )

    if powered_confirmed:
        energy_state = power_module.F3_POWER_STATE_POWERED
    elif off_confirmed:
        energy_state = power_module.F3_POWER_STATE_OFF
    else:
        energy_state = power_module.F3_POWER_STATE_UNCONFIRMED

    return {
        "available": bool(details),
        "source": F3_UNIFIED_POWER_SOURCE,
        "primary_authority": F3_POWER_PRIMARY_SOURCE,
        "secondary_guard": F3_POWER_SECONDARY_SOURCE,
        "legacy_power_evidence_used": False,
        "energy_state": energy_state,
        "powered_confirmed": powered_confirmed,
        "off_confirmed": off_confirmed,
        "logical_check_independent": True,
        "energy_scope": "all_discriminative_live_masks",
        "vote_policy": F3_POWER_VOTE_POLICY,
        "evaluated_mask_count": len(details),
        "same_mask_pair_count": len(local_pairs),
        "minimum_discriminative_on_count": int(minimum_on),
        "required_powered_votes": int(required_powered),
        # Compatibilidade com consumidores históricos do gate/debug.
        "expected_on_mask_count": int(minimum_on),
        "required_consensus_votes": int(required_powered),
        "powered_votes": int(powered_votes),
        "off_votes": int(off_votes),
        "tie_votes": int(tie_votes),
        "valid_votes": int(valid_votes),
        "raw_analysis_ready": bool(details),
        "raw_analysis_approved": None,
        "raw_analysis_matched_mask_count": 0,
        "raw_analysis_active_mask_count": len(details),
        "mask_classifications": classifications,
        "mask_geometry_source": geometry_source,
        "mask_geometry_space": geometry_space,
        "check_id": str((context or {}).get("check_id") or ""),
        "project_name": str(project_name or ""),
        "details": details,
    }


def _analysis_matches_context(analysis: dict | None, project_name: str, check_id: str) -> bool:
    return bool(
        isinstance(analysis, dict)
        and str(analysis.get("project_name") or "") == str(project_name or "")
        and str(analysis.get("check_id") or "") == str(check_id or "")
    )


def _run_raw_current_check_analysis(app, frame, project_name: str, context: dict) -> dict | None:
    repository = getattr(app, "display_project_repository", None)
    if repository is None or not _valid_image(frame):
        return None

    check_id = str(context.get("check_id") or "")
    signature = (str(project_name or ""), check_id, _frame_token(app, frame))
    if getattr(app, "_display_f3_unified_raw_cache_signature", None) == signature:
        cached = getattr(app, "_display_f3_unified_raw_analysis", None)
        if _analysis_matches_context(cached, project_name, check_id):
            return deepcopy(cached)

    analyzer = getattr(app, "_display_f3_unified_power_analyzer", None)
    if analyzer is None or getattr(analyzer, "repository", None) is not repository:
        analyzer = F3CheckPhotoLearningAnalyzer(repository)
        app._display_f3_unified_power_analyzer = analyzer

    try:
        rotation = int(app._obter_rotacao_visual_display_f3()) % 360
    except Exception:
        rotation = 0

    try:
        analysis = analyzer.analyze(
            frame=frame,
            project_name=str(project_name or ""),
            check_id=check_id,
            visual_rotation=rotation,
        )
    except Exception:
        return None
    if not isinstance(analysis, dict):
        return None

    analysis = deepcopy(analysis)
    analysis["decision_authority"] = False
    analysis["raw_diagnostic_only"] = True
    analysis["energy_evidence_authority"] = True
    analysis["energy_evidence_source"] = F3_POWER_PRIMARY_SOURCE
    app._display_f3_unified_raw_cache_signature = signature
    app._display_f3_unified_raw_analysis = deepcopy(analysis)
    return analysis


def _secondary_full_pixel_details(app, frame, project_name: str, context: dict) -> dict[str, dict]:
    """Compara LIVE com OFF e ON usando a métrica BGR/S/V/pixel existente.

    Não cria threshold novo: usa a banda ambígua já adotada pelo gabarito exato.
    O resultado é proteção/veto quando há uma preferência óptica inequívoca; em
    empate, a autoridade primária das máscaras permanece válida.
    """
    references = power_module._reference_context(app, frame, project_name, context)
    if not isinstance(references, dict) or not references.get("available"):
        return {}

    repository = getattr(app, "display_project_repository", None)
    project = repository.carregar_projeto(project_name) if repository is not None else None
    if not isinstance(project, dict):
        return {}
    resolution = normalizar_resolucao_display(project.get("master_resolution"))
    if resolution is None:
        return {}

    masks = [item for item in (project.get("masks") or []) if isinstance(item, dict)]
    live_visual, live_resolution, live_masks = preparar_check_visual_display(
        frame,
        resolution,
        masks,
        int(references.get("rotation", 0) or 0),
    )
    live_visual = _resize_visual_frame(live_visual, live_resolution)
    if not _valid_image(live_visual):
        return {}

    live_by_id = {
        str(mask.get("id") or ""): mask
        for mask in live_masks
        if isinstance(mask, dict) and str(mask.get("id") or "")
    }
    details: dict[str, dict] = {}
    for mask_id in references.get("expected_on_ids") or ():
        visual_mask = live_by_id.get(mask_id) or references.get("masks", {}).get(mask_id)
        if not isinstance(visual_mask, dict):
            continue
        try:
            selection = display_mask_to_analysis_selection(visual_mask)
        except (TypeError, ValueError):
            continue

        live_on = comparar_mascara_com_gabarito_f3(
            live_visual,
            references.get("on_frame"),
            selection,
        )
        live_off = comparar_mascara_com_gabarito_f3(
            live_visual,
            references.get("off_frame"),
            selection,
        )
        off_on = comparar_mascara_com_gabarito_f3(
            references.get("off_frame"),
            references.get("on_frame"),
            selection,
        )
        if not all(isinstance(item, dict) for item in (live_on, live_off, off_on)):
            continue

        similarity_on = _safe_float(live_on.get("similarity"))
        similarity_off = _safe_float(live_off.get("similarity"))
        reference_similarity = _safe_float(off_on.get("similarity"))
        reference_separation = max(0.0, 1.0 - reference_similarity)
        delta = similarity_on - similarity_off

        # Se a própria referência OFF e ON não se separa pelo menos pela banda
        # ambígua do matcher exato, ela não pode vetar a análise primária.
        discriminative = reference_separation >= F3_EXACT_MASK_AMBIGUOUS_BAND
        winner = "tie"
        if discriminative and delta >= F3_EXACT_MASK_AMBIGUOUS_BAND:
            winner = "powered"
        elif discriminative and delta <= -F3_EXACT_MASK_AMBIGUOUS_BAND:
            winner = "off"

        details[str(mask_id)] = {
            "mask_id": str(mask_id),
            "winner": winner,
            "similarity_on": round(similarity_on, 4),
            "similarity_off": round(similarity_off, 4),
            "delta_on_minus_off": round(delta, 4),
            "reference_similarity_off_on": round(reference_similarity, 4),
            "reference_separation": round(reference_separation, 4),
            "reference_discriminative": bool(discriminative),
            "source": F3_POWER_SECONDARY_SOURCE,
        }
    return details


def resumir_energia_por_analise_bruta_f3(
    analysis: dict | None,
    secondary_by_mask: dict[str, dict] | None = None,
) -> dict:
    """Transforma a leitura bruta do CHECK em uma única evidência de energia."""
    data = analysis if isinstance(analysis, dict) else {}
    secondary_by_mask = secondary_by_mask if isinstance(secondary_by_mask, dict) else {}
    rows = [item for item in (data.get("mask_results") or ()) if isinstance(item, dict)]
    expected_on_rows = [
        item for item in rows if str(item.get("expected") or "") == DISPLAY_CHECK_STATE_ON
    ]

    details = []
    powered_votes = 0
    off_votes = 0
    uncertain_votes = 0
    for item in expected_on_rows:
        mask_id = str(item.get("mask_id") or "")
        confidence = _safe_float(item.get("confidence"))
        confident = confidence >= DISPLAY_AUTO_MIN_CONFIDENCE
        matched = bool(item.get("matched"))
        classified = str(item.get("classified") or "")
        secondary = secondary_by_mask.get(mask_id)
        secondary_winner = str((secondary or {}).get("winner") or "tie")

        primary_winner = "tie"
        if confident and matched and classified == DISPLAY_CHECK_STATE_ON:
            primary_winner = "powered"
        elif confident and not matched and classified != DISPLAY_CHECK_STATE_ON:
            primary_winner = "off"

        # Proteção secundária: somente uma preferência inequívoca pode vetar o
        # primário. Empate/indisponível nunca impede um ON que o matcher completo
        # já confirmou com confiança.
        final_winner = primary_winner
        if primary_winner == "powered" and secondary_winner == "off":
            final_winner = "tie"
        elif primary_winner == "off" and secondary_winner == "powered":
            final_winner = "tie"
        elif primary_winner == "tie" and secondary_winner in {"powered", "off"}:
            final_winner = secondary_winner

        if final_winner == "powered":
            powered_votes += 1
        elif final_winner == "off":
            off_votes += 1
        else:
            uncertain_votes += 1

        details.append(
            {
                "mask_id": mask_id,
                "expected": DISPLAY_CHECK_STATE_ON,
                "classified": classified,
                "matched": matched,
                "confidence": round(confidence, 4),
                "primary_winner": primary_winner,
                "secondary_winner": secondary_winner,
                "winner": final_winner,
                "template_similarity": item.get("template_similarity"),
                "secondary": deepcopy(secondary) if isinstance(secondary, dict) else None,
            }
        )

    expected = len(expected_on_rows)
    required_votes = _required_consensus_votes(expected)
    analysis_ready = bool(data.get("ready"))
    complete_vote_set = bool(expected > 0 and len(details) == expected)

    # Não basta UMA máscara dizer ON. Depois de redesenhar/recalibrar referências,
    # pequenas diferenças ópticas podem produzir 1-3 falsos positivos em H1.
    # Energia e OFF usam a mesma maioria estrita sobre as máscaras que o CHECK
    # espera acesas. Empate/mistura insuficiente permanece UNCONFIRMED e, portanto,
    # não colore overlay/visor nem libera julgamento produtivo.
    powered_confirmed = bool(
        analysis_ready
        and complete_vote_set
        and required_votes > 0
        and powered_votes >= required_votes
    )
    off_confirmed = bool(
        analysis_ready
        and complete_vote_set
        and required_votes > 0
        and off_votes >= required_votes
    )

    if powered_confirmed:
        energy_state = power_module.F3_POWER_STATE_POWERED
    elif off_confirmed:
        energy_state = power_module.F3_POWER_STATE_OFF
    else:
        energy_state = power_module.F3_POWER_STATE_UNCONFIRMED

    return {
        "available": bool(data.get("ready") and expected > 0),
        "source": F3_UNIFIED_POWER_SOURCE,
        "primary_authority": F3_POWER_PRIMARY_SOURCE,
        "secondary_guard": F3_POWER_SECONDARY_SOURCE,
        "legacy_power_evidence_used": False,
        "energy_state": energy_state,
        "powered_confirmed": powered_confirmed,
        "off_confirmed": off_confirmed,
        "all_expected_on_off": bool(
            expected > 0 and off_votes == expected and complete_vote_set
        ),
        "expected_on_mask_count": expected,
        "required_consensus_votes": int(required_votes),
        "vote_policy": F3_POWER_VOTE_POLICY,
        "powered_votes": int(powered_votes),
        "off_votes": int(off_votes),
        "tie_votes": int(uncertain_votes),
        "valid_votes": int(powered_votes + off_votes),
        "raw_analysis_ready": bool(data.get("ready")),
        "raw_analysis_approved": data.get("approved"),
        "raw_analysis_matched_mask_count": int(data.get("matched_mask_count", 0) or 0),
        "raw_analysis_active_mask_count": int(data.get("active_mask_count", 0) or 0),
        "details": details,
    }


def avaliar_evidencia_energia_unificada_display_f3(
    app,
    frame,
    project_name: str,
    context: dict | None,
) -> dict:
    authority_frame, authority_frame_source = _energy_authority_frame(app, frame)
    if not isinstance(context, dict) or not _valid_image(authority_frame):
        return {
            "available": False,
            "source": F3_UNIFIED_POWER_SOURCE,
            "energy_state": power_module.F3_POWER_STATE_UNCONFIRMED,
            "powered_confirmed": False,
            "off_confirmed": False,
            "reason": "frame_ou_contexto_ausente",
            "authority_frame_source": authority_frame_source,
        }

    check_id = str(context.get("check_id") or "")
    geometry = getattr(app, "_display_f3_tracking_live_geometry", None)
    geometry_token = (
        id(geometry),
        str((geometry or {}).get("geometry_space") or "")
        if isinstance(geometry, dict)
        else "",
    )
    cache_key = (
        str(project_name or ""),
        check_id,
        authority_frame_source,
        _frame_token(app, authority_frame),
        geometry_token,
    )
    cached = getattr(app, "_display_f3_unified_power_cache", None)
    if isinstance(cached, dict) and cached.get("key") == cache_key:
        return deepcopy(cached.get("value"))

    evidence = _generic_live_mask_energy(
        app,
        authority_frame,
        project_name,
        context,
    )

    # Compatibilidade fail-safe para projetos antigos que ainda não possuem
    # pares ON/OFF da mesma máscara em suas fotos de CHECK.
    if not bool(isinstance(evidence, dict) and evidence.get("available")):
        raw = _run_raw_current_check_analysis(
            app,
            authority_frame,
            project_name,
            context,
        )
        secondary = _secondary_full_pixel_details(
            app,
            authority_frame,
            project_name,
            context,
        )
        fallback = resumir_energia_por_analise_bruta_f3(raw, secondary)
        fallback["logical_check_independent"] = False
        fallback["energy_scope"] = "current_check_fallback"
        fallback["fallback_reason"] = str((evidence or {}).get("reason") or "")
        evidence = fallback

    evidence["project_name"] = str(project_name or "")
    evidence["check_id"] = check_id
    evidence["same_mask_comparison"] = True
    evidence["same_visual_rotation"] = True
    evidence["authority_frame_source"] = authority_frame_source
    evidence["tracking_aligned_frame_ignored_for_energy"] = bool(
        authority_frame is not frame
    )
    try:
        evidence["visual_rotation"] = int(app._obter_rotacao_visual_display_f3()) % 360
    except Exception:
        evidence["visual_rotation"] = 0

    app._display_f3_unified_power_cache = {"key": cache_key, "value": deepcopy(evidence)}
    return deepcopy(evidence)


def _clear_legacy_energy_keys(state: dict) -> None:
    for key in (
        "powered_mask_evidence",
        "power_mask_evidence_v2",
        "power_mask_evidence_v1",
        "current_check_power_mask_evidence",
    ):
        state.pop(key, None)


def aplicar_autoridade_energia_unificada_ao_estado_f3(
    app,
    state: dict | None,
    frame,
    project_name: str,
    context: dict | None,
) -> dict:
    """Única verdade operacional de energia do F3."""
    result = deepcopy(state) if isinstance(state, dict) else {}
    _clear_legacy_energy_keys(result)
    result[contract_module.F3_MASK_LIVE_KEY] = True

    if power_module._rearm_active(app):
        result["allow_auto"] = False
        result[contract_module.F3_DECISION_ALLOWED_KEY] = False
        result["power_gate_blocked"] = True
        result["power_gate_reason"] = "aguardando_rearme_fisico"
        result["power_authority_source"] = F3_UNIFIED_POWER_SOURCE
        return result

    presence = power_module._presence_from_global_scores(result)
    result["board_presence_evidence"] = presence
    if not bool(presence.get("board_present")):
        if str(result.get("kind") or "").strip().lower() != "empty":
            result.update(
                {
                    "kind": "unknown",
                    "text": "IDENTIFICANDO PRESENÇA DA PLACA...",
                    "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"],
                    "physical_state_key": "presence:unknown",
                }
            )
        result["allow_auto"] = False
        result[contract_module.F3_DECISION_ALLOWED_KEY] = False
        result["power_gate_blocked"] = True
        result["power_gate_reason"] = "placa_nao_confirmada_no_suporte"
        result["power_authority_source"] = F3_UNIFIED_POWER_SOURCE
        app._display_f3_power_authority_status = {
            "source": F3_UNIFIED_POWER_SOURCE,
            "board_present": False,
            "presence": deepcopy(presence),
            "energy": None,
            "decision_allowed": False,
            "reason": result["power_gate_reason"],
        }
        return result

    evidence = avaliar_evidencia_energia_unificada_display_f3(
        app,
        frame,
        project_name,
        context,
    )
    result["power_evidence"] = evidence
    result["power_authority_source"] = F3_UNIFIED_POWER_SOURCE
    check_id = str((context or {}).get("check_id") or "")
    check_name = str((context or {}).get("check_name") or check_id or "CHECK").strip().upper()

    if bool(evidence.get("powered_confirmed")):
        result.update(
            {
                "kind": "powered",
                "text": f"PLACA NO SUPORTE • LIGADA • ANALISANDO {check_name}",
                "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["check"],
                "allow_auto": True,
                "physical_state_key": "powered:live_same_mask_learning",
                "expected_check_id": check_id,
                "physical_matches_expected_check": False,
                "powered_board_confirmed": True,
                "power_gate_blocked": False,
                "power_gate_reason": "energia_confirmada_pelas_mascaras_fisicas_live",
                contract_module.F3_DECISION_ALLOWED_KEY: True,
                contract_module.F3_MASK_LIVE_KEY: True,
            }
        )
        decision_allowed = True
    else:
        is_off = bool(evidence.get("off_confirmed"))
        result.update(
            {
                "kind": "off" if is_off else "unknown",
                "text": (
                    "PLACA NO SUPORTE • DESLIGADA • AGUARDANDO DISPLAY LIGADO"
                    if is_off
                    else "PLACA NO SUPORTE • ENERGIA DO DISPLAY NÃO CONFIRMADA"
                ),
                "color": operational_module.F3_OPERATIONAL_STATUS_COLORS[
                    "off" if is_off else "unknown"
                ],
                "allow_auto": False,
                "physical_state_key": "off" if is_off else "power:unconfirmed",
                "powered_board_confirmed": False,
                "power_gate_blocked": True,
                "power_gate_reason": (
                    "todos_segmentos_esperados_acesos_estao_apagados"
                    if is_off
                    else "nenhum_segmento_aceso_confirmou_energia"
                ),
                contract_module.F3_DECISION_ALLOWED_KEY: False,
                contract_module.F3_MASK_LIVE_KEY: True,
            }
        )
        decision_allowed = False

    app._display_f3_power_authority_status = {
        "source": F3_UNIFIED_POWER_SOURCE,
        "board_present": True,
        "presence": deepcopy(presence),
        "energy": deepcopy(evidence),
        "decision_allowed": bool(decision_allowed),
        "reason": str(result.get("power_gate_reason") or ""),
    }
    return result


def _reference_sha256_24(metadata: dict | None) -> str:
    if not isinstance(metadata, dict):
        return "--"
    path = Path(str(metadata.get("image_path") or ""))
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:24]
    except OSError:
        return "--"


def _cache_key_digest(analyzer) -> tuple[str, str]:
    key = getattr(analyzer, "_check_template_cache_key", None)
    if not isinstance(key, tuple):
        return "--", "--"
    check_id = str(key[1]) if len(key) > 1 else "--"
    digest = hashlib.sha256(repr(key).encode("utf-8", errors="replace")).hexdigest()[:16]
    return check_id, digest


def _reference_provenance(repository, project_name: str, check_id: str, analyzer) -> dict:
    store = DisplayCheckPresenceReferenceStore(repository)
    metadata = store.get(project_name, check_id)
    check = repository.carregar_check(project_name, check_id)
    loaded_id = str((check or {}).get("id") or "") if isinstance(check, dict) else ""
    cache_check_id, cache_digest = _cache_key_digest(analyzer)
    return {
        "check_id_requested": str(check_id),
        "check_id_loaded": loaded_id,
        "reference_image": str((metadata or {}).get("image_path") or "--"),
        "reference_sha256_24": _reference_sha256_24(metadata),
        "cache_key_check_id": cache_check_id,
        "cache_key_digest_16": cache_digest,
        "fresh_analyzer_per_check": True,
        "canonical_analyzer": "F3CheckPhotoLearningAnalyzer",
    }


def _debug_energy_from_analysis(analysis: dict | None) -> dict:
    result = resumir_energia_por_analise_bruta_f3(analysis, {})
    result["diagnostic_only"] = True
    result["decision_authority"] = False
    # Campos históricos esperados pelo formatador.
    for item in result.get("details") or ():
        item["distance_off"] = None
        item["distance_check"] = None
        item["reference_span"] = None
        item["separation"] = None
    return result


def _run_check_analyses_with_provenance(
    repository,
    matcher,
    frame,
    project_name: str,
    checks: list[dict],
    rotation: int,
) -> list[dict]:
    """DEBUG separa gabarito exato do classificador produtivo por mesma máscara."""
    rows = []
    # O aprendizado ON/OFF é o mesmo dataset para todos os CHECKS. Compartilhar
    # esta instância evita reler as quatro fotos e reextrair 28 máscaras quatro
    # vezes no mesmo clique de DEBUG.
    productive_analyzer = same_mask_module.F3SameMaskReferenceAnalyzer(repository)
    for check in checks:
        check_id = str(check.get("id") or "")
        if not check_id:
            continue

        exact_analyzer = F3CheckPhotoLearningAnalyzer(repository)
        try:
            exact_analysis = exact_analyzer.analyze(
                frame=frame,
                project_name=project_name,
                check_id=check_id,
                visual_rotation=int(rotation or 0),
            )
        except Exception as exc:
            exact_analysis = {
                "ready": False,
                "approved": None,
                "reason": f"debug_exact_analysis_error:{type(exc).__name__}:{exc}",
                "project_name": str(project_name),
                "check_id": check_id,
                "check_name": str(check.get("name") or check_id),
                "mask_results": [],
            }

        try:
            productive_analysis = productive_analyzer.analyze(
                frame=frame,
                project_name=project_name,
                check_id=check_id,
                visual_rotation=int(rotation or 0),
            )
        except Exception as exc:
            productive_analysis = {
                "ready": False,
                "approved": None,
                "reason": f"debug_productive_analysis_error:{type(exc).__name__}:{exc}",
                "project_name": str(project_name),
                "check_id": check_id,
                "check_name": str(check.get("name") or check_id),
                "mask_results": [],
            }

        provenance = _reference_provenance(
            repository,
            project_name,
            check_id,
            exact_analyzer,
        )
        exact_analysis = deepcopy(exact_analysis)
        exact_analysis["reference_provenance"] = provenance
        exact_analysis["debug_fresh_analyzer_per_check"] = True
        exact_analysis["debug_decision_authority"] = False

        productive_analysis = deepcopy(productive_analysis)
        productive_analysis["debug_productive_classifier"] = True
        productive_analysis["debug_shared_learning_dataset"] = True
        productive_analysis["debug_decision_authority"] = False

        rows.append(
            {
                "check_id": check_id,
                "check_name": str(check.get("name") or check_id),
                "exact_template": exact_analysis,
                "check_photo_learning": productive_analysis,
                # Diagnóstico legado por CHECK. A energia produtiva real é global
                # e aparece no bloco POWER AUTHORITY do runtime.
                "power_mask_evidence": _debug_energy_from_analysis(exact_analysis),
                "reference_provenance": provenance,
                "single_canonical_analysis": False,
            }
        )
    return rows


def _install_debug_check_provenance() -> None:
    manual_debug_module._run_check_analyses = _run_check_analyses_with_provenance

    if bool(getattr(manual_debug_module, "_display_f3_reference_provenance_formatter_installed", False)):
        return
    previous_append = manual_debug_module._append_analysis_summary

    def append(lines: list[str], title: str, analysis: dict | None) -> None:
        previous_append(lines, title, analysis)
        data = analysis if isinstance(analysis, dict) else {}
        provenance = data.get("reference_provenance")
        if not isinstance(provenance, dict):
            return
        if "GABARITO EXATO" in str(title).upper():
            lines.append("[PROVENIÊNCIA DA REFERÊNCIA DO CHECK]")
            lines.append(
                " | ".join(
                    (
                        f"check_id_requested={provenance.get('check_id_requested', '--')}",
                        f"check_id_loaded={provenance.get('check_id_loaded', '--')}",
                        f"cache_check_id={provenance.get('cache_key_check_id', '--')}",
                        f"cache_digest={provenance.get('cache_key_digest_16', '--')}",
                    )
                )
            )
            lines.append(f"reference_image={provenance.get('reference_image', '--')}")
            lines.append(f"reference_sha256_24={provenance.get('reference_sha256_24', '--')}")
            lines.append("fresh_analyzer_per_check=SIM | cache_compartilhado_entre_checks=NÃO")

    manual_debug_module._append_analysis_summary = append
    manual_debug_module._display_f3_reference_provenance_formatter_installed = True


def _install_debug_power_summary_v2() -> None:
    previous_report = power_module._report_summary_power

    def report(snapshot: dict) -> str:
        base = previous_report(snapshot)
        lines = str(base).splitlines()

        runtime = snapshot.get("runtime_at_click") if isinstance(snapshot, dict) else {}
        runtime = runtime if isinstance(runtime, dict) else {}
        status = runtime.get("power_authority")
        status = status if isinstance(status, dict) else {}
        energy = status.get("energy")
        energy = energy if isinstance(energy, dict) else {}
        generic = bool(energy.get("logical_check_independent"))

        if generic:
            replacements = {
                "SEGMENTOS ESPERADOS ON:": "BASE MÍNIMA ON PARA PROVAR ENERGIA:",
                "ON CONFIRMADOS:": "MÁSCARAS LIVE ON CONFIRMADAS:",
                "OFF CONFIRMADOS NOS ON ESPERADOS:": "MÁSCARAS LIVE OFF CONFIRMADAS:",
            }
            for index, line in enumerate(lines):
                for prefix, replacement in replacements.items():
                    if str(line).startswith(prefix):
                        lines[index] = str(line).replace(prefix, replacement, 1)
                        break

        insert_at = 7 if len(lines) >= 7 else len(lines)
        lines[insert_at:insert_at] = [
            f"FONTE ÚNICA DE ENERGIA: {F3_POWER_PRIMARY_SOURCE}",
            "ESCOPO DA ENERGIA: TODAS AS MÁSCARAS FÍSICAS DISCRIMINANTES • INDEPENDENTE DO CHECK LÓGICO",
            f"FALLBACK LEGADO: {F3_POWER_SECONDARY_SOURCE}",
        ]
        return "\n".join(lines)

    power_module._report_summary_power = report
    debug_clarity_module._report_summary_block = report


def _install_raw_overlay_reuse() -> None:
    if bool(getattr(power_module, "_display_f3_unified_raw_overlay_reuse_installed", False)):
        return
    previous_raw = power_module._raw_analysis_for_overlay

    def raw(app, frame, context: dict):
        project_name = str((context or {}).get("project_name") or "")
        check_id = str((context or {}).get("check_id") or "")
        authority_frame, authority_frame_source = _energy_authority_frame(app, frame)
        signature = (project_name, check_id, _frame_token(app, authority_frame))
        cached = getattr(app, "_display_f3_unified_raw_analysis", None)
        if (
            getattr(app, "_display_f3_unified_raw_cache_signature", None) == signature
            and _analysis_matches_context(cached, project_name, check_id)
        ):
            analysis = deepcopy(cached)
            analysis["decision_authority"] = False
            analysis["raw_diagnostic_only"] = True
            analysis["blocked_by_power_gate"] = True
            analysis["authority_frame_source"] = authority_frame_source
            app._display_auto_last_analysis = deepcopy(analysis)
            app._display_f3_power_blocked_raw_analysis = deepcopy(analysis)
            return analysis
        return previous_raw(app, authority_frame, context)

    power_module._raw_analysis_for_overlay = raw
    power_module._display_f3_unified_raw_overlay_reuse_installed = True


_INSTALLED = False


def instalar_autoridade_energia_unificada_display_f3() -> None:
    """Fecha a autoridade F3 depois de todas as camadas históricas."""
    global _INSTALLED
    if _INSTALLED:
        return

    # Os builders/process wrappers já instalados por display_f3_power_authority
    # resolvem estes nomes no módulo em tempo de execução. Trocá-los aqui mantém
    # a ordem de wrappers e substitui somente a fonte final de verdade.
    power_module.avaliar_evidencia_energia_relativa_display_f3 = (
        avaliar_evidencia_energia_unificada_display_f3
    )
    power_module.aplicar_autoridade_energia_ao_estado_f3 = (
        aplicar_autoridade_energia_unificada_ao_estado_f3
    )
    power_module.F3_POWER_AUTHORITY_SOURCE = F3_UNIFIED_POWER_SOURCE

    _install_raw_overlay_reuse()
    _install_debug_check_provenance()
    _install_debug_power_summary_v2()

    power_module._display_f3_unified_power_authority_installed = True
    _INSTALLED = True
