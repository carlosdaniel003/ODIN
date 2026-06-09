import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def desenhar_placeholders_laterais(self, resultado: LedAnalysisResult | None = None) -> None:
        if resultado is None:
            self.desenhar_placeholder(self.canvas_mapa_intensidade, "Mapa de intensidade\naguardando imagem")
            self.desenhar_placeholder(self.canvas_imagem_teste, "Canal V\naguardando imagem")
            self.desenhar_placeholder(self.canvas_mascara, "Máscara visual\naguardando ROI")
            self.desenhar_placeholder(self.canvas_roi_debug, "ROI debug\naguardando seleção")
            return

        cor = self.COR_VERDE_CLARO if resultado.valor_binario == 1 else self.COR_VERMELHO_CLARO
        self.desenhar_placeholder(
            self.canvas_mapa_intensidade,
            f"Mapa de intensidade\nLED {resultado.status}",
            cor=cor,
        )
        self.desenhar_placeholder(
            self.canvas_imagem_teste,
            "Canal V / HSV",
            cor=cor,
        )
        self.desenhar_placeholder(
            self.canvas_mascara,
            f"Máscara ROI\nCentro ({resultado.centro_x}, {resultado.centro_y})",
            cor=cor,
        )
        self.desenhar_placeholder(
            self.canvas_roi_debug,
            "ROI debug ampliado",
            cor=cor,
        )
