import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def abrir_janela_configuracoes(self, salvar_resultados_analise: bool, callback_salvar) -> None:
        janela = tk.Toplevel(self.root)
        janela.title("Configurações - LumusPCI")
        janela.geometry("520x430")
        janela.resizable(False, False)
        janela.configure(bg=self.COR_CARD)
        janela.transient(self.root)
        janela.grab_set()

        frame = tk.Frame(janela, bg=self.COR_CARD)
        frame.pack(fill=tk.BOTH, expand=True, padx=18, pady=16)

        label_titulo = tk.Label(
            frame,
            text="Configurações do sistema",
            font=("Segoe UI", 15, "bold"),
            fg=self.COR_TEXTO,
            bg=self.COR_CARD,
            anchor="w",
        )
        label_titulo.pack(fill=tk.X, pady=(0, 10))

        frame_referencias = tk.Frame(frame, bg=self.COR_CARD_2, highlightthickness=1, highlightbackground=self.COR_BORDA)
        frame_referencias.pack(fill=tk.X, pady=(0, 14))

        tk.Label(
            frame_referencias,
            text="Referências fixas",
            font=("Segoe UI", 11, "bold"),
            fg=self.COR_TEXTO,
            bg=self.COR_CARD_2,
            anchor="w",
        ).pack(fill=tk.X, padx=12, pady=(10, 4))

        tk.Label(
            frame_referencias,
            text=(
                "Use esta área para configurar o banco de conhecimento do sistema: "
                "uma imagem de LED aceso e uma imagem de LED apagado. Ao carregar as duas, "
                "as referências são salvas automaticamente."
            ),
            font=("Segoe UI", 9),
            fg=self.COR_TEXTO_2,
            bg=self.COR_CARD_2,
            wraplength=460,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=12, pady=(0, 10))

        frame_botoes_ref = tk.Frame(frame_referencias, bg=self.COR_CARD_2)
        frame_botoes_ref.pack(fill=tk.X, padx=12, pady=(0, 12))

        def executar_e_fechar(nome_callback: str) -> None:
            janela.destroy()
            self.root.after(80, self.callbacks[nome_callback])

        self.criar_botao_config(frame_botoes_ref, "Ref. aceso", lambda: executar_e_fechar("carregar_referencia_led_aceso")).pack(side=tk.LEFT, padx=(0, 8))
        self.criar_botao_config(frame_botoes_ref, "Ref. apagado", lambda: executar_e_fechar("carregar_referencia_led_apagado")).pack(side=tk.LEFT, padx=(0, 8))
        self.criar_botao_config(frame_botoes_ref, "Carregar refs.", lambda: executar_e_fechar("carregar_configuracao")).pack(side=tk.LEFT, padx=(0, 8))

        label_descricao = tk.Label(
            frame,
            text=(
                "Controle se o LumusPCI deve gravar automaticamente os arquivos "
                "da análise em data/resultados. Com a opção desativada, as imagens "
                "continuam aparecendo na interface, mas não ocupam espaço em disco."
            ),
            font=("Segoe UI", 9),
            fg=self.COR_TEXTO_2,
            bg=self.COR_CARD,
            wraplength=470,
            justify=tk.LEFT,
            anchor="w",
        )
        label_descricao.pack(fill=tk.X, pady=(0, 14))

        valor_salvar_resultados = tk.BooleanVar(value=salvar_resultados_analise)

        check_salvar_resultados = tk.Checkbutton(
            frame,
            text="Salvar resultados da análise automaticamente",
            variable=valor_salvar_resultados,
            font=("Segoe UI", 10, "bold"),
            fg=self.COR_TEXTO,
            bg=self.COR_CARD,
            activebackground=self.COR_CARD,
            activeforeground=self.COR_TEXTO,
            selectcolor=self.COR_CARD_2,
            anchor="w",
        )
        check_salvar_resultados.pack(fill=tk.X, pady=(0, 16))

        frame_botoes = tk.Frame(frame, bg=self.COR_CARD)
        frame_botoes.pack(fill=tk.X, side=tk.BOTTOM, pady=(8, 0))

        def confirmar() -> None:
            callback_salvar(bool(valor_salvar_resultados.get()))
            janela.destroy()

        botao_cancelar = tk.Button(
            frame_botoes,
            text="Cancelar",
            command=janela.destroy,
            width=12,
            height=2,
            bg=self.COR_CARD_2,
            fg=self.COR_TEXTO_2,
            activebackground=self.COR_BORDA,
            activeforeground=self.COR_TEXTO,
            relief=tk.FLAT,
            bd=0,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        botao_cancelar.pack(side=tk.RIGHT, padx=(8, 0))

        botao_salvar = tk.Button(
            frame_botoes,
            text="Salvar",
            command=confirmar,
            width=12,
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
        botao_salvar.pack(side=tk.RIGHT)
