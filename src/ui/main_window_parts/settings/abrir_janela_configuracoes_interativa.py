from __future__ import annotations

import importlib
import tkinter as tk

from config import (
    CAMERA_BRIGHTNESS_MAX,
    CAMERA_BRIGHTNESS_MIN,
    CAMERA_EXPOSURE_MAX,
    CAMERA_EXPOSURE_MIN,
    CAMERA_FOCUS_MAX,
    CAMERA_FOCUS_MIN,
    CAMERA_GAIN_MAX,
    CAMERA_GAIN_MIN,
    CAMERA_GAMMA_MAX,
    CAMERA_GAMMA_MIN,
    CAMERA_WHITE_BALANCE_MAX,
    CAMERA_WHITE_BALANCE_MIN,
    DEFAULT_CAMERA_SETTINGS,
)
from src.ui.main_window_parts.settings.abrir_janela_configuracoes import (
    abrir_janela_configuracoes as abrir_janela_configuracoes_base,
)
from src.ui.main_window_parts.widgets.select_lista import SelectLista


_MODULO_CONFIGURACOES = importlib.import_module(
    "src.ui.main_window_parts.settings.abrir_janela_configuracoes"
)


def _percorrer_widgets(widget):
    for filho in widget.winfo_children():
        yield filho
        yield from _percorrer_widgets(filho)


def _encontrar_corpo_controles(janela: tk.Toplevel):
    for widget in _percorrer_widgets(janela):
        if not isinstance(widget, tk.Label):
            continue

        try:
            texto = str(widget.cget("text"))
        except tk.TclError:
            continue

        if texto != "Controles de imagem e posição":
            continue

        card = widget.master
        frames = [
            filho
            for filho in card.winfo_children()
            if isinstance(filho, tk.Frame)
        ]
        return frames[-1] if frames else None

    return None


def _criar_variaveis_avancadas(configuracoes_camera: dict) -> dict:
    origem = (
        configuracoes_camera
        if isinstance(configuracoes_camera, dict)
        else {}
    )
    padrao = DEFAULT_CAMERA_SETTINGS

    return {
        "exposure_auto": tk.BooleanVar(
            value=bool(origem.get("exposure_auto", padrao["exposure_auto"]))
        ),
        "exposure_enabled": tk.BooleanVar(
            value=bool(origem.get("exposure_enabled", padrao["exposure_enabled"]))
        ),
        "exposure": tk.DoubleVar(
            value=float(origem.get("exposure", padrao["exposure"]))
        ),
        "gain_enabled": tk.BooleanVar(
            value=bool(origem.get("gain_enabled", padrao["gain_enabled"]))
        ),
        "gain": tk.DoubleVar(
            value=float(origem.get("gain", padrao["gain"]))
        ),
        "focus_auto": tk.BooleanVar(
            value=bool(origem.get("focus_auto", padrao["focus_auto"]))
        ),
        "focus_enabled": tk.BooleanVar(
            value=bool(origem.get("focus_enabled", padrao["focus_enabled"]))
        ),
        "focus": tk.DoubleVar(
            value=float(origem.get("focus", padrao["focus"]))
        ),
        "white_balance_auto": tk.BooleanVar(
            value=bool(
                origem.get(
                    "white_balance_auto",
                    padrao["white_balance_auto"],
                )
            )
        ),
        "white_balance_enabled": tk.BooleanVar(
            value=bool(
                origem.get(
                    "white_balance_enabled",
                    padrao["white_balance_enabled"],
                )
            )
        ),
        "white_balance": tk.DoubleVar(
            value=float(
                origem.get(
                    "white_balance",
                    padrao["white_balance"],
                )
            )
        ),
        "brightness_enabled": tk.BooleanVar(
            value=bool(
                origem.get(
                    "brightness_enabled",
                    padrao["brightness_enabled"],
                )
            )
        ),
        "brightness": tk.DoubleVar(
            value=float(origem.get("brightness", padrao["brightness"]))
        ),
        "gamma_enabled": tk.BooleanVar(
            value=bool(origem.get("gamma_enabled", padrao["gamma_enabled"]))
        ),
        "gamma": tk.DoubleVar(
            value=float(origem.get("gamma", padrao["gamma"]))
        ),
    }


