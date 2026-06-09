import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def criar_barra_metadados(self) -> None:
        self.frame_metadados = tk.Frame(self.frame_principal, bg=self.COR_CARD, height=42)
        self.frame_metadados.pack(fill=tk.X, padx=10, pady=(0, 8))
        self.frame_metadados.pack_propagate(False)

        self.label_meta_placa = self.criar_item_metadado("Placa", "MANUAL")
        self.label_meta_lado = self.criar_item_metadado("Lado", "A (Frente)")
        self.label_meta_roi = self.criar_item_metadado("ROI", f"Manual | raio {self.raio_atual_px}px")
        self.label_meta_resolucao = self.criar_item_metadado("Resolução", "--")
        self.label_meta_tempo = self.criar_item_metadado("Tempo ciclo", "-- ms")
        self.label_meta_status = self.criar_item_metadado("Status", "Aguardando referências", destaque=True)
        self.label_meta_data = self.criar_item_metadado("Data/Hora", self.obter_data_hora())
