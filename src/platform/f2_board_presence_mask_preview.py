from __future__ import annotations

"""Mostra as máscaras/ROIs do projeto nas duas previews de placa do F2.

A alteração é somente visual na janela de Configurações. As referências salvas
continuam sendo as imagens originais completas, sem desenhos persistidos. A
preview de suporte vazio permanece limpa porque não existe placa/ROI a validar.
"""

import tkinter as tk

import cv2
import numpy as np

from src.core.roi_geometry import (
    TIPO_ROI_SEGMENTO,
    normalizar_tipo_roi,
    pontos_segmento,
)
from src.platform.f2_board_presence_references import (
    F2_BOARD_REF_BOARD_OFF,
    F2_BOARD_REF_BOARD_ON,
    F2BoardPresenceReferenceController,
)
from src.platform.reference_capture import _criar_photo_preview


F2_BOARD_MASK_PREVIEW_COLOR_BGR = (248, 189, 56)  # #38BDF8
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


def _leds_do_projeto(controller, projeto: str):
    repository = getattr(controller.app, "config_repository", None)
    getter = getattr(repository, "carregar_leds_fixos", None)
    if callable(getter):
        try:
            return list(getter(projeto) or [])
        except TypeError:
            try:
                return list(getter() or [])
            except Exception:
                pass
        except Exception:
            pass
    return list(getattr(controller.app, "leds_fixos_configurados", []) or [])


def sobrepor_mascaras_preview_f2(imagem, leds):
    """Desenha somente contornos neutros das ROIs nas coordenadas do projeto."""
    if imagem is None or getattr(imagem, "size", 0) == 0:
        return imagem

    saida = imagem.copy()
    altura, largura = saida.shape[:2]
    espessura = max(3, int(round(min(largura, altura) / 120.0)))

    for led in tuple(leds or ()):
        try:
            tipo = normalizar_tipo_roi(getattr(led, "tipo_roi", None))
            if tipo == TIPO_ROI_SEGMENTO:
                pontos = np.rint(pontos_segmento(led)).astype(np.int32)
                cv2.polylines(
                    saida,
                    [pontos],
                    True,
                    F2_BOARD_MASK_PREVIEW_COLOR_BGR,
                    espessura,
                    cv2.LINE_AA,
                )
            else:
                centro = (
                    int(getattr(led, "centro_x", 0)),
                    int(getattr(led, "centro_y", 0)),
                )
                raio = max(1, int(getattr(led, "raio", 1) or 1))
                cv2.circle(
                    saida,
                    centro,
                    raio,
                    F2_BOARD_MASK_PREVIEW_COLOR_BGR,
                    espessura,
                    cv2.LINE_AA,
                )
        except Exception:
            continue

    return saida


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

        anotada = sobrepor_mascaras_preview_f2(image, leds)
        photo = _criar_photo_preview(anotada, largura_max=180, altura_max=104)
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
