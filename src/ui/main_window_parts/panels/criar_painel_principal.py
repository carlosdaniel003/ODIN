
import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection


def criar_painel_principal(self) -> None:
    self.frame_painel_principal = self.criar_card(self.frame_dashboard)
    self.frame_painel_principal.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 6))
    self.frame_painel_principal.grid_rowconfigure(1, weight=1)
    self.frame_painel_principal.grid_columnconfigure(0, weight=1)

    self.criar_titulo_card(self.frame_painel_principal, "Imagem Principal (AO vivo)").grid(
        row=0,
        column=0,
        sticky="ew",
        padx=12,
        pady=(10, 6),
    )

    self.canvas = tk.Canvas(
        self.frame_painel_principal,
        bg="#020617",
        highlightthickness=1,
        highlightbackground=self.COR_BORDA,
        cursor="crosshair",
    )
    self.canvas.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))
    self.canvas.bind("<Button-1>", self.callbacks["evento_clique_esquerdo"])
    self.canvas.bind("<Configure>", self.evento_redimensionar_canvas_principal)
    self.canvas.bind("<Motion>", self.atualizar_lupa_canvas)
    self.canvas.bind("<Leave>", self.limpar_lupa_canvas)

    self.frame_parametros = tk.Frame(self.frame_painel_principal, bg=self.COR_CARD)
    self.frame_parametros.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 10))
    self.frame_parametros.grid_columnconfigure(0, weight=1)
    self.frame_parametros.grid_columnconfigure(1, weight=1)

    self.frame_parametros_analise = tk.Frame(self.frame_parametros, bg=self.COR_CARD_2)
    self.frame_parametros_analise.grid(row=0, column=0, sticky="nsew", padx=(0, 5))

    self.label_parametros = tk.Label(
        self.frame_parametros_analise,
        text=(
            "Parâmetros de análise\n"
            "Método: referência aceso/apagado\n"
            f"ROI: manual | raio {self.raio_atual_px}px\n"
            "Região: LEDs selecionados\n"
            "Modo: múltiplos LEDs por análise"
        ),
        font=("Consolas", 9),
        fg=self.COR_TEXTO_2,
        bg=self.COR_CARD_2,
        justify=tk.LEFT,
        anchor="w",
    )
    self.label_parametros.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

    self.frame_resumo = tk.Frame(self.frame_parametros, bg=self.COR_CARD_2)
    self.frame_resumo.grid(row=0, column=1, sticky="nsew", padx=(5, 0))

    self.label_resumo = tk.Label(
        self.frame_resumo,
        text=(
            "Resumo do LED\n"
            "Status: sem análise\n"
            "Confiança: --\n"
            "Posição: --\n"
            "Valor binário: --"
        ),
        font=("Consolas", 9),
        fg=self.COR_TEXTO_2,
        bg=self.COR_CARD_2,
        justify=tk.LEFT,
        anchor="w",
    )
    self.label_resumo.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)