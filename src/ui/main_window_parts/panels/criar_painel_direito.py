import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def criar_painel_direito(self) -> None:
        self.frame_direito = tk.Frame(self.frame_dashboard, bg=self.COR_FUNDO_APP)
        self.frame_direito.grid(row=0, column=2, sticky="nsew", padx=(6, 0), pady=(0, 6))
        self.frame_direito.grid_rowconfigure(0, weight=2)
        self.frame_direito.grid_rowconfigure(1, weight=2)
        self.frame_direito.grid_rowconfigure(2, weight=2)
        self.frame_direito.grid_rowconfigure(3, weight=2)
        self.frame_direito.grid_columnconfigure(0, weight=1)

        self.frame_imagem_teste = self.criar_card(self.frame_direito)
        self.frame_imagem_teste.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        self.frame_imagem_teste.grid_rowconfigure(1, weight=1)
        self.frame_imagem_teste.grid_columnconfigure(0, weight=1)
        self.criar_titulo_card(self.frame_imagem_teste, "Imagem de Teste - Canal V").grid(
            row=0,
            column=0,
            sticky="ew",
            padx=12,
            pady=(10, 6),
        )
        self.canvas_imagem_teste = tk.Canvas(
            self.frame_imagem_teste,
            bg="#020617",
            highlightthickness=1,
            highlightbackground=self.COR_BORDA,
        )
        self.canvas_imagem_teste.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.desenhar_placeholder(self.canvas_imagem_teste, "Imagem processada\nEtapa 2")

        self.frame_mascara = self.criar_card(self.frame_direito)
        self.frame_mascara.grid(row=1, column=0, sticky="nsew", pady=6)
        self.frame_mascara.grid_rowconfigure(1, weight=1)
        self.frame_mascara.grid_columnconfigure(0, weight=1)
        self.criar_titulo_card(self.frame_mascara, "Máscara / ROI selecionado").grid(
            row=0,
            column=0,
            sticky="ew",
            padx=12,
            pady=(10, 6),
        )
        self.canvas_mascara = tk.Canvas(
            self.frame_mascara,
            bg="#020617",
            highlightthickness=1,
            highlightbackground=self.COR_BORDA,
        )
        self.canvas_mascara.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.desenhar_placeholder(self.canvas_mascara, "Máscara visual\nEtapa 2")

        self.frame_roi_debug = self.criar_card(self.frame_direito)
        self.frame_roi_debug.grid(row=2, column=0, sticky="nsew", pady=6)
        self.frame_roi_debug.grid_rowconfigure(1, weight=1)
        self.frame_roi_debug.grid_columnconfigure(0, weight=1)
        self.criar_titulo_card(self.frame_roi_debug, "ROI debug ampliado").grid(
            row=0,
            column=0,
            sticky="ew",
            padx=12,
            pady=(10, 6),
        )
        self.canvas_roi_debug = tk.Canvas(
            self.frame_roi_debug,
            bg="#020617",
            highlightthickness=1,
            highlightbackground=self.COR_BORDA,
        )
        self.canvas_roi_debug.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.desenhar_placeholder(self.canvas_roi_debug, "ROI debug\nEtapa 2")

        self.frame_debug = self.criar_card(self.frame_direito)
        self.frame_debug.grid(row=3, column=0, sticky="nsew", pady=(6, 0))
        self.frame_debug.grid_rowconfigure(1, weight=1)
        self.frame_debug.grid_columnconfigure(0, weight=1)
        self.criar_titulo_card(self.frame_debug, "Debug técnico").grid(
            row=0,
            column=0,
            sticky="ew",
            padx=12,
            pady=(10, 6),
        )
        self.texto_resultados = tk.Text(
            self.frame_debug,
            bg="#020617",
            fg=self.COR_TEXTO_2,
            insertbackground=self.COR_TEXTO,
            font=("Consolas", 9),
            relief=tk.FLAT,
            wrap=tk.WORD,
        )
        self.texto_resultados.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
