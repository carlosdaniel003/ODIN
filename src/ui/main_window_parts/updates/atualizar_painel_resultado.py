import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def atualizar_painel_resultado(self, resultado: LedAnalysisResult) -> None:
        cor_resultado = self.COR_VERDE_CLARO if resultado.valor_binario == 1 else self.COR_VERMELHO_CLARO
        self.label_resultado_grande.config(text=f"LED {resultado.status}", fg=cor_resultado)
        self.label_confianca.config(text=f"Confiança\n{resultado.confianca}")
        self.desenhar_barra_confianca(float(resultado.confianca), cor_resultado)

        self.card_binario.label_valor.config(text=str(resultado.valor_binario), fg=cor_resultado)
        self.card_v_mean.label_valor.config(text=str(resultado.features.v_mean))
        self.card_v_max.label_valor.config(text=str(resultado.features.v_max))
        self.card_dist_on.label_valor.config(text=str(resultado.distancia_on))
        self.card_dist_off.label_valor.config(text=str(resultado.distancia_off))
        self.card_glow.label_valor.config(text=str(resultado.features.glow_score))

        self.label_resumo.config(
            text=(
                "Resumo do LED\n"
                f"Status: {resultado.status}\n"
                f"Confiança: {resultado.confianca}\n"
                f"Posição: ({resultado.centro_x}, {resultado.centro_y})\n"
                f"Valor binário: {resultado.valor_binario}"
            )
        )
