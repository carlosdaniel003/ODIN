from __future__ import annotations

"""Mostra as máscaras/ROIs do projeto nas duas previews de placa do F2.

A alteração é somente visual na janela de Configurações. As referências salvas
continuam sendo as imagens originais completas, sem desenhos persistidos. A
preview de suporte vazio permanece limpa porque não existe placa/ROI a validar.

As máscaras são desenhadas *depois* do redimensionamento da foto para a preview.
Isso evita que contornos de poucos pixels desapareçam quando uma imagem 640x480
ou maior é reduzida para aproximadamente 180x104.
"""

import base64
import tkinter as tk

import cv2
import numpy as np

from src.core.roi_geometry import (
    TIPO_ROI_SEGMENTO,
    normalizar_tipo_roi,
    pontos_segmento,
)
from src.models.led_selection import LedSelection
from src.platform.f2_board_presence_references import (
    F2_BOARD_REF_BOARD_OFF,
    F2_BOARD_REF_BOARD_ON,
    F2BoardPresenceReferenceController,
)


F2_BOARD_MASK_PREVIEW_COLOR_BGR = (248, 189, 56)  # #38BDF8
F2_BOARD_MASK_PREVIEW_SHADOW_BGR = (3, 7, 18)
F2_BOARD_MASK_PREVIEW_WIDTH = 180
F2_BOARD_MASK_PREVIEW_HEIGHT = 104
F2_BOARD_MASK_PREVIEW_TITLES = {
    F2_BOARD_REF_BOARD_ON: "1. Placa fixa ligada",
    F2_BOARD_REF_BOARD_OFF: "2. Placa fixa desligada",
}


def _percorrer_widgets(widget):
    for filho in widget.winfo_children():
        yield filho
        yield from _percorrer_widgets(filho)


def _encontrar_card_por_titulo(window, titulo: str):
    for widget in _percorrer_widgets(window):
        if not isinstance(widget, tk.Label):
            continue
        try:
            if str(widget.cget("text")) == titulo:
                return widget.master
        except tk.TclError:
            continue
    return None


def _encontrar_label_preview(card):
    if card is None:
        return None
    for widget in _percorrer_widgets(card):
        if not isinstance(widget, tk.Label):
            continue
        try:
            parent = widget.master
            if str(parent.cget("bg")) == "#020617":
                return widget
        except (tk.TclError, AttributeError):
            continue
    return None


def _leds_direto_da_configuracao(controller, projeto: str):
    """Lê as ROIs do próprio projeto, sem depender do espelho ativo do runtime."""
    repository = getattr(controller.app, "config_repository", None)
    if repository is None:
        return []
    try:
        config = repository.carregar_configuracao_existente_sem_alerta()
    except Exception:
        return []
    projetos = config.get("led_projects", {}) if isinstance(config, dict) else {}
    dados = projetos.get(projeto, {}) if isinstance(projetos, dict) else {}
    itens = dados.get("fixed_leds", []) if isinstance(dados, dict) else []
    if not isinstance(itens, list):
        return []

    leds = []
    for item in itens:
        try:
            led = LedSelection.from_dict(item)
        except Exception:
            led = None
        if led is not None:
            leds.append(led)
    return leds


def _leds_do_projeto(controller, projeto: str):
    # Fonte preferida: o próprio bloco fixed_leds do projeto mostrado na tela.
    # Isso evita depender do espelho global/ativo quando a janela está reconstruindo
    # referências e garante que as máscaras pertencem à mesma resolução/projeto.
    leds = _leds_direto_da_configuracao(controller, projeto)
    if leds:
        return leds

    repository = getattr(controller.app, "config_repository", None)
    getter = getattr(repository, "carregar_leds_fixos", None)
    if callable(getter):
        try:
            leds = list(getter(projeto) or [])
        except TypeError:
            try:
                leds = list(getter() or [])
            except Exception:
                leds = []
        except Exception:
            leds = []
        if leds:
            return leds

    return list(getattr(controller.app, "leds_fixos_configurados", []) or [])


def _adaptar_led_para_imagem(led, largura: int, altura: int):
    """Adapta ROI antiga/normalizada quando a base salva difere da referência."""
    largura_base = getattr(led, "largura_base", None)
    altura_base = getattr(led, "altura_base", None)
    if largura_base and altura_base:
        try:
            if int(largura_base) != int(largura) or int(altura_base) != int(altura):
                adaptar = getattr(led, "adaptar_para_resolucao", None)
                if callable(adaptar):
                    return adaptar(
                        int(largura),
                        int(altura),
                        raio_minimo=1,
                        raio_maximo=max(int(largura), int(altura)),
                    )
        except Exception:
            pass
    return led


def _redimensionar_para_preview(imagem, largura_max: int, altura_max: int):
    if imagem is None or getattr(imagem, "size", 0) == 0:
        return None, 1.0, 1.0

    altura, largura = imagem.shape[:2]
    if largura <= 0 or altura <= 0:
        return None, 1.0, 1.0

    escala = min(
        float(largura_max) / float(largura),
        float(altura_max) / float(altura),
    )
    largura_final = max(1, int(round(largura * escala)))
    altura_final = max(1, int(round(altura * escala)))
    interpolacao = cv2.INTER_AREA if escala < 1.0 else cv2.INTER_LINEAR
    reduzida = cv2.resize(
        imagem,
        (largura_final, altura_final),
        interpolation=interpolacao,
    )
    return (
        reduzida,
        float(largura_final) / float(largura),
        float(altura_final) / float(altura),
    )


