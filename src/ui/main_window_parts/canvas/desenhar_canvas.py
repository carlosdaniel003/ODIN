import tkinter as tk


TAG_FUNDO = "fundo_canvas"
TAG_IMAGEM = "imagem_canvas"
TAG_PLACEHOLDER = "placeholder_canvas"
TAG_MARCACOES = "marcacoes_canvas"
TAG_LUPA = "lupa_canvas"
TAG_AVISO = "aviso_camera"


def _primeiro_item_com_tag(canvas: tk.Canvas, tag: str):
    itens = canvas.find_withtag(tag)
    return itens[0] if itens else None


def _atualizar_fundo_canvas(
    self,
    largura_canvas: int,
    altura_canvas: int,
) -> None:
    item_fundo = _primeiro_item_com_tag(
        self.canvas,
        TAG_FUNDO,
    )

    if item_fundo is None:
        item_fundo = self.canvas.create_rectangle(
            0,
            0,
            largura_canvas,
            altura_canvas,
            fill="#020617",
            outline="",
            tags=(TAG_FUNDO,),
        )
    else:
        self.canvas.coords(
            item_fundo,
            0,
            0,
            largura_canvas,
            altura_canvas,
        )
        self.canvas.itemconfigure(
            item_fundo,
            fill="#020617",
            outline="",
        )

    self.canvas.tag_lower(item_fundo)


def _atualizar_imagem_canvas(self) -> None:
    item_imagem = _primeiro_item_com_tag(
        self.canvas,
        TAG_IMAGEM,
    )

    if item_imagem is None:
        item_imagem = self.canvas.create_image(
            self.deslocamento_imagem_x,
            self.deslocamento_imagem_y,
            image=self.imagem_tk,
            anchor=tk.NW,
            tags=(TAG_IMAGEM,),
        )
    else:
        self.canvas.coords(
            item_imagem,
            self.deslocamento_imagem_x,
            self.deslocamento_imagem_y,
        )
        self.canvas.itemconfigure(
            item_imagem,
            image=self.imagem_tk,
            anchor=tk.NW,
        )

    item_fundo = _primeiro_item_com_tag(
        self.canvas,
        TAG_FUNDO,
    )

    if item_fundo is not None:
        self.canvas.tag_raise(
            item_imagem,
            item_fundo,
        )


def _desenhar_placeholder(
    self,
    largura_canvas: int,
    altura_canvas: int,
) -> None:
    item_placeholder = _primeiro_item_com_tag(
        self.canvas,
        TAG_PLACEHOLDER,
    )

    if item_placeholder is None:
        self.canvas.create_text(
            largura_canvas / 2,
            altura_canvas / 2,
            text="Carregue a imagem da PCI",
            fill=self.COR_TEXTO_2,
            font=("Segoe UI", 18, "bold"),
            tags=(TAG_PLACEHOLDER,),
        )
        return

    self.canvas.coords(
        item_placeholder,
        largura_canvas / 2,
        altura_canvas / 2,
    )
    self.canvas.itemconfigure(
        item_placeholder,
        text="Carregue a imagem da PCI",
        fill=self.COR_TEXTO_2,
    )


def _elevar_camadas_temporarias(self) -> None:
    for tag in (
        TAG_MARCACOES,
        TAG_LUPA,
        TAG_AVISO,
    ):
        if self.canvas.find_withtag(tag):
            self.canvas.tag_raise(tag)


def desenhar_canvas(
    self,
    led_selecionado,
    resultado_led_atual,
) -> None:
    leds_selecionados = self._normalizar_leds_selecionados(
        led_selecionado
    )
    resultados_led = self._normalizar_resultados_led(
        resultado_led_atual
    )

    self.ultimo_led_selecionado = leds_selecionados
    self.ultimo_resultado_led_atual = resultados_led

    largura_canvas, altura_canvas = (
        self.obter_tamanho_canvas_principal()
    )

    _atualizar_fundo_canvas(
        self,
        largura_canvas,
        altura_canvas,
    )

    if self.imagem_tk is None:
        self.canvas.delete(TAG_IMAGEM)
        self.canvas.delete(TAG_MARCACOES)
        self.canvas.delete(TAG_LUPA)

        _desenhar_placeholder(
            self,
            largura_canvas,
            altura_canvas,
        )
        return

    self.canvas.delete(TAG_PLACEHOLDER)
    _atualizar_imagem_canvas(self)

    self.canvas.delete(TAG_MARCACOES)

    if resultados_led:
        self.desenhar_resultados_led(resultados_led)
        self.atualizar_painel_resultado_multiplos(
            resultados_led
        )

        for resultado in resultados_led:
            self.adicionar_resultado_historico(resultado)

    elif leds_selecionados:
        selecao_manual_camera = bool(
            getattr(
                self,
                "selecao_manual_camera_visivel",
                False,
            )
        )

        if (
            getattr(self, "tela_ao_vivo_ativa", False)
            and not selecao_manual_camera
        ):
            self.desenhar_guias_leds_camera(
                leds_selecionados
            )
        else:
            self.desenhar_leds_selecionados(
                leds_selecionados
            )

        self.atualizar_resumo_selecoes(
            leds_selecionados
        )
    else:
        self.atualizar_resumo_sem_analise()

    _elevar_camadas_temporarias(self)
