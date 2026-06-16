
import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def atualizar_imagem_principal_redimensionada(self) -> None:
        if self.imagem_canvas_original is None:
            return

        altura_canvas_original, largura_canvas_original = self.imagem_canvas_original.shape[:2]
        largura_disponivel, altura_disponivel = self.obter_tamanho_canvas_principal()

        escala_largura = largura_disponivel / largura_canvas_original
        escala_altura = altura_disponivel / altura_canvas_original
        self.escala_exibicao = min(escala_largura, escala_altura, 1.0)

        self.largura_imagem_exibida = max(1, int(largura_canvas_original * self.escala_exibicao))
        self.altura_imagem_exibida = max(1, int(altura_canvas_original * self.escala_exibicao))

        self.deslocamento_imagem_x = max(0, int((largura_disponivel - self.largura_imagem_exibida) / 2))
        self.deslocamento_imagem_y = max(0, int((altura_disponivel - self.altura_imagem_exibida) / 2))

        self.imagem_exibicao = cv2.resize(
            self.imagem_canvas_original,
            (self.largura_imagem_exibida, self.altura_imagem_exibida),
            interpolation=cv2.INTER_AREA,
        )

        imagem_rgb = cv2.cvtColor(self.imagem_exibicao, cv2.COLOR_BGR2RGB)
        sucesso, buffer = cv2.imencode(".png", imagem_rgb)

        if not sucesso:
            return

        imagem_base64 = base64.b64encode(buffer).decode("ascii")
        self.imagem_tk = tk.PhotoImage(data=imagem_base64)
