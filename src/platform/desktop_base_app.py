from __future__ import annotations

import tkinter as tk

from src.platform.desktop_profile import DesktopODINApp
from src.platform.led_mask_editor import LedMaskEditorMixin
from src.platform.led_project_manager import LedProjectManagerMixin
from src.platform.performance_metrics import PerformanceMetricsMixin


class DesktopBaseODINApp(
    PerformanceMetricsMixin,
    LedProjectManagerMixin,
    LedMaskEditorMixin,
    DesktopODINApp,
):
    """Base desktop sem GPIO, mantendo projetos, máscaras e métricas do F2."""

    def __init__(self, root: tk.Tk) -> None:
        super().__init__(root)
        self.inicializar_editor_mascaras_led()

    def iniciar_tela_ao_vivo(self) -> None:
        self._editor_leds_carregados_explicitamente = False
        super().iniciar_tela_ao_vivo()

    def salvar_leds_fixos(self) -> None:
        super().salvar_leds_fixos()
        self._editor_leds_carregados_explicitamente = False
