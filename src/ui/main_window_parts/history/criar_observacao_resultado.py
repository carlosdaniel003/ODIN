import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def criar_observacao_resultado(self, resultado: LedAnalysisResult) -> str:
        if resultado.status == "ACESO":
            return "Classificado como aceso pela regra atual de referência e métricas."

        return "Classificado como apagado pela regra atual de referência e métricas."
