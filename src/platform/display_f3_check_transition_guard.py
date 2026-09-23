from __future__ import annotations

import cv2
import numpy as np

import src.platform.display_f3_operational_status as operational_module
import src.platform.display_visual_reference_status as visual_status_module
from src.platform.display_visual_reference_status import (
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
    DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
    DISPLAY_PROJECT_REFERENCE_TYPES,
)


F3_CHECK_TRANSITION_STABLE_FRAMES = 4
F3_CHECK_TRANSITION_GLOBAL_SCORE_MARGIN = 0.05
F3_CHECK_TRANSITION_REFERENCE_DELTA = 8.0
F3_CHECK_TRANSITION_ERROR_MARGIN = 1.5
F3_CHECK_TRANSITION_ERROR_RATIO = 0.82

F3_PHYSICAL_STATE_STABLE_FRAMES = 3
F3_PHYSICAL_REFERENCE_DELTA = 8.0
F3_PHYSICAL_ERROR_MARGIN = 1.5
F3_PHYSICAL_MIN_DIFFERENT_RATIO = 0.002
F3_PHYSICAL_MIN_SCORE_MARGIN = 0.015

# O threshold absoluto das fotos (normalmente 0.72) continua sendo a autoridade
# para CHECKS. Para os dois estados físicos estruturais, OFF x EMPTY, permitimos
# uma segunda decisão relativa somente quando nenhum candidato atingiu o threshold
# normal e uma das duas referências físicas domina claramente a outra e todos os
# CHECKS. Isso usa os mesmos scores já calculados sobre a ROI configurada e não
# acrescenta uma segunda passagem de visão computacional.
F3_PHYSICAL_BOARD_FALLBACK_MIN_SCORE = 0.36
F3_PHYSICAL_BOARD_FALLBACK_MIN_MARGIN = 0.12
F3_PHYSICAL_BOARD_FALLBACK_MIN_RATIO = 1.45
F3_PHYSICAL_EMPTY_FALLBACK_MIN_SCORE = 0.36
F3_PHYSICAL_EMPTY_FALLBACK_MIN_MARGIN = 0.15
F3_PHYSICAL_EMPTY_FALLBACK_MIN_RATIO = 1.70
F3_PHYSICAL_BOARD_FALLBACK_MIN_CHECK_MARGIN = 0.08


def _as_color_image(image):
    if image is None or getattr(image, "size", 0) == 0:
        return None
    result = image
    if result.ndim == 2:
        result = cv2.cvtColor(result, cv2.COLOR_GRAY2BGR)
    elif result.ndim == 3 and result.shape[2] == 4:
        result = cv2.cvtColor(result, cv2.COLOR_BGRA2BGR)
    elif result.ndim != 3 or result.shape[2] != 3:
        return None
    return result


def _resize_like(image, target):
    if image is None or target is None:
        return None
    target_height, target_width = target.shape[:2]
    if image.shape[:2] == (target_height, target_width):
        return image
    return cv2.resize(
        image,
        (target_width, target_height),
        interpolation=cv2.INTER_AREA,
    )


