import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def criar_card(self, parent) -> tk.Frame:
        return tk.Frame(
            parent,
            bg=self.COR_CARD,
            highlightthickness=1,
            highlightbackground=self.COR_BORDA,
        )
