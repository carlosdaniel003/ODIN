from __future__ import annotations

"""Autoridade final de presença -> energia -> CHECK -> conformidade do F3.

A comparação visual de quadro inteiro permanece útil para responder somente se
há placa no suporte. Ela não decide mais se o display está em H1/BLUE/USB/AUX e
não possui autoridade para liberar OK/NG.

A energia é confirmada dentro das próprias máscaras que o CHECK lógico espera
ACESAS. Para cada uma delas comparamos a MESMA máscara, na MESMA rotação visual,
em três imagens:

* PLACA DESLIGADA (OFF);
* foto capturada do CHECK atual (ON para aquela máscara);
* frame ao vivo.

Enquanto nenhuma máscara esperada ACESA estiver inequivocamente mais próxima da
referência ON, o analisador produtivo não recebe autoridade de decisão. A análise
bruta continua podendo rodar somente para overlay/debug, sem OK, NG ou avanço.

Este módulo é exclusivo do F3 e é instalado por último, depois das camadas
históricas. Não cria timer, não lê uma segunda câmera e não altera o F2.
"""

from copy import deepcopy
from pathlib import Path

import cv2
import numpy as np

import src.platform.display_auto_check_runtime as runtime_module
import src.platform.display_f3_debug_clarity_fix as debug_clarity_module
import src.platform.display_f3_live_runtime_fix as live_runtime_module
import src.platform.display_f3_operational_status as operational_module
import src.platform.display_f3_physical_learning_policy as physical_policy_module
import src.platform.display_f3_runtime_contract_fix as contract_module
from src.core.roi_geometry import criar_mascaras_roi
from src.platform.display_auto_check_analyzer import display_mask_to_analysis_selection
from src.platform.display_f3_exact_check_template import (
    _read_reference_full,
    _resize_visual_frame,
)
from src.platform.display_f3_physical_powered_gate import (
    F3_POWERED_MIN_BOARD_SCENE_SCORE,
    F3_POWERED_MIN_OFF_OVER_EMPTY_MARGIN,
)
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_ON,
    normalizar_resolucao_display,
)
from src.platform.display_visual_reference_status import (
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
    DisplayVisualReferenceMatcher,
)
from src.platform.display_visual_rotation import preparar_check_visual_display


F3_POWER_AUTHORITY_SOURCE = "f3_same_mask_relative_power_authority"
F3_POWER_STATE_POWERED = "powered"
F3_POWER_STATE_OFF = "off"
F3_POWER_STATE_UNCONFIRMED = "unconfirmed"

# Estes limiares são relativos entre a MESMA máscara OFF <-> ON; não alteram os
# thresholds/margens globais das referências visuais.
F3_POWER_RELATIVE_OFF_MAX = 0.35
F3_POWER_RELATIVE_ON_MIN = 0.65
F3_POWER_MIN_REFERENCE_DISTANCE = 0.06

# V médio/picos detectam energia do segmento; percentuais de pixels muito claros
# ajudam a separar LED realmente aceso de reflexo/placa clara.
F3_POWER_FEATURE_WEIGHTS = {
    "v_mean": 0.34,
    "v_p95": 0.18,
    "v_p99": 0.12,
    "hot_235": 0.20,
    "hot_245": 0.16,
}


def _safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _file_signature(path_value) -> tuple[str, int, int]:
    path = Path(str(path_value or ""))
    try:
        stat = path.stat()
        return str(path), int(stat.st_mtime_ns), int(stat.st_size)
    except OSError:
        return str(path), 0, 0


def _valid_image(frame) -> bool:
    return frame is not None and getattr(frame, "size", 0) > 0


