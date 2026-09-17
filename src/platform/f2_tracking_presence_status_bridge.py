from __future__ import annotations

"""Usa o rastreamento angular real como evidência positiva de presença no F2.

O classificador histórico de presença compara a cena inteira com PLACA LIGADA,
PLACA DESLIGADA e SUPORTE VAZIO. Quando a placa gira 90/180/270 graus, essa
comparação global pode ficar ambígua mesmo quando o rastreador ORB está travado
na placa.

Esta ponte atua somente quando ``Ativar rastreamento automático de objetos`` está
ligado. Uma correspondência válida com uma das referências reais 90/180/270 é
uma evidência estrutural de que existe uma placa na câmera. A referência angular
não inventa um estado elétrico novo: se o F2 já sabia que a mesma placa estava
LIGADA/DESLIGADA, esse estado é preservado durante a rotação; se ainda não havia
prova elétrica, a UI mostra simplesmente PLACA PRESENTE em vez de IDENTIFICANDO.

HOLD/grace_lock não são aceitos como prova, pois representam apenas a última pose
mantida visualmente e poderiam atrasar a detecção de retirada da placa.
"""

import src.platform.f2_object_tracking_visual_overlay as visual_overlay
from src.platform.f2_board_presence_references import (
    F2_BOARD_PRESENCE_PRESENT,
    F2BoardPresenceReferenceController,
)
from src.platform.f2_tracking_orientation_references import (
    F2_ORIENTATION_ANGLE,
    F2_ORIENTATION_SLOTS,
)
from src.platform.segment_display_operation_window import F2_BOARD_STATUS_UI


_PATCH_INSTALADO = False
F2_BOARD_STATUS_PRESENT = "board_present"


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


def status_visual_presenca_angular_f2(app, current_status: str | None = None) -> str | None:
    """Converte um lock real 90/180/270 em status útil para a UI.

    A orientação prova PRESENÇA, não potência. Se a UI acabou de conhecer o estado
    elétrico da mesma placa em 0°, preservamos LIGADA/DESLIGADA durante a rotação.
    Caso contrário mostramos PLACA PRESENTE, nunca IDENTIFICANDO.
    """
    evidence = evidencia_presenca_orientacao_real_f2(app)
    if evidence is None:
        return None

    normalized = str(current_status or "").strip().lower()
    if normalized in {"board_on", "board_off"}:
        return normalized
    return F2_BOARD_STATUS_PRESENT


def _instalar_publicacao_status_angular() -> None:
    atual = visual_overlay._publicar_status_placa_tracking_f2
    if bool(getattr(atual, "_odin_f2_tracking_orientation_status", False)):
        return
    anterior = atual

    def publicar_status_com_orientacao(app, raw_frame, presence: str | None = None):
        # A análise automática já possui estados vivos dos LEDs e continua sendo
        # a autoridade para LIGADA/DESLIGADA/JÁ ANALISADA.
        auto_enabled = bool(getattr(app, "_f2_auto_enabled", lambda: False)())
        if auto_enabled:
            return anterior(app, raw_frame, presence)

        window = getattr(app, "operacao_window", None)
        setter = getattr(window, "set_board_presence_status", None)
        if not callable(setter):
            return anterior(app, raw_frame, presence)

        angular_status = status_visual_presenca_angular_f2(
            app,
            getattr(window, "_board_presence_status", None),
        )
        if angular_status is None:
            return anterior(app, raw_frame, presence)

        try:
            setter(angular_status, enabled=True)
        except Exception:
            return anterior(app, raw_frame, presence)
        return angular_status

    publicar_status_com_orientacao._odin_f2_tracking_orientation_status = True
    publicar_status_com_orientacao._odin_f2_tracking_orientation_status_base = anterior
    visual_overlay._publicar_status_placa_tracking_f2 = publicar_status_com_orientacao


def instalar_presenca_por_referencias_angulares_f2() -> None:
    """Complementa presença e status do F2 somente com tracking ativo."""
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return

    # O setter da janela valida a chave contra este mapa. O novo estado é usado
    # apenas quando a orientação prova a presença mas ainda não existe prova de
    # LIGADA/DESLIGADA naquele ciclo.
    F2_BOARD_STATUS_UI.setdefault(
        F2_BOARD_STATUS_PRESENT,
        ("PLACA PRESENTE", "#86EFAC"),
    )

    atual = F2BoardPresenceReferenceController.classify
    if not bool(getattr(atual, "_odin_f2_tracking_orientation_presence", False)):
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

    # O bug visto em campo estava nesta segunda etapa: a presença já chegava como
    # PRESENT, mas o publisher antigo aceitava somente as referências board_on/
    # board_off e convertia orientation_90/180/270 novamente em UNKNOWN.
    _instalar_publicacao_status_angular()
    _PATCH_INSTALADO = True
