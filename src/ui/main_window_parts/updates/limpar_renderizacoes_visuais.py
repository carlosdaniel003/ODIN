import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def limpar_renderizacoes_visuais(self) -> None:
        self.desenhar_placeholders_laterais()