def _mask_optical_signature(frame, selection) -> dict | None:
    """Extrai somente energia luminosa dentro da geometria da máscara."""
    if not _valid_image(frame):
        return None
    height, width = frame.shape[:2]
    prepared = criar_mascaras_roi(selection, width, height)
    if prepared is None:
        return None

    x1, y1, x2, y2, mask, _inner, _ring = prepared
    roi = frame[y1:y2, x1:x2]
    if not _valid_image(roi) or mask is None:
        return None

    mask_bool = np.asarray(mask).astype(bool)
    if mask_bool.size == 0 or int(np.count_nonzero(mask_bool)) <= 0:
        return None

    blur = cv2.GaussianBlur(roi, (3, 3), 0)
    hsv = cv2.cvtColor(blur, cv2.COLOR_BGR2HSV)
    values = hsv[:, :, 2][mask_bool].astype(np.float32)
    if values.size <= 0:
        return None

    return {
        "v_mean": float(np.mean(values)),
        "v_p95": float(np.percentile(values, 95)),
        "v_p99": float(np.percentile(values, 99)),
        "hot_235": float(np.mean(values >= 235.0)),
        "hot_245": float(np.mean(values >= 245.0)),
        "pixel_count": int(values.size),
    }


def _normalized_feature(signature: dict, name: str) -> float:
    value = _safe_float(signature.get(name), 0.0)
    if name.startswith("v_"):
        return max(0.0, min(1.0, value / 255.0))
    return max(0.0, min(1.0, value))


def distancia_optica_mascara_f3(left: dict, right: dict) -> float:
    """Distância normalizada 0..1 entre duas assinaturas da mesma máscara."""
    total = 0.0
    for name, weight in F3_POWER_FEATURE_WEIGHTS.items():
        total += abs(
            _normalized_feature(left, name) - _normalized_feature(right, name)
        ) * float(weight)
    return float(total)


def classificar_posicao_relativa_energia_f3(
    live: dict,
    off: dict,
    on: dict,
) -> dict:
    """Posiciona LIVE no eixo óptico OFF(0) <-> ON(1) da mesma máscara."""
    reference_distance = distancia_optica_mascara_f3(off, on)
    distance_off = distancia_optica_mascara_f3(live, off)
    distance_on = distancia_optica_mascara_f3(live, on)

    if reference_distance < F3_POWER_MIN_REFERENCE_DISTANCE:
        return {
            "winner": "tie",
            "power_position": None,
            "reference_discriminative": False,
            "reference_distance": round(reference_distance, 4),
            "distance_off": round(distance_off, 4),
            "distance_on": round(distance_on, 4),
            "reason": "off_on_muito_proximos_na_mesma_mascara",
        }

    denominator = distance_off + distance_on
    if denominator <= 1e-9:
        position = 0.5
    else:
        position = distance_off / denominator

    winner = "tie"
    if position <= F3_POWER_RELATIVE_OFF_MAX:
        winner = "off"
    elif position >= F3_POWER_RELATIVE_ON_MIN:
        winner = "powered"

    return {
        "winner": winner,
        "power_position": round(float(position), 4),
        "reference_discriminative": True,
        "reference_distance": round(reference_distance, 4),
        "distance_off": round(distance_off, 4),
        "distance_on": round(distance_on, 4),
    }


def resumir_votos_energia_f3(details: list[dict], expected_on_count: int) -> dict:
    powered = sum(1 for item in details if item.get("winner") == "powered")
    off = sum(1 for item in details if item.get("winner") == "off")
    ties = sum(1 for item in details if item.get("winner") == "tie")
    expected = max(0, int(expected_on_count or 0))
    valid = powered + off

    # Regra operacional principal: um único segmento ON inequivocamente detectado
    # já prova que o display está energizado. Só chamamos de OFF confirmado quando
    # TODAS as máscaras que deveriam estar ON foram lidas inequivocamente como OFF.
    powered_confirmed = bool(powered >= 1)
    all_expected_on_off = bool(expected > 0 and off == expected and len(details) == expected)

    if powered_confirmed:
        energy_state = F3_POWER_STATE_POWERED
    elif all_expected_on_off:
        energy_state = F3_POWER_STATE_OFF
    else:
        energy_state = F3_POWER_STATE_UNCONFIRMED

    return {
        "energy_state": energy_state,
        "powered_confirmed": powered_confirmed,
        "off_confirmed": all_expected_on_off,
        "all_expected_on_off": all_expected_on_off,
        "expected_on_mask_count": expected,
        "powered_votes": int(powered),
        "off_votes": int(off),
        "tie_votes": int(ties),
        "valid_votes": int(valid),
    }


