import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def exibir_imagem_em_canvas(self, canvas: tk.Canvas, imagem, chave: str) -> None:
        canvas.delete("all")

        if imagem is None:
            self.desenhar_placeholder(canvas, "sem imagem")
            return

        canvas.update_idletasks()
        largura_canvas = max(260, canvas.winfo_width())
        altura_canvas = max(120, canvas.winfo_height())

        if len(imagem.shape) == 2:
            imagem_bgr = cv2.cvtColor(imagem, cv2.COLOR_GRAY2BGR)
        else:
            imagem_bgr = imagem

        altura_imagem, largura_imagem = imagem_bgr.shape[:2]
        escala_largura = largura_canvas / largura_imagem
        escala_altura = altura_canvas / altura_imagem
        escala = min(escala_largura, escala_altura, 1.0)

        largura_final = max(1, int(largura_imagem * escala))
        altura_final = max(1, int(altura_imagem * escala))

        imagem_redimensionada = cv2.resize(
            imagem_bgr,
            (largura_final, altura_final),
            interpolation=cv2.INTER_AREA,
        )

        imagem_rgb = cv2.cvtColor(imagem_redimensionada, cv2.COLOR_BGR2RGB)
        sucesso, buffer = cv2.imencode(".png", imagem_rgb)

        if not sucesso:
            self.desenhar_placeholder(canvas, "erro ao renderizar imagem")
            return

        imagem_base64 = base64.b64encode(buffer).decode("ascii")
        imagem_tk = tk.PhotoImage(data=imagem_base64)
        self.imagens_auxiliares_tk[chave] = imagem_tk

        x = int((largura_canvas - largura_final) / 2)
        y = int((altura_canvas - altura_final) / 2)

        canvas.create_rectangle(0, 0, largura_canvas, altura_canvas, fill="#020617", outline="")
        canvas.create_image(x, y, image=imagem_tk, anchor=tk.NW)
