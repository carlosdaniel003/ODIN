import base64
from pathlib import Path

import cv2
import tkinter as tk


def carregar_logo_sistema(self, caminho_logo: str = "assets/logo_lumus.png", tamanho_px: int = 58):
    caminho_logo_path = Path(caminho_logo)

    if not caminho_logo_path.exists():
        return None

    imagem_logo = cv2.imread(str(caminho_logo_path), cv2.IMREAD_COLOR)

    if imagem_logo is None:
        return None

    altura_original, largura_original = imagem_logo.shape[:2]
    escala = tamanho_px / max(altura_original, largura_original)

    largura_final = max(1, int(largura_original * escala))
    altura_final = max(1, int(altura_original * escala))

    imagem_logo = cv2.resize(
        imagem_logo,
        (largura_final, altura_final),
        interpolation=cv2.INTER_AREA,
    )

    cor_fundo_hex = self.COR_TOPO.replace("#", "")
    cor_fundo_rgb = tuple(int(cor_fundo_hex[indice:indice + 2], 16) for indice in (0, 2, 4))
    cor_fundo_bgr = (cor_fundo_rgb[2], cor_fundo_rgb[1], cor_fundo_rgb[0])

    mascara_fundo_branco = (
        (imagem_logo[:, :, 0] > 245)
        & (imagem_logo[:, :, 1] > 245)
        & (imagem_logo[:, :, 2] > 245)
    )

    imagem_logo[mascara_fundo_branco] = cor_fundo_bgr

    imagem_rgb = cv2.cvtColor(imagem_logo, cv2.COLOR_BGR2RGB)
    sucesso, buffer = cv2.imencode(".png", imagem_rgb)

    if not sucesso:
        return None

    imagem_base64 = base64.b64encode(buffer).decode("ascii")
    return tk.PhotoImage(data=imagem_base64)