def _reference_context(app, frame, project_name: str, context: dict) -> dict | None:
    repository = getattr(app, "display_project_repository", None)
    if repository is None:
        return None

    project = repository.carregar_projeto(project_name)
    check_id = str(context.get("check_id") or "")
    check = repository.carregar_check(project_name, check_id)
    if not isinstance(project, dict) or not isinstance(check, dict):
        return None

    resolution = normalizar_resolucao_display(project.get("master_resolution"))
    if resolution is None:
        return None

    masks = [item for item in (project.get("masks") or []) if isinstance(item, dict)]
    states = check.get("mask_states") if isinstance(check.get("mask_states"), dict) else {}
    expected_on_ids = [
        str(mask.get("id") or "")
        for mask in masks
        if states.get(str(mask.get("id") or "")) == DISPLAY_CHECK_STATE_ON
    ]
    if not expected_on_ids:
        return {
            "available": False,
            "reason": "check_sem_mascara_esperada_acesa",
            "expected_on_ids": [],
        }

    matcher = getattr(app, "_display_f3_operational_matcher", None)
    if matcher is None or getattr(matcher, "repository", None) is not repository:
        matcher = DisplayVisualReferenceMatcher(repository)
        app._display_f3_operational_matcher = matcher

    project_refs = matcher.project_store.get_all(project_name)
    off_metadata = project_refs.get(DISPLAY_PROJECT_REFERENCE_BOARD_OFF)
    on_metadata = matcher.check_store.get(project_name, check_id)
    if not isinstance(off_metadata, dict) or not isinstance(on_metadata, dict):
        return {
            "available": False,
            "reason": "referencia_off_ou_check_ausente",
            "expected_on_ids": expected_on_ids,
        }

    try:
        rotation = int(app._obter_rotacao_visual_display_f3()) % 360
    except Exception:
        rotation = 0

    cache_key = (
        str(project_name),
        check_id,
        rotation,
        tuple(resolution),
        str(project.get("updated_at") or ""),
        _file_signature(off_metadata.get("image_path")),
        _file_signature(on_metadata.get("image_path")),
    )
    cached = getattr(app, "_display_f3_power_reference_cache", None)
    if isinstance(cached, dict) and cached.get("key") == cache_key:
        return cached.get("value")

    off_raw = _read_reference_full(off_metadata)
    on_raw = _read_reference_full(on_metadata)
    if not _valid_image(off_raw) or not _valid_image(on_raw):
        return {
            "available": False,
            "reason": "arquivo_referencia_off_ou_check_indisponivel",
            "expected_on_ids": expected_on_ids,
        }

    off_visual, visual_resolution, visual_masks = preparar_check_visual_display(
        off_raw,
        resolution,
        masks,
        rotation,
    )
    on_visual, on_resolution, on_masks = preparar_check_visual_display(
        on_raw,
        resolution,
        masks,
        rotation,
    )
    off_visual = _resize_visual_frame(off_visual, visual_resolution)
    on_visual = _resize_visual_frame(on_visual, on_resolution)
    if not _valid_image(off_visual) or not _valid_image(on_visual):
        return {
            "available": False,
            "reason": "referencia_visual_rotacionada_invalida",
            "expected_on_ids": expected_on_ids,
        }

    visual_by_id = {
        str(mask.get("id") or ""): mask
        for mask in visual_masks
        if isinstance(mask, dict) and str(mask.get("id") or "")
    }
    on_by_id = {
        str(mask.get("id") or ""): mask
        for mask in on_masks
        if isinstance(mask, dict) and str(mask.get("id") or "")
    }
    if any(mask_id not in visual_by_id or mask_id not in on_by_id for mask_id in expected_on_ids):
        return {
            "available": False,
            "reason": "mascara_visual_esperada_nao_encontrada",
            "expected_on_ids": expected_on_ids,
        }

    value = {
        "available": True,
        "rotation": rotation,
        "resolution": tuple(visual_resolution),
        "masks": visual_by_id,
        "off_frame": off_visual,
        "on_frame": on_visual,
        "expected_on_ids": expected_on_ids,
    }
    app._display_f3_power_reference_cache = {"key": cache_key, "value": value}
    return value


