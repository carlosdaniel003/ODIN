from __future__ import annotations

"""Overlay final e diagnosticável das máscaras nas referências de presença F2.

Este módulo existe porque a janela de Configurações é composta por vários mixins.
Em vez de depender de qual mixin renderizou por último, o patch envolve diretamente
RaspberryPi3ProductionApp.abrir_configuracoes e substitui somente o conteúdo visual
dos dois quadros de referência com placa depois que a janela já existe.

As imagens persistidas não são alteradas. O overlay é gerado em memória.
"""

import base64
import tkinter as tk

import cv2

from src.core.roi_geometry import roi_dentro_imagem
from src.platform.f2_board_presence_mask_preview import (
    F2_BOARD_MASK_PREVIEW_HEIGHT,
    F2_BOARD_MASK_PREVIEW_TITLES,
    F2_BOARD_MASK_PREVIEW_WIDTH,
    _adaptar_led_para_imagem,
    _leds_do_projeto,
    criar_imagem_preview_presenca_com_mascaras_f2,
)


_PATCH_INSTALADO = False


def _percorrer_widgets(widget):
    try:
        filhos = tuple(widget.winfo_children())
    except Exception:
        filhos = ()
    for filho in filhos:
        yield filho
        yield from _percorrer_widgets(filho)


def _card_por_titulo(container, titulo: str):
    if container is None:
        return None
    for widget in _percorrer_widgets(container):
        if not isinstance(widget, tk.Label):
            continue
        try:
            if str(widget.cget("text")) == str(titulo):
                return widget.master
        except Exception:
            continue
    return None


def _frame_preview_do_card(card):
    if card is None:
        return None

    # O renderer oficial cria o quadro preto como filho direto do card.
    try:
        filhos = tuple(card.winfo_children())
    except Exception:
        filhos = ()
    for widget in filhos:
        if not isinstance(widget, tk.Frame):
            continue
        try:
            if str(widget.cget("bg")).lower() == "#020617":
                return widget
        except Exception:
            continue

    # Fallback para eventual mudança de hierarquia visual.
    for widget in _percorrer_widgets(card):
        if not isinstance(widget, tk.Frame):
            continue
        try:
            if str(widget.cget("bg")).lower() == "#020617":
                return widget
        except Exception:
            continue
    return None


def _photo_bgr(imagem):
    if imagem is None or getattr(imagem, "size", 0) == 0:
        return None
    ok, buffer = cv2.imencode(".png", imagem)
    if not ok:
        return None
    return tk.PhotoImage(data=base64.b64encode(buffer).decode("ascii"))


def _contar_rois_visiveis(leds, largura: int, altura: int) -> int:
    total = 0
    for led_original in tuple(leds or ()):
        try:
            led = _adaptar_led_para_imagem(led_original, largura, altura)
            if roi_dentro_imagem(led, largura, altura):
                total += 1
        except Exception:
            continue
    return total


