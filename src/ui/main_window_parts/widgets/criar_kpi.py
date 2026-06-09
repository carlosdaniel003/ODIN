import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def criar_kpi(self, parent, titulo: str, valor: str) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.COR_CARD_2, height=58)
        frame.pack_propagate(False)

        label_titulo = tk.Label(
            frame,
            text=titulo,
            font=("Segoe UI", 8, "bold"),
            fg=self.COR_TEXTO_3,
            bg=self.COR_CARD_2,
        )
        label_titulo.pack(anchor="center", pady=(8, 0))

        label_valor = tk.Label(
            frame,
            text=valor,
            font=("Segoe UI", 13, "bold"),
            fg=self.COR_TEXTO,
            bg=self.COR_CARD_2,
        )
        label_valor.pack(anchor="center")

        frame.label_valor = label_valor
        return frame