def avaliar_evidencia_energia_relativa_display_f3(
    app,
    frame,
    project_name: str,
    context: dict | None,
) -> dict:
    """Compara OFF/LIVE/ON pela mesma máscara e mesma rotação visual."""
    if not isinstance(context, dict) or not _valid_image(frame):
        return {
            "available": False,
            "energy_state": F3_POWER_STATE_UNCONFIRMED,
            "powered_confirmed": False,
            "reason": "frame_ou_contexto_ausente",
        }

    try:
        frame_token = app._display_auto_frame_token(frame)
    except Exception:
        frame_token = ("object", id(frame))
    cache_key = (
        str(project_name),
        str(context.get("check_id") or ""),
        frame_token,
    )
    cached = getattr(app, "_display_f3_power_evidence_cache", None)
    if isinstance(cached, dict) and cached.get("key") == cache_key:
        return deepcopy(cached.get("value"))

    references = _reference_context(app, frame, project_name, context)
    if not isinstance(references, dict) or not references.get("available"):
        result = {
            "available": False,
            "energy_state": F3_POWER_STATE_UNCONFIRMED,
            "powered_confirmed": False,
            "reason": str((references or {}).get("reason") or "referencias_indisponiveis"),
            "expected_on_mask_count": len((references or {}).get("expected_on_ids") or ()),
            "details": [],
        }
        app._display_f3_power_evidence_cache = {"key": cache_key, "value": result}
        return deepcopy(result)

    repository = getattr(app, "display_project_repository", None)
    project = repository.carregar_projeto(project_name) if repository is not None else None
    if not isinstance(project, dict):
        return {
            "available": False,
            "energy_state": F3_POWER_STATE_UNCONFIRMED,
            "powered_confirmed": False,
            "reason": "projeto_indisponivel",
        }

    resolution = normalizar_resolucao_display(project.get("master_resolution"))
    masks = [item for item in (project.get("masks") or []) if isinstance(item, dict)]
    live_visual, live_resolution, live_masks = preparar_check_visual_display(
        frame,
        resolution,
        masks,
        int(references.get("rotation", 0) or 0),
    )
    live_visual = _resize_visual_frame(live_visual, live_resolution)
    live_by_id = {
        str(mask.get("id") or ""): mask
        for mask in live_masks
        if isinstance(mask, dict) and str(mask.get("id") or "")
    }

    details: list[dict] = []
    for mask_id in references.get("expected_on_ids") or ():
        visual_mask = live_by_id.get(mask_id) or references["masks"].get(mask_id)
        if not isinstance(visual_mask, dict):
            continue
        try:
            selection = display_mask_to_analysis_selection(visual_mask)
        except (TypeError, ValueError):
            continue

        live_signature = _mask_optical_signature(live_visual, selection)
        off_signature = _mask_optical_signature(references["off_frame"], selection)
        on_signature = _mask_optical_signature(references["on_frame"], selection)
        if not all(isinstance(item, dict) for item in (live_signature, off_signature, on_signature)):
            continue

        relative = classificar_posicao_relativa_energia_f3(
            live_signature,
            off_signature,
            on_signature,
        )
        details.append(
            {
                "mask_id": str(mask_id),
                **relative,
                "live": {key: round(_safe_float(value), 4) for key, value in live_signature.items()},
                "off": {key: round(_safe_float(value), 4) for key, value in off_signature.items()},
                "on": {key: round(_safe_float(value), 4) for key, value in on_signature.items()},
            }
        )

    summary = resumir_votos_energia_f3(
        details,
        len(references.get("expected_on_ids") or ()),
    )
    result = {
        "available": bool(details),
        "source": F3_POWER_AUTHORITY_SOURCE,
        "same_mask_comparison": True,
        "same_visual_rotation": True,
        "visual_rotation": int(references.get("rotation", 0) or 0),
        **summary,
        "details": details,
    }
    app._display_f3_power_evidence_cache = {"key": cache_key, "value": result}
    return deepcopy(result)


