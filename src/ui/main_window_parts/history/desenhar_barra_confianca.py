import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def desenhar_barra_confianca(self, confianca: float, cor: str) -> None:
        self.canvas_barra_confianca.delete("all")
        largura = max(1, self.canvas_barra_confianca.winfo_width())
        if largura <= 1:
            largura = 300

        altura = 8
        x1 = 0
        y1 = 4
        x2 = largura
        y2 = y1 + altura
        preenchimento = int(largura * max(0.0, min(1.0, confianca)))

        self.canvas_barra_confianca.create_rectangle(x1, y1, x2, y2, fill="#111827", outline="")
        self.canvas_barra_confianca.create_rectangle(x1, y1, preenchimento, y2, fill=cor, outline="")
        self.canvas_barra_confianca.create_text(0, y2 + 8, text="0.0000", fill=self.COR_TEXTO_3, anchor="w", font=("Consolas", 7))
        self.canvas_barra_confianca.create_text(largura, y2 + 8, text="1.0000", fill=self.COR_TEXTO_3, anchor="e", font=("Consolas", 7))
