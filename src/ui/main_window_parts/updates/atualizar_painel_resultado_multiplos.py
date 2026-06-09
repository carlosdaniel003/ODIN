import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def atualizar_painel_resultado_multiplos(self, resultados: list[LedAnalysisResult]) -> None:
        if not resultados:
            self.atualizar_resumo_sem_analise()
            return

        total_leds = len(resultados)
        leds_acesos = sum(1 for resultado in resultados if resultado.valor_binario == 1)
        leds_apagados = total_leds - leds_acesos
        confianca_media = sum(float(resultado.confianca) for resultado in resultados) / total_leds
        ultimo = resultados[-1]

        if leds_apagados > 0:
            cor_resultado = self.COR_VERMELHO_CLARO
            texto_resultado = "ANÁLISE COM APAGADO"
        else:
            cor_resultado = self.COR_VERDE_CLARO
            texto_resultado = "TODOS ACESOS"

        self.label_resultado_grande.config(text=texto_resultado, fg=cor_resultado)
        self.label_confianca.config(text=f"Confiança média\n{round(confianca_media, 4)}")
        self.desenhar_barra_confianca(float(confianca_media), cor_resultado)

        media_v_mean = sum(float(resultado.features.v_mean) for resultado in resultados) / total_leds
        max_v_max = max(float(resultado.features.v_max) for resultado in resultados)
        media_dist_on = sum(float(resultado.distancia_on) for resultado in resultados) / total_leds
        media_dist_off = sum(float(resultado.distancia_off) for resultado in resultados) / total_leds
        media_glow = sum(float(resultado.features.glow_score) for resultado in resultados) / total_leds

        self.card_binario.label_valor.config(text=f"{leds_acesos}/{total_leds}", fg=cor_resultado)
        self.card_v_mean.label_valor.config(text=str(round(media_v_mean, 4)))
        self.card_v_max.label_valor.config(text=str(round(max_v_max, 4)))
        self.card_dist_on.label_valor.config(text=str(round(media_dist_on, 4)))
        self.card_dist_off.label_valor.config(text=str(round(media_dist_off, 4)))
        self.card_glow.label_valor.config(text=str(round(media_glow, 4)))

        self.label_resumo.config(
            text=(
                "Resumo da análise\n"
                f"LEDs selecionados: {total_leds}\n"
                f"Acesos: {leds_acesos}\n"
                f"Apagados: {leds_apagados}\n"
                f"Último: {ultimo.id} {ultimo.status}"
            )
        )
