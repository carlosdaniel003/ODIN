import base64
import tkinter as tk

import cv2


def _converter_imagem_bgr_para_photoimage(imagem_bgr):
    imagem_rgb = cv2.cvtColor(imagem_bgr, cv2.COLOR_BGR2RGB)
    sucesso, buffer = cv2.imencode(".png", imagem_rgb)

    if not sucesso:
        return None

    imagem_base64 = base64.b64encode(buffer).decode("ascii")
    return tk.PhotoImage(data=imagem_base64)


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
    altura_imagem, largura_imagem = imagem.shape[:2]

    raio_atual = max(3, int(self.raio_atual_px))
    margem_recorte = max(28, raio_atual * 4)

    x1 = max(0, imagem_x - margem_recorte)
    y1 = max(0, imagem_y - margem_recorte)
    x2 = min(largura_imagem, imagem_x + margem_recorte)
    y2 = min(altura_imagem, imagem_y + margem_recorte)

    if x2 <= x1 or y2 <= y1:
        self.limpar_lupa_canvas()
        return

    recorte = imagem[y1:y2, x1:x2].copy()

    if recorte.size == 0:
        self.limpar_lupa_canvas()
        return

    tamanho_lupa = 190

    recorte_ampliado = cv2.resize(
        recorte,
        (tamanho_lupa, tamanho_lupa),
        interpolation=cv2.INTER_NEAREST,
    )

    largura_recorte = max(1, x2 - x1)
    altura_recorte = max(1, y2 - y1)

    escala_x = tamanho_lupa / largura_recorte
    escala_y = tamanho_lupa / altura_recorte

    centro_lupa_x = int((imagem_x - x1) * escala_x)
    centro_lupa_y = int((imagem_y - y1) * escala_y)
    raio_lupa = max(8, int(raio_atual * ((escala_x + escala_y) / 2)))

    cor_azul = (248, 189, 56)
    cor_verde = (94, 234, 212)
    cor_fundo = (15, 23, 42)

    cv2.circle(
        recorte_ampliado,
        (centro_lupa_x, centro_lupa_y),
        raio_lupa,
        cor_azul,
        2,
    )

    cv2.line(
        recorte_ampliado,
        (centro_lupa_x - raio_lupa - 10, centro_lupa_y),
        (centro_lupa_x + raio_lupa + 10, centro_lupa_y),
        cor_verde,
        1,
    )

    cv2.line(
        recorte_ampliado,
        (centro_lupa_x, centro_lupa_y - raio_lupa - 10),
        (centro_lupa_x, centro_lupa_y + raio_lupa + 10),
        cor_verde,
        1,
    )

    cv2.circle(
        recorte_ampliado,
        (centro_lupa_x, centro_lupa_y),
        2,
        (255, 255, 255),
        -1,
    )

    cv2.rectangle(
        recorte_ampliado,
        (0, 0),
        (tamanho_lupa - 1, tamanho_lupa - 1),
        cor_azul,
        2,
    )

    imagem_tk = _converter_imagem_bgr_para_photoimage(recorte_ampliado)

    if imagem_tk is None:
        self.limpar_lupa_canvas()
        return

    self.lupa_tk = imagem_tk
    self.canvas.delete("lupa_canvas")

    largura_canvas, altura_canvas = self.obter_tamanho_canvas_principal()

    x_lupa = largura_canvas - tamanho_lupa - 18
    y_lupa = 42

    mouse_sobre_lupa = (
        canvas_x >= x_lupa - 20
        and canvas_x <= x_lupa + tamanho_lupa + 20
        and canvas_y >= y_lupa - 40
        and canvas_y <= y_lupa + tamanho_lupa + 50
    )

    if mouse_sobre_lupa:
        x_lupa = 18
        y_lupa = 42

    x_lupa = max(12, x_lupa)
    y_lupa = max(12, y_lupa)

    texto_topo = f"LUPA | X:{imagem_x} Y:{imagem_y} | raio {raio_atual}px"

    self.canvas.create_rectangle(
        x_lupa - 6,
        y_lupa - 28,
        x_lupa + tamanho_lupa + 6,
        y_lupa + tamanho_lupa + 8,
        fill="#020617",
        outline=self.COR_BORDA,
        width=1,
        tags=("lupa_canvas",),
    )

    self.canvas.create_text(
        x_lupa,
        y_lupa - 15,
        text=texto_topo,
        fill=self.COR_TEXTO_2,
        font=("Segoe UI", 8, "bold"),
        anchor=tk.W,
        tags=("lupa_canvas",),
    )

    self.canvas.create_image(
        x_lupa,
        y_lupa,
        image=self.lupa_tk,
        anchor=tk.NW,
        tags=("lupa_canvas",),
    )

    self.canvas.create_rectangle(
        x_lupa,
        y_lupa,
        x_lupa + tamanho_lupa,
        y_lupa + tamanho_lupa,
        outline=self.COR_AZUL,
        width=2,
        tags=("lupa_canvas",),
    )

    self.canvas.tag_raise("lupa_canvas")