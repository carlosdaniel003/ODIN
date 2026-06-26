from src.models.led_selection import LedSelection


TAG_MARCACOES = "marcacoes_canvas"


def desenhar_led_selecionado(
    self,
    led_selecionado: LedSelection,
) -> None:
    centro_x_canvas = (
        self.deslocamento_imagem_x
        + int(
            led_selecionado.centro_x
            * self.escala_exibicao
        )
    )
    centro_y_canvas = (
        self.deslocamento_imagem_y
        + int(
            led_selecionado.centro_y
            * self.escala_exibicao
        )
    )
    raio_canvas = max(
        3,
        int(
            led_selecionado.raio
            * self.escala_exibicao
        ),
    )

    id_led = getattr(led_selecionado, "id", "LED")
    numero_led = (
        id_led.split("_")[-1]
        if "_" in id_led
        else id_led
    )

    tags = (TAG_MARCACOES,)

    self.canvas.create_oval(
        centro_x_canvas - raio_canvas,
        centro_y_canvas - raio_canvas,
        centro_x_canvas + raio_canvas,
        centro_y_canvas + raio_canvas,
        outline=self.COR_AZUL,
        width=2,
        tags=tags,
    )

    self.canvas.create_line(
        centro_x_canvas - raio_canvas,
        centro_y_canvas,
        centro_x_canvas + raio_canvas,
        centro_y_canvas,
        fill=self.COR_AZUL,
        width=1,
        tags=tags,
    )

    self.canvas.create_line(
        centro_x_canvas,
        centro_y_canvas - raio_canvas,
        centro_x_canvas,
        centro_y_canvas + raio_canvas,
        fill=self.COR_AZUL,
        width=1,
        tags=tags,
    )

    self.canvas.create_oval(
        centro_x_canvas - 8,
        centro_y_canvas - 8,
        centro_x_canvas + 8,
        centro_y_canvas + 8,
        fill="#020617",
        outline=self.COR_AZUL,
        width=1,
        tags=tags,
    )

    self.canvas.create_text(
        centro_x_canvas,
        centro_y_canvas,
        text=numero_led,
        fill=self.COR_AZUL,
        font=("Segoe UI", 6, "bold"),
        tags=tags,
    )