def _adicionar_controles_avancados(
    self,
    janela: tk.Toplevel,
    variaveis: dict,
    status_controles_camera: dict,
) -> None:
    corpo = _encontrar_corpo_controles(janela)
    if corpo is None:
        return

    tk.Frame(
        corpo,
        bg="#172033",
        height=1,
    ).pack(fill=tk.X, padx=12, pady=(8, 12))

    tk.Label(
        corpo,
        text="Controles avançados da câmera",
        font=("Segoe UI", 10, "bold"),
        fg=self.COR_TEXTO,
        bg=self.COR_CARD_2,
        anchor="w",
    ).pack(fill=tk.X, padx=12, pady=(0, 4))

    tk.Label(
        corpo,
        text=(
            "A disponibilidade e a escala real dependem da webcam e do driver. "
            "Quando não houver suporte, o ODIN mantém o padrão da câmera."
        ),
        font=("Segoe UI", 8),
        fg=self.COR_TEXTO_3,
        bg=self.COR_CARD_2,
        anchor="w",
        justify=tk.LEFT,
        wraplength=620,
    ).pack(fill=tk.X, padx=12, pady=(0, 8))

    nomes_status = {
        "aplicado": "Aplicado",
        "manual_pronto": "Pronto para ajuste",
        "manual_disponivel": "Manual disponível",
        "restaurado": "Restaurado",
        "ignorado_driver": "Driver não confirmou este valor",
        "ajustado_driver": "Limitado ao passo aceito pelo driver",
        "nao_suportado": "Não suportado",
        "padrao_driver": "Padrão do driver",
        "aguardando_camera": "Aguardando câmera",
        "aplicado_software": "Aplicado por software",
        "automatico": "Automático",
    }

    def criar_controle(
        nome: str,
        titulo: str,
        minimo: int,
        maximo: int,
        descricao: str,
        automatico_chave: str | None = None,
        automatico_texto: str | None = None,
    ) -> None:
        linha = tk.Frame(corpo, bg=self.COR_CARD_2)
        linha.pack(fill=tk.X, padx=12, pady=(5, 9))

        habilitado = variaveis[f"{nome}_enabled"]
        valor = variaveis[nome]
        automatico = (
            variaveis[automatico_chave]
            if automatico_chave is not None
            else None
        )

        topo = tk.Frame(linha, bg=self.COR_CARD_2)
        topo.pack(fill=tk.X)

        check_manual = tk.Checkbutton(
            topo,
            text=titulo,
            variable=habilitado,
            font=("Segoe UI", 9, "bold"),
            fg=self.COR_TEXTO,
            bg=self.COR_CARD_2,
            activebackground=self.COR_CARD_2,
            activeforeground=self.COR_TEXTO,
            selectcolor=self.COR_CARD,
            anchor="w",
        )
        check_manual.pack(side=tk.LEFT)

        status_atual = status_controles_camera.get(
            nome,
            {},
        ).get("status", "aguardando_camera")

        tk.Label(
            topo,
            text=nomes_status.get(status_atual, status_atual),
            font=("Segoe UI", 8, "bold"),
            fg=self.COR_TEXTO_3,
            bg=self.COR_CARD_2,
        ).pack(side=tk.RIGHT)

        if automatico is not None:
            tk.Checkbutton(
                linha,
                text=automatico_texto or "Automático",
                variable=automatico,
                font=("Segoe UI", 8, "bold"),
                fg="#BAE6FD",
                bg=self.COR_CARD_2,
                activebackground=self.COR_CARD_2,
                activeforeground="#E0F2FE",
                selectcolor=self.COR_CARD,
                anchor="w",
            ).pack(fill=tk.X, pady=(2, 1))

        ajuste = tk.Frame(linha, bg=self.COR_CARD_2)
        ajuste.pack(fill=tk.X, pady=(3, 0))

        label_valor = tk.Label(
            ajuste,
            text=str(int(round(valor.get()))),
            width=7,
            font=("Segoe UI", 9, "bold"),
            fg=self.COR_AZUL,
            bg=self.COR_CARD_2,
        )
        label_valor.pack(side=tk.RIGHT, padx=(8, 0))

        escala = tk.Scale(
            ajuste,
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
            command=lambda texto, label=label_valor: label.config(
                text=str(int(round(float(texto))))
            ),
        )
        escala.pack(side=tk.LEFT, fill=tk.X, expand=True)

        def atualizar_estado(*_args) -> None:
            modo_automatico = bool(
                automatico.get()
            ) if automatico is not None else False
            manual_habilitado = bool(habilitado.get())

            check_manual.config(
                state=tk.DISABLED if modo_automatico else tk.NORMAL
            )
            escala.config(
                state=(
                    tk.NORMAL
                    if manual_habilitado and not modo_automatico
                    else tk.DISABLED
                )
            )
            label_valor.config(
                fg=(
                    self.COR_AZUL
                    if manual_habilitado and not modo_automatico
                    else self.COR_TEXTO_3
                )
            )

        habilitado.trace_add("write", atualizar_estado)
        if automatico is not None:
            automatico.trace_add("write", atualizar_estado)
        atualizar_estado()

        tk.Label(
            linha,
            text=descricao,
            font=("Segoe UI", 8),
            fg=self.COR_TEXTO_3,
            bg=self.COR_CARD_2,
            anchor="w",
            justify=tk.LEFT,
            wraplength=620,
        ).pack(fill=tk.X)

    criar_controle(
        "exposure",
        "Exposição manual",
        CAMERA_EXPOSURE_MIN,
        CAMERA_EXPOSURE_MAX,
        "Controla o tempo de exposição. Desative o automático para aplicar.",
        automatico_chave="exposure_auto",
        automatico_texto="Exposição automática",
    )
    criar_controle(
        "gain",
        "Ganho manual",
        CAMERA_GAIN_MIN,
        CAMERA_GAIN_MAX,
        "Amplifica o sinal da câmera; valores altos podem aumentar o ruído.",
    )
    criar_controle(
        "focus",
        "Foco manual",
        CAMERA_FOCUS_MIN,
        CAMERA_FOCUS_MAX,
        "Ajusta o foco quando a webcam oferece lente com controle eletrônico.",
        automatico_chave="focus_auto",
        automatico_texto="Foco automático",
    )
    criar_controle(
        "white_balance",
        "Balanço de branco manual",
        CAMERA_WHITE_BALANCE_MIN,
        CAMERA_WHITE_BALANCE_MAX,
        "Temperatura de cor em Kelvin. Desative o automático para aplicar.",
        automatico_chave="white_balance_auto",
        automatico_texto="Balanço de branco automático",
    )
    criar_controle(
        "brightness",
        "Brilho manual",
        CAMERA_BRIGHTNESS_MIN,
        CAMERA_BRIGHTNESS_MAX,
        "Ajusta o nível geral de brilho entregue pelo driver da câmera.",
    )
    criar_controle(
        "gamma",
        "Gamma manual",
        CAMERA_GAMMA_MIN,
        CAMERA_GAMMA_MAX,
        "Altera a resposta tonal entre regiões escuras e claras.",
    )


