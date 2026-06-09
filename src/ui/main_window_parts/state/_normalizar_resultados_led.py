import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def _normalizar_resultados_led(self, resultados_led_atual):
        if resultados_led_atual is None:
            return []
        if isinstance(resultados_led_atual, list):
            return resultados_led_atual
        return [resultados_led_atual]
