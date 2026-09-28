from __future__ import annotations

"""Contrato único de aprovação positiva do Display F3.

Todo CHECK produtivo usa exatamente um frame integralmente conforme para OK.
O debounce de NG permanece independente e conservador.
"""

import src.platform.display_f3_h1_single_frame_probe as probe_module
import src.platform.display_f3_live_diagnostic_trace as trace_module
from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin


F3_OK_REQUIRED_FRAMES = 1


def frames_necessarios_aprovacao_f3(app=None, context: dict | None = None) -> int:
    """Retorna o contrato único: um frame conforme aprova qualquer CHECK."""
    return F3_OK_REQUIRED_FRAMES


_INSTALLED = False


def instalar_aprovacao_um_frame_display_f3() -> None:
    """Unifica runtime, sonda e trace no mesmo contrato de um frame."""
    global _INSTALLED
    if _INSTALLED:
        return

    DisplayAutomaticCheckF3Mixin.DISPLAY_AUTO_OK_STABLE_FRAMES = (
        F3_OK_REQUIRED_FRAMES
    )
    probe_module.frames_necessarios_sonda_positiva_f3 = (
        frames_necessarios_aprovacao_f3
    )
    trace_module._probe_required_frames = frames_necessarios_aprovacao_f3

    DisplayAutomaticCheckF3Mixin._display_f3_single_frame_approval_installed = True
    _INSTALLED = True
