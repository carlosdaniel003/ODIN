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

    coordenadas_imagem = self.converter_canvas_para_imagem_original(evento.x, evento.y)

    if coordenadas_imagem is None:
        self.limpar_lupa_canvas()
        return

    imagem_x, imagem_y = coordenadas_imagem

    self.desenhar_lupa_canvas(
        canvas_x=evento.x,
        canvas_y=evento.y,
        imagem_x=imagem_x,
        imagem_y=imagem_y,
    )