def _renderizar_overlay_final(app, window) -> dict:
    diagnostico = {
        "project": "",
        "roi_count": 0,
        "visible_roi_count": 0,
        "rendered_slots": 0,
        "error": None,
    }
    if window is None:
        diagnostico["error"] = "settings_window_missing"
        return diagnostico

    try:
        if not bool(window.winfo_exists()):
            diagnostico["error"] = "settings_window_closed"
            return diagnostico
    except Exception as exc:
        diagnostico["error"] = repr(exc)
        return diagnostico

    controller = getattr(app, "_f2_board_presence_refs", None)
    if controller is None:
        diagnostico["error"] = "presence_controller_missing"
        return diagnostico

    try:
        projeto = str(controller.project_name() or "").strip()
        diagnostico["project"] = projeto
        if not projeto:
            diagnostico["error"] = "active_project_missing"
            return diagnostico

        leds = list(_leds_do_projeto(controller, projeto) or [])
        diagnostico["roi_count"] = len(leds)
        entries = controller._entries(projeto)
        container = getattr(window, "_odin_f2_board_presence_container", None)
        if container is None:
            diagnostico["error"] = "presence_container_missing"
            return diagnostico

        photos = []
        canvases = []
        visiveis_max = 0

        for slot, titulo in F2_BOARD_MASK_PREVIEW_TITLES.items():
            entry = entries.get(slot, {})
            caminho = str(entry.get("image_path") or "").strip()
            imagem = cv2.imread(caminho) if caminho else None
            if imagem is None or getattr(imagem, "size", 0) == 0:
                continue

            altura, largura = imagem.shape[:2]
            visiveis = _contar_rois_visiveis(leds, largura, altura)
            visiveis_max = max(visiveis_max, visiveis)

            # Gera a miniatura já com as máscaras gravadas SOMENTE em memória.
            # Assim não dependemos de ordem/z-index entre PhotoImage e vetores Tk.
            preview = criar_imagem_preview_presenca_com_mascaras_f2(
                imagem,
                leds,
                largura_max=F2_BOARD_MASK_PREVIEW_WIDTH,
                altura_max=F2_BOARD_MASK_PREVIEW_HEIGHT,
            )
            photo = _photo_bgr(preview)
            if photo is None:
                continue

            card = _card_por_titulo(container, titulo)
            frame_preview = _frame_preview_do_card(card)
            if frame_preview is None:
                continue

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

            ph = int(preview.shape[0])
            pw = int(preview.shape[1])
            offset_x = (F2_BOARD_MASK_PREVIEW_WIDTH - pw) / 2.0
            offset_y = (F2_BOARD_MASK_PREVIEW_HEIGHT - ph) / 2.0
            canvas.create_image(offset_x, offset_y, image=photo, anchor="nw")
            canvas._odin_photo_preview = photo

            # Diagnóstico só aparece quando algo está objetivamente errado.
            if not leds:
                canvas.create_text(
                    5,
                    F2_BOARD_MASK_PREVIEW_HEIGHT - 5,
                    anchor="sw",
                    text="0 ROIs carregadas",
                    fill="#FBBF24",
                    font=("Segoe UI", 7, "bold"),
                )
            elif visiveis == 0:
                canvas.create_text(
                    5,
                    F2_BOARD_MASK_PREVIEW_HEIGHT - 5,
                    anchor="sw",
                    text=f"{len(leds)} ROIs fora da referência",
                    fill="#FCA5A5",
                    font=("Segoe UI", 7, "bold"),
                )

            photos.append(photo)
            canvases.append(canvas)

        diagnostico["visible_roi_count"] = visiveis_max
        diagnostico["rendered_slots"] = len(canvases)
        if len(canvases) != len(F2_BOARD_MASK_PREVIEW_TITLES):
            diagnostico["error"] = f"rendered_slots={len(canvases)}"

        window._odin_f2_board_presence_mask_preview_final_photos = photos
        window._odin_f2_board_presence_mask_preview_final_canvases = canvases
        window._odin_f2_board_presence_mask_preview_diagnostic = diagnostico
        return diagnostico
    except Exception as exc:
        diagnostico["error"] = repr(exc)
        try:
            window._odin_f2_board_presence_mask_preview_diagnostic = diagnostico
        except Exception:
            pass
        return diagnostico


def _agendar_render_final(app, window) -> None:
    if window is None:
        return

    def aplicar():
        diag = _renderizar_overlay_final(app, window)
        # Telemetria explícita no console: se ainda houver problema, saberemos se
        # foi origem das ROIs, coordenadas ou localização do widget.
        try:
            print(
                "[F2 MASK PREVIEW] "
                f"project={diag.get('project')!r} "
                f"rois={diag.get('roi_count')} "
                f"visible={diag.get('visible_roi_count')} "
                f"slots={diag.get('rendered_slots')} "
                f"error={diag.get('error')!r}"
            )
        except Exception:
            pass

    aplicar()
    for atraso_ms in (0, 80, 220):
        try:
            window.after(atraso_ms, aplicar)
        except Exception:
            pass


def instalar_reaplicacao_tardia_mascaras_previews_f2() -> None:
    """Instala o hook no método FINAL da aplicação, acima de toda a MRO."""
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return

    # Import tardio evita ciclo durante a definição da classe principal.
    from src.platform.raspberry_pi3_production_app import RaspberryPi3ProductionApp

    current = RaspberryPi3ProductionApp.abrir_configuracoes
    if bool(getattr(current, "_odin_f2_mask_preview_final_hook", False)):
        _PATCH_INSTALADO = True
        return

    previous = current

    def abrir_configuracoes_com_overlay_final(self):
        result = previous(self)

        finder = getattr(self, "_encontrar_janela_configuracoes_aberta", None)
        window = None
        if callable(finder):
            try:
                window = finder()
            except Exception:
                window = None

        _agendar_render_final(self, window)
        return result

    abrir_configuracoes_com_overlay_final._odin_f2_mask_preview_final_hook = True
    abrir_configuracoes_com_overlay_final._odin_f2_mask_preview_final_hook_base = previous
    RaspberryPi3ProductionApp.abrir_configuracoes = abrir_configuracoes_com_overlay_final
    _PATCH_INSTALADO = True