def _desenhar_contorno_preview(imagem, led, escala_x: float, escala_y: float) -> None:
    """Desenha em coordenadas já reduzidas para manter o contorno visível."""
    tipo = normalizar_tipo_roi(getattr(led, "tipo_roi", None))
    if tipo == TIPO_ROI_SEGMENTO:
        pontos = pontos_segmento(led).astype(np.float32)
        pontos[:, 0] *= float(escala_x)
        pontos[:, 1] *= float(escala_y)
        pts = np.rint(pontos).astype(np.int32)
        cv2.polylines(
            imagem,
            [pts],
            True,
            F2_BOARD_MASK_PREVIEW_SHADOW_BGR,
            4,
            cv2.LINE_AA,
        )
        cv2.polylines(
            imagem,
            [pts],
            True,
            F2_BOARD_MASK_PREVIEW_COLOR_BGR,
            2,
            cv2.LINE_AA,
        )
        return

    centro = (
        int(round(float(getattr(led, "centro_x", 0)) * escala_x)),
        int(round(float(getattr(led, "centro_y", 0)) * escala_y)),
    )
    raio = max(
        2,
        int(
            round(
                float(max(1, int(getattr(led, "raio", 1) or 1)))
                * min(float(escala_x), float(escala_y))
            )
        ),
    )
    cv2.circle(
        imagem,
        centro,
        raio,
        F2_BOARD_MASK_PREVIEW_SHADOW_BGR,
        4,
        cv2.LINE_AA,
    )
    cv2.circle(
        imagem,
        centro,
        raio,
        F2_BOARD_MASK_PREVIEW_COLOR_BGR,
        2,
        cv2.LINE_AA,
    )


def criar_imagem_preview_presenca_com_mascaras_f2(
    imagem,
    leds,
    largura_max: int = F2_BOARD_MASK_PREVIEW_WIDTH,
    altura_max: int = F2_BOARD_MASK_PREVIEW_HEIGHT,
):
    """Cria a preview já reduzida e só então sobrepõe as ROIs do projeto."""
    reduzida, escala_x, escala_y = _redimensionar_para_preview(
        imagem,
        largura_max,
        altura_max,
    )
    if reduzida is None:
        return None

    saida = reduzida.copy()
    altura_original, largura_original = imagem.shape[:2]
    for led_original in tuple(leds or ()):
        try:
            led = _adaptar_led_para_imagem(
                led_original,
                largura_original,
                altura_original,
            )
            _desenhar_contorno_preview(saida, led, escala_x, escala_y)
        except Exception:
            continue
    return saida


def sobrepor_mascaras_preview_f2(imagem, leds):
    """Compatibilidade: desenha contornos na imagem sem redimensioná-la."""
    if imagem is None or getattr(imagem, "size", 0) == 0:
        return imagem
    saida = imagem.copy()
    altura, largura = saida.shape[:2]
    for led_original in tuple(leds or ()):
        try:
            led = _adaptar_led_para_imagem(led_original, largura, altura)
            _desenhar_contorno_preview(saida, led, 1.0, 1.0)
        except Exception:
            continue
    return saida


def _criar_photo_from_bgr(imagem):
    if imagem is None or getattr(imagem, "size", 0) == 0:
        return None
    sucesso, buffer = cv2.imencode(".png", imagem)
    if not sucesso:
        return None
    dados = base64.b64encode(buffer).decode("ascii")
    return tk.PhotoImage(data=dados)


def _aplicar_mascaras_nas_previews(controller, window) -> None:
    projeto = controller.project_name()
    if not projeto:
        return

    leds = _leds_do_projeto(controller, projeto)
    if not leds:
        return

    entries = controller._entries(projeto)
    photos = []

    for slot, titulo in F2_BOARD_MASK_PREVIEW_TITLES.items():
        entry = entries.get(slot, {})
        caminho = str(entry.get("image_path") or "").strip()
        image = cv2.imread(caminho) if caminho else None
        if image is None:
            continue

        preview_bgr = criar_imagem_preview_presenca_com_mascaras_f2(
            image,
            leds,
            largura_max=F2_BOARD_MASK_PREVIEW_WIDTH,
            altura_max=F2_BOARD_MASK_PREVIEW_HEIGHT,
        )
        photo = _criar_photo_from_bgr(preview_bgr)
        if photo is None:
            continue

        card = _encontrar_card_por_titulo(window, titulo)
        label = _encontrar_label_preview(card)
        if label is None:
            continue

        try:
            label.configure(image=photo, text="")
        except tk.TclError:
            continue
        photos.append(photo)

    # Mantém os PhotoImage vivos enquanto a janela existir.
    window._odin_f2_board_presence_mask_preview_tk = photos


def instalar_mascaras_previews_presenca_f2() -> None:
    """Envolve somente a renderização das Configurações do F2."""
    current = F2BoardPresenceReferenceController.render_settings
    if bool(getattr(current, "_odin_f2_board_presence_mask_preview", False)):
        return

    previous = current

    def render_settings_com_mascaras(self, window) -> None:
        result = previous(self, window)
        try:
            _aplicar_mascaras_nas_previews(self, window)
        except Exception:
            # Uma falha puramente visual não pode impedir Configurações nem F2.
            pass
        return result

    render_settings_com_mascaras._odin_f2_board_presence_mask_preview = True
    render_settings_com_mascaras._odin_f2_board_presence_mask_preview_base = previous
    F2BoardPresenceReferenceController.render_settings = render_settings_com_mascaras
