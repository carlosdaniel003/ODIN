import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def evento_redimensionar_canvas_principal(self, evento=None) -> None:
        if self.imagem_canvas_original is None:
            return

        if self._redimensionamento_pendente is not None:
            self.root.after_cancel(self._redimensionamento_pendente)

        self._redimensionamento_pendente = self.root.after(80, self.redesenhar_imagem_principal_apos_redimensionamento)
