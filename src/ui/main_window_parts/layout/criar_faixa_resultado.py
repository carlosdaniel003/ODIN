import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def criar_faixa_resultado(self) -> None:
        self.frame_faixa_resultado = tk.Frame(self.frame_principal, bg=self.COR_NEUTRO, height=64)
        self.frame_faixa_resultado.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 8))
        self.frame_faixa_resultado.pack_propagate(False)

        self.label_faixa_resultado = tk.Label(
            self.frame_faixa_resultado,
            text="SEM ANÁLISE",
            font=("Segoe UI", 22, "bold"),
            fg=self.COR_TEXTO,
            bg=self.COR_NEUTRO,
        )
        self.label_faixa_resultado.pack(fill=tk.BOTH, expand=True)
