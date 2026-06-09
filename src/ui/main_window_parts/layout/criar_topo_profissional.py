import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def criar_topo_profissional(self) -> None:
        self.frame_topo = tk.Frame(self.frame_principal, bg=self.COR_TOPO, height=88)
        self.frame_topo.pack(fill=tk.X, padx=10, pady=(8, 4))
        self.frame_topo.pack_propagate(False)

        self.frame_marca = tk.Frame(self.frame_topo, bg=self.COR_TOPO, width=260)
        self.frame_marca.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 12))
        self.frame_marca.pack_propagate(False)

        self.label_icone = tk.Label(
        self.frame_marca,
        text="▌",
        font=("Segoe UI", 38, "bold"),
        fg=self.COR_VERDE_CLARO,
        bg=self.COR_TOPO,
)
        self.label_icone.pack(side=tk.LEFT, padx=(0, 10))

        self.frame_titulo = tk.Frame(self.frame_marca, bg=self.COR_TOPO)
        self.frame_titulo.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.label_titulo = tk.Label(
            self.frame_titulo,
            text="LumusPCI",
            font=("Segoe UI", 22, "bold"),
            fg=self.COR_TEXTO,
            bg=self.COR_TOPO,
            anchor="w",
        )
        self.label_titulo.pack(anchor="w", pady=(13, 0))

        self.label_subtitulo = tk.Label(
            self.frame_titulo,
            text="Análise Visual de LED",
            font=("Segoe UI", 9, "bold"),
            fg=self.COR_TEXTO_3,
            bg=self.COR_TOPO,
            anchor="w",
        )
        self.label_subtitulo.pack(anchor="w")

        self.frame_botoes = tk.Frame(self.frame_topo, bg=self.COR_TOPO)
        self.frame_botoes.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=18)

        self.criar_botao_topo(
            texto="Tela ao vivo",
            comando=None,
            ativo=False,
            cor_fundo="#0F3D24",
        ).pack(side=tk.LEFT, padx=4)

        self.criar_botao_topo(
            texto="Carregar imagem",
            comando=self.callbacks["carregar_imagem"],
            cor_fundo="#0B2742",
            cor_texto="#BAE6FD",
        ).pack(side=tk.LEFT, padx=4)

        self.botao_selecionar_leds = self.criar_botao_topo(
            texto="Selecionar LEDs",
            comando=self.callbacks["iniciar_selecao_led"],
        )
        self.botao_selecionar_leds.pack(side=tk.LEFT, padx=4)

        self.criar_botao_topo(
            texto="Analisar",
            comando=self.callbacks["analisar_led_selecionado"],
            cor_fundo="#0F3D24",
            cor_texto="#BBF7D0",
        ).pack(side=tk.LEFT, padx=4)

        self.criar_botao_topo(
            texto="Limpar seleção",
            comando=self.callbacks["limpar_tela"],
        ).pack(side=tk.LEFT, padx=4)

        self.frame_topo_direita = tk.Frame(self.frame_topo, bg=self.COR_TOPO, width=260)
        self.frame_topo_direita.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 10))
        self.frame_topo_direita.pack_propagate(False)

        self.botao_configuracoes = tk.Button(
            self.frame_topo_direita,
            text="⚙",
            command=self.callbacks["abrir_configuracoes"],
            font=("Segoe UI", 20),
            fg=self.COR_TEXTO_2,
            bg=self.COR_TOPO,
            activebackground=self.COR_CARD_2,
            activeforeground=self.COR_TEXTO,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
        )
        self.botao_configuracoes.pack(side=tk.RIGHT, padx=(8, 0), pady=18)

        self.botao_toggle_relogio = tk.Button(
            self.frame_topo_direita,
            text="Hora ON",
            command=self.alternar_visibilidade_relogio,
            width=9,
            height=2,
            bg="#0F3D24",
            fg="#BBF7D0",
            activebackground="#14532D",
            activeforeground=self.COR_TEXTO,
            relief=tk.FLAT,
            bd=0,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        self.botao_toggle_relogio.pack(side=tk.RIGHT, padx=(0, 8), pady=22)
