import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def _normalizar_leds_selecionados(self, leds_selecionados):
        if leds_selecionados is None:
            return []
        if isinstance(leds_selecionados, list):
            return leds_selecionados
        return [leds_selecionados]
