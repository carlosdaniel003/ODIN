
import base64
import tkinter as tk

import cv2


def exibir_imagem_em_canvas(
    self,
    canvas: tk.Canvas,
    imagem,
    chave: str,
) -> None:
    canvas.delete("all")

    if imagem is None:
        self.desenhar_placeholder(canvas, "sem imagem")
        return

    canvas.update_idletasks()

    largura_canvas = max(260, canvas.winfo_width())
    altura_canvas = max(120, canvas.winfo_height())

    # Imagens em escala de cinza são convertidas para três canais
    # apenas para permitir a codificação e exibição no Tkinter.
    if len(imagem.shape) == 2:
        imagem_bgr = cv2.cvtColor(imagem, cv2.COLOR_GRAY2BGR)
    else:
        imagem_bgr = imagem

    altura_imagem, largura_imagem = imagem_bgr.shape[:2]

    escala_largura = largura_canvas / largura_imagem
    escala_altura = altura_canvas / altura_imagem
    escala = min(escala_largura, escala_altura, 1.0)

    largura_final = max(1, int(largura_imagem * escala))
    altura_final = max(1, int(altura_imagem * escala))

    imagem_redimensionada = cv2.resize(
        imagem_bgr,
        (largura_final, altura_final),
        interpolation=cv2.INTER_AREA,
    )

    # A imagem já está no formato BGR utilizado pelo OpenCV.
    # Não deve ser convertida para RGB antes do cv2.imencode,
    # pois isso troca visualmente os canais azul e vermelho.
    sucesso, buffer = cv2.imencode(
        ".png",
        imagem_redimensionada,
    )

    if not sucesso:
        self.desenhar_placeholder(
            canvas,
            "erro ao renderizar imagem",
        )
        return

    imagem_base64 = base64.b64encode(buffer).decode("ascii")
    imagem_tk = tk.PhotoImage(data=imagem_base64)

    # Mantém uma referência da imagem para evitar que o Tkinter
    # remova a imagem por coleta de memória.
    self.imagens_auxiliares_tk[chave] = imagem_tk

    x = int((largura_canvas - largura_final) / 2)
    y = int((altura_canvas - altura_final) / 2)

    canvas.create_rectangle(
        0,
        0,
        largura_canvas,
        altura_canvas,
        fill="#020617",
        outline="",
    )

    canvas.create_image(
        x,
        y,
        image=imagem_tk,
        anchor=tk.NW,
    )
