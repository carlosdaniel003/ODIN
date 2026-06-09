import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def atualizar_faixa_resultado(self, status: str = "SEM ANÁLISE", confianca=None) -> None:
        if status == "ACESO":
            cor_fundo = self.COR_VERDE
            texto = "LED ACESO"
            cor_resultado = self.COR_VERDE_CLARO
        elif status == "APAGADO":
            cor_fundo = self.COR_VERMELHO
            texto = "LED APAGADO"
            cor_resultado = self.COR_VERMELHO_CLARO
        else:
            cor_fundo = self.COR_NEUTRO
            texto = "SEM ANÁLISE"
            cor_resultado = self.COR_TEXTO_3

        if confianca is not None and status in ["ACESO", "APAGADO"]:
            texto = f"{texto} | confiança {confianca}"

        self.frame_faixa_resultado.config(bg=cor_fundo)
        self.label_faixa_resultado.config(text=texto, bg=cor_fundo)
        self.label_resultado_grande.config(text=status, fg=cor_resultado)

        if confianca is None:
            self.label_confianca.config(text="Confiança\n--")
            self.desenhar_barra_confianca(0.0, self.COR_NEUTRO)
        else:
            self.label_confianca.config(text=f"Confiança\n{confianca}")
            self.desenhar_barra_confianca(float(confianca), cor_resultado)