def _presence_from_global_scores(state: dict | None) -> dict:
    """Quadro inteiro responde somente PRESENÇA; nunca CHECK/energia."""
    data = state if isinstance(state, dict) else {}
    kind = str(data.get("kind") or "unknown").strip().lower()
    scores = data.get("reference_scores") if isinstance(data.get("reference_scores"), dict) else {}
    off_score = _safe_float(scores.get("off"), -1.0)
    empty_score = _safe_float(scores.get("empty"), -1.0)

    if kind == "empty":
        return {
            "available": True,
            "board_present": False,
            "reason": "suporte_vazio_confirmado",
            "off_score": off_score,
            "empty_score": empty_score,
        }

    if off_score >= 0.0 and empty_score >= 0.0:
        margin = off_score - empty_score
        present = bool(
            off_score >= F3_POWERED_MIN_BOARD_SCENE_SCORE
            and margin >= F3_POWERED_MIN_OFF_OVER_EMPTY_MARGIN
        )
        return {
            "available": True,
            "board_present": present,
            "off_score": round(off_score, 4),
            "empty_score": round(empty_score, 4),
            "off_over_empty_margin": round(margin, 4),
            "reason": "off_vs_empty_somente_presenca",
        }

    # Estados históricos CHECK/OFF/POWERED ainda provam ocupação física quando
    # os scores não foram anexados, mas seu nome de CHECK nunca é reaproveitado.
    return {
        "available": kind in {"check", "off", "powered"},
        "board_present": kind in {"check", "off", "powered"},
        "reason": "fallback_presenca_sem_scores",
    }


def _rearm_active(app) -> bool:
    return bool(
        getattr(app, "_display_f3_waiting_empty_rearm", False)
        or getattr(app, "_display_f3_waiting_new_board_after_empty", False)
    )


def aplicar_autoridade_energia_ao_estado_f3(
    app,
    state: dict | None,
    frame,
    project_name: str,
    context: dict | None,
) -> dict:
    """Impõe PRESENÇA -> POTÊNCIA antes de qualquer autoridade produtiva."""
    result = deepcopy(state) if isinstance(state, dict) else {}
    result[contract_module.F3_MASK_LIVE_KEY] = True

    if _rearm_active(app):
        result["allow_auto"] = False
        result[contract_module.F3_DECISION_ALLOWED_KEY] = False
        result["power_gate_blocked"] = True
        result["power_gate_reason"] = "aguardando_rearme_fisico"
        return result

    presence = _presence_from_global_scores(result)
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
        result["source"] = F3_POWER_AUTHORITY_SOURCE
        app._display_f3_power_authority_status = {
            "board_present": False,
            "presence": deepcopy(presence),
            "energy": None,
            "decision_allowed": False,
            "reason": result["power_gate_reason"],
        }
        return result

    evidence = avaliar_evidencia_energia_relativa_display_f3(
        app,
        frame,
        project_name,
        context,
    )
    result["power_mask_evidence_v2"] = evidence
    check_id = str((context or {}).get("check_id") or "")
    check_name = str((context or {}).get("check_name") or check_id or "CHECK").strip().upper()

    if bool(evidence.get("powered_confirmed")):
        result.update(
            {
                "kind": "powered",
                "text": f"PLACA NO SUPORTE • LIGADA • ANALISANDO {check_name}",
                "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["check"],
                "allow_auto": True,
                "physical_state_key": "check:powered_by_same_mask",
                "expected_check_id": check_id,
                "physical_matches_expected_check": False,
                "powered_board_confirmed": True,
                "power_gate_blocked": False,
                "power_gate_reason": "segmento_aceso_confirmou_energia",
                "source": F3_POWER_AUTHORITY_SOURCE,
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
                "source": F3_POWER_AUTHORITY_SOURCE,
                contract_module.F3_DECISION_ALLOWED_KEY: False,
                contract_module.F3_MASK_LIVE_KEY: True,
            }
        )
        decision_allowed = False

    app._display_f3_power_authority_status = {
        "board_present": True,
        "presence": deepcopy(presence),
        "energy": deepcopy(evidence),
        "decision_allowed": bool(decision_allowed),
        "reason": str(result.get("power_gate_reason") or ""),
    }
    return result


