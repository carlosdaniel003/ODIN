import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def desenhar_canvas(self, led_selecionado, resultado_led_atual) -> None:
        leds_selecionados = self._normalizar_leds_selecionados(led_selecionado)
        resultados_led = self._normalizar_resultados_led(resultado_led_atual)

        self.ultimo_led_selecionado = leds_selecionados
        self.ultimo_resultado_led_atual = resultados_led
        self.canvas.delete("all")

        largura_canvas, altura_canvas = self.obter_tamanho_canvas_principal()
        self.canvas.create_rectangle(0, 0, largura_canvas, altura_canvas, fill="#020617", outline="")

        if self.imagem_tk is None:
            self.canvas.create_text(
                largura_canvas / 2,
                altura_canvas / 2,
                text="Carregue a imagem da PCI",
                fill=self.COR_TEXTO_2,
                font=("Segoe UI", 18, "bold"),
            )
            self.desenhar_placeholders_laterais()
            return

        self.canvas.create_image(
            self.deslocamento_imagem_x,
            self.deslocamento_imagem_y,
            image=self.imagem_tk,
            anchor=tk.NW,
        )

        if resultados_led:
            self.desenhar_resultados_led(resultados_led)
            self.atualizar_painel_resultado_multiplos(resultados_led)
            for resultado in resultados_led:
                self.adicionar_resultado_historico(resultado)
            self.desenhar_placeholders_laterais(resultados_led[-1])
        elif leds_selecionados:
            self.desenhar_leds_selecionados(leds_selecionados)
            self.atualizar_resumo_selecoes(leds_selecionados)
            self.desenhar_placeholders_laterais()
        else:
            self.atualizar_resumo_sem_analise()
            self.desenhar_placeholders_laterais()
