import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def criar_item_metadado(self, titulo: str, valor: str, destaque: bool = False) -> tk.Label:
        frame = tk.Frame(self.frame_metadados, bg=self.COR_CARD)
        frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=8, pady=6)

        label_titulo = tk.Label(
            frame,
            text=f"{titulo}: ",
            font=("Segoe UI", 8, "bold"),
            fg=self.COR_TEXTO_3,
            bg=self.COR_CARD,
            anchor="w",
        )
        label_titulo.pack(side=tk.LEFT)

        label_valor = tk.Label(
            frame,
            text=valor,
            font=("Segoe UI", 8, "bold"),
            fg=self.COR_VERDE_CLARO if destaque else self.COR_TEXTO_2,
            bg=self.COR_CARD,
            anchor="w",
        )
        label_valor.pack(side=tk.LEFT, fill=tk.X, expand=True)
        return label_valor