def avaliar_preferencia_transicao_referencias_f3(
    matcher,
    current_small,
    last_metadata: dict | None,
    current_metadata: dict | None,
) -> dict:
    """Compara somente as regiões que diferenciam dois CHECKS consecutivos."""
    if not isinstance(last_metadata, dict) or not isinstance(current_metadata, dict):
        return {"current_preferred": False, "available": False}

    last_reference = _as_color_image(matcher._reference_image(last_metadata))
    current_reference = _as_color_image(matcher._reference_image(current_metadata))
    observed = _as_color_image(current_small)
    if last_reference is None or current_reference is None or observed is None:
        return {"current_preferred": False, "available": False}

    last_reference = _resize_like(last_reference, current_reference)
    observed = _resize_like(observed, current_reference)

    current_score = matcher._score(current_small, current_metadata)
    last_score = matcher._score(current_small, last_metadata)
    current_threshold = matcher._threshold(current_metadata)
    last_threshold = matcher._threshold(last_metadata)
    if current_score is None or last_score is None:
        return {"current_preferred": False, "available": False}

    current_score = float(current_score)
    last_score = float(last_score)
    current_matched = current_score >= float(current_threshold)
    last_matched = last_score >= float(last_threshold)

    current_f = current_reference.astype(np.float32)
    last_f = last_reference.astype(np.float32)
    observed_f = observed.astype(np.float32)

    reference_delta = np.mean(np.abs(current_f - last_f), axis=2)
    difference_mask = reference_delta >= F3_CHECK_TRANSITION_REFERENCE_DELTA
    different_pixels = int(np.count_nonzero(difference_mask))
    minimum_pixels = max(32, int(reference_delta.size * 0.002))

    if different_pixels < minimum_pixels:
        # Transição é uma comparação RELATIVA entre o CHECK anterior e o atual.
        # O threshold absoluto continua útil como diagnóstico, mas não pode
        # impedir a decisão quando ambas as fotos ficam abaixo de 0.72 por foco,
        # exposição, tracking ou pequenas mudanças globais da câmera.
        relative_preferred = bool(
            current_score
            >= last_score + F3_CHECK_TRANSITION_GLOBAL_SCORE_MARGIN
        )
        preferred = bool(
            relative_preferred
            or (current_matched and not last_matched)
        )
        return {
            "current_preferred": preferred,
            "available": True,
            "mode": "global_fallback",
            "current_score": current_score,
            "last_score": last_score,
            "current_matched": bool(current_matched),
            "last_matched": bool(last_matched),
            "relative_preferred": bool(relative_preferred),
            "different_pixels": different_pixels,
        }

    current_error_map = np.mean(np.abs(observed_f - current_f), axis=2)
    last_error_map = np.mean(np.abs(observed_f - last_f), axis=2)
    current_error = float(np.mean(current_error_map[difference_mask]))
    last_error = float(np.mean(last_error_map[difference_mask]))

    if last_error <= 1e-6:
        error_ratio = float("inf") if current_error > 0 else 1.0
    else:
        error_ratio = current_error / last_error

    # Nas regiões que REALMENTE mudam entre os dois CHECKS, a foto atual
    # precisa parecer inequivocamente mais com o destino do que com a função
    # anterior. Isto é independente do score absoluto da cena inteira.
    relative_preferred = bool(
        current_error + F3_CHECK_TRANSITION_ERROR_MARGIN < last_error
        and error_ratio <= F3_CHECK_TRANSITION_ERROR_RATIO
    )
    preferred = bool(relative_preferred)
    return {
        "current_preferred": preferred,
        "available": True,
        "mode": "difference_mask",
        "current_score": current_score,
        "last_score": last_score,
        "current_matched": bool(current_matched),
        "last_matched": bool(last_matched),
        "relative_preferred": bool(relative_preferred),
        "current_error": current_error,
        "last_error": last_error,
        "error_ratio": error_ratio,
        "different_pixels": different_pixels,
    }


