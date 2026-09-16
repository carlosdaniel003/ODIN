from __future__ import annotations

"""Mostra as máscaras/ROIs do projeto nas duas previews de placa do F2.

A alteração é somente visual na janela de Configurações. As referências salvas
continuam sendo as imagens originais completas, sem desenhos persistidos. A
preview de suporte vazio permanece limpa porque não existe placa/ROI a validar.

As máscaras são desenhadas como vetores Tk sobre a fotografia já reduzida. Isso
impede que os contornos desapareçam quando uma imagem 640x480 (ou maior) vira
uma miniatura e evita depender da substituição posterior do PhotoImage original.
"""

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
from src.platform.led_project_preview import _criar_photo_preview_real


F2_BOARD_MASK_PREVIEW_COLOR = "#38BDF8"
F2_BOARD_MASK_PREVIEW_SHADOW = "#020617"
F2_BOARD_MASK_PREVIEW_WIDTH = 180
F2_BOARD_MASK_PREVIEW_HEIGHT = 104
F2_BOARD_MASK_PREVIEW_TITLES = {
    F2_BOARD_REF_BOARD_ON: "1. Placa fixa ligada",
    F2_BOARD_REF_BOARD_OFF: "2. Placa fixa desligada",
}


def _percorrer_widgets(widget):
    try:
        filhos = tuple(widget.winfo_children())
    except Exception:
        filhos = ()
    for filho in filhos:
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


def _encontrar_frame_preview(card):
    """Localiza o quadro preto que originalmente contém a foto da referência."""
    if card is None:
        return None
    for widget in _percorrer_widgets(card):
        if not isinstance(widget, tk.Frame):
            continue
        try:
            if str(widget.cget("bg")).lower() == "#020617":
                return widget
        except (tk.TclError, AttributeError):
            continue
    return None


def _leds_direto_da_configuracao(controller, projeto: str):
    repository = getattr(controller.app, "config_repository", None)
    if repository is None:
        return []
    try:
        config = repository.carregar_configuracao_existente_sem_alerta()
    except Exception:
        return []
    if not isinstance(config, dict):
        return []

    projetos = config.get("led_projects", {})
    dados = projetos.get(projeto, {}) if isinstance(projetos, dict) else {}
    itens = dados.get("fixed_leds", []) if isinstance(dados, dict) else []

    # Projetos antigos também mantêm um espelho top-level das máscaras ativas.
    if not isinstance(itens, list) or not itens:
        itens = config.get("fixed_leds", [])
    if not isinstance(itens, list):
        return []

    leds = []
    for item in itens:
        try:
            led = item if isinstance(item, LedSelection) else LedSelection.from_dict(item)
        except Exception:
            led = None
        if led is not None:
            leds.append(led)
    return leds


def _leds_do_projeto(controller, projeto: str):
    """Obtém exatamente as ROIs que o F2 usa no projeto ativo.

    O estado já carregado no app é preferido porque é a mesma lista usada pelo
    runtime F2. Depois vêm repository/configuração para cobrir reconstruções da
    janela e projetos migrados.
    """
    runtime_leds = list(
        getattr(controller.app, "leds_fixos_configurados", []) or []
    )
    if runtime_leds:
        return runtime_leds

    repository = getattr(controller.app, "config_repository", None)
    getter = getattr(repository, "carregar_leds_fixos", None)
    if callable(getter):
        try:
            leds = list(getter(projeto=projeto) or [])
        except TypeError:
            try:
                leds = list(getter(projeto) or [])
            except TypeError:
                try:
                    leds = list(getter() or [])
                except Exception:
                    leds = []
            except Exception:
                leds = []
        except Exception:
            leds = []
        if leds:
            return leds

    return _leds_direto_da_configuracao(controller, projeto)


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


