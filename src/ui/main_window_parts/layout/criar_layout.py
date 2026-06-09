import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def criar_layout(self) -> None:
        self.frame_principal = tk.Frame(self.root, bg=self.COR_FUNDO_APP)
        self.frame_principal.pack(fill=tk.BOTH, expand=True)

        self.criar_topo_profissional()
        self.criar_barra_metadados()
        self.criar_faixa_resultado()
        self.criar_area_dashboard()
