
import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def preparar_imagem_para_exibicao(self, imagem_canvas) -> None:
        if imagem_canvas is None:
            return

        self.imagem_canvas_original = imagem_canvas

        altura_canvas_original, largura_canvas_original = imagem_canvas.shape[:2]
        self.resolucao_atual = f"{largura_canvas_original} x {altura_canvas_original}"
        self.label_meta_resolucao.config(text=self.resolucao_atual)

        self.atualizar_imagem_principal_redimensionada()
