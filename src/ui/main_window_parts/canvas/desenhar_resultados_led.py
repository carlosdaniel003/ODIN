import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def desenhar_resultados_led(self, resultados_led: list[LedAnalysisResult]) -> None:
        for resultado_led in resultados_led:
            self.desenhar_resultado_led(resultado_led)
