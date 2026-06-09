import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def atualizar_status(self, texto: str) -> None:
        self.label_meta_status.config(text=texto)
        self.label_meta_data.config(text=self.obter_data_hora())
