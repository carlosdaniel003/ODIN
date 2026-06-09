import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def atualizar_label_raio(self, raio_atual_px: int) -> None:
        self.raio_atual_px = raio_atual_px
        self.label_meta_roi.config(text=f"Manual | raio {self.raio_atual_px}px")
        self.label_parametros.config(
            text=(
                "Parâmetros de análise\n"
                "Método: referência aceso/apagado\n"
                f"ROI: manual | raio {self.raio_atual_px}px\n"
                "Região: LEDs selecionados\n"
                "Modo: múltiplos LEDs por análise"
            )
        )
