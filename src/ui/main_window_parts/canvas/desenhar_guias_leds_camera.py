import tkinter as tk

from src.models.led_selection import LedSelection


TAG_MARCACOES = "marcacoes_canvas"


def desenhar_guias_leds_camera(
    self,
    leds_selecionados: list[LedSelection],
) -> None:
    tags = (TAG_MARCACOES,)

    for led_selecionado in leds_selecionados:
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

        self.canvas.create_oval(
            centro_x_canvas - raio_canvas,
            centro_y_canvas - raio_canvas,
            centro_x_canvas + raio_canvas,
            centro_y_canvas + raio_canvas,
            outline=self.COR_AMARELO,
            width=2,
            dash=(5, 4),
            tags=tags,
        )

        self.canvas.create_oval(
            centro_x_canvas - 4,
            centro_y_canvas - 4,
            centro_x_canvas + 4,
            centro_y_canvas + 4,
            fill=self.COR_AMARELO,
            outline="",
            tags=tags,
        )

        self.canvas.create_line(
            centro_x_canvas - raio_canvas,
            centro_y_canvas,
            centro_x_canvas + raio_canvas,
            centro_y_canvas,
            fill=self.COR_AMARELO,
            width=1,
            dash=(3, 3),
            tags=tags,
        )

        self.canvas.create_line(
            centro_x_canvas,
            centro_y_canvas - raio_canvas,
            centro_x_canvas,
            centro_y_canvas + raio_canvas,
            fill=self.COR_AMARELO,
            width=1,
            dash=(3, 3),
            tags=tags,
        )

        self.canvas.create_text(
            centro_x_canvas,
            centro_y_canvas - raio_canvas - 10,
            text=numero_led,
            fill=self.COR_AMARELO,
            font=("Segoe UI", 7, "bold"),
            anchor=tk.CENTER,
            tags=tags,
        )
