from __future__ import annotations

"""Impede julgamento produtivo com uma pose apenas mantida por HOLD.

O HOLD é útil para continuidade visual por poucos frames, mas sua matriz pode estar
ligeiramente defasada da posição física atual da placa. Enquanto o rastreamento
estiver em HOLD, a câmera pode continuar exibindo o último contorno, porém Enter,
GPIO e análise automática aguardam uma nova pose confirmada antes de ler LEDs.
"""

import src.platform.f2_tracking_analysis_rois as tracking_analysis


_PATCH_INSTALADO = False


def instalar_guarda_analise_pose_fresca_f2() -> None:
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return

    atual = tracking_analysis._tracking_com_lock
    if bool(getattr(atual, "_odin_f2_fresh_pose_guard", False)):
        _PATCH_INSTALADO = True
        return
    anterior = atual

    def tracking_com_lock_fresco(app) -> bool:
        if not bool(anterior(app)):
            return False

        tracker = getattr(app, "_f2_object_tracker", None)
        status = getattr(app, "_f2_object_tracking_last_status", {})
        reason = ""
        if isinstance(status, dict):
            reason = str(status.get("reason", "") or "").strip().lower()
        if not reason and tracker is not None:
            result = getattr(tracker, "last_result", None)
            reason = str(getattr(result, "reason", "") or "").strip().lower()

        method = str(
            getattr(tracker, "_f2_tracking_last_method", "") or ""
        ).strip().upper()

        # HOLD/grace_lock representa somente continuidade visual; nunca deve ser
        # autoridade para posicionar a ROI que decide OK/NG.
        if method == "HOLD" or reason == "grace_lock":
            return False
        return True

    tracking_com_lock_fresco._odin_f2_fresh_pose_guard = True
    tracking_com_lock_fresco._odin_f2_fresh_pose_guard_base = anterior
    tracking_analysis._tracking_com_lock = tracking_com_lock_fresco
    _PATCH_INSTALADO = True
