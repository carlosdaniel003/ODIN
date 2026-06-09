import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def obter_data_hora(self) -> str:
        return datetime.now().strftime("%d/%m/%Y %H:%M:%S")