def _raw_analysis_for_overlay(app, frame, context: dict) -> dict | None:
    """Calcula diagnóstico bruto no mesmo frame, sem autoridade de decisão."""
    repository = getattr(app, "display_project_repository", None)
    if repository is None:
        return None
    analyzer = getattr(app, "_display_auto_analyzer", None)
    if analyzer is None or getattr(analyzer, "repository", None) is not repository:
        analyzer = runtime_module.DisplayAutomaticCheckAnalyzer(repository)
        app._display_auto_analyzer = analyzer

    try:
        rotation = int(app._obter_rotacao_visual_display_f3())
    except Exception:
        rotation = 0

    try:
        analysis = analyzer.analyze(
            frame=frame,
            project_name=str(context.get("project_name") or ""),
            check_id=str(context.get("check_id") or ""),
            visual_rotation=rotation,
        )
    except Exception:
        return None
    if not isinstance(analysis, dict):
        return None

    analysis["decision_authority"] = False
    analysis["raw_diagnostic_only"] = True
    analysis["blocked_by_power_gate"] = True
    app._display_auto_last_analysis = analysis
    app._display_f3_power_blocked_raw_analysis = deepcopy(analysis)
    return analysis


def _blocked_preview_text(state: dict) -> str:
    reason = str(state.get("power_gate_reason") or "")
    if reason == "todos_segmentos_esperados_acesos_estao_apagados":
        return "AUTO • placa desligada • aguardando ao menos 1 segmento aceso"
    if reason == "nenhum_segmento_aceso_confirmou_energia":
        return "AUTO • energia não confirmada • buscando segmento aceso"
    if reason == "placa_nao_confirmada_no_suporte":
        return "AUTO • aguardando placa no suporte"
    return "AUTO • gate físico bloqueado • aguardando condição segura"


def _install_final_process_gate() -> None:
    cls = runtime_module.DisplayAutomaticCheckF3Mixin
    if bool(getattr(cls, "_display_f3_final_power_authority_installed", False)):
        return

    previous_process = cls._process_display_auto_check

    def process(self):
        if not bool(getattr(self, "display_f3_ativo", False)):
            return previous_process(self)

        # Rearme e card final precisam continuar usando os wrappers históricos
        # que observam EMPTY. Nenhuma decisão produtiva é possível nesses estados.
        if (
            getattr(self, "display_f3_result_after_id", None) is not None
            or _rearm_active(self)
        ):
            return previous_process(self)

        frame = getattr(self, "camera_frame_atual", None)
        repository = getattr(self, "display_project_repository", None)
        if not _valid_image(frame) or repository is None:
            return previous_process(self)

        try:
            context = self._display_auto_current_context()
        except Exception:
            context = None
        if not isinstance(context, dict):
            return previous_process(self)

        project_name = str(context.get("project_name") or "")
        if not project_name:
            return previous_process(self)

        try:
            state = physical_policy_module._build_physical_operational_state(
                self,
                frame,
                project_name,
                context,
            )
        except Exception:
            return previous_process(self)

        self._display_f3_operational_state = deepcopy(state)
        window = getattr(self, "display_f3_window", None)
        if window is not None:
            try:
                window.set_operational_reference_status(
                    str(state.get("text") or "IDENTIFICANDO..."),
                    str(state.get("color") or "#FDE68A"),
                )
            except Exception:
                pass

        allowed = bool(
            state.get(
                contract_module.F3_DECISION_ALLOWED_KEY,
                state.get("allow_auto", False),
            )
        )
        if allowed:
            self._display_f3_power_blocked_raw_analysis = None
            return previous_process(self)

        # Não chamamos o pipeline produtivo: logo não existe OK, NG ou avanço.
        # Ainda calculamos a análise bruta no MESMO frame para overlay/debug.
        raw = _raw_analysis_for_overlay(self, frame, context)
        self._display_auto_last_decision = None
        self._display_auto_stable_frames = 0

        if window is not None:
            try:
                window.set_mask_analysis_status(
                    "MÁSCARAS • LEITURA BRUTA • SEM AUTORIDADE ATÉ CONFIRMAR ENERGIA",
                    "#FDE68A",
                )
            except Exception:
                pass
        try:
            self._display_auto_set_preview_status(_blocked_preview_text(state), "#FDE68A")
        except Exception:
            pass

        return {
            "event": "power_gate_blocked",
            "raw_analysis_ready": bool(isinstance(raw, dict) and raw.get("ready")),
            "state": deepcopy(state),
        }

    cls._process_display_auto_check = process
    cls._display_f3_final_power_authority_installed = True


