import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def escrever_resultados(self, texto: str) -> None:
        self.texto_resultados.delete("1.0", tk.END)
        self.texto_resultados.insert(tk.END, texto)
