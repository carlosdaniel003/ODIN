import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def configurar_estilo_tabela(self) -> None:
        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "Treeview",
            background="#020617",
            foreground=self.COR_TEXTO_2,
            fieldbackground="#020617",
            borderwidth=0,
            rowheight=24,
            font=("Consolas", 9),
        )
        style.configure(
            "Treeview.Heading",
            background="#0B1626",
            foreground=self.COR_TEXTO,
            relief="flat",
            font=("Segoe UI", 9, "bold"),
        )
        style.map("Treeview", background=[("selected", "#1E3A8A")])
