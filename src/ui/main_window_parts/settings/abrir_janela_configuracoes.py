import tkinter as tk
from tkinter import ttk

from config import (
    CAMERA_FORMATS,
    CAMERA_FPS_PRESETS,
    CAMERA_HEIGHT_MAX,
    CAMERA_HEIGHT_MIN,
    CAMERA_IMAGE_CONTROL_MAX,
    CAMERA_IMAGE_CONTROL_MIN,
    CAMERA_PAN_MAX,
    CAMERA_PAN_MIN,
    CAMERA_RESOLUTION_PRESETS,
    CAMERA_ROTATIONS,
    CAMERA_TILT_MAX,
    CAMERA_TILT_MIN,
    CAMERA_WIDTH_MAX,
    CAMERA_WIDTH_MIN,
    DEFAULT_CAMERA_SETTINGS,
    MAX_RADIUS_PX,
    MIN_RADIUS_PX,
)


def abrir_janela_configuracoes(
    self,
    salvar_resultados_analise: bool,
    callback_salvar,
    raio_atual_px: int = 15,
    configuracoes_camera: dict | None = None,
    camera_conectada: bool = False,
    status_controles_camera: dict | None = None,
) -> None:
    largura_preferida = 820
    altura_preferida = 860

    janela = tk.Toplevel(self.root)
    janela.title("Configurações - ODIN")
    janela.withdraw()
    janela.overrideredirect(False)
    janela.resizable(True, True)
    janela.configure(bg=self.COR_CARD)
    janela.minsize(680, 620)

    # Quando a janela principal está em fullscreen sem bordas, usar
    # transient pode fazer o Windows ocultar a moldura da janela filha.
    try:
        raiz_sem_bordas = bool(self.root.overrideredirect())
    except tk.TclError:
        raiz_sem_bordas = False

    if not raiz_sem_bordas:
        janela.transient(self.root)

    def fechar_janela(evento=None) -> str | None:
        try:
            janela.grab_release()
        except tk.TclError:
            pass

        if janela.winfo_exists():
            janela.destroy()

        if evento is not None:
            return "break"

        return None

    janela.protocol("WM_DELETE_WINDOW", fechar_janela)
    janela.bind("<Escape>", fechar_janela)
    janela.grab_set()

    self.root.update_idletasks()

    largura_root = self.root.winfo_width()
    altura_root = self.root.winfo_height()
    posicao_root_x = self.root.winfo_x()
    posicao_root_y = self.root.winfo_y()

    largura_tela = max(680, janela.winfo_screenwidth())
    altura_tela = max(620, janela.winfo_screenheight())

    largura_janela = min(
        largura_preferida,
        max(680, largura_tela - 80),
    )
    altura_janela = min(
        altura_preferida,
        max(620, altura_tela - 100),
    )

    posicao_janela_x = posicao_root_x + int(
        (largura_root - largura_janela) / 2
    )
    posicao_janela_y = posicao_root_y + int(
        (altura_root - altura_janela) / 2
    )

    posicao_janela_x = max(
        10,
        min(posicao_janela_x, largura_tela - largura_janela - 10),
    )
    posicao_janela_y = max(
        10,
        min(posicao_janela_y, altura_tela - altura_janela - 50),
    )

    janela.geometry(
        f"{largura_janela}x{altura_janela}+"
        f"{posicao_janela_x}+{posicao_janela_y}"
    )

    frame_raiz = tk.Frame(janela, bg=self.COR_CARD)
    frame_raiz.pack(fill=tk.BOTH, expand=True, padx=18, pady=16)

    # Cabeçalho visual ----------------------------------------------------
    frame_cabecalho = tk.Frame(
        frame_raiz,
        bg=self.COR_CARD_2,
        highlightthickness=1,
        highlightbackground=self.COR_BORDA,
    )
    frame_cabecalho.pack(fill=tk.X, pady=(0, 16))

    tk.Frame(
        frame_cabecalho,
        bg="#22C55E",
        width=5,
    ).pack(side=tk.LEFT, fill=tk.Y)

    frame_cabecalho_textos = tk.Frame(
        frame_cabecalho,
        bg=self.COR_CARD_2,
    )
    frame_cabecalho_textos.pack(
        side=tk.LEFT,
        fill=tk.BOTH,
        expand=True,
        padx=16,
        pady=14,
    )

    frame_cabecalho_linha = tk.Frame(
        frame_cabecalho_textos,
        bg=self.COR_CARD_2,
    )
    frame_cabecalho_linha.pack(fill=tk.X)

    tk.Label(
        frame_cabecalho_linha,
        text="Configurações do sistema",
        font=("Segoe UI", 17, "bold"),
        fg=self.COR_TEXTO,
        bg=self.COR_CARD_2,
        anchor="w",
    ).pack(side=tk.LEFT, fill=tk.X, expand=True)

    botao_fechar = tk.Button(
        frame_cabecalho_linha,
        text="✕",
        command=fechar_janela,
        width=3,
        bg=self.COR_CARD_2,
        fg=self.COR_TEXTO_3,
        activebackground="#7F1D1D",
        activeforeground="#FECACA",
        relief=tk.FLAT,
        bd=0,
        font=("Segoe UI Symbol", 10, "bold"),
        cursor="hand2",
        takefocus=True,
    )
    botao_fechar.pack(side=tk.RIGHT, padx=(10, 0))

    tk.Label(
        frame_cabecalho_linha,
        text="ODIN",
        font=("Segoe UI", 8, "bold"),
        fg="#BBF7D0",
        bg="#0F3D24",
        padx=10,
        pady=4,
    ).pack(side=tk.RIGHT)

    tk.Label(
        frame_cabecalho_textos,
        text=(
            "Ajuste referências, LEDs fixos, armazenamento e perfil da "
            "câmera sem alterar a tela principal."
        ),
        font=("Segoe UI", 9),
        fg=self.COR_TEXTO_2,
        bg=self.COR_CARD_2,
        anchor="w",
        justify=tk.LEFT,
    ).pack(fill=tk.X, pady=(5, 0))

    estilo = ttk.Style(janela)

    # O tema ttk é global para toda a aplicação. Não alteramos o tema aqui,
    # para que abrir Configurações não modifique a aparência da tela principal.
    janela.option_add(
        "*TCombobox*Listbox.background",
        "#020617",
    )
    janela.option_add(
        "*TCombobox*Listbox.foreground",
        self.COR_TEXTO,
    )
    janela.option_add(
        "*TCombobox*Listbox.selectBackground",
        "#0F3D24",
    )
    janela.option_add(
        "*TCombobox*Listbox.selectForeground",
        "#BBF7D0",
    )
    janela.option_add(
        "*TCombobox*Listbox.font",
        "Segoe UI 9",
    )

    estilo.configure(
        "Odin.TNotebook",
        background=self.COR_CARD,
        borderwidth=0,
        tabmargins=(0, 0, 0, 0),
    )
    estilo.configure(
        "Odin.TNotebook.Tab",
        background=self.COR_CARD_2,
        foreground=self.COR_TEXTO_2,
        padding=(24, 11),
        font=("Segoe UI", 9, "bold"),
        borderwidth=0,
    )
    estilo.map(
        "Odin.TNotebook.Tab",
        background=[
            ("selected", "#0F3D24"),
            ("active", "#102033"),
        ],
        foreground=[
            ("selected", "#BBF7D0"),
            ("active", self.COR_TEXTO),
        ],
    )

    estilo.configure(
        "Odin.TCombobox",
        fieldbackground="#020617",
        background=self.COR_CARD_2,
        foreground=self.COR_TEXTO,
        selectbackground="#0F3D24",
        selectforeground="#BBF7D0",
        arrowcolor=self.COR_TEXTO_2,
        bordercolor=self.COR_BORDA,
        lightcolor=self.COR_BORDA,
        darkcolor=self.COR_BORDA,
        padding=(8, 6),
        relief="flat",
    )
    estilo.map(
        "Odin.TCombobox",
        fieldbackground=[
            ("readonly", "#020617"),
            ("disabled", self.COR_CARD),
        ],
        foreground=[
            ("readonly", self.COR_TEXTO),
            ("disabled", self.COR_TEXTO_3),
        ],
        background=[
            ("readonly", self.COR_CARD_2),
            ("active", "#102033"),
            ("disabled", self.COR_CARD),
        ],
        arrowcolor=[
            ("readonly", self.COR_TEXTO_2),
            ("disabled", self.COR_TEXTO_3),
        ],
        bordercolor=[
            ("focus", self.COR_AZUL),
            ("readonly", self.COR_BORDA),
        ],
    )

    notebook = ttk.Notebook(
        frame_raiz,
        style="Odin.TNotebook",
    )
    notebook.pack(fill=tk.BOTH, expand=True)

    aba_sistema = tk.Frame(notebook, bg=self.COR_CARD)
    aba_camera = tk.Frame(notebook, bg=self.COR_CARD)

    notebook.add(aba_sistema, text="Sistema")
    notebook.add(aba_camera, text="Câmera")

    def criar_area_rolavel(parent):
        container = tk.Frame(parent, bg=self.COR_CARD)
        container.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        canvas = tk.Canvas(
            container,
            bg=self.COR_CARD,
            highlightthickness=0,
            bd=0,
        )
        scrollbar = tk.Scrollbar(
            container,
            orient=tk.VERTICAL,
            command=canvas.yview,
        )
        conteudo = tk.Frame(canvas, bg=self.COR_CARD)

        janela_conteudo = canvas.create_window(
            (0, 0),
            window=conteudo,
            anchor=tk.NW,
        )
        canvas.configure(yscrollcommand=scrollbar.set)

        def atualizar_regiao(_evento=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def ajustar_largura(evento):
            canvas.itemconfigure(
                janela_conteudo,
                width=evento.width,
            )

        conteudo.bind("<Configure>", atualizar_regiao)
        canvas.bind("<Configure>", ajustar_largura)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        return conteudo

    conteudo_sistema = criar_area_rolavel(aba_sistema)
    conteudo_camera = criar_area_rolavel(aba_camera)

    def criar_card(parent, titulo: str):
        card = tk.Frame(
            parent,
            bg=self.COR_CARD_2,
            highlightthickness=1,
            highlightbackground=self.COR_BORDA,
        )
        card.pack(fill=tk.X, padx=(0, 8), pady=(0, 14))

        # Faixa superior cria hierarquia visual sem destoar do tema escuro.
        tk.Frame(
            card,
            bg="#22C55E",
            height=3,
        ).pack(fill=tk.X)

        tk.Label(
            card,
            text=titulo,
            font=("Segoe UI", 11, "bold"),
            fg=self.COR_TEXTO,
            bg=self.COR_CARD_2,
            anchor="w",
        ).pack(fill=tk.X, padx=14, pady=(12, 6))

        tk.Frame(
            card,
            bg="#172033",
            height=1,
        ).pack(fill=tk.X, padx=14, pady=(0, 10))

        corpo = tk.Frame(card, bg=self.COR_CARD_2)
        corpo.pack(fill=tk.X, padx=2, pady=(0, 2))

        return corpo

    def executar_e_fechar(nome_callback: str) -> None:
        fechar_janela()
        self.root.after(80, self.callbacks[nome_callback])

    # Aba Sistema ---------------------------------------------------------
    frame_referencias = criar_card(
        conteudo_sistema,
        "Referências fixas",
    )

    tk.Label(
        frame_referencias,
        text=(
            "Configure uma imagem de LED aceso e outra de LED apagado. "
            "Ao carregar as duas referências, elas são salvas "
            "automaticamente."
        ),
        font=("Segoe UI", 9),
        fg=self.COR_TEXTO_2,
        bg=self.COR_CARD_2,
        wraplength=600,
        justify=tk.LEFT,
        anchor="w",
    ).pack(fill=tk.X, padx=12, pady=(0, 10))

    frame_botoes_ref = tk.Frame(
        frame_referencias,
        bg=self.COR_CARD_2,
    )
    frame_botoes_ref.pack(fill=tk.X, padx=12, pady=(0, 12))

    self.criar_botao_config(
        frame_botoes_ref,
        "Ref. aceso",
        lambda: executar_e_fechar(
            "carregar_referencia_led_aceso"
        ),
    ).pack(side=tk.LEFT, padx=(0, 8))

    self.criar_botao_config(
        frame_botoes_ref,
        "Ref. apagado",
        lambda: executar_e_fechar(
            "carregar_referencia_led_apagado"
        ),
    ).pack(side=tk.LEFT, padx=(0, 8))

    self.criar_botao_config(
        frame_botoes_ref,
        "Carregar refs.",
        lambda: executar_e_fechar("carregar_configuracao"),
    ).pack(side=tk.LEFT)

    frame_leds_fixos = criar_card(
        conteudo_sistema,
        "LEDs fixos",
    )

    tk.Label(
        frame_leds_fixos,
        text=(
            "Configure posições fixas para inspeções repetitivas. "
            "Marque os LEDs na imagem e salve as posições."
        ),
        font=("Segoe UI", 9),
        fg=self.COR_TEXTO_2,
        bg=self.COR_CARD_2,
        wraplength=600,
        justify=tk.LEFT,
        anchor="w",
    ).pack(fill=tk.X, padx=12, pady=(0, 10))

    frame_botoes_leds = tk.Frame(
        frame_leds_fixos,
        bg=self.COR_CARD_2,
    )
    frame_botoes_leds.pack(fill=tk.X, padx=12, pady=(0, 12))

    self.criar_botao_config(
        frame_botoes_leds,
        "Configurar LEDs",
        lambda: executar_e_fechar("configurar_leds_fixos"),
    ).pack(side=tk.LEFT, padx=(0, 8))

    self.criar_botao_config(
        frame_botoes_leds,
        "Salvar LEDs",
        lambda: executar_e_fechar("salvar_leds_fixos"),
    ).pack(side=tk.LEFT)

    frame_raio = criar_card(
        conteudo_sistema,
        "Raio de seleção dos LEDs",
    )

    tk.Label(
        frame_raio,
        text=(
            "Define o tamanho do ROI circular usado ao selecionar "
            f"LEDs. Limite: {MIN_RADIUS_PX}px a {MAX_RADIUS_PX}px."
        ),
        font=("Segoe UI", 9),
        fg=self.COR_TEXTO_2,
        bg=self.COR_CARD_2,
        wraplength=600,
        justify=tk.LEFT,
        anchor="w",
    ).pack(fill=tk.X, padx=12, pady=(0, 8))

    valor_raio_led = tk.IntVar(
        value=min(
            MAX_RADIUS_PX,
            max(MIN_RADIUS_PX, int(raio_atual_px)),
        )
    )

    frame_controle_raio = tk.Frame(
        frame_raio,
        bg=self.COR_CARD_2,
    )
    frame_controle_raio.pack(
        fill=tk.X,
        padx=12,
        pady=(0, 12),
    )

    tk.Label(
        frame_controle_raio,
        text="Raio:",
        font=("Segoe UI", 10, "bold"),
        fg=self.COR_TEXTO,
        bg=self.COR_CARD_2,
    ).pack(side=tk.LEFT, padx=(0, 8))

    tk.Spinbox(
        frame_controle_raio,
        from_=MIN_RADIUS_PX,
        to=MAX_RADIUS_PX,
        increment=1,
        textvariable=valor_raio_led,
        width=6,
        font=("Segoe UI", 10, "bold"),
        bg="#020617",
        fg=self.COR_TEXTO,
        buttonbackground=self.COR_CARD_2,
        disabledbackground=self.COR_CARD,
        disabledforeground=self.COR_TEXTO_3,
        readonlybackground="#020617",
        relief=tk.FLAT,
        bd=2,
        justify=tk.CENTER,
    ).pack(side=tk.LEFT, padx=(0, 8))

    tk.Label(
        frame_controle_raio,
        text="px",
        font=("Segoe UI", 10, "bold"),
        fg=self.COR_TEXTO_2,
        bg=self.COR_CARD_2,
    ).pack(side=tk.LEFT)

    frame_armazenamento = criar_card(
        conteudo_sistema,
        "Armazenamento",
    )

    tk.Label(
        frame_armazenamento,
        text=(
            "Com a opção desativada, as imagens continuam aparecendo "
            "na interface, mas não são gravadas em data/resultados."
        ),
        font=("Segoe UI", 9),
        fg=self.COR_TEXTO_2,
        bg=self.COR_CARD_2,
        wraplength=600,
        justify=tk.LEFT,
        anchor="w",
    ).pack(fill=tk.X, padx=12, pady=(0, 8))

    valor_salvar_resultados = tk.BooleanVar(
        value=salvar_resultados_analise
    )

    tk.Checkbutton(
        frame_armazenamento,
        text="Salvar resultados da análise automaticamente",
        variable=valor_salvar_resultados,
        font=("Segoe UI", 10, "bold"),
        fg=self.COR_TEXTO,
        bg=self.COR_CARD_2,
        activebackground=self.COR_CARD_2,
        activeforeground=self.COR_TEXTO,
        selectcolor=self.COR_CARD,
        anchor="w",
    ).pack(fill=tk.X, padx=12, pady=(0, 12))

    # Aba Câmera ----------------------------------------------------------
    configuracoes_camera = (
        configuracoes_camera
        if isinstance(configuracoes_camera, dict)
        else {}
    )
    status_controles_camera = (
        status_controles_camera
        if isinstance(status_controles_camera, dict)
        else {}
    )

    def obter_config(nome: str):
        return configuracoes_camera.get(
            nome,
            DEFAULT_CAMERA_SETTINGS.get(nome),
        )

    frame_estado_camera = criar_card(
        conteudo_camera,
        "Estado da câmera",
    )

    texto_estado = (
        "Câmera conectada. Os ajustes serão enviados ao driver "
        "quando você clicar em Salvar."
        if camera_conectada
        else
        "Câmera desligada ou reconectando. Os ajustes serão salvos "
        "e aplicados automaticamente na próxima conexão."
    )
    cor_estado = "#BBF7D0" if camera_conectada else "#FDE68A"

    tk.Label(
        frame_estado_camera,
        text=texto_estado,
        font=("Segoe UI", 9, "bold"),
        fg=cor_estado,
        bg=self.COR_CARD_2,
        wraplength=600,
        justify=tk.LEFT,
        anchor="w",
    ).pack(fill=tk.X, padx=12, pady=(0, 12))



    frame_perfil_camera = criar_card(
        conteudo_camera,
        "Perfil de captura",
    )

    tk.Label(
        frame_perfil_camera,
        text=(
            "Define a resolução, FPS e formato solicitados ao driver. "
            "A resolução real entregue pela câmera é detectada durante a conexão."
        ),
        font=("Segoe UI", 9),
        fg=self.COR_TEXTO_2,
        bg=self.COR_CARD_2,
        wraplength=600,
        justify=tk.LEFT,
        anchor="w",
    ).pack(fill=tk.X, padx=12, pady=(0, 8))

    mapa_label_para_resolucao = {
        dados["label"]: modo
        for modo, dados in CAMERA_RESOLUTION_PRESETS.items()
    }
    mapa_resolucao_para_label = {
        modo: dados["label"]
        for modo, dados in CAMERA_RESOLUTION_PRESETS.items()
    }

    modo_resolucao_atual = str(
        obter_config("resolution_mode") or "auto"
    )

    if modo_resolucao_atual not in CAMERA_RESOLUTION_PRESETS:
        modo_resolucao_atual = "auto"

    valor_resolucao = tk.StringVar(
        value=mapa_resolucao_para_label[modo_resolucao_atual]
    )
    valor_largura_camera = tk.IntVar(
        value=int(obter_config("width") or DEFAULT_CAMERA_SETTINGS["width"])
    )
    valor_altura_camera = tk.IntVar(
        value=int(obter_config("height") or DEFAULT_CAMERA_SETTINGS["height"])
    )

    fps_atual = int(obter_config("fps") or 0)
    fps_modo_atual = str(obter_config("fps_mode") or "manual").lower()
    valor_fps_camera = tk.StringVar(
        value="Automático" if fps_modo_atual == "auto" or fps_atual <= 0 else str(fps_atual)
    )
    valor_formato_camera = tk.StringVar(
        value=str(obter_config("format") or DEFAULT_CAMERA_SETTINGS["format"]).upper()
    )

    def criar_linha_combo(parent, titulo: str):
        linha = tk.Frame(parent, bg=self.COR_CARD_2)
        linha.pack(fill=tk.X, padx=12, pady=(4, 8))
        tk.Label(
            linha,
            text=titulo,
            width=14,
            font=("Segoe UI", 9, "bold"),
            fg=self.COR_TEXTO,
            bg=self.COR_CARD_2,
            anchor="w",
        ).pack(side=tk.LEFT)
        return linha

    linha_resolucao = criar_linha_combo(frame_perfil_camera, "Resolução:")
    combo_resolucao = ttk.Combobox(
        linha_resolucao,
        textvariable=valor_resolucao,
        values=list(mapa_label_para_resolucao.keys()),
        state="readonly",
        width=24,
        font=("Segoe UI", 9, "bold"),
        style="Odin.TCombobox",
    )
    combo_resolucao.pack(side=tk.LEFT, fill=tk.X, expand=True)

    linha_personalizada = tk.Frame(frame_perfil_camera, bg=self.COR_CARD_2)
    linha_personalizada.pack(fill=tk.X, padx=12, pady=(0, 8))

    tk.Label(
        linha_personalizada,
        text="Personalizada:",
        width=14,
        font=("Segoe UI", 9, "bold"),
        fg=self.COR_TEXTO,
        bg=self.COR_CARD_2,
        anchor="w",
    ).pack(side=tk.LEFT)

    spin_largura = tk.Spinbox(
        linha_personalizada,
        from_=CAMERA_WIDTH_MIN,
        to=CAMERA_WIDTH_MAX,
        increment=10,
        textvariable=valor_largura_camera,
        width=8,
        font=("Segoe UI", 9, "bold"),
        bg="#020617",
        fg=self.COR_TEXTO,
        buttonbackground=self.COR_CARD_2,
        disabledbackground=self.COR_CARD,
        disabledforeground=self.COR_TEXTO_3,
        readonlybackground="#020617",
        relief=tk.FLAT,
        bd=2,
        justify=tk.CENTER,
    )
    spin_largura.pack(side=tk.LEFT, padx=(0, 6))

    tk.Label(
        linha_personalizada,
        text="x",
        font=("Segoe UI", 9, "bold"),
        fg=self.COR_TEXTO_2,
        bg=self.COR_CARD_2,
    ).pack(side=tk.LEFT, padx=(0, 6))

    spin_altura = tk.Spinbox(
        linha_personalizada,
        from_=CAMERA_HEIGHT_MIN,
        to=CAMERA_HEIGHT_MAX,
        increment=10,
        textvariable=valor_altura_camera,
        width=8,
        font=("Segoe UI", 9, "bold"),
        bg="#020617",
        fg=self.COR_TEXTO,
        buttonbackground=self.COR_CARD_2,
        disabledbackground=self.COR_CARD,
        disabledforeground=self.COR_TEXTO_3,
        readonlybackground="#020617",
        relief=tk.FLAT,
        bd=2,
        justify=tk.CENTER,
    )
    spin_altura.pack(side=tk.LEFT)

    linha_fps = criar_linha_combo(frame_perfil_camera, "FPS:")
    ttk.Combobox(
        linha_fps,
        textvariable=valor_fps_camera,
        values=list(CAMERA_FPS_PRESETS),
        state="readonly",
        width=16,
        font=("Segoe UI", 9, "bold"),
        style="Odin.TCombobox",
    ).pack(side=tk.LEFT)

    linha_formato = criar_linha_combo(frame_perfil_camera, "Formato:")
    ttk.Combobox(
        linha_formato,
        textvariable=valor_formato_camera,
        values=list(CAMERA_FORMATS),
        state="readonly",
        width=16,
        font=("Segoe UI", 9, "bold"),
        style="Odin.TCombobox",
    ).pack(side=tk.LEFT)

    def atualizar_campos_resolucao(*_args):
        modo = mapa_label_para_resolucao.get(valor_resolucao.get(), "auto")
        estado = tk.NORMAL if modo == "custom" else tk.DISABLED
        spin_largura.config(state=estado)
        spin_altura.config(state=estado)

        if modo != "custom":
            preset = CAMERA_RESOLUTION_PRESETS[modo]
            valor_largura_camera.set(int(preset["width"]))
            valor_altura_camera.set(int(preset["height"]))

    combo_resolucao.bind("<<ComboboxSelected>>", atualizar_campos_resolucao)
    atualizar_campos_resolucao()

    frame_controles = criar_card(
        conteudo_camera,
        "Controles de imagem e posição",
    )

    tk.Label(
        frame_controles,
        text=(
            "Panorâmica, inclinação, contraste, nitidez e saturação "
            "dependem do suporte do hardware e do driver USB. "
            "Desative o ajuste manual para manter o padrão da câmera."
        ),
        font=("Segoe UI", 9),
        fg=self.COR_TEXTO_2,
        bg=self.COR_CARD_2,
        wraplength=600,
        justify=tk.LEFT,
        anchor="w",
    ).pack(fill=tk.X, padx=12, pady=(0, 8))

    variaveis_camera = {}

    nomes_status = {
        "aplicado": "Aplicado",
        "nao_suportado": "Não suportado",
        "padrao_driver": "Padrão do driver",
        "aguardando_camera": "Aguardando câmera",
        "aplicado_software": "Aplicado por software",
    }

    def criar_controle_camera(
        nome_chave: str,
        titulo: str,
        minimo: int,
        maximo: int,
        descricao: str,
    ) -> None:
        linha = tk.Frame(frame_controles, bg=self.COR_CARD_2)
        linha.pack(fill=tk.X, padx=12, pady=(5, 8))

        habilitado = tk.BooleanVar(
            value=bool(obter_config(f"{nome_chave}_enabled"))
        )
        valor = tk.DoubleVar(
            value=float(obter_config(nome_chave))
        )
        variaveis_camera[f"{nome_chave}_enabled"] = habilitado
        variaveis_camera[nome_chave] = valor

        topo_linha = tk.Frame(linha, bg=self.COR_CARD_2)
        topo_linha.pack(fill=tk.X)

        tk.Checkbutton(
            topo_linha,
            text=titulo,
            variable=habilitado,
            font=("Segoe UI", 9, "bold"),
            fg=self.COR_TEXTO,
            bg=self.COR_CARD_2,
            activebackground=self.COR_CARD_2,
            activeforeground=self.COR_TEXTO,
            selectcolor=self.COR_CARD,
            anchor="w",
        ).pack(side=tk.LEFT)

        status_atual = status_controles_camera.get(
            nome_chave,
            {},
        ).get("status", "aguardando_camera")

        tk.Label(
            topo_linha,
            text=nomes_status.get(status_atual, status_atual),
            font=("Segoe UI", 8, "bold"),
            fg=self.COR_TEXTO_3,
            bg=self.COR_CARD_2,
        ).pack(side=tk.RIGHT)

        frame_ajuste = tk.Frame(linha, bg=self.COR_CARD_2)
        frame_ajuste.pack(fill=tk.X, pady=(3, 0))

        label_valor = tk.Label(
            frame_ajuste,
            text=str(int(round(valor.get()))),
            width=6,
            font=("Segoe UI", 9, "bold"),
            fg=self.COR_AZUL,
            bg=self.COR_CARD_2,
        )
        label_valor.pack(side=tk.RIGHT, padx=(8, 0))

        escala = tk.Scale(
            frame_ajuste,
            from_=minimo,
            to=maximo,
            orient=tk.HORIZONTAL,
            resolution=1,
            showvalue=False,
            variable=valor,
            bg=self.COR_CARD_2,
            fg=self.COR_TEXTO,
            activebackground=self.COR_AZUL,
            troughcolor="#020617",
            highlightthickness=0,
            bd=0,
            command=lambda valor_texto, label=label_valor: (
                label.config(
                    text=str(int(round(float(valor_texto))))
                )
            ),
        )
        escala.pack(side=tk.LEFT, fill=tk.X, expand=True)

        def atualizar_estado_controle(*_args):
            estado = tk.NORMAL if habilitado.get() else tk.DISABLED
            escala.config(state=estado)
            label_valor.config(
                fg=self.COR_AZUL
                if habilitado.get()
                else self.COR_TEXTO_3
            )

        habilitado.trace_add(
            "write",
            atualizar_estado_controle,
        )
        atualizar_estado_controle()

        tk.Label(
            linha,
            text=descricao,
            font=("Segoe UI", 8),
            fg=self.COR_TEXTO_3,
            bg=self.COR_CARD_2,
            anchor="w",
            justify=tk.LEFT,
        ).pack(fill=tk.X)

    criar_controle_camera(
        "pan",
        "Panorâmica manual",
        CAMERA_PAN_MIN,
        CAMERA_PAN_MAX,
        "Movimento horizontal. O valor é interpretado pelo driver.",
    )
    criar_controle_camera(
        "tilt",
        "Inclinação manual",
        CAMERA_TILT_MIN,
        CAMERA_TILT_MAX,
        "Movimento vertical. O valor é interpretado pelo driver.",
    )
    criar_controle_camera(
        "contrast",
        "Contraste manual",
        CAMERA_IMAGE_CONTROL_MIN,
        CAMERA_IMAGE_CONTROL_MAX,
        "Aumenta ou reduz a diferença entre áreas claras e escuras.",
    )
    criar_controle_camera(
        "sharpness",
        "Nitidez manual",
        CAMERA_IMAGE_CONTROL_MIN,
        CAMERA_IMAGE_CONTROL_MAX,
        "Ajusta a nitidez fornecida pelo hardware da câmera.",
    )
    criar_controle_camera(
        "saturation",
        "Saturação manual",
        CAMERA_IMAGE_CONTROL_MIN,
        CAMERA_IMAGE_CONTROL_MAX,
        "Ajusta a intensidade das cores fornecida pelo driver.",
    )

    frame_rotacao = criar_card(
        conteudo_camera,
        "Rotação da imagem",
    )

    tk.Label(
        frame_rotacao,
        text=(
            "A rotação é realizada pelo ODIN e funciona mesmo "
            "quando o driver não oferece esse controle."
        ),
        font=("Segoe UI", 9),
        fg=self.COR_TEXTO_2,
        bg=self.COR_CARD_2,
        wraplength=600,
        justify=tk.LEFT,
        anchor="w",
    ).pack(fill=tk.X, padx=12, pady=(0, 8))

    valor_rotacao = tk.StringVar(
        value=f"{int(obter_config('rotation'))}°"
    )

    combo_rotacao = ttk.Combobox(
        frame_rotacao,
        textvariable=valor_rotacao,
        values=[f"{angulo}°" for angulo in CAMERA_ROTATIONS],
        state="readonly",
        width=12,
        font=("Segoe UI", 10, "bold"),
        style="Odin.TCombobox",
    )
    combo_rotacao.pack(
        anchor="w",
        padx=12,
        pady=(0, 8),
    )

    tk.Label(
        frame_rotacao,
        text=(
            "Ao alterar a rotação, as posições fixas dos LEDs podem "
            "precisar ser configuradas novamente para a nova orientação."
        ),
        font=("Segoe UI", 8),
        fg="#FDE68A",
        bg=self.COR_CARD_2,
        wraplength=600,
        justify=tk.LEFT,
        anchor="w",
    ).pack(fill=tk.X, padx=12, pady=(0, 12))

    def restaurar_camera() -> None:
        for nome in (
            "pan",
            "tilt",
            "contrast",
            "sharpness",
            "saturation",
        ):
            variaveis_camera[f"{nome}_enabled"].set(False)
            variaveis_camera[nome].set(
                float(DEFAULT_CAMERA_SETTINGS[nome])
            )

        valor_resolucao.set(
            mapa_resolucao_para_label[
                DEFAULT_CAMERA_SETTINGS["resolution_mode"]
            ]
        )
        valor_largura_camera.set(int(DEFAULT_CAMERA_SETTINGS["width"]))
        valor_altura_camera.set(int(DEFAULT_CAMERA_SETTINGS["height"]))
        valor_fps_camera.set(
            "Automático"
            if str(DEFAULT_CAMERA_SETTINGS["fps_mode"]).lower() == "auto"
            else str(int(DEFAULT_CAMERA_SETTINGS["fps"]))
        )
        valor_formato_camera.set(str(DEFAULT_CAMERA_SETTINGS["format"]).upper())
        atualizar_campos_resolucao()

        valor_rotacao.set(
            f"{int(DEFAULT_CAMERA_SETTINGS['rotation'])}°"
        )

    self.criar_botao_config(
        conteudo_camera,
        "Restaurar padrões da câmera",
        restaurar_camera,
    ).pack(anchor="w", padx=2, pady=(0, 14))

    # Botões gerais -------------------------------------------------------
    frame_rodape = tk.Frame(frame_raiz, bg=self.COR_CARD)
    frame_rodape.pack(fill=tk.X, pady=(14, 0))

    tk.Label(
        frame_rodape,
        text="As alterações serão salvas no arquivo de configuração de ODIN.",
        font=("Segoe UI", 8),
        fg=self.COR_TEXTO_3,
        bg=self.COR_CARD,
        anchor="w",
    ).pack(side=tk.LEFT, fill=tk.X, expand=True)

    frame_botoes = tk.Frame(frame_rodape, bg=self.COR_CARD)
    frame_botoes.pack(side=tk.RIGHT)

    def confirmar() -> None:
        try:
            raio_configurado_px = int(valor_raio_led.get())
        except (TypeError, ValueError):
            raio_configurado_px = MAX_RADIUS_PX

        raio_configurado_px = min(
            MAX_RADIUS_PX,
            max(MIN_RADIUS_PX, raio_configurado_px),
        )

        resolucao_modo = mapa_label_para_resolucao.get(
            valor_resolucao.get(),
            "auto",
        )

        try:
            largura_camera = int(valor_largura_camera.get())
        except (TypeError, ValueError):
            largura_camera = int(DEFAULT_CAMERA_SETTINGS["width"])

        try:
            altura_camera = int(valor_altura_camera.get())
        except (TypeError, ValueError):
            altura_camera = int(DEFAULT_CAMERA_SETTINGS["height"])

        fps_texto = valor_fps_camera.get()
        fps_mode = "auto" if fps_texto == "Automático" else "manual"

        try:
            fps_camera = 0 if fps_mode == "auto" else int(fps_texto)
        except (TypeError, ValueError):
            fps_camera = int(DEFAULT_CAMERA_SETTINGS["fps"])

        configuracoes_camera_salvar = {
            "resolution_mode": resolucao_modo,
            "width": largura_camera,
            "height": altura_camera,
            "fps_mode": fps_mode,
            "fps": fps_camera,
            "format": str(valor_formato_camera.get()).upper(),
            "pan_enabled": bool(
                variaveis_camera["pan_enabled"].get()
            ),
            "pan": float(variaveis_camera["pan"].get()),
            "tilt_enabled": bool(
                variaveis_camera["tilt_enabled"].get()
            ),
            "tilt": float(variaveis_camera["tilt"].get()),
            "contrast_enabled": bool(
                variaveis_camera["contrast_enabled"].get()
            ),
            "contrast": float(
                variaveis_camera["contrast"].get()
            ),
            "sharpness_enabled": bool(
                variaveis_camera["sharpness_enabled"].get()
            ),
            "sharpness": float(
                variaveis_camera["sharpness"].get()
            ),
            "saturation_enabled": bool(
                variaveis_camera["saturation_enabled"].get()
            ),
            "saturation": float(
                variaveis_camera["saturation"].get()
            ),
            "rotation": int(
                valor_rotacao.get().replace("°", "")
            ),
        }

        callback_salvar(
            bool(valor_salvar_resultados.get()),
            raio_configurado_px,
            configuracoes_camera_salvar,
        )
        fechar_janela()

    tk.Button(
        frame_botoes,
        text="Cancelar",
        command=fechar_janela,
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
    ).pack(side=tk.RIGHT, padx=(8, 0))

    tk.Button(
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
    ).pack(side=tk.RIGHT)

    janela.bind(
        "<Control-Return>",
        lambda _evento: confirmar(),
    )

    janela.update_idletasks()
    janela.deiconify()
    janela.lift()
    janela.focus_force()
