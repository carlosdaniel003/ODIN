import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def redesenhar_imagem_principal_apos_redimensionamento(self) -> None:
        self._redimensionamento_pendente = None

        if self.imagem_canvas_original is None:
            return

        self.atualizar_imagem_principal_redimensionada()
        self.desenhar_canvas(self.ultimo_led_selecionado, self.ultimo_resultado_led_atual)
