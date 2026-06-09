import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def criar_botao_config(self, parent, texto: str, comando) -> tk.Button:
        return tk.Button(
            parent,
            text=texto,
            command=comando,
            width=14,
            height=2,
            bg="#0B1626",
            fg=self.COR_TEXTO_2,
            activebackground=self.COR_BORDA,
            activeforeground=self.COR_TEXTO,
            relief=tk.FLAT,
            bd=0,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
