import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def atualizar_resumo_selecao(self, led_selecionado: LedSelection) -> None:
        self.atualizar_resumo_selecoes([led_selecionado])
