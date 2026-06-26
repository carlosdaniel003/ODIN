import base64
import tkinter as tk

import cv2


TAG_FUNDO_AUXILIAR = "fundo_imagem_auxiliar"
TAG_IMAGEM_AUXILIAR = "imagem_auxiliar"


def _obter_tamanho_real_canvas(
    canvas: tk.Canvas,
) -> tuple[int, int]:
    canvas.update_idletasks()

    largura = int(canvas.winfo_width())
    altura = int(canvas.winfo_height())

    if largura <= 1:
        largura = int(canvas.winfo_reqwidth())

    if altura <= 1:
        altura = int(canvas.winfo_reqheight())

    return max(1, largura), max(1, altura)


def _obter_primeiro_item(
    canvas: tk.Canvas,
    tag: str,
):
    itens = canvas.find_withtag(tag)
    return itens[0] if itens else None


def exibir_imagem_em_canvas(
    self,
    canvas: tk.Canvas,
    imagem,
    chave: str,
) -> None:
    if imagem is None:
        canvas.delete("all")
        self.desenhar_placeholder(
            canvas,
            "sem imagem",
        )
        return

    largura_canvas, altura_canvas = (
        _obter_tamanho_real_canvas(canvas)
    )

    # Imagens monocromáticas são convertidas para três canais para
    # manter a mesma rotina de codificação PNG usada nos demais painéis.
    if len(imagem.shape) == 2:
        imagem_bgr = cv2.cvtColor(
            imagem,
            cv2.COLOR_GRAY2BGR,
        )
    else:
        imagem_bgr = imagem

    altura_imagem, largura_imagem = (
        imagem_bgr.shape[:2]
    )

    if largura_imagem <= 0 or altura_imagem <= 0:
        canvas.delete("all")
        self.desenhar_placeholder(
            canvas,
            "imagem inválida",
        )
        return

    escala = min(
        largura_canvas / largura_imagem,
        altura_canvas / altura_imagem,
    )

    largura_final = max(
        1,
        int(round(largura_imagem * escala)),
    )
    altura_final = max(
        1,
        int(round(altura_imagem * escala)),
    )

    interpolacao = (
        cv2.INTER_AREA
        if escala < 1.0
        else cv2.INTER_LINEAR
    )

    imagem_redimensionada = cv2.resize(
        imagem_bgr,
        (largura_final, altura_final),
        interpolation=interpolacao,
    )

    # cv2.imencode recebe a imagem no padrão BGR do OpenCV.
    sucesso, buffer = cv2.imencode(
        ".png",
        imagem_redimensionada,
    )

    if not sucesso:
        canvas.delete("all")
        self.desenhar_placeholder(
            canvas,
            "erro ao renderizar imagem",
        )
        return

    imagem_base64 = base64.b64encode(
        buffer
    ).decode("ascii")
    imagem_tk = tk.PhotoImage(
        data=imagem_base64
    )

    # Mantém a referência para impedir que o Tkinter descarte a imagem.
    self.imagens_auxiliares_tk[chave] = imagem_tk

    x = int(
        (largura_canvas - largura_final) / 2
    )
    y = int(
        (altura_canvas - altura_final) / 2
    )

    item_fundo = _obter_primeiro_item(
        canvas,
        TAG_FUNDO_AUXILIAR,
    )
    item_imagem = _obter_primeiro_item(
        canvas,
        TAG_IMAGEM_AUXILIAR,
    )

    if item_fundo is None or item_imagem is None:
        # Remove placeholders antigos somente na primeira renderização.
        canvas.delete("all")

        item_fundo = canvas.create_rectangle(
            0,
            0,
            largura_canvas,
            altura_canvas,
            fill="#020617",
            outline="",
            tags=(TAG_FUNDO_AUXILIAR,),
        )
        item_imagem = canvas.create_image(
            x,
            y,
            image=imagem_tk,
            anchor=tk.NW,
            tags=(TAG_IMAGEM_AUXILIAR,),
        )
    else:
        canvas.coords(
            item_fundo,
            0,
            0,
            largura_canvas,
            altura_canvas,
        )
        canvas.itemconfigure(
            item_fundo,
            fill="#020617",
            outline="",
        )

        canvas.coords(
            item_imagem,
            x,
            y,
        )
        canvas.itemconfigure(
            item_imagem,
            image=imagem_tk,
            anchor=tk.NW,
        )

    canvas.tag_lower(item_fundo)
    canvas.tag_raise(
        item_imagem,
        item_fundo,
    )