def _transformacao_preview(imagem) -> tuple[float, float, float, int, int]:
    altura, largura = imagem.shape[:2]
    escala = min(
        F2_BOARD_MASK_PREVIEW_WIDTH / float(max(1, largura)),
        F2_BOARD_MASK_PREVIEW_HEIGHT / float(max(1, altura)),
    )
    largura_desenho = max(1, int(round(largura * escala)))
    altura_desenho = max(1, int(round(altura * escala)))
    offset_x = (F2_BOARD_MASK_PREVIEW_WIDTH - largura_desenho) / 2.0
    offset_y = (F2_BOARD_MASK_PREVIEW_HEIGHT - altura_desenho) / 2.0
    return escala, offset_x, offset_y, largura_desenho, altura_desenho


def _projetar(x: float, y: float, escala: float, offset_x: float, offset_y: float):
    return offset_x + float(x) * escala, offset_y + float(y) * escala


def _desenhar_roi_canvas(canvas, led, escala: float, offset_x: float, offset_y: float):
    tipo = normalizar_tipo_roi(getattr(led, "tipo_roi", None))
    if tipo == TIPO_ROI_SEGMENTO:
        coords = []
        for ponto in pontos_segmento(led):
            x, y = _projetar(
                float(ponto[0]),
                float(ponto[1]),
                escala,
                offset_x,
                offset_y,
            )
            coords.extend((x, y))
        if len(coords) >= 6:
            canvas.create_polygon(
                *coords,
                fill="",
                outline=F2_BOARD_MASK_PREVIEW_SHADOW,
                width=4,
            )
            canvas.create_polygon(
                *coords,
                fill="",
                outline=F2_BOARD_MASK_PREVIEW_COLOR,
                width=2,
            )
        return

    centro_x, centro_y = _projetar(
        float(getattr(led, "centro_x", 0)),
        float(getattr(led, "centro_y", 0)),
        escala,
        offset_x,
        offset_y,
    )
    raio = max(2.5, float(getattr(led, "raio", 1) or 1) * escala)
    canvas.create_oval(
        centro_x - raio,
        centro_y - raio,
        centro_x + raio,
        centro_y + raio,
        fill="",
        outline=F2_BOARD_MASK_PREVIEW_SHADOW,
        width=4,
    )
    canvas.create_oval(
        centro_x - raio,
        centro_y - raio,
        centro_x + raio,
        centro_y + raio,
        fill="",
        outline=F2_BOARD_MASK_PREVIEW_COLOR,
        width=2,
    )


def _renderizar_preview_canvas(frame_preview, imagem, leds):
    """Substitui o label raster pela foto + máscaras vetoriais no mesmo canvas."""
    if frame_preview is None or imagem is None or getattr(imagem, "size", 0) == 0:
        return None

    for filho in tuple(frame_preview.winfo_children()):
        try:
            filho.destroy()
        except Exception:
            pass

    canvas = tk.Canvas(
        frame_preview,
        width=F2_BOARD_MASK_PREVIEW_WIDTH,
        height=F2_BOARD_MASK_PREVIEW_HEIGHT,
        bg="#020617",
        bd=0,
        relief=tk.FLAT,
        highlightthickness=0,
    )
    canvas.pack(expand=True)

    escala, offset_x, offset_y, largura_desenho, altura_desenho = (
        _transformacao_preview(imagem)
    )
    photo = _criar_photo_preview_real(
        imagem,
        largura_desenho,
        altura_desenho,
    )
    if photo is not None:
        canvas._odin_photo_preview = photo
        canvas.create_image(offset_x, offset_y, image=photo, anchor="nw")

    altura_original, largura_original = imagem.shape[:2]
    desenhadas = 0
    for led_original in tuple(leds or ()):
        try:
            led = _adaptar_led_para_imagem(
                led_original,
                largura_original,
                altura_original,
            )
            _desenhar_roi_canvas(canvas, led, escala, offset_x, offset_y)
            desenhadas += 1
        except Exception:
            continue

    # Não deixa uma falha de origem das ROIs parecer um problema de desenho.
    if desenhadas == 0:
        canvas.create_text(
            5,
            F2_BOARD_MASK_PREVIEW_HEIGHT - 5,
            anchor="sw",
            text="0 ROIs do projeto",
            fill="#FBBF24",
            font=("Segoe UI", 7, "bold"),
        )

    canvas._odin_f2_mask_count = desenhadas
    return canvas


