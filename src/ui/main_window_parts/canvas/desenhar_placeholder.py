import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def desenhar_placeholder(self, canvas: tk.Canvas, texto: str, cor: str | None = None) -> None:
        canvas.delete("all")
        cor_texto = cor or self.COR_TEXTO_3
        canvas.update_idletasks()
        largura = max(260, canvas.winfo_width())
        altura = max(120, canvas.winfo_height())

        canvas.create_rectangle(0, 0, largura, altura, fill="#020617", outline="")
        canvas.create_text(
            largura / 2,
            altura / 2,
            text=texto,
            fill=cor_texto,
            font=("Segoe UI", 11, "bold"),
            justify=tk.CENTER,
        )
