import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def exibir_renderizacoes_visuais(self, renderizacoes: dict | None) -> None:
        if not renderizacoes:
            self.limpar_renderizacoes_visuais()
            return

        self.exibir_imagem_em_canvas(
            canvas=self.canvas_imagem_teste,
            imagem=renderizacoes.get("canal_v"),
            chave="canal_v",
        )
        self.exibir_imagem_em_canvas(
            canvas=self.canvas_mapa_intensidade,
            imagem=renderizacoes.get("heatmap"),
            chave="heatmap",
        )
        self.exibir_imagem_em_canvas(
            canvas=self.canvas_mascara,
            imagem=renderizacoes.get("mascara"),
            chave="mascara",
        )

        roi_debug = renderizacoes.get("roi_debug")
        if roi_debug is None:
            self.desenhar_placeholder(self.canvas_roi_debug, "ROI debug\nselecione um LED")
        else:
            self.exibir_imagem_em_canvas(
                canvas=self.canvas_roi_debug,
                imagem=roi_debug,
                chave="roi_debug",
            )