def avaliar_transicao_fisica_checks_f3(
    app,
    frame,
    project_name: str,
    previous_check_id: str,
    current_check_id: str,
) -> dict:
    """Compara o frame real somente entre o CHECK anterior e o CHECK esperado.

    Esta é uma autoridade de ENTRADA no CHECK, não de conformidade. Energia
    ligada prova apenas que o display está energizado; ela não prova que a função
    lógica seguinte já apareceu. Por isso USB não pode liberar AUX, por exemplo,
    até a imagem atual preferir fisicamente AUX nas regiões que diferenciam as
    duas referências.
    """
    previous_id = str(previous_check_id or "").strip()
    current_id = str(current_check_id or "").strip()
    if not previous_id or not current_id or previous_id == current_id:
        return {
            "available": False,
            "current_preferred": False,
            "reason": "checks_transicao_invalidos",
            "previous_check_id": previous_id,
            "current_check_id": current_id,
        }
    if frame is None or getattr(frame, "size", 0) == 0:
        return {
            "available": False,
            "current_preferred": False,
            "reason": "frame_ausente",
            "previous_check_id": previous_id,
            "current_check_id": current_id,
        }

    repository = getattr(app, "display_project_repository", None)
    if repository is None:
        return {
            "available": False,
            "current_preferred": False,
            "reason": "repositorio_ausente",
            "previous_check_id": previous_id,
            "current_check_id": current_id,
        }

    matcher = getattr(app, "_display_f3_operational_matcher", None)
    if matcher is None or getattr(matcher, "repository", None) is not repository:
        matcher = operational_module.DisplayVisualReferenceMatcher(repository)
        app._display_f3_operational_matcher = matcher

    previous_metadata = matcher.check_store.get(project_name, previous_id)
    current_metadata = matcher.check_store.get(project_name, current_id)
    if not isinstance(previous_metadata, dict) or not isinstance(current_metadata, dict):
        return {
            "available": False,
            "current_preferred": False,
            "reason": "referencias_transicao_incompletas",
            "previous_check_id": previous_id,
            "current_check_id": current_id,
        }

    current_small = visual_status_module._small_image(frame)
    evidence = avaliar_preferencia_transicao_referencias_f3(
        matcher,
        current_small,
        previous_metadata,
        current_metadata,
    )
    result = dict(evidence) if isinstance(evidence, dict) else {}
    result.update(
        {
            "source": "f3_previous_to_current_check_physical_transition",
            "previous_check_id": previous_id,
            "current_check_id": current_id,
            "project_name": str(project_name or ""),
        }
    )
    if not result.get("available"):
        result.setdefault("reason", "comparacao_transicao_indisponivel")
    elif result.get("current_preferred"):
        result["reason"] = "frame_prefere_check_atual_ao_anterior"
    else:
        result["reason"] = "frame_ainda_nao_prefere_check_atual"
    return result


def decidir_transicao_estavel_f3(
    *,
    current_check_id: str,
    preferred: bool,
    pending_check_id: str = "",
    pending_frames: int = 0,
) -> dict:
    check_id = str(current_check_id or "")
    if not check_id or not bool(preferred):
        return {
            "promote": False,
            "pending_check_id": "",
            "pending_frames": 0,
        }

    previous_id = str(pending_check_id or "")
    frames = int(pending_frames or 0) + 1 if previous_id == check_id else 1
    return {
        "promote": frames >= F3_CHECK_TRANSITION_STABLE_FRAMES,
        "pending_check_id": check_id,
        "pending_frames": frames,
    }


def _reference_candidates(matcher, project_name: str) -> list[dict]:
    candidates: list[dict] = []
    project_references = matcher.project_store.get_all(project_name)

    empty_metadata = project_references.get(DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT)
    if isinstance(empty_metadata, dict):
        candidates.append(
            {
                "key": "empty",
                "kind": "empty",
                "name": "PLACA FORA DO SUPORTE",
                "metadata": empty_metadata,
            }
        )

    off_metadata = project_references.get(DISPLAY_PROJECT_REFERENCE_BOARD_OFF)
    if isinstance(off_metadata, dict):
        candidates.append(
            {
                "key": "off",
                "kind": "off",
                "name": "PLACA NO SUPORTE • DESLIGADA",
                "metadata": off_metadata,
            }
        )

    for check in matcher.repository.listar_checks(project_name):
        check_id = str(check.get("id") or "")
        if not check_id:
            continue
        metadata = matcher.check_store.get(project_name, check_id)
        if not isinstance(metadata, dict):
            continue
        check_name = str(check.get("name") or check_id).strip().upper()
        candidates.append(
            {
                "key": f"check:{check_id}",
                "kind": "check",
                "name": check_name,
                "check_id": check_id,
                "metadata": metadata,
            }
        )
    return candidates