def _install_final_builders() -> None:
    previous_physical = physical_policy_module._build_physical_operational_state
    previous_operational = operational_module._build_operational_state

    def physical_builder(self, frame, project_name: str, context: dict | None):
        state = previous_physical(self, frame, project_name, context)
        return aplicar_autoridade_energia_ao_estado_f3(
            self,
            state,
            frame,
            project_name,
            context,
        )

    def operational_builder(self, frame, project_name: str, context: dict | None):
        state = previous_operational(self, frame, project_name, context)
        return aplicar_autoridade_energia_ao_estado_f3(
            self,
            state,
            frame,
            project_name,
            context,
        )

    physical_policy_module._build_physical_operational_state = physical_builder
    operational_module._build_operational_state = operational_builder
    physical_policy_module._display_f3_final_power_authority_builder = True
    operational_module._display_f3_final_power_authority_builder = True


def construir_resumo_energia_debug_f3(snapshot: dict) -> dict:
    """Resumo operacional onde análise bruta nunca parece decisão produtiva."""
    base = debug_clarity_module._legacy_power_summary_builder(snapshot)
    result = dict(base) if isinstance(base, dict) else {}
    runtime = snapshot.get("runtime_at_click") if isinstance(snapshot, dict) else {}
    runtime = runtime if isinstance(runtime, dict) else {}
    status = runtime.get("power_authority")
    status = status if isinstance(status, dict) else {}
    evidence = status.get("energy")
    evidence = evidence if isinstance(evidence, dict) else {}

    board_present = bool(status.get("board_present"))
    energy_state = str(evidence.get("energy_state") or F3_POWER_STATE_UNCONFIRMED)
    decision_allowed = bool(status.get("decision_allowed"))
    expected_on = int(evidence.get("expected_on_mask_count", 0) or 0)
    powered = int(evidence.get("powered_votes", 0) or 0)
    off = int(evidence.get("off_votes", 0) or 0)

    analysis = debug_clarity_module._productive_analysis(snapshot)
    matched, active = debug_clarity_module._productive_counts(analysis)
    ready = bool(isinstance(analysis, dict) and analysis.get("ready"))
    check_name = str(result.get("check_name") or "CHECK")
    raw_text = (
        f"{check_name}: {matched}/{active} máscaras"
        if ready and active > 0
        else f"{check_name}: análise bruta indisponível"
    )

    rearm_blocked = bool(
        result.get("waiting_empty_rearm")
        or result.get("waiting_new_board_after_empty")
        or result.get("cycle_rearm_waiting")
        or result.get("cycle_rearmed_waiting_new_board")
    )
    power_blocked = bool(board_present and not decision_allowed)
    flow_blocked = bool(rearm_blocked or not decision_allowed)

    if rearm_blocked:
        flow_reason = str(result.get("flow_reason") or "aguardando rearme físico")
    elif not board_present:
        flow_reason = "placa ainda não confirmada no suporte"
    elif energy_state == F3_POWER_STATE_OFF:
        flow_reason = "display sem energia; aguardando ao menos 1 segmento aceso"
    elif energy_state == F3_POWER_STATE_UNCONFIRMED:
        flow_reason = "display ainda não confirmado como ligado"
    else:
        flow_reason = "energia confirmada; CHECK produtivo liberado"

    result.update(
        {
            "board_present": board_present,
            "energy_state": energy_state,
            "expected_on_mask_count": expected_on,
            "powered_on_count": powered,
            "off_on_expected_count": off,
            "decision_allowed": decision_allowed,
            "power_gate_blocked": power_blocked,
            "flow_blocked": flow_blocked,
            "flow_reason": flow_reason,
            "raw_analysis_text": raw_text,
            "productive_text": (
                str(base.get("productive_text") or "--")
                if decision_allowed
                else "SEM DECISÃO PRODUTIVA • GATE DE ENERGIA BLOQUEADO"
            ),
        }
    )
    return result


