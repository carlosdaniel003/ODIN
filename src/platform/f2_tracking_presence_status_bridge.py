from __future__ import annotations

"""Usa o rastreamento angular real como evidência positiva de presença no F2.

O classificador histórico de presença compara a cena inteira com PLACA LIGADA,
PLACA DESLIGADA e SUPORTE VAZIO. Quando a placa gira 90/180/270 graus, essa
comparação global pode ficar ambígua mesmo quando o rastreador ORB está travado
na placa.

Esta ponte atua somente quando ``Ativar rastreamento automático de objetos`` está
ligado. Uma correspondência válida com uma das referências reais 90/180/270 é
uma evidência estrutural de que existe uma placa na câmera. A referência angular
não decide se a placa está ligada ou desligada: essa parte continua vindo dos
estados vivos das ROIs dos LEDs.

HOLD/grace_lock não são aceitos como prova, pois representam apenas a última pose
mantida visualmente e poderiam atrasar a detecção de retirada da placa.
"""

from src.platform.f2_board_presence_references import (
    F2_BOARD_PRESENCE_PRESENT,
    F2BoardPresenceReferenceController,
)
from src.platform.f2_tracking_orientation_references import (
    F2_ORIENTATION_ANGLE,
    F2_ORIENTATION_SLOTS,
)


_PATCH_INSTALADO = False


def _tracking_automatico_ativo(app) -> bool:
    getter = getattr(app, "_f2_tracking_enabled", None)
    if callable(getter):
        try:
            return bool(getter())
        except Exception:
            return False
    return bool(getattr(app, "rastreamento_automatico_f2", False))


def evidencia_presenca_orientacao_real_f2(app) -> dict | None:
    """Retorna a referência angular que prova presença, ou ``None``.

    A decisão exige simultaneamente:
    - rastreamento automático F2 habilitado;
    - lock atual do rastreador;
    - pose não baseada em HOLD;
    - pelo menos um slot real calibrado/carregado;
    - o lock vencedor ou um candidato RANSAC válido vindo de 90/180/270.
    """
    if app is None or not _tracking_automatico_ativo(app):
        return None

    status = getattr(app, "_f2_object_tracking_last_status", {})
    if not isinstance(status, dict) or not bool(status.get("locked", False)):
        return None

    tracker = getattr(app, "_f2_object_tracker", None)
    if tracker is None:
        return None

    method = str(getattr(tracker, "_f2_tracking_last_method", "") or "").strip().upper()
    reason = str(status.get("reason", "") or "").strip().lower()
    if not reason:
        result = getattr(tracker, "last_result", None)
        reason = str(getattr(result, "reason", "") or "").strip().lower()

    # HOLD serve apenas para continuidade visual e nunca deve manter a placa
    # artificialmente PRESENTE depois que ela saiu da câmera.
    if method == "HOLD" or reason == "grace_lock":
        return None

    loaded_slots = set(
        getattr(tracker, "_f2_real_orientation_slots", set()) or set()
    )
    valid_slots = loaded_slots.intersection(F2_ORIENTATION_SLOTS)
    if not valid_slots:
        return None

    reference = str(status.get("reference", "") or "").strip()
    if not reference:
        result = getattr(tracker, "last_result", None)
        reference = str(getattr(result, "reference", "") or "").strip()

    if reference in valid_slots:
        return {
            "slot": reference,
            "angle_deg": float(F2_ORIENTATION_ANGLE.get(reference, 0.0)),
            "matches": int(status.get("matches", 0) or 0),
            "inliers": int(status.get("inliers", 0) or 0),
            "inlier_ratio": float(status.get("inlier_ratio", 0.0) or 0.0),
            "source": "winning_reference",
        }

    # Uma referência real pode ter produzido RANSAC válido no mesmo frame mesmo
    # quando outra vista obteve pontuação ligeiramente maior. Ela continua sendo
    # evidência independente de que a placa existe na cena.
    candidates = getattr(tracker, "_f2_real_orientation_candidate_results", {})
    if not isinstance(candidates, dict):
        return None

    best_slot = None
    best_candidate = None
    for slot in valid_slots:
        candidate = candidates.get(slot)
        if not isinstance(candidate, dict):
            continue
        if best_candidate is None or float(candidate.get("score", 0.0) or 0.0) > float(
            best_candidate.get("score", 0.0) or 0.0
        ):
            best_slot = slot
            best_candidate = candidate

    if best_slot is None or best_candidate is None:
        return None

    return {
        "slot": best_slot,
        "angle_deg": float(F2_ORIENTATION_ANGLE.get(best_slot, 0.0)),
        "matches": int(best_candidate.get("matches", 0) or 0),
        "inliers": int(best_candidate.get("inliers", 0) or 0),
        "inlier_ratio": float(best_candidate.get("ratio", 0.0) or 0.0),
        "source": "validated_candidate",
    }


def instalar_presenca_por_referencias_angulares_f2() -> None:
    """Complementa somente a classificação de presença do F2 com tracking ativo."""
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return

    atual = F2BoardPresenceReferenceController.classify
    if bool(getattr(atual, "_odin_f2_tracking_orientation_presence", False)):
        _PATCH_INSTALADO = True
        return
    anterior = atual

    def classify_com_presenca_angular(self, frame):
        presence, scores = anterior(self, frame)
        evidence = evidencia_presenca_orientacao_real_f2(getattr(self, "app", None))
        if evidence is None:
            return presence, scores

        merged_scores = dict(scores or {})
        merged_scores["tracking_orientation_present"] = 1.0
        merged_scores["tracking_orientation_angle"] = float(
            evidence.get("angle_deg", 0.0) or 0.0
        )
        merged_scores["tracking_orientation_matches"] = float(
            evidence.get("matches", 0) or 0
        )
        merged_scores["tracking_orientation_inliers"] = float(
            evidence.get("inliers", 0) or 0
        )
        merged_scores["tracking_orientation_inlier_ratio"] = float(
            evidence.get("inlier_ratio", 0.0) or 0.0
        )

        # A referência real é uma fotografia da própria placa. Se o ORB/RANSAC
        # confirmou essa referência neste frame, ela tem autoridade positiva sobre
        # UNKNOWN e sobre um falso EMPTY causado apenas pela rotação da cena.
        return F2_BOARD_PRESENCE_PRESENT, merged_scores

    classify_com_presenca_angular._odin_f2_tracking_orientation_presence = True
    classify_com_presenca_angular._odin_f2_tracking_orientation_presence_base = anterior
    F2BoardPresenceReferenceController.classify = classify_com_presenca_angular
    _PATCH_INSTALADO = True
