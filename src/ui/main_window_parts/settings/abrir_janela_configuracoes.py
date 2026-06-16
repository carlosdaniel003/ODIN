import tkinter as tk
from tkinter import ttk

from config import (
    CAMERA_IMAGE_CONTROL_MAX,
    CAMERA_IMAGE_CONTROL_MIN,
    CAMERA_PAN_MAX,
    CAMERA_PAN_MIN,
    CAMERA_ROTATIONS,
    CAMERA_TILT_MAX,
    CAMERA_TILT_MIN,
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
    largura_janela = 680
    altura_janela = 780

    janela = tk.Toplevel(self.root)
    janela.title("Configurações - LumusPCI")
    janela.withdraw()
    janela.resizable(False, False)
    janela.configure(bg=self.COR_CARD)
    janela.transient(self.root)
    janela.grab_set()

    self.root.update_idletasks()

    largura_root = self.root.winfo_width()
    altura_root = self.root.winfo_height()
    posicao_root_x = self.root.winfo_x()
    posicao_root_y = self.root.winfo_y()

    posicao_janela_x = posicao_root_x + int(
        (largura_root - largura_janela) / 2
    )
    posicao_janela_y = posicao_root_y + int(
        (altura_root - altura_janela) / 2
    )

    janela.geometry(
        f"{largura_janela}x{altura_janela}+"
        f"{posicao_janela_x}+{posicao_janela_y}"
    )

    frame_raiz = tk.Frame(janela, bg=self.COR_CARD)
    frame_raiz.pack(fill=tk.BOTH, expand=True, padx=18, pady=16)

    tk.Label(
        frame_raiz,
        text="Configurações do sistema",
        font=("Segoe UI", 15, "bold"),
        fg=self.COR_TEXTO,
        bg=self.COR_CARD,
        anchor="w",
    ).pack(fill=tk.X, pady=(0, 10))

    estilo = ttk.Style(janela)

    try:
        estilo.theme_use("clam")
    except tk.TclError:
        pass

    estilo.configure(
        "Lumus.TNotebook",
        background=self.COR_CARD,
        borderwidth=0,
    )
    estilo.configure(
        "Lumus.TNotebook.Tab",
        background=self.COR_CARD_2,
        foreground=self.COR_TEXTO_2,
        padding=(18, 9),
        font=("Segoe UI", 9, "bold"),
        borderwidth=0,
    )
    estilo.map(
        "Lumus.TNotebook.Tab",
        background=[("selected", "#0F3D24")],
        foreground=[("selected", "#BBF7D0")],
    )

    notebook = ttk.Notebook(
        frame_raiz,
        style="Lumus.TNotebook",
    )
    notebook.pack(fill=tk.BOTH, expand=True)

    aba_sistema = tk.Frame(notebook, bg=self.COR_CARD)
    aba_camera = tk.Frame(notebook, bg=self.COR_CARD)

    notebook.add(aba_sistema, text="Sistema")
    notebook.add(aba_camera, text="Câmera")

    def criar_area_rolavel(parent):
        container = tk.Frame(parent, bg=self.COR_CARD)
        container.pack(fill=tk.BOTH, expand=True)

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
        card.pack(fill=tk.X, padx=(0, 6), pady=(0, 12))

        tk.Label(
            card,
            text=titulo,
            font=("Segoe UI", 11, "bold"),
            fg=self.COR_TEXTO,
            bg=self.COR_CARD_2,
            anchor="w",
        ).pack(fill=tk.X, padx=12, pady=(10, 4))

        return card

    def executar_e_fechar(nome_callback: str) -> None:
        janela.destroy()
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
            DEFAULT_CAMERA_SETTINGS[nome],
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
            "A rotação é realizada pelo LumusPCI e funciona mesmo "
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

        valor_rotacao.set(
            f"{int(DEFAULT_CAMERA_SETTINGS['rotation'])}°"
        )

    self.criar_botao_config(
        conteudo_camera,
        "Restaurar padrões da câmera",
        restaurar_camera,
    ).pack(anchor="w", padx=2, pady=(0, 14))

    # Botões gerais -------------------------------------------------------
    frame_botoes = tk.Frame(frame_raiz, bg=self.COR_CARD)
    frame_botoes.pack(fill=tk.X, pady=(12, 0))

    def confirmar() -> None:
        try:
            raio_configurado_px = int(valor_raio_led.get())
        except (TypeError, ValueError):
            raio_configurado_px = MAX_RADIUS_PX

        raio_configurado_px = min(
            MAX_RADIUS_PX,
            max(MIN_RADIUS_PX, raio_configurado_px),
        )

        configuracoes_camera_salvar = {
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
        janela.destroy()

    tk.Button(
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

    janela.deiconify()
    janela.lift()
    janela.focus_force()
