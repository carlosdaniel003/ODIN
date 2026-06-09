from pathlib import Path

import cv2
import numpy as np


def carregar_imagem_opencv(caminho_imagem: str):
    """
    Carrega imagem de forma segura no Windows.
    Evita falha do cv2.imread() com caminhos contendo acentos ou caracteres especiais.
    """
    try:
        dados_imagem = np.fromfile(caminho_imagem, dtype=np.uint8)
        imagem = cv2.imdecode(dados_imagem, cv2.IMREAD_COLOR)
        return imagem
    except Exception:
        return None


def salvar_imagem_opencv(caminho_imagem: Path, imagem) -> bool:
    """
    Salva imagem de forma segura no Windows.
    Evita falha do cv2.imwrite() com caminhos contendo acentos ou caracteres especiais.
    """
    try:
        extensao = caminho_imagem.suffix or ".png"
        sucesso, buffer = cv2.imencode(extensao, imagem)

        if not sucesso:
            return False

        buffer.tofile(str(caminho_imagem))
        return True
    except Exception:
        return False
