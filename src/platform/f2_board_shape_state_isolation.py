"""Isola o desenho físico da placa das máscaras fixas e da câmera do F2.

O editor de placa reutiliza infraestrutura antiga baseada em ``leds_selecionados``.
No jig Linux essa mesma lista também é republicada pela câmera e pelas guias dos
LEDs. O contorno passa, portanto, a possuir uma lista dedicada enquanto o editor
está aberto. A lista global permanece apenas como espelho visual.

Também filtramos contaminação legada de ``f2_board_shape`` quando as formas salvas
são cópias reais das ROIs fixas do mesmo projeto.
"""
from __future__ import annotations

import importlib
from typing import Iterable

from src.core.roi_geometry import (
    TIPO_ROI_SEGMENTO,
    normalizar_tipo_roi,
    pontos_segmento,
)
from src.models.led_selection import LedSelection
from src.platform.freeform_segment_roi import copiar_led_com_segmento_livre

import src.platform.f2_board_shape_editor as board_shape_editor


_PATCH_INSTALADO = False
_EDITOR_ROIS_ATTR = "_f2_board_shape_editor_rois"
_EDITOR_IMAGE_ATTR = "_f2_board_shape_editor_reference_image"
_EDITOR_PATH_ATTR = "_f2_board_shape_editor_reference_path"

_ORIGINAL_CARREGAR_CONTORNO = board_shape_editor.carregar_contorno_placa_leds
_ORIGINAL_ABRIR_EDITOR = board_shape_editor.abrir_editor_contorno_placa_f2


def _contexto_placa(app) -> dict | None:
    getter = getattr(board_shape_editor, "_contexto_editor_placa_ativo", None)
    if callable(getter):
        try:
            contexto = getter(app)
            return contexto if isinstance(contexto, dict) else None
        except Exception:
            return None
    contexto = getattr(app, "_f2_board_shape_edit_context", None)
    return contexto if isinstance(contexto, dict) else None


def _copiar_rois(rois: Iterable[LedSelection] | None) -> list[LedSelection]:
    resultado: list[LedSelection] = []
    for roi in tuple(rois or ()):
        try:
            resultado.append(copiar_led_com_segmento_livre(roi))
        except Exception:
            resultado.append(roi)
    return resultado


def _carregar_leds_fixos(controller, projeto: str) -> list[LedSelection]:
    repository = getattr(getattr(controller, "app", None), "config_repository", None)
    getter = getattr(repository, "carregar_leds_fixos", None)
    if not callable(getter):
        return []
    try:
        return list(getter(projeto=projeto) or ())
    except TypeError:
        try:
            return list(getter(projeto) or ())
        except Exception:
            return []
    except Exception:
        return []


def _mesma_geometria_roi(a, b) -> bool:
    """Reconhece uma ROI fixa copiada para o campo de contorno."""
    try:
        if str(getattr(a, "id", "")) != str(getattr(b, "id", "")):
            return False
        tipo_a = normalizar_tipo_roi(getattr(a, "tipo_roi", None))
        tipo_b = normalizar_tipo_roi(getattr(b, "tipo_roi", None))
        if tipo_a != tipo_b:
            return False
        if abs(int(getattr(a, "centro_x", 0)) - int(getattr(b, "centro_x", 0))) > 2:
            return False
        if abs(int(getattr(a, "centro_y", 0)) - int(getattr(b, "centro_y", 0))) > 2:
            return False
        if tipo_a != TIPO_ROI_SEGMENTO:
            return abs(int(getattr(a, "raio", 0)) - int(getattr(b, "raio", 0))) <= 2

        pontos_a = list(pontos_segmento(a))
        pontos_b = list(pontos_segmento(b))
        if len(pontos_a) != len(pontos_b):
            return False
        return all(
            abs(float(ax) - float(bx)) <= 2.0
            and abs(float(ay) - float(by)) <= 2.0
            for (ax, ay), (bx, by) in zip(pontos_a, pontos_b)
        )
    except Exception:
        return False


def filtrar_contaminacao_leds_f2(controller, projeto: str, rois) -> list[LedSelection]:
    """Retira apenas formas que coincidem com ROIs fixas reais do projeto."""
    formas = list(rois or ())
    if not formas:
        return []
    leds_fixos = _carregar_leds_fixos(controller, projeto)
    if not leds_fixos:
        return _copiar_rois(formas)

    limpas = []
    removidas = 0
    for forma in formas:
        if any(_mesma_geometria_roi(forma, led) for led in leds_fixos):
            removidas += 1
        else:
            limpas.append(forma)

    app = getattr(controller, "app", None)
    if app is not None:
        app._f2_board_shape_legacy_led_contamination = int(removidas)
    return _copiar_rois(limpas)


