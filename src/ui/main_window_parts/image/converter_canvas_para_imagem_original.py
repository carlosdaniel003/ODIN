import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def converter_canvas_para_imagem_original(self, canvas_x: int, canvas_y: int):
        if self.imagem_canvas_original is None:
            return None

        x_relativo = canvas_x - self.deslocamento_imagem_x
        y_relativo = canvas_y - self.deslocamento_imagem_y

        if x_relativo < 0 or y_relativo < 0:
            return None

        if x_relativo >= self.largura_imagem_exibida or y_relativo >= self.altura_imagem_exibida:
            return None

        if self.escala_exibicao <= 0:
            return None

        centro_x = int(x_relativo / self.escala_exibicao)
        centro_y = int(y_relativo / self.escala_exibicao)
        return centro_x, centro_y
