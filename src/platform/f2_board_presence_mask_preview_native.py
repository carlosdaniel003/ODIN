from __future__ import annotations

"""Renderer nativo das máscaras nas referências de presença do F2.

Esta camada substitui diretamente ``F2BoardPresenceReferenceController.render_settings``
depois que a aplicação inteira terminou de inicializar. Assim a própria criação das
previews de ``Placa fixa ligada`` e ``Placa fixa desligada`` já recebe a imagem com
as ROIs do projeto desenhadas em memória. Não há busca posterior de widgets, não há
reaplicação por timer e nenhum arquivo de referência é modificado.
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
    F2_BOARD_REF_EMPTY,
    F2_BOARD_REF_SLOTS,
    F2BoardPresenceReferenceController,
    _SLOT_UI,
    normalizar_referencias_presenca,
)
from src.platform.reference_capture import (
    _criar_photo_preview,
    _encontrar_corpo_referencias,
)


F2_PRESENCE_MASK_COLOR_BGR = (21, 204, 250)  # #FACC15, igual ao preview do projeto
F2_PRESENCE_MASK_SHADOW_BGR = (2, 6, 23)
F2_PRESENCE_MASK_SHADOW_THICKNESS = 8
F2_PRESENCE_MASK_THICKNESS = 4

_PATCH_INSTALADO = False


def _carregar_rois_do_projeto(controller, projeto: str):
    """Usa a mesma fonte do gerenciador 'Carregar LEDs': o repositório do projeto."""
    repository = getattr(controller.app, "config_repository", None)
    getter = getattr(repository, "carregar_leds_fixos", None)
    if callable(getter):
        try:
            return list(getter(projeto=projeto) or [])
        except TypeError:
            try:
                return list(getter(projeto) or [])
            except Exception:
                pass
        except Exception:
            pass

    # Fallback somente para projetos antigos já carregados no runtime.
    for nome in ("leds_fixos_configurados", "operacao_leds_preview"):
        itens = getattr(controller.app, nome, None)
        if itens:
            try:
                return list(itens)
            except Exception:
                pass
    return []


def _adaptar_roi_para_referencia(led, largura: int, altura: int):
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


def desenhar_rois_na_referencia_f2(imagem, leds):
    """Retorna cópia BGR com as ROIs amarelas; nunca altera a referência original."""
    if imagem is None or getattr(imagem, "size", 0) == 0:
        return imagem, 0

    saida = imagem.copy()
    altura, largura = saida.shape[:2]
    desenhadas = 0

    for led_original in tuple(leds or ()):
        try:
            led = _adaptar_roi_para_referencia(led_original, largura, altura)
            tipo = normalizar_tipo_roi(getattr(led, "tipo_roi", None))

            if tipo == TIPO_ROI_SEGMENTO:
                pontos = np.rint(pontos_segmento(led)).astype(np.int32)
                if len(pontos) < 3:
                    continue
                cv2.polylines(
                    saida,
                    [pontos],
                    True,
                    F2_PRESENCE_MASK_SHADOW_BGR,
                    F2_PRESENCE_MASK_SHADOW_THICKNESS,
                    cv2.LINE_AA,
                )
                cv2.polylines(
                    saida,
                    [pontos],
                    True,
                    F2_PRESENCE_MASK_COLOR_BGR,
                    F2_PRESENCE_MASK_THICKNESS,
                    cv2.LINE_AA,
                )
            else:
                centro = (
                    int(getattr(led, "centro_x", 0)),
                    int(getattr(led, "centro_y", 0)),
                )
                raio = max(2, int(getattr(led, "raio", 2) or 2))
                cv2.circle(
                    saida,
                    centro,
                    raio,
                    F2_PRESENCE_MASK_SHADOW_BGR,
                    F2_PRESENCE_MASK_SHADOW_THICKNESS,
                    cv2.LINE_AA,
                )
                cv2.circle(
                    saida,
                    centro,
                    raio,
                    F2_PRESENCE_MASK_COLOR_BGR,
                    F2_PRESENCE_MASK_THICKNESS,
                    cv2.LINE_AA,
                )
            desenhadas += 1
        except Exception:
            continue

    return saida, desenhadas


def _render_settings_com_mascaras(self, window) -> None:
    """Cópia deliberada do renderer oficial, com overlay nativo nas duas fotos da placa."""
    if window is None:
        return
    body = _encontrar_corpo_referencias(window)
    if body is None:
        return

    previous = getattr(window, "_odin_f2_board_presence_container", None)
    if previous is not None:
        try:
            previous.destroy()
        except Exception:
            pass

    view = self.app.view
    container = tk.Frame(body, bg=view.COR_CARD_2)
    container.pack(fill=tk.X, padx=12, pady=(2, 12))
    window._odin_f2_board_presence_container = container

    tk.Frame(container, bg="#172033", height=1).pack(fill=tk.X, pady=(0, 10))
    tk.Label(
        container,
        text="Presença da placa — F2 automático",
        font=("Segoe UI", 10, "bold"),
        fg=view.COR_TEXTO,
        bg=view.COR_CARD_2,
        anchor="w",
    ).pack(fill=tk.X, pady=(0, 4))

    projeto = self.project_name()
    resolution = self.master_resolution(projeto) if projeto else None
    resolution_text = (
        f"{resolution[0]}x{resolution[1]}"
        if resolution is not None
        else "resolução mestre não definida"
    )
    tk.Label(
        container,
        text=(
            f"Projeto ativo: {projeto or 'SEM PROJETO'} • {resolution_text}. "
            "Salve três imagens completas da câmera: placa ligada, placa desligada e suporte vazio. "
            "Estas imagens pertencem somente a este projeto LED e são usadas para decidir presença/retirada da placa."
        ),
        font=("Segoe UI", 8),
        fg=view.COR_TEXTO_2,
        bg=view.COR_CARD_2,
        wraplength=690,
        justify=tk.LEFT,
        anchor="w",
    ).pack(fill=tk.X, pady=(0, 9))

    entries = self._entries(projeto) if projeto else normalizar_referencias_presenca({})
    leds = _carregar_rois_do_projeto(self, projeto) if projeto else []

    grid = tk.Frame(container, bg=view.COR_CARD_2)
    grid.pack(fill=tk.X)
    for column in range(3):
        grid.grid_columnconfigure(column, weight=1, uniform="f2_board_refs")

    photos = []
    overlay_counts = {}

    for column, slot in enumerate(F2_BOARD_REF_SLOTS):
        ui = _SLOT_UI[slot]
        entry = entries.get(slot, {})
        card = tk.Frame(
            grid,
            bg=view.COR_CARD,
            highlightthickness=1,
            highlightbackground=view.COR_BORDA,
        )
        card.grid(
            row=0,
            column=column,
            sticky="nsew",
            padx=(0 if column == 0 else 5, 0 if column == 2 else 5),
        )
        tk.Label(
            card,
            text=ui["title"],
            font=("Segoe UI", 8, "bold"),
            fg=ui["color"],
            bg=view.COR_CARD,
            anchor="w",
        ).pack(fill=tk.X, padx=7, pady=(7, 4))

        preview = tk.Frame(card, bg="#020617", height=112)
        preview.pack(fill=tk.X, padx=7)
        preview.pack_propagate(False)

        image = cv2.imread(str(entry.get("image_path") or "")) if entry else None
        image_preview = image
        desenhadas = 0
        if slot in {F2_BOARD_REF_BOARD_ON, F2_BOARD_REF_BOARD_OFF}:
            image_preview, desenhadas = desenhar_rois_na_referencia_f2(image, leds)
        overlay_counts[slot] = desenhadas

        photo = _criar_photo_preview(image_preview, largura_max=180, altura_max=104)
        if photo is not None:
            photos.append(photo)
            tk.Label(preview, image=photo, bg="#020617", bd=0).pack(
                fill=tk.BOTH,
                expand=True,
            )
        else:
            tk.Label(
                preview,
                text="SEM IMAGEM",
                font=("Segoe UI", 8, "bold"),
                fg=view.COR_TEXTO_3,
                bg="#020617",
            ).pack(fill=tk.BOTH, expand=True)

        state = tk.NORMAL if projeto and resolution is not None else tk.DISABLED
        actions = tk.Frame(card, bg=view.COR_CARD)
        actions.pack(fill=tk.X, padx=7, pady=6)
        tk.Button(
            actions,
            text="Capturar câmera",
            state=state,
            command=lambda s=slot, w=window: self.capture_current(s, w),
            font=("Segoe UI", 7, "bold"),
            bg=view.COR_CARD_2,
            fg=view.COR_TEXTO,
            disabledforeground=view.COR_TEXTO_3,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=5,
            pady=4,
        ).pack(fill=tk.X)
        tk.Button(
            actions,
            text="Carregar imagem",
            state=state,
            command=lambda s=slot, w=window: self.load_file(s, w),
            font=("Segoe UI", 7),
            bg=view.COR_CARD_2,
            fg=view.COR_TEXTO_2,
            disabledforeground=view.COR_TEXTO_3,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=5,
            pady=3,
        ).pack(fill=tk.X, pady=(3, 0))
        if entry:
            tk.Button(
                actions,
                text="Remover",
                command=lambda s=slot, w=window: self.remove(s, w),
                font=("Segoe UI", 7),
                bg=view.COR_CARD,
                fg="#FCA5A5",
                relief=tk.FLAT,
                bd=0,
                cursor="hand2",
                padx=5,
                pady=3,
            ).pack(fill=tk.X, pady=(3, 0))

    window._odin_f2_board_presence_preview_tk = photos
    window._odin_f2_board_presence_preview_roi_count = len(leds)
    window._odin_f2_board_presence_preview_overlay_counts = overlay_counts

    ready = self._ensure_classifier()
    tk.Label(
        container,
        text=(
            "Status: 3/3 referências prontas para identificação visual."
            if ready
            else "Status: complete os 3 slots para ativar a identificação visual por projeto."
        ),
        font=("Segoe UI", 8, "bold"),
        fg="#86EFAC" if ready else "#FBBF24",
        bg=view.COR_CARD_2,
        anchor="w",
    ).pack(fill=tk.X, pady=(8, 0))

    try:
        window.update_idletasks()
    except Exception:
        pass


def instalar_renderer_nativo_mascaras_previews_presenca_f2() -> None:
    """Troca somente o renderer visual das referências de presença do F2."""
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return

    current = F2BoardPresenceReferenceController.render_settings
    if bool(getattr(current, "_odin_f2_native_mask_preview", False)):
        _PATCH_INSTALADO = True
        return

    _render_settings_com_mascaras._odin_f2_native_mask_preview = True
    _render_settings_com_mascaras._odin_f2_native_mask_preview_base = current
    F2BoardPresenceReferenceController.render_settings = _render_settings_com_mascaras
    _PATCH_INSTALADO = True
