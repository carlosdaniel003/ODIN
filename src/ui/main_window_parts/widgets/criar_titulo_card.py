import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def criar_titulo_card(self, parent, texto: str) -> tk.Label:
        return tk.Label(
            parent,
            text=texto,
            font=("Segoe UI", 10, "bold"),
            fg=self.COR_TEXTO_2,
            bg=self.COR_CARD,
            anchor="w",
        )
