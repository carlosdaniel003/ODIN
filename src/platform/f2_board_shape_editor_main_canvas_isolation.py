from __future__ import annotations

"""Evita que a referência usada em "Desenhar placa" vaze para a tela principal.

O editor de contorno reutiliza temporariamente o estado visual do ODIN para abrir o
editor fullscreen. Ao fechar, a tela de desenvolvimento deve voltar exatamente ao
estado visual que possuía antes da edição. Em especial, se "Imagem principal ao
vivo" estava vazia, a foto de referência da placa não pode permanecer ali.
"""

import copy

import src.platform.f2_board_shape_editor as board_shape_editor


_PATCH_INSTALADO = False
_SNAPSHOT_VIEW_IMAGE_KEY = "_f2_board_shape_view_image_before"
_SNAPSHOT_VIEW_RESOLUTION_KEY = "_f2_board_shape_view_resolution_before"


def _copiar_imagem(imagem):
    if imagem is None:
        return None
    try:
        return imagem.copy()
    except Exception:
        return imagem


def _limpar_imagem_principal_view(view, resolucao_anterior: str = "--") -> None:
    """Restaura o estado realmente vazio da imagem principal."""
    view.imagem_canvas_original = None
    view.imagem_exibicao = None
    view.imagem_tk = None
    view.lupa_tk = None
    view._imagem_tk_largura = None
    view._imagem_tk_altura = None
    view._imagem_render_largura = 0
    view._imagem_render_altura = 0
    view._imagem_render_offset_x = 0
    view._imagem_render_offset_y = 0
    view.escala_exibicao = 1.0
    view.deslocamento_imagem_x = 0
    view.deslocamento_imagem_y = 0
    view.largura_imagem_exibida = 0
    view.altura_imagem_exibida = 0
    view.ultimo_led_selecionado = None
    view.ultimo_resultado_led_atual = None
    view.resolucao_atual = str(resolucao_anterior or "--")

    label_resolucao = getattr(view, "label_meta_resolucao", None)
    if label_resolucao is not None:
        try:
            label_resolucao.configure(text=view.resolucao_atual)
        except Exception:
            pass

    limpar_lupa = getattr(view, "limpar_lupa_canvas", None)
    if callable(limpar_lupa):
        try:
            limpar_lupa()
        except Exception:
            pass

    desenhar = getattr(view, "desenhar_canvas", None)
    if callable(desenhar):
        try:
            desenhar([], [])
            return
        except Exception:
            pass

    canvas = getattr(view, "canvas", None)
    if canvas is not None:
        try:
            canvas.delete("all")
        except Exception:
            pass


def instalar_isolamento_imagem_principal_editor_placa_f2() -> None:
    """Preserva/restaura a tela principal sem alterar o editor fullscreen."""
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return

    snapshot_atual = board_shape_editor._snapshot_contexto_app
    restore_atual = board_shape_editor._restaurar_contexto_app

    if bool(getattr(snapshot_atual, "_odin_f2_board_main_canvas_isolation", False)):
        _PATCH_INSTALADO = True
        return

    def snapshot_com_view(app) -> dict:
        snapshot = snapshot_atual(app)
        view = getattr(app, "view", None)
        if view is not None:
            snapshot[_SNAPSHOT_VIEW_IMAGE_KEY] = _copiar_imagem(
                getattr(view, "imagem_canvas_original", None)
            )
            snapshot[_SNAPSHOT_VIEW_RESOLUTION_KEY] = str(
                getattr(view, "resolucao_atual", "--") or "--"
            )
        else:
            snapshot[_SNAPSHOT_VIEW_IMAGE_KEY] = None
            snapshot[_SNAPSHOT_VIEW_RESOLUTION_KEY] = "--"
        return snapshot

    def restaurar_com_view(app, snapshot: dict) -> None:
        restore_atual(app, snapshot)
        view = getattr(app, "view", None)
        if view is None:
            return

        imagem_anterior = snapshot.get(_SNAPSHOT_VIEW_IMAGE_KEY)
        resolucao_anterior = str(
            snapshot.get(_SNAPSHOT_VIEW_RESOLUTION_KEY, "--") or "--"
        )

        if imagem_anterior is None or getattr(imagem_anterior, "size", 0) == 0:
            _limpar_imagem_principal_view(view, resolucao_anterior)
            return

        # Se havia uma imagem principal legítima antes de abrir o editor, restaura
        # aquela imagem — nunca a referência temporária usada para desenhar a placa.
        try:
            view.imagem_tk = None
            view._imagem_tk_largura = None
            view._imagem_tk_altura = None
            view.preparar_imagem_para_exibicao(_copiar_imagem(imagem_anterior))
            view.desenhar_canvas(
                copy.deepcopy(getattr(app, "leds_selecionados", [])),
                copy.deepcopy(getattr(app, "resultados_led_atual", [])),
            )
        except Exception:
            _limpar_imagem_principal_view(view, resolucao_anterior)

    snapshot_com_view._odin_f2_board_main_canvas_isolation = True
    snapshot_com_view._odin_f2_board_main_canvas_isolation_base = snapshot_atual
    restaurar_com_view._odin_f2_board_main_canvas_isolation = True
    restaurar_com_view._odin_f2_board_main_canvas_isolation_base = restore_atual

    board_shape_editor._snapshot_contexto_app = snapshot_com_view
    board_shape_editor._restaurar_contexto_app = restaurar_com_view
    _PATCH_INSTALADO = True
