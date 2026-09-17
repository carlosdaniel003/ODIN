from __future__ import annotations

"""Reaquisição de precisão quando o F2 entra em HOLD.

O HOLD existe para evitar que o overlay pisque quando ORB/ECC perdem a placa por
poucos frames. Porém, quando a placa está em rotações grandes (principalmente
90°/180°), esse HOLD também pode manter uma matriz antiga por alguns ciclos e as
ROIs ficam visualmente deslocadas mesmo com a placa ainda presente.

Esta camada transforma HOLD em estado provisório: mantém o último desenho apenas
para continuidade visual, mas força o banco multivista a tentar uma nova pose no
mesmo frame. Se a nova correspondência for válida, ela substitui imediatamente a
matriz antiga. Nenhuma referência ou ROI persistida é alterada.
"""

from src.platform.f2_object_tracking import F2BoardObjectTracker
import src.platform.f2_object_tracking_multiview as multiview


_PATCH_INSTALADO = False


def _resultado_e_hold(tracker, result) -> bool:
    if result is None or not bool(getattr(result, "locked", False)):
        return False
    reason = str(getattr(result, "reason", "") or "").strip().lower()
    method = str(getattr(tracker, "_f2_tracking_last_method", "") or "").strip().upper()
    return bool(reason == "grace_lock" or method == "HOLD")


def instalar_reaquisicao_durante_hold_f2() -> None:
    """Permite ao multiview substituir imediatamente uma matriz HOLD defasada."""
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return

    align_atual = F2BoardObjectTracker.align
    if bool(getattr(align_atual, "_odin_f2_hold_reacquire", False)):
        _PATCH_INSTALADO = True
        return

    align_anterior = align_atual

    def align_com_reaquisicao_hold(self, frame, frame_id=None):
        result = align_anterior(self, frame, frame_id=frame_id)
        if not _resultado_e_hold(self, result):
            return result

        # O multiview possui seu próprio limitador temporal, portanto esta chamada
        # não multiplica o custo em todos os frames. Em HOLD ela tenta substituir
        # a pose congelada por uma correspondência fresca da imagem atual.
        try:
            fresh = multiview._tentar_multiview(
                self,
                frame,
                frame_id=frame_id,
            )
        except Exception:
            fresh = None

        if fresh is not None and bool(getattr(fresh, "locked", False)):
            return fresh
        return result

    align_com_reaquisicao_hold._odin_f2_hold_reacquire = True
    align_com_reaquisicao_hold._odin_f2_hold_reacquire_base = align_anterior
    F2BoardObjectTracker.align = align_com_reaquisicao_hold
    _PATCH_INSTALADO = True