def criar_imagem_preview_presenca_com_mascaras_f2(
    imagem,
    leds,
    largura_max: int = F2_BOARD_MASK_PREVIEW_WIDTH,
    altura_max: int = F2_BOARD_MASK_PREVIEW_HEIGHT,
):
    """Compatibilidade para testes/utilitários que esperam uma imagem BGR."""
    if imagem is None or getattr(imagem, "size", 0) == 0:
        return None
    altura, largura = imagem.shape[:2]
    escala = min(
        float(largura_max) / float(max(1, largura)),
        float(altura_max) / float(max(1, altura)),
    )
    largura_final = max(1, int(round(largura * escala)))
    altura_final = max(1, int(round(altura * escala)))
    reduzida = cv2.resize(
        imagem,
        (largura_final, altura_final),
        interpolation=cv2.INTER_AREA if escala < 1.0 else cv2.INTER_LINEAR,
    )
    saida = reduzida.copy()
    escala_x = largura_final / float(max(1, largura))
    escala_y = altura_final / float(max(1, altura))
    for led_original in tuple(leds or ()):
        try:
            led = _adaptar_led_para_imagem(led_original, largura, altura)
            tipo = normalizar_tipo_roi(getattr(led, "tipo_roi", None))
            cor = (248, 189, 56)
            sombra = (3, 7, 18)
            if tipo == TIPO_ROI_SEGMENTO:
                pts = pontos_segmento(led).astype(np.float32)
                pts[:, 0] *= escala_x
                pts[:, 1] *= escala_y
                pts = np.rint(pts).astype(np.int32)
                cv2.polylines(saida, [pts], True, sombra, 4, cv2.LINE_AA)
                cv2.polylines(saida, [pts], True, cor, 2, cv2.LINE_AA)
            else:
                centro = (
                    int(round(float(getattr(led, "centro_x", 0)) * escala_x)),
                    int(round(float(getattr(led, "centro_y", 0)) * escala_y)),
                )
                raio = max(
                    2,
                    int(round(float(getattr(led, "raio", 1) or 1) * min(escala_x, escala_y))),
                )
                cv2.circle(saida, centro, raio, sombra, 4, cv2.LINE_AA)
                cv2.circle(saida, centro, raio, cor, 2, cv2.LINE_AA)
        except Exception:
            continue
    return saida


def sobrepor_mascaras_preview_f2(imagem, leds):
    if imagem is None or getattr(imagem, "size", 0) == 0:
        return imagem
    altura, largura = imagem.shape[:2]
    return criar_imagem_preview_presenca_com_mascaras_f2(
        imagem,
        leds,
        largura_max=largura,
        altura_max=altura,
    )


def _aplicar_mascaras_nas_previews(controller, window) -> None:
    projeto = controller.project_name()
    if not projeto:
        return

    leds = _leds_do_projeto(controller, projeto)
    entries = controller._entries(projeto)
    canvases = []

    for slot, titulo in F2_BOARD_MASK_PREVIEW_TITLES.items():
        entry = entries.get(slot, {})
        caminho = str(entry.get("image_path") or "").strip()
        image = cv2.imread(caminho) if caminho else None
        if image is None:
            continue

        card = _encontrar_card_por_titulo(window, titulo)
        frame_preview = _encontrar_frame_preview(card)
        if frame_preview is None:
            continue

        canvas = _renderizar_preview_canvas(frame_preview, image, leds)
        if canvas is not None:
            canvases.append(canvas)

    window._odin_f2_board_presence_mask_preview_canvas = canvases
    window._odin_f2_board_presence_mask_count = len(leds)


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
