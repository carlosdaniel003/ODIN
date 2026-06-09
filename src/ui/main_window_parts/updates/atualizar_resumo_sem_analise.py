import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def atualizar_resumo_sem_analise(self) -> None:
        self.label_resumo.config(
            text=(
                "Resumo da seleção\n"
                "LEDs selecionados: 0\n"
                "Status: sem análise\n"
                "Último: --\n"
                "Valor binário: --"
            )
        )