def carregar_contorno_placa_leds_isolado(
    controller,
    projeto: str,
    largura: int,
    altura: int,
):
    rois = _ORIGINAL_CARREGAR_CONTORNO(controller, projeto, largura, altura)
    return filtrar_contaminacao_leds_f2(controller, projeto, rois)


def _definir_rois_editor(app, rois) -> None:
    # O projeto F2 possui exatamente UM contorno físico. FreeformSegmentDrawing
    # cria a nova forma anexando-a à coleção existente; portanto filtramos aqui
    # e mantemos apenas o último polígono válido: o recém-desenhado substitui o
    # anterior imediatamente.
    filtrar = getattr(
        board_shape_editor,
        "_filtrar_rois_contorno_placa",
        None,
    )
    if callable(filtrar):
        try:
            rois = filtrar(rois)
        except Exception:
            pass

    dedicadas = _copiar_rois(rois)
    setattr(app, _EDITOR_ROIS_ATTR, dedicadas)

    contexto = _contexto_placa(app)
    if isinstance(contexto, dict):
        contexto["working_rois"] = _copiar_rois(dedicadas)

    app.leds_selecionados = _copiar_rois(dedicadas)
    app.resultados_led_atual = []


def _rois_editor(app) -> list[LedSelection]:
    dedicadas = getattr(app, _EDITOR_ROIS_ATTR, None)
    if dedicadas is not None:
        return _copiar_rois(dedicadas or ())

    contexto = _contexto_placa(app)
    if isinstance(contexto, dict):
        return _copiar_rois(contexto.get("working_rois", []) or ())
    return []


def _sincronizar_espelho_editor(app) -> list[LedSelection]:
    rois = _rois_editor(app)
    app.leds_selecionados = _copiar_rois(rois)
    app.resultados_led_atual = []
    return rois


def _restaurar_referencia_editor(app) -> None:
    """Mantém foto e ROIs do editor imunes à republicação da câmera Linux."""
    if _contexto_placa(app) is None:
        return
    app.camera_em_pausa_analise = True
    imagem = getattr(app, _EDITOR_IMAGE_ATTR, None)
    if imagem is not None and getattr(imagem, "size", 0):
        try:
            app.imagem_original = imagem
            altura, largura = imagem.shape[:2]
            app.altura_original = int(altura)
            app.largura_original = int(largura)
            app.caminho_imagem_atual = str(getattr(app, _EDITOR_PATH_ATTR, "") or "")
        except Exception:
            pass
    _sincronizar_espelho_editor(app)


def abrir_editor_contorno_placa_f2_isolado(controller, slot: str, settings_window) -> None:
    resultado = _ORIGINAL_ABRIR_EDITOR(controller, slot, settings_window)
    app = getattr(controller, "app", None)
    contexto = _contexto_placa(app) if app is not None else None
    if app is None or contexto is None:
        return resultado

    atuais = filtrar_contaminacao_leds_f2(
        controller,
        str(contexto.get("project") or ""),
        getattr(app, "leds_selecionados", []),
    )

    # "Desenhar placa" é uma sessão de REDESENHO. O contorno salvo permanece no
    # JSON até um novo SALVAR concluir com sucesso, mas o canvas começa limpo para
    # que a geometria antiga não fique embaixo da nova nem seja salva novamente
    # por engano.
    contexto["original_rois"] = _copiar_rois(atuais)
    contexto["redraw_session"] = True
    _definir_rois_editor(app, [])

    imagem = getattr(app, "imagem_original", None)
    if imagem is not None and getattr(imagem, "size", 0):
        try:
            setattr(app, _EDITOR_IMAGE_ATTR, imagem.copy())
        except Exception:
            setattr(app, _EDITOR_IMAGE_ATTR, imagem)
    else:
        setattr(app, _EDITOR_IMAGE_ATTR, None)
    setattr(app, _EDITOR_PATH_ATTR, str(getattr(app, "caminho_imagem_atual", "") or ""))
    _restaurar_referencia_editor(app)

    redesenhar = getattr(app, "_redesenhar_selecao_no_canvas_atual", None)
    if callable(redesenhar):
        try:
            redesenhar()
        except Exception:
            pass
        janela = getattr(app, "_selecao_tela_cheia_window", None)
        if janela is not None:
            try:
                janela.after(90, redesenhar)
            except Exception:
                pass
    return resultado