def _fallback_estado_fisico_por_dominancia_referencias_f3(
    prepared: list[dict],
    board_complete: bool,
) -> dict | None:
    """Resolve somente OFF/EMPTY quando as duas fotos físicas dominam claramente.

    O fallback não reduz o threshold de H1/BLUE/USB/AUX. Ele só existe para o
    caso em que nenhuma referência passou do threshold absoluto, mas OFF ou EMPTY
    é inequivocamente a melhor referência na ROI física configurada.
    """
    if not board_complete:
        return None

    valid = [
        item
        for item in prepared
        if isinstance(item, dict) and item.get("score") is not None
    ]
    by_key = {str(item.get("key") or ""): item for item in valid}
    off = by_key.get("off")
    empty = by_key.get("empty")
    if off is None or empty is None:
        return None

    off_score = float(off.get("score") or 0.0)
    empty_score = float(empty.get("score") or 0.0)
    winner = off if off_score >= empty_score else empty
    loser = empty if winner is off else off
    winner_score = float(winner.get("score") or 0.0)
    loser_score = float(loser.get("score") or 0.0)

    # A decisão relativa só pode ser usada se OFF/EMPTY também for o vencedor
    # global. Um CHECK que pontua mais alto mantém o comportamento anterior.
    overall = max(valid, key=lambda item: float(item.get("score") or 0.0))
    if str(overall.get("key") or "") != str(winner.get("key") or ""):
        return None

    best_check_score = max(
        (
            float(item.get("score") or 0.0)
            for item in valid
            if str(item.get("key") or "").startswith("check:")
        ),
        default=0.0,
    )
    board_margin = winner_score - loser_score
    check_margin = winner_score - best_check_score
    ratio = winner_score / max(loser_score, 1e-6)

    if str(winner.get("key") or "") == "empty":
        min_score = F3_PHYSICAL_EMPTY_FALLBACK_MIN_SCORE
        min_margin = F3_PHYSICAL_EMPTY_FALLBACK_MIN_MARGIN
        min_ratio = F3_PHYSICAL_EMPTY_FALLBACK_MIN_RATIO
    else:
        min_score = F3_PHYSICAL_BOARD_FALLBACK_MIN_SCORE
        min_margin = F3_PHYSICAL_BOARD_FALLBACK_MIN_MARGIN
        min_ratio = F3_PHYSICAL_BOARD_FALLBACK_MIN_RATIO

    if winner_score < min_score:
        return None
    if board_margin < min_margin:
        return None
    if ratio < min_ratio:
        return None
    if check_margin < F3_PHYSICAL_BOARD_FALLBACK_MIN_CHECK_MARGIN:
        return None

    result = dict(winner)
    result["physical_low_score_fallback"] = True
    result["physical_low_score_fallback_source"] = (
        "board_reference_relative_dominance"
    )
    result["physical_low_score_fallback_margin"] = float(board_margin)
    result["physical_low_score_fallback_ratio"] = float(ratio)
    result["physical_low_score_best_check_score"] = float(best_check_score)
    result["physical_low_score_check_margin"] = float(check_margin)
    return result


