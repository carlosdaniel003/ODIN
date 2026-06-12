import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection


def desenhar_resultado_led(self, resultado_led_atual: LedAnalysisResult) -> None:
    cor = self.COR_VERDE_CLARO if resultado_led_atual.valor_binario == 1 else self.COR_VERMELHO_CLARO

    centro_x_canvas = self.deslocamento_imagem_x + int(resultado_led_atual.centro_x * self.escala_exibicao)
    centro_y_canvas = self.deslocamento_imagem_y + int(resultado_led_atual.centro_y * self.escala_exibicao)
    raio_canvas = max(3, int(resultado_led_atual.raio * self.escala_exibicao))

    id_led = getattr(resultado_led_atual, "id", "LED")
    numero_led = id_led.split("_")[-1] if "_" in id_led else id_led

    largura_linha = 2
    raio_visual = raio_canvas

    if resultado_led_atual.valor_binario == 0:
        largura_linha = 4
        raio_visual = int(raio_canvas * 1.25)

    self.canvas.create_oval(
        centro_x_canvas - raio_visual,
        centro_y_canvas - raio_visual,
        centro_x_canvas + raio_visual,
        centro_y_canvas + raio_visual,
        outline=cor,
        width=largura_linha,
    )

    self.canvas.create_line(
        centro_x_canvas - raio_visual,
        centro_y_canvas,
        centro_x_canvas + raio_visual,
        centro_y_canvas,
        fill=cor,
        width=1,
    )

    self.canvas.create_line(
        centro_x_canvas,
        centro_y_canvas - raio_visual,
        centro_x_canvas,
        centro_y_canvas + raio_visual,
        fill=cor,
        width=1,
    )

    x_label = centro_x_canvas + raio_visual + 4
    y_label = centro_y_canvas - raio_visual - 4

    if resultado_led_atual.valor_binario == 0:
        texto = f"{numero_led} OFF"
        fonte = ("Segoe UI", 8, "bold")
        padding_x = 4
        padding_y = 2

        largura_aproximada = max(42, len(texto) * 7)
        altura_aproximada = 16

        self.canvas.create_rectangle(
            x_label - padding_x,
            y_label - altura_aproximada,
            x_label + largura_aproximada,
            y_label + padding_y,
            fill="#1F0505",
            outline=cor,
            width=1,
        )

        self.canvas.create_text(
            x_label,
            y_label - 8,
            text=texto,
            fill=cor,
            font=fonte,
            anchor=tk.W,
        )

        return

    self.canvas.create_oval(
        centro_x_canvas - 8,
        centro_y_canvas - 8,
        centro_x_canvas + 8,
        centro_y_canvas + 8,
        fill="#03120A",
        outline=cor,
        width=1,
    )

    self.canvas.create_text(
        centro_x_canvas,
        centro_y_canvas,
        text=numero_led,
        fill=cor,
        font=("Segoe UI", 6, "bold"),
    )