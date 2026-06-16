import tkinter as tk


def criar_botao_config(self, parent, texto: str, comando) -> tk.Button:
    botao = tk.Button(
        parent,
        text=texto,
        command=comando,
        width=16,
        height=2,
        bg="#0B1626",
        fg=self.COR_TEXTO_2,
        activebackground="#102033",
        activeforeground=self.COR_TEXTO,
        relief=tk.FLAT,
        bd=0,
        font=("Segoe UI", 9, "bold"),
        cursor="hand2",
        padx=10,
    )

    def ao_entrar(_evento):
        botao.configure(
            bg="#102033",
            fg=self.COR_TEXTO,
        )

    def ao_sair(_evento):
        botao.configure(
            bg="#0B1626",
            fg=self.COR_TEXTO_2,
        )

    botao.bind("<Enter>", ao_entrar)
    botao.bind("<Leave>", ao_sair)
    return botao