def _report_summary_power(snapshot: dict) -> str:
    summary = construir_resumo_energia_debug_f3(snapshot)
    visual = snapshot.get("visual_analysis") if isinstance(snapshot, dict) else {}
    visual = visual if isinstance(visual, dict) else {}
    raw_visual = str(visual.get("status_text_raw") or visual.get("status_text") or "--")

    if summary.get("board_present"):
        board_text = "PRESENTE"
    else:
        board_text = "NÃO CONFIRMADA / FORA"

    energy_state = str(summary.get("energy_state") or F3_POWER_STATE_UNCONFIRMED)
    energy_text = {
        F3_POWER_STATE_POWERED: "CONFIRMADA",
        F3_POWER_STATE_OFF: "DESLIGADA",
        F3_POWER_STATE_UNCONFIRMED: "NÃO CONFIRMADA",
    }.get(energy_state, "NÃO CONFIRMADA")

    lines = [
        debug_clarity_module.SUMMARY_MARKER,
        f"ESTADO DA PLACA: {board_text}",
        f"ENERGIA DO DISPLAY: {energy_text}",
        f"CHECK LÓGICO: {summary.get('check_name', '--')}",
        f"SEGMENTOS ESPERADOS ON: {summary.get('expected_on_mask_count', 0)}",
        f"ON CONFIRMADOS: {summary.get('powered_on_count', 0)}",
        (
            "OFF CONFIRMADOS NOS ON ESPERADOS: "
            f"{summary.get('off_on_expected_count', 0)}"
        ),
        "",
        (
            "GATE PRODUTIVO: BLOQUEADO"
            if bool(summary.get("flow_blocked"))
            else "GATE PRODUTIVO: LIBERADO"
        ),
        f"MOTIVO: {summary.get('flow_reason', '--')}",
        f"ANÁLISE BRUTA {summary.get('raw_analysis_text', '--')} • SEM AUTORIDADE QUANDO O GATE ESTÁ BLOQUEADO",
        (
            "REARME: "
            f"waiting_empty={summary.get('waiting_empty_rearm', False)} • "
            f"waiting_new_board={summary.get('waiting_new_board_after_empty', False)} • "
            f"cycle_waiting={summary.get('cycle_rearm_waiting', False)}"
        ),
        "ANÁLISE VISUAL GLOBAL: SOMENTE PRESENÇA/INFORMATIVA • não decide OFF/H1/BLUE/USB/AUX",
        f"TEXTO VISUAL ORIGINAL: {raw_visual}",
    ]
    return "\n".join(lines)


def _install_debug_power_summary() -> None:
    if bool(getattr(debug_clarity_module, "_display_f3_power_summary_installed", False)):
        return

    # Guardamos os builders antigos para os novos wrappers sem recursão.
    debug_clarity_module._legacy_power_summary_builder = (
        debug_clarity_module.construir_resumo_operacional_debug_f3
    )
    previous_apply = debug_clarity_module.aplicar_clareza_snapshot_debug_f3

    debug_clarity_module.construir_resumo_operacional_debug_f3 = (
        construir_resumo_energia_debug_f3
    )
    debug_clarity_module._report_summary_block = _report_summary_power

    def apply(snapshot: dict, app):
        if isinstance(snapshot, dict):
            runtime = snapshot.get("runtime_at_click")
            if not isinstance(runtime, dict):
                runtime = {}
                snapshot["runtime_at_click"] = runtime
            runtime["power_authority"] = deepcopy(
                getattr(app, "_display_f3_power_authority_status", None)
            )
            raw = getattr(app, "_display_f3_power_blocked_raw_analysis", None)
            if isinstance(raw, dict):
                runtime["power_blocked_raw_analysis"] = deepcopy(raw)
                # O helper histórico procura last_auto_analysis primeiro.
                runtime["last_auto_analysis"] = deepcopy(raw)

        result = previous_apply(snapshot, app)
        if isinstance(result, dict):
            result["operational_summary"] = construir_resumo_energia_debug_f3(result)
        return result

    debug_clarity_module.aplicar_clareza_snapshot_debug_f3 = apply
    debug_clarity_module._display_f3_power_summary_installed = True


_INSTALLED = False


def instalar_autoridade_energia_final_display_f3() -> None:
    """Instala a hierarquia final F3 depois de todos os wrappers históricos."""
    global _INSTALLED
    if _INSTALLED:
        return

    _install_final_builders()
    _install_final_process_gate()
    _install_debug_power_summary()
    _INSTALLED = True
