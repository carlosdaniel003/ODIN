import base64
import time
import tkinter as tk

import cv2


TAG_LUPA = "lupa_canvas"


def _converter_imagem_bgr_para_photoimage(imagem_bgr):
    """
    Converte uma imagem BGR do OpenCV para PhotoImage.

    cv2.imencode espera a imagem no padrão BGR; por isso não há conversão
    BGR -> RGB antes da codificação.
    """
    if imagem_bgr is None or imagem_bgr.size == 0:
        return None

    sucesso, buffer = cv2.imencode(
        ".png",
        imagem_bgr,
    )

    if not sucesso:
        return None

    imagem_base64 = base64.b64encode(
        buffer
    ).decode("ascii")

    return tk.PhotoImage(
        data=imagem_base64
    )


def _normalizar_leds_selecionados_preview(self) -> list:
    leds = getattr(
        self,
        "ultimo_led_selecionado",
        [],
    )

    if leds is None:
        return []

    if isinstance(leds, list):
        return [
            led
            for led in leds
            if led is not None
        ]

    return [leds]


def _obter_numero_led_preview(led) -> str:
    id_led = str(
        getattr(led, "id", "LED")
    )

    if "_" in id_led:
        return id_led.split("_")[-1]

    return id_led


def _desenhar_leds_confirmados_no_recorte(
    self,
    recorte_ampliado,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    escala_x: float,
    escala_y: float,
) -> None:
    """
    Desenha dentro da lupa todos os LEDs já confirmados que intersectam
    o recorte atual. Assim, a marcação não fica escondida atrás do preview.
    """
    cor_selecionado = (72, 255, 110)

    for led in _normalizar_leds_selecionados_preview(
        self
    ):
        centro_x = int(
            getattr(led, "centro_x", -1)
        )
        centro_y = int(
            getattr(led, "centro_y", -1)
        )
        raio = max(
            1,
            int(getattr(led, "raio", 1)),
        )

        if (
            centro_x + raio < x1
            or centro_x - raio >= x2
            or centro_y + raio < y1
            or centro_y - raio >= y2
        ):
            continue

        centro_local_x = int(
            (centro_x - x1) * escala_x
        )
        centro_local_y = int(
            (centro_y - y1) * escala_y
        )
        raio_local = max(
            8,
            int(
                raio
                * (
                    (escala_x + escala_y)
                    / 2.0
                )
            ),
        )

        cv2.circle(
            recorte_ampliado,
            (
                centro_local_x,
                centro_local_y,
            ),
            raio_local,
            cor_selecionado,
            3,
        )
        cv2.circle(
            recorte_ampliado,
            (
                centro_local_x,
                centro_local_y,
            ),
            4,
            cor_selecionado,
            -1,
        )

        numero_led = _obter_numero_led_preview(
            led
        )

        cv2.putText(
            recorte_ampliado,
            numero_led,
            (
                max(
                    2,
                    centro_local_x
                    - raio_local,
                ),
                max(
                    13,
                    centro_local_y
                    - raio_local
                    - 4,
                ),
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            cor_selecionado,
            1,
            cv2.LINE_AA,
        )


def _obter_confirmacao_lupa(self):
    confirmacao = getattr(
        self,
        "_lupa_confirmacao",
        None,
    )

    if not isinstance(confirmacao, dict):
        return None

    expira_em = float(
        confirmacao.get(
            "expira_em",
            0.0,
        )
    )

    if time.monotonic() > expira_em:
        return None

    return confirmacao


def desenhar_lupa_canvas(
    self,
    canvas_x: int,
    canvas_y: int,
    imagem_x: int,
    imagem_y: int,
) -> None:
    if self.imagem_canvas_original is None:
        self.limpar_lupa_canvas()
        return

    imagem = self.imagem_canvas_original
    altura_imagem, largura_imagem = (
        imagem.shape[:2]
    )

    raio_atual = max(
        3,
        int(self.raio_atual_px),
    )
    margem_recorte = max(
        28,
        raio_atual * 4,
    )

    x1 = max(
        0,
        imagem_x - margem_recorte,
    )
    y1 = max(
        0,
        imagem_y - margem_recorte,
    )
    x2 = min(
        largura_imagem,
        imagem_x + margem_recorte,
    )
    y2 = min(
        altura_imagem,
        imagem_y + margem_recorte,
    )

    if x2 <= x1 or y2 <= y1:
        self.limpar_lupa_canvas()
        return

    recorte = imagem[
        y1:y2,
        x1:x2,
    ].copy()

    if recorte.size == 0:
        self.limpar_lupa_canvas()
        return

    tamanho_lupa = 190

    recorte_ampliado = cv2.resize(
        recorte,
        (
            tamanho_lupa,
            tamanho_lupa,
        ),
        interpolation=cv2.INTER_NEAREST,
    )

    largura_recorte = max(
        1,
        x2 - x1,
    )
    altura_recorte = max(
        1,
        y2 - y1,
    )

    escala_x = (
        tamanho_lupa / largura_recorte
    )
    escala_y = (
        tamanho_lupa / altura_recorte
    )

    centro_lupa_x = int(
        (imagem_x - x1) * escala_x
    )
    centro_lupa_y = int(
        (imagem_y - y1) * escala_y
    )
    raio_lupa = max(
        8,
        int(
            raio_atual
            * (
                (escala_x + escala_y)
                / 2.0
            )
        ),
    )

    # Primeiro desenha todas as seleções já confirmadas.
    _desenhar_leds_confirmados_no_recorte(
        self=self,
        recorte_ampliado=recorte_ampliado,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
        escala_x=escala_x,
        escala_y=escala_y,
    )

    cor_mira = (248, 189, 56)
    cor_linhas = (94, 234, 212)
    cor_centro = (255, 255, 255)
    espessura_mira = 2

    confirmacao = _obter_confirmacao_lupa(
        self
    )

    if confirmacao is not None:
        tipo_confirmacao = str(
            confirmacao.get(
                "tipo",
                "",
            )
        )
        centro_confirmado_x = int(
            confirmacao.get(
                "centro_x",
                -99999,
            )
        )
        centro_confirmado_y = int(
            confirmacao.get(
                "centro_y",
                -99999,
            )
        )
        distancia_confirmacao = (
            (
                imagem_x
                - centro_confirmado_x
            )
            ** 2
            + (
                imagem_y
                - centro_confirmado_y
            )
            ** 2
        )

        if (
            distancia_confirmacao
            <= max(10, raio_atual) ** 2
        ):
            if tipo_confirmacao == "duplicado":
                cor_mira = (0, 190, 255)
            else:
                cor_mira = (72, 255, 110)

            cor_linhas = cor_mira
            espessura_mira = 4

    cv2.circle(
        recorte_ampliado,
        (
            centro_lupa_x,
            centro_lupa_y,
        ),
        raio_lupa,
        cor_mira,
        espessura_mira,
    )

    cv2.line(
        recorte_ampliado,
        (
            centro_lupa_x
            - raio_lupa
            - 10,
            centro_lupa_y,
        ),
        (
            centro_lupa_x
            + raio_lupa
            + 10,
            centro_lupa_y,
        ),
        cor_linhas,
        1,
    )

    cv2.line(
        recorte_ampliado,
        (
            centro_lupa_x,
            centro_lupa_y
            - raio_lupa
            - 10,
        ),
        (
            centro_lupa_x,
            centro_lupa_y
            + raio_lupa
            + 10,
        ),
        cor_linhas,
        1,
    )

    cv2.circle(
        recorte_ampliado,
        (
            centro_lupa_x,
            centro_lupa_y,
        ),
        3,
        cor_centro,
        -1,
    )

    cv2.rectangle(
        recorte_ampliado,
        (0, 0),
        (
            tamanho_lupa - 1,
            tamanho_lupa - 1,
        ),
        cor_mira,
        2,
    )

    imagem_tk = (
        _converter_imagem_bgr_para_photoimage(
            recorte_ampliado
        )
    )

    if imagem_tk is None:
        self.limpar_lupa_canvas()
        return

    self.lupa_tk = imagem_tk
    self.canvas.delete(TAG_LUPA)

    largura_canvas, _ = (
        self.obter_tamanho_canvas_principal()
    )

    x_lupa = (
        largura_canvas
        - tamanho_lupa
        - 18
    )
    y_lupa = 42

    mouse_sobre_lupa = (
        canvas_x >= x_lupa - 20
        and canvas_x
        <= x_lupa + tamanho_lupa + 20
        and canvas_y >= y_lupa - 40
        and canvas_y
        <= y_lupa + tamanho_lupa + 50
    )

    if mouse_sobre_lupa:
        x_lupa = 18
        y_lupa = 42

    x_lupa = max(12, x_lupa)
    y_lupa = max(12, y_lupa)

    total_selecionados = len(
        _normalizar_leds_selecionados_preview(
            self
        )
    )

    texto_topo = (
        f"MIRA | {total_selecionados} "
        "selecionado(s)"
    )
    cor_fundo_topo = "#07111F"
    cor_texto_topo = self.COR_TEXTO_2
    cor_borda = self.COR_AZUL

    if confirmacao is not None:
        id_confirmacao = str(
            confirmacao.get(
                "id",
                "LED",
            )
        )
        tipo_confirmacao = str(
            confirmacao.get(
                "tipo",
                "",
            )
        )

        if tipo_confirmacao == "duplicado":
            texto_topo = (
                f"! {id_confirmacao} "
                "JÁ SELECIONADO"
            )
            cor_fundo_topo = "#422006"
            cor_texto_topo = "#FDE68A"
            cor_borda = "#F59E0B"
        else:
            texto_topo = (
                f"✓ {id_confirmacao} "
                f"SELECIONADO | {total_selecionados}"
            )
            cor_fundo_topo = "#052E1A"
            cor_texto_topo = "#86EFAC"
            cor_borda = "#22C55E"

    self.canvas.create_rectangle(
        x_lupa - 6,
        y_lupa - 30,
        x_lupa + tamanho_lupa + 6,
        y_lupa + tamanho_lupa + 8,
        fill="#020617",
        outline=cor_borda,
        width=2,
        tags=(TAG_LUPA,),
    )

    self.canvas.create_rectangle(
        x_lupa - 5,
        y_lupa - 29,
        x_lupa + tamanho_lupa + 5,
        y_lupa - 2,
        fill=cor_fundo_topo,
        outline="",
        tags=(TAG_LUPA,),
    )

    self.canvas.create_text(
        x_lupa,
        y_lupa - 16,
        text=texto_topo,
        fill=cor_texto_topo,
        font=(
            "Segoe UI",
            7,
            "bold",
        ),
        anchor=tk.W,
        tags=(TAG_LUPA,),
    )

    self.canvas.create_image(
        x_lupa,
        y_lupa,
        image=self.lupa_tk,
        anchor=tk.NW,
        tags=(TAG_LUPA,),
    )

    self.canvas.create_rectangle(
        x_lupa,
        y_lupa,
        x_lupa + tamanho_lupa,
        y_lupa + tamanho_lupa,
        outline=cor_borda,
        width=2,
        tags=(TAG_LUPA,),
    )

    self.canvas.tag_raise(TAG_LUPA)
    self._lupa_visivel = True
