import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def atualizar_faixa_resultado_multiplos(self, resultados_led: list[LedAnalysisResult]) -> None:
        if not resultados_led:
            self.atualizar_faixa_resultado()
            return

        total_leds = len(resultados_led)
        leds_acesos = sum(1 for resultado in resultados_led if resultado.valor_binario == 1)
        leds_apagados = total_leds - leds_acesos

        if leds_apagados > 0:
            cor_fundo = self.COR_VERMELHO
            cor_resultado = self.COR_VERMELHO_CLARO
            texto = f"ANÁLISE COM LED APAGADO | acesos {leds_acesos} | apagados {leds_apagados}"
            titulo = "LED APAGADO"
        else:
            cor_fundo = self.COR_VERDE
            cor_resultado = self.COR_VERDE_CLARO
            texto = f"TODOS OS LEDS ACESOS | total {total_leds}"
            titulo = "TODOS ACESOS"

        self.frame_faixa_resultado.config(bg=cor_fundo)
        self.label_faixa_resultado.config(text=texto, bg=cor_fundo)
        self.label_resultado_grande.config(text=titulo, fg=cor_resultado)

        confianca_media = sum(float(resultado.confianca) for resultado in resultados_led) / total_leds
        self.label_confianca.config(text=f"Confiança média\n{round(confianca_media, 4)}")
        self.desenhar_barra_confianca(float(confianca_media), cor_resultado)
