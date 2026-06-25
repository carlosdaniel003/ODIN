import time


INTERVALO_MINIMO_LUPA_S = 0.035
MOVIMENTO_MINIMO_LUPA_PX = 3


def atualizar_lupa_canvas(self, evento=None) -> None:
    if evento is None:
        self.limpar_lupa_canvas()
        return

    if not getattr(self, "selecao_led_ativa", False):
        self.limpar_lupa_canvas()
        return

    if self.imagem_canvas_original is None:
        self.limpar_lupa_canvas()
        return

    coordenadas_imagem = self.converter_canvas_para_imagem_original(
        evento.x,
        evento.y,
    )

    if coordenadas_imagem is None:
        self.limpar_lupa_canvas()
        return

    tempo_atual = time.perf_counter()
    ultimo_tempo = float(getattr(self, "_lupa_ultimo_tempo_s", 0.0))
    ultima_posicao = getattr(self, "_lupa_ultima_posicao_canvas", None)

    if ultima_posicao is not None:
        ultimo_x, ultimo_y = ultima_posicao
        movimento_pequeno = (
            abs(evento.x - ultimo_x) < MOVIMENTO_MINIMO_LUPA_PX
            and abs(evento.y - ultimo_y) < MOVIMENTO_MINIMO_LUPA_PX
        )

        if movimento_pequeno:
            return

    if tempo_atual - ultimo_tempo < INTERVALO_MINIMO_LUPA_S:
        return

    imagem_x, imagem_y = coordenadas_imagem

    self._lupa_ultimo_tempo_s = tempo_atual
    self._lupa_ultima_posicao_canvas = (evento.x, evento.y)

    self.desenhar_lupa_canvas(
        canvas_x=evento.x,
        canvas_y=evento.y,
        imagem_x=imagem_x,
        imagem_y=imagem_y,
    )
