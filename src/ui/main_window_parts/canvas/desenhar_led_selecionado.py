import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def desenhar_led_selecionado(self, led_selecionado: LedSelection) -> None:
        centro_x_canvas = self.deslocamento_imagem_x + int(led_selecionado.centro_x * self.escala_exibicao)
        centro_y_canvas = self.deslocamento_imagem_y + int(led_selecionado.centro_y * self.escala_exibicao)
        raio_canvas = max(3, int(led_selecionado.raio * self.escala_exibicao))
        id_led = getattr(led_selecionado, "id", "LED")

        self.canvas.create_oval(
            centro_x_canvas - raio_canvas,
            centro_y_canvas - raio_canvas,
            centro_x_canvas + raio_canvas,
            centro_y_canvas + raio_canvas,
            outline=self.COR_AZUL,
            width=3,
        )
        self.canvas.create_line(centro_x_canvas - raio_canvas, centro_y_canvas, centro_x_canvas + raio_canvas, centro_y_canvas, fill=self.COR_AZUL, width=2)
        self.canvas.create_line(centro_x_canvas, centro_y_canvas - raio_canvas, centro_x_canvas, centro_y_canvas + raio_canvas, fill=self.COR_AZUL, width=2)
        self.canvas.create_text(
            centro_x_canvas + 48,
            centro_y_canvas - 16,
            text=id_led,
            fill=self.COR_AZUL,
            font=("Segoe UI", 10, "bold"),
        )