def classificar_estado_fisico_referencias_f3(
    matcher,
    frame,
    project_name: str,
) -> dict:
    """Classifica o que existe fisicamente na câmera, sem usar o CHECK esperado.

    Todas as referências configuradas disputam em igualdade: suporte vazio,
    placa desligada e cada estado do Display. A decisão usa comparações par a
    par apenas nas regiões em que duas referências realmente diferem. Isso
    impede que uma cena desligada seja chamada de H1 e que BLUE vire USB antes
    da mudança física real.
    """
    current_small = visual_status_module._small_image(frame)
    observed = _as_color_image(current_small)
    candidates = _reference_candidates(matcher, project_name)
    board_references = matcher.project_store.get_all(project_name)
    board_complete = all(
        kind in board_references for kind in DISPLAY_PROJECT_REFERENCE_TYPES
    )

    if observed is None:
        return {
            "kind": "unknown",
            "text": "AGUARDANDO CÂMERA",
            "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"],
            "allow_auto": False,
            "board_references_complete": board_complete,
            "configured_count": len(candidates),
        }

    prepared: list[dict] = []
    for candidate in candidates:
        metadata = candidate["metadata"]
        reference = _as_color_image(matcher._reference_image(metadata))
        if reference is None:
            continue
        reference = _resize_like(reference, observed)
        score = matcher._score(current_small, metadata)
        if score is None:
            continue
        item = dict(candidate)
        item["reference"] = reference.astype(np.float32)
        item["score"] = float(score)
        item["threshold"] = float(matcher._threshold(metadata))
        item["wins"] = 0
        item["losses"] = 0
        item["comparisons"] = 0
        item["error_total"] = 0.0
        prepared.append(item)

    if not prepared:
        return {
            "kind": "unavailable",
            "text": "REFERÊNCIAS VISUAIS NÃO CONFIGURADAS",
            "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["unavailable"],
            "allow_auto": False,
            "board_references_complete": board_complete,
            "configured_count": 0,
        }

    observed_f = observed.astype(np.float32)
    for index, left in enumerate(prepared):
        for right in prepared[index + 1 :]:
            delta = np.mean(np.abs(left["reference"] - right["reference"]), axis=2)
            mask = delta >= F3_PHYSICAL_REFERENCE_DELTA
            different_pixels = int(np.count_nonzero(mask))
            minimum_pixels = max(
                32,
                int(delta.size * F3_PHYSICAL_MIN_DIFFERENT_RATIO),
            )
            if different_pixels < minimum_pixels:
                continue

            left_error_map = np.mean(
                np.abs(observed_f - left["reference"]), axis=2
            )
            right_error_map = np.mean(
                np.abs(observed_f - right["reference"]), axis=2
            )
            left_error = float(np.mean(left_error_map[mask]))
            right_error = float(np.mean(right_error_map[mask]))

            left["comparisons"] += 1
            right["comparisons"] += 1
            left["error_total"] += left_error
            right["error_total"] += right_error

            if left_error + F3_PHYSICAL_ERROR_MARGIN < right_error:
                left["wins"] += 1
                right["losses"] += 1
            elif right_error + F3_PHYSICAL_ERROR_MARGIN < left_error:
                right["wins"] += 1
                left["losses"] += 1

    eligible = [
        item
        for item in prepared
        if float(item["score"]) >= float(item["threshold"])
    ]

    def ranking(item: dict):
        comparisons = max(1, int(item["comparisons"]))
        average_error = float(item["error_total"]) / comparisons
        return (
            int(item["wins"]) - int(item["losses"]),
            int(item["wins"]),
            -average_error,
            float(item["score"]),
        )

    if not eligible:
        winner = _fallback_estado_fisico_por_dominancia_referencias_f3(
            prepared,
            board_complete,
        )
        if winner is None:
            best = max(prepared, key=lambda item: float(item["score"]))
            return {
                "kind": "unknown",
                "text": "IDENTIFICANDO...",
                "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"],
                "allow_auto": False,
                "board_references_complete": board_complete,
                "configured_count": len(prepared),
                "best_score": float(best["score"]),
            }
    else:
        eligible.sort(key=ranking, reverse=True)
        winner = eligible[0]
        if len(eligible) >= 2:
            second = eligible[1]
            winner_net = int(winner["wins"]) - int(winner["losses"])
            second_net = int(second["wins"]) - int(second["losses"])
            score_margin = float(winner["score"]) - float(second["score"])
            if winner_net == second_net and score_margin < F3_PHYSICAL_MIN_SCORE_MARGIN:
                return {
                    "kind": "unknown",
                    "text": "IDENTIFICANDO...",
                    "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"],
                    "allow_auto": False,
                    "board_references_complete": board_complete,
                    "configured_count": len(prepared),
                    "ambiguous": True,
                }

    kind = str(winner["kind"])
    state = {
        "kind": kind,
        "allow_auto": False,
        "board_references_complete": board_complete,
        "configured_count": len(prepared),
        "physical_state_key": str(winner["key"]),
        "score": float(winner["score"]),
        "physical_wins": int(winner["wins"]),
        "physical_losses": int(winner["losses"]),
    }
    for diagnostic_key in (
        "physical_low_score_fallback",
        "physical_low_score_fallback_source",
        "physical_low_score_fallback_margin",
        "physical_low_score_fallback_ratio",
        "physical_low_score_best_check_score",
        "physical_low_score_check_margin",
    ):
        if diagnostic_key in winner:
            state[diagnostic_key] = winner[diagnostic_key]

    if kind == "empty":
        state.update(
            text="PLACA FORA DO SUPORTE",
            color=operational_module.F3_OPERATIONAL_STATUS_COLORS["empty"],
        )
    elif kind == "off":
        state.update(
            text="PLACA NO SUPORTE • DESLIGADA",
            color=operational_module.F3_OPERATIONAL_STATUS_COLORS["off"],
        )
    else:
        check_name = str(winner.get("name") or "CHECK").strip().upper()
        state.update(
            text=f"DISPLAY EM {check_name}",
            color=operational_module.F3_OPERATIONAL_STATUS_COLORS["check"],
            check_id=str(winner.get("check_id") or ""),
            check_name=check_name,
        )
    return state


