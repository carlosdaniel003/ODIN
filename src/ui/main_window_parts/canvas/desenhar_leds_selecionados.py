import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def desenhar_leds_selecionados(self, leds_selecionados: list[LedSelection]) -> None:
        for led_selecionado in leds_selecionados:
            self.desenhar_led_selecionado(led_selecionado)
