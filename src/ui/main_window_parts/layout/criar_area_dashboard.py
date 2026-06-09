import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def criar_area_dashboard(self) -> None:
        self.frame_dashboard = tk.Frame(self.frame_principal, bg=self.COR_FUNDO_APP)
        self.frame_dashboard.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))

        self.frame_dashboard.grid_rowconfigure(0, weight=6)
        self.frame_dashboard.grid_rowconfigure(1, weight=2)
        self.frame_dashboard.grid_columnconfigure(0, weight=5)
        self.frame_dashboard.grid_columnconfigure(1, weight=3)
        self.frame_dashboard.grid_columnconfigure(2, weight=4)

        self.criar_painel_principal()
        self.criar_painel_central()
        self.criar_painel_direito()
        self.criar_tabela_inferior()
