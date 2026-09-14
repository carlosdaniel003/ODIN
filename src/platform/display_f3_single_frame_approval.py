from __future__ import annotations

"""Contrato de estabilidade positiva do Display F3.

CHECKS estáveis usam dois frames positivos consecutivos. CHECKS fisicamente
transitórios, como BLUE/BT, continuam podendo ser capturados em um único frame.
NG permanece com seu debounce conservador independente.
"""

import src.platform.display_f3_h1_single_frame_probe as probe_module
import src.platform.display_f3_live_diagnostic_trace as trace_module
from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin


F3_OK_REQUIRED_FRAMES = 2
F3_TRANSIENT_OK_REQUIRED_FRAMES = 1
F3_TRANSIENT_NAMES = frozenset({"BLUE", "BLUETOOTH", "BT"})


def _is_transient_context(app, context: dict | None) -> bool:
    if not isinstance(context, dict):
        return False
    try:
        if app is not None and app._display_auto_is_transient_check(context):
            return True
    except Exception:
        pass

    name = str(context.get("check_name") or "").strip().upper()
    normalized = " ".join(name.replace("-", " ").replace("_", " ").split())
    tokens = set(normalized.split())
    return bool(
        normalized in F3_TRANSIENT_NAMES
        or tokens.intersection(F3_TRANSIENT_NAMES)
    )


def frames_necessarios_aprovacao_f3(app=None, context: dict | None = None) -> int:
    """BLUE/BT usa 1 frame; H1 e demais CHECKS usam 2 frames consecutivos."""
    return (
        F3_TRANSIENT_OK_REQUIRED_FRAMES
        if _is_transient_context(app, context)
        else F3_OK_REQUIRED_FRAMES
    )


_INSTALLED = False


def instalar_aprovacao_um_frame_display_f3() -> None:
    """Aplica a mesma estabilidade segura a runtime, sonda e camada final."""
    global _INSTALLED
    if _INSTALLED:
        return

    # O runtime já trata CHECK transitório separadamente com 1 frame. Este valor
    # passa a representar o contrato dos CHECKS estáveis, inclusive H1.
    DisplayAutomaticCheckF3Mixin.DISPLAY_AUTO_OK_STABLE_FRAMES = F3_OK_REQUIRED_FRAMES

    # A sonda e o rastreador consultam a mesma regra dinâmica para não existir um
    # caminho rápido que aprove H1 em apenas um frame isolado.
    probe_module.frames_necessarios_sonda_positiva_f3 = frames_necessarios_aprovacao_f3
    trace_module._probe_required_frames = frames_necessarios_aprovacao_f3

    DisplayAutomaticCheckF3Mixin._display_f3_single_frame_approval_installed = True
    _INSTALLED = True