def _estado_fisico_estavel(self, raw_state: dict) -> dict:
    kind = str(raw_state.get("kind") or "unknown")
    if kind in {"unknown", "unavailable"}:
        self._display_f3_physical_pending_key = ""
        self._display_f3_physical_pending_frames = 0
        return raw_state

    key = str(raw_state.get("physical_state_key") or kind)
    stable_key = str(getattr(self, "_display_f3_physical_stable_key", "") or "")
    if key == stable_key:
        self._display_f3_physical_pending_key = ""
        self._display_f3_physical_pending_frames = 0
        self._display_f3_physical_stable_state = dict(raw_state)
        return raw_state

    pending_key = str(getattr(self, "_display_f3_physical_pending_key", "") or "")
    pending_frames = int(getattr(self, "_display_f3_physical_pending_frames", 0) or 0)
    pending_frames = pending_frames + 1 if pending_key == key else 1
    self._display_f3_physical_pending_key = key
    self._display_f3_physical_pending_frames = pending_frames

    if pending_frames < F3_PHYSICAL_STATE_STABLE_FRAMES:
        return {
            "kind": "unknown",
            "text": "IDENTIFICANDO...",
            "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"],
            "allow_auto": False,
            "board_references_complete": bool(
                raw_state.get("board_references_complete")
            ),
            "physical_transition_pending": True,
        }

    self._display_f3_physical_stable_key = key
    self._display_f3_physical_stable_state = dict(raw_state)
    self._display_f3_physical_pending_key = ""
    self._display_f3_physical_pending_frames = 0
    return raw_state


def _install_transition_guard() -> None:
    if bool(getattr(operational_module, "_display_f3_check_transition_guard_installed", False)):
        return

    base_build = operational_module._build_operational_state

    def guarded_build(self, frame, project_name: str, context: dict | None):
        matcher = getattr(self, "_display_f3_operational_matcher", None)
        repository = getattr(self, "display_project_repository", None)
        if matcher is None or getattr(matcher, "repository", None) is not repository:
            if repository is None:
                return base_build(self, frame, project_name, context)
            matcher = operational_module.DisplayVisualReferenceMatcher(repository)
            self._display_f3_operational_matcher = matcher

        raw_state = classificar_estado_fisico_referencias_f3(
            matcher,
            frame,
            project_name,
        )
        state = _estado_fisico_estavel(self, raw_state)

        current_check_id = str((context or {}).get("check_id") or "")
        current_metadata = (
            matcher.check_store.get(project_name, current_check_id)
            if current_check_id
            else None
        )
        state["current_check_reference_configured"] = isinstance(
            current_metadata, dict
        )

        if str(state.get("kind") or "") == "check":
            physical_check_id = str(state.get("check_id") or "")
            # O status continua mostrando o estado físico real mesmo que o
            # sequenciador esteja esperando outro CHECK. O automático só é
            # liberado quando ambos forem exatamente o mesmo estado.
            state["allow_auto"] = bool(
                current_check_id and physical_check_id == current_check_id
            )
            state["expected_check_id"] = current_check_id
            state["physical_matches_expected_check"] = bool(state["allow_auto"])
        else:
            state["allow_auto"] = False

        return state

    operational_module._build_operational_state = guarded_build
    operational_module._display_f3_check_transition_guard_installed = True


_DISPLAY_F3_CHECK_TRANSITION_GUARD_INSTALLED = False


def instalar_guard_transicao_check_display_f3() -> None:
    """Faz o status/gate F3 obedecer somente ao estado físico da câmera."""
    global _DISPLAY_F3_CHECK_TRANSITION_GUARD_INSTALLED
    if _DISPLAY_F3_CHECK_TRANSITION_GUARD_INSTALLED:
        return
    _install_transition_guard()
    _DISPLAY_F3_CHECK_TRANSITION_GUARD_INSTALLED = True