def abrir_janela_configuracoes(self, *args, **kwargs) -> None:
    """Abre configurações com selects e controles avançados compatíveis."""

    configuracoes_camera = kwargs.get("configuracoes_camera") or {}
    status_controles = kwargs.get("status_controles_camera") or {}
    variaveis = _criar_variaveis_avancadas(configuracoes_camera)
    callback_original = kwargs.get("callback_salvar")

    def callback_salvar_estendido(
        salvar_resultados_analise,
        raio_configurado_px,
        configuracoes_camera_salvar,
    ) -> None:
        configuracoes = dict(configuracoes_camera_salvar or {})

        for chave in (
            "exposure_auto",
            "exposure_enabled",
            "gain_enabled",
            "focus_auto",
            "focus_enabled",
            "white_balance_auto",
            "white_balance_enabled",
            "brightness_enabled",
            "gamma_enabled",
        ):
            configuracoes[chave] = bool(variaveis[chave].get())

        for chave in (
            "exposure",
            "gain",
            "focus",
            "white_balance",
            "brightness",
            "gamma",
        ):
            configuracoes[chave] = float(variaveis[chave].get())

        callback_original(
            salvar_resultados_analise,
            raio_configurado_px,
            configuracoes,
        )

    kwargs["callback_salvar"] = callback_salvar_estendido

    janelas_antes = {
        widget
        for widget in self.root.winfo_children()
        if isinstance(widget, tk.Toplevel)
    }

    combobox_original = _MODULO_CONFIGURACOES.ttk.Combobox
    _MODULO_CONFIGURACOES.ttk.Combobox = SelectLista

    try:
        abrir_janela_configuracoes_base(
            self,
            *args,
            **kwargs,
        )
    finally:
        _MODULO_CONFIGURACOES.ttk.Combobox = combobox_original

    novas_janelas = [
        widget
        for widget in self.root.winfo_children()
        if isinstance(widget, tk.Toplevel)
        and widget not in janelas_antes
        and widget.winfo_exists()
    ]

    if not novas_janelas:
        return

    janela = novas_janelas[-1]
    _adicionar_controles_avancados(
        self,
        janela,
        variaveis,
        status_controles,
    )
    janela.update_idletasks()