def _patch_aliases() -> None:
    board_shape_editor.carregar_contorno_placa_leds = carregar_contorno_placa_leds_isolado
    board_shape_editor.abrir_editor_contorno_placa_f2 = abrir_editor_contorno_placa_f2_isolado

    for nome in (
        "src.platform.f2_board_presence_mask_preview_native",
        "src.platform.f2_board_shape_runtime_authority",
        "src.platform.f2_object_tracking",
        "src.platform.f2_object_tracking_runtime_fix",
        "src.platform.f2_object_tracking_visual_overlay",
    ):
        try:
            modulo = importlib.import_module(nome)
        except Exception:
            continue
        if hasattr(modulo, "carregar_contorno_placa_leds"):
            modulo.carregar_contorno_placa_leds = carregar_contorno_placa_leds_isolado

    try:
        preview = importlib.import_module("src.platform.f2_board_presence_mask_preview_native")
        preview.abrir_editor_contorno_placa_f2 = abrir_editor_contorno_placa_f2_isolado
    except Exception:
        pass


def instalar_isolamento_estado_contorno_placa_f2() -> None:
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return

    from src.platform.raspberry_pi3_production_app import RaspberryPi3ProductionApp

    _patch_aliases()

    modo_atual = RaspberryPi3ProductionApp._modo_edicao_roi_ativo
    if not bool(getattr(modo_atual, "_odin_f2_board_state_mode", False)):
        modo_anterior = modo_atual

        def modo_com_estado_dedicado(self):
            if _contexto_placa(self) is not None:
                return True
            return modo_anterior(self)

        modo_com_estado_dedicado._odin_f2_board_state_mode = True
        RaspberryPi3ProductionApp._modo_edicao_roi_ativo = modo_com_estado_dedicado

    leds_atual = RaspberryPi3ProductionApp._leds_editaveis
    if not bool(getattr(leds_atual, "_odin_f2_board_state_leds", False)):
        leds_anterior = leds_atual

        def leds_com_estado_dedicado(self):
            if _contexto_placa(self) is not None:
                return _rois_editor(self)
            return leds_anterior(self)

        leds_com_estado_dedicado._odin_f2_board_state_leds = True
        RaspberryPi3ProductionApp._leds_editaveis = leds_com_estado_dedicado

    substituir_atual = RaspberryPi3ProductionApp._substituir_leds_editaveis
    if not bool(getattr(substituir_atual, "_odin_f2_board_state_replace", False)):
        substituir_anterior = substituir_atual

        def substituir_com_estado_dedicado(self, leds):
            if _contexto_placa(self) is not None:
                _definir_rois_editor(self, leds)
                return None
            return substituir_anterior(self, leds)

        substituir_com_estado_dedicado._odin_f2_board_state_replace = True
        RaspberryPi3ProductionApp._substituir_leds_editaveis = substituir_com_estado_dedicado

    camera_atual = RaspberryPi3ProductionApp.atualizar_frame_camera
    if not bool(getattr(camera_atual, "_odin_f2_board_state_camera_guard", False)):
        camera_anterior = camera_atual

        def atualizar_camera_com_guard_editor(self, *args, **kwargs):
            if _contexto_placa(self) is not None:
                self.camera_em_pausa_analise = True
            resultado = camera_anterior(self, *args, **kwargs)
            if _contexto_placa(self) is not None:
                _restaurar_referencia_editor(self)
            return resultado

        atualizar_camera_com_guard_editor._odin_f2_board_state_camera_guard = True
        RaspberryPi3ProductionApp.atualizar_frame_camera = atualizar_camera_com_guard_editor

    salvar_atual = board_shape_editor._salvar_e_fechar_editor_placa
    if not bool(getattr(salvar_atual, "_odin_f2_board_state_save", False)):
        salvar_anterior = salvar_atual

        def salvar_com_estado_dedicado(app):
            contexto_antes = _contexto_placa(app)
            if contexto_antes is not None:
                _sincronizar_espelho_editor(app)
            resultado = salvar_anterior(app)
            if contexto_antes is not None and _contexto_placa(app) is None:
                for atributo in (_EDITOR_ROIS_ATTR, _EDITOR_IMAGE_ATTR, _EDITOR_PATH_ATTR):
                    try:
                        delattr(app, atributo)
                    except Exception:
                        pass
            return resultado

        salvar_com_estado_dedicado._odin_f2_board_state_save = True
        board_shape_editor._salvar_e_fechar_editor_placa = salvar_com_estado_dedicado

    try:
        authority = importlib.import_module("src.platform.f2_board_shape_runtime_authority")
        salvar_final_atual = authority._salvar_por_autoridade_final
        if not bool(getattr(salvar_final_atual, "_odin_f2_board_state_authority", False)):
            salvar_final_anterior = salvar_final_atual

            def salvar_final_com_estado_dedicado(app):
                if _contexto_placa(app) is not None:
                    _sincronizar_espelho_editor(app)
                return salvar_final_anterior(app)

            salvar_final_com_estado_dedicado._odin_f2_board_state_authority = True
            authority._salvar_por_autoridade_final = salvar_final_com_estado_dedicado
    except Exception:
        pass

    _PATCH_INSTALADO = True
