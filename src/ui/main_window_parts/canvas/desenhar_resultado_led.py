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

        self.canvas.create_oval(
            centro_x_canvas - raio_canvas,
            centro_y_canvas - raio_canvas,
            centro_x_canvas + raio_canvas,
            centro_y_canvas + raio_canvas,
            outline=cor,
            width=3,
        )
        self.canvas.create_line(centro_x_canvas - raio_canvas, centro_y_canvas, centro_x_canvas + raio_canvas, centro_y_canvas, fill=cor, width=2)
        self.canvas.create_line(centro_x_canvas, centro_y_canvas - raio_canvas, centro_x_canvas, centro_y_canvas + raio_canvas, fill=cor, width=2)
        self.canvas.create_text(
            centro_x_canvas + 48,
            centro_y_canvas - 16,
            text=f"{resultado_led_atual.id} {resultado_led_atual.status}",
            fill=cor,
            font=("Segoe UI", 10, "bold"),
        )
