import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def obter_tamanho_canvas_principal(self) -> tuple[int, int]:
        self.root.update_idletasks()
        largura_canvas = self.canvas.winfo_width()
        altura_canvas = self.canvas.winfo_height()

        if largura_canvas <= 1:
            largura_canvas = self.frame_painel_principal.winfo_width() - 24

        if altura_canvas <= 1:
            altura_canvas = self.frame_painel_principal.winfo_height() - 120

        largura_canvas = max(320, int(largura_canvas))
        altura_canvas = max(220, int(altura_canvas))
        return largura_canvas, altura_canvas
