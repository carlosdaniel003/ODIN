import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def atualizar_resumo_selecoes(self, leds_selecionados: list[LedSelection]) -> None:
        if not leds_selecionados:
            self.atualizar_resumo_sem_analise()
            return

        ultimo = leds_selecionados[-1]
        self.label_resumo.config(
            text=(
                "Resumo da seleção\n"
                f"LEDs selecionados: {len(leds_selecionados)}\n"
                "Status: aguardando análise\n"
                f"Último: {ultimo.id}\n"
                f"Posição: ({ultimo.centro_x}, {ultimo.centro_y})"
            )
        )
