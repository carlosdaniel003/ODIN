import tkinter as tk


def _criar_card_visual(
    self,
    parent,
    titulo: str,
    texto_placeholder: str,
):
    card = self.criar_card(parent)
    card.grid_rowconfigure(1, weight=1)
    card.grid_columnconfigure(0, weight=1)

    self.criar_titulo_card(
        card,
        titulo,
    ).grid(
        row=0,
        column=0,
        sticky="ew",
        padx=10,
        pady=(8, 5),
    )

    canvas = tk.Canvas(
        card,
        bg="#020617",
        highlightthickness=1,
        highlightbackground=self.COR_BORDA,
        bd=0,
        relief=tk.FLAT,
        width=180,
        height=150,
    )
    canvas.grid(
        row=1,
        column=0,
        sticky="nsew",
        padx=10,
        pady=(0, 10),
    )

    self.desenhar_placeholder(
        canvas,
        texto_placeholder,
    )

    return card, canvas


def criar_painel_direito(self) -> None:
    """
    Cria o painel lateral direito.

    Os três painéis visuais ficam lado a lado para que cada Canvas tenha
    altura suficiente para exibir o frame completo da câmera sem virar uma
    faixa horizontal minúscula. O debug técnico permanece abaixo deles,
    ocupando toda a largura.
    """
    self.frame_direito = tk.Frame(
        self.frame_dashboard,
        bg=self.COR_FUNDO_APP,
    )
    self.frame_direito.grid(
        row=0,
        column=2,
        sticky="nsew",
        padx=(6, 0),
        pady=(0, 6),
    )

    # Área superior para as três imagens e área inferior para o texto.
    self.frame_direito.grid_rowconfigure(
        0,
        weight=3,
        minsize=235,
    )
    self.frame_direito.grid_rowconfigure(
        1,
        weight=2,
        minsize=150,
    )
    self.frame_direito.grid_columnconfigure(
        0,
        weight=1,
    )

    self.frame_visuais_direita = tk.Frame(
        self.frame_direito,
        bg=self.COR_FUNDO_APP,
    )
    self.frame_visuais_direita.grid(
        row=0,
        column=0,
        sticky="nsew",
        pady=(0, 6),
    )
    self.frame_visuais_direita.grid_rowconfigure(
        0,
        weight=1,
    )

    for coluna in range(3):
        self.frame_visuais_direita.grid_columnconfigure(
            coluna,
            weight=1,
            uniform="cards_visuais_direita",
            minsize=150,
        )

    (
        self.frame_imagem_teste,
        self.canvas_imagem_teste,
    ) = _criar_card_visual(
        self,
        self.frame_visuais_direita,
        "Imagem de Teste - Canal V",
        "Imagem processada\nEtapa 2",
    )
    self.frame_imagem_teste.grid(
        row=0,
        column=0,
        sticky="nsew",
        padx=(0, 4),
    )

    (
        self.frame_mascara,
        self.canvas_mascara,
    ) = _criar_card_visual(
        self,
        self.frame_visuais_direita,
        "Máscara / ROI selecionado",
        "Máscara visual\nEtapa 2",
    )
    self.frame_mascara.grid(
        row=0,
        column=1,
        sticky="nsew",
        padx=4,
    )

    (
        self.frame_roi_debug,
        self.canvas_roi_debug,
    ) = _criar_card_visual(
        self,
        self.frame_visuais_direita,
        "ROI debug ampliado",
        "ROI debug\nEtapa 2",
    )
    self.frame_roi_debug.grid(
        row=0,
        column=2,
        sticky="nsew",
        padx=(4, 0),
    )

    self.frame_debug = self.criar_card(
        self.frame_direito
    )
    self.frame_debug.grid(
        row=1,
        column=0,
        sticky="nsew",
        pady=(6, 0),
    )
    self.frame_debug.grid_rowconfigure(
        1,
        weight=1,
    )
    self.frame_debug.grid_columnconfigure(
        0,
        weight=1,
    )

    self.criar_titulo_card(
        self.frame_debug,
        "Debug técnico",
    ).grid(
        row=0,
        column=0,
        sticky="ew",
        padx=12,
        pady=(10, 6),
    )

    # O height reduzido evita que o tamanho solicitado pelo Text roube
    # espaço dos três painéis de imagem.
    self.texto_resultados = tk.Text(
        self.frame_debug,
        bg="#020617",
        fg=self.COR_TEXTO_2,
        insertbackground=self.COR_TEXTO,
        font=("Consolas", 9),
        relief=tk.FLAT,
        wrap=tk.WORD,
        height=7,
        bd=0,
    )
    self.texto_resultados.grid(
        row=1,
        column=0,
        sticky="nsew",
        padx=12,
        pady=(0, 12),
    )
