import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def criar_tabela_inferior(self) -> None:
        self.frame_tabela = self.criar_card(self.frame_dashboard)
        self.frame_tabela.grid(row=1, column=0, columnspan=3, sticky="nsew", padx=0, pady=(2, 0))
        self.frame_tabela.grid_rowconfigure(1, weight=1)
        self.frame_tabela.grid_columnconfigure(0, weight=1)

        self.criar_titulo_card(self.frame_tabela, "Histórico da sessão / LEDs analisados").grid(
            row=0,
            column=0,
            sticky="ew",
            padx=12,
            pady=(8, 4),
        )

        colunas = ("id", "posicao", "status", "confianca", "v_mean", "v_max", "glow", "observacao")
        self.tabela_historico = ttk.Treeview(
            self.frame_tabela,
            columns=colunas,
            show="headings",
            height=4,
        )

        titulos = {
            "id": "ID LED",
            "posicao": "Posição (x, y)",
            "status": "Status",
            "confianca": "Confiança",
            "v_mean": "v_mean",
            "v_max": "v_max",
            "glow": "Glow",
            "observacao": "Observação",
        }
        larguras = {
            "id": 110,
            "posicao": 130,
            "status": 100,
            "confianca": 100,
            "v_mean": 90,
            "v_max": 90,
            "glow": 90,
            "observacao": 520,
        }

        for coluna in colunas:
            self.tabela_historico.heading(coluna, text=titulos[coluna])
            self.tabela_historico.column(coluna, width=larguras[coluna], anchor=tk.CENTER)

        self.tabela_historico.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 10))
