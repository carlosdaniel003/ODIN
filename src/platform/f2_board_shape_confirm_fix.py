from __future__ import annotations

"""Confirmação robusta do desenho físico da placa no editor F2.

No editor por pontos o traçado azul ainda é apenas um rascunho enquanto o
operador não clica novamente perto do primeiro vértice. No jig Linux era comum
o operador terminar o contorno e pressionar OK diretamente; nesse caso o
rascunho era visível na tela, mas ainda não fazia parte de ``leds_selecionados``
e o salvamento persistia zero formas.

Esta camada faz o botão OK fechar automaticamente um rascunho válido com três
ou mais vértices antes do salvamento. Rascunhos incompletos permanecem abertos
com aviso. Depois de salvar, o cache visual/rastreador F2 é invalidado para que
o novo contorno seja usado imediatamente. Nenhum fluxo do F3 é alterado.
"""

from tkinter import messagebox

import src.platform.f2_board_shape_editor as board_shape_editor


_PATCH_INSTALADO = False


def _parent_editor(app):
    return (
        getattr(app, "_selecao_tela_cheia_window", None)
        or getattr(
            getattr(app, "_f2_board_shape_edit_context", {}) or {},
            "get",
            lambda *_: None,
        )("settings_window")
    )


def finalizar_rascunho_contorno_placa_f2(app) -> bool:
    """Materializa o polígono ainda aberto antes de o OK persistir o contorno."""
    pontos = list(getattr(app, "_segmento_livre_pontos", []) or ())
    if not pontos:
        return True

    parent = _parent_editor(app)
    if len(pontos) < 3:
        try:
            messagebox.showwarning(
                "Contorno incompleto",
                "O desenho da placa precisa de pelo menos 3 vértices. "
                "Continue o contorno antes de pressionar OK.",
                parent=parent,
            )
        except Exception:
            pass
        return False

    finalizar = getattr(app, "_finalizar_segmento_livre", None)
    if not callable(finalizar):
        try:
            messagebox.showerror(
                "Falha ao confirmar contorno",
                "O editor não conseguiu finalizar o desenho por pontos.",
                parent=parent,
            )
        except Exception:
            pass
        return False

    antes = len(list(getattr(app, "leds_selecionados", []) or ()))
    try:
        finalizar()
    except Exception as exc:
        try:
            messagebox.showerror(
                "Falha ao confirmar contorno",
                str(exc),
                parent=parent,
            )
        except Exception:
            pass
        return False

    pendentes = list(getattr(app, "_segmento_livre_pontos", []) or ())
    depois = len(list(getattr(app, "leds_selecionados", []) or ()))
    if pendentes or depois <= antes:
        try:
            messagebox.showwarning(
                "Contorno não concluído",
                "O desenho ainda não pôde ser fechado. Confira se o contorno "
                "possui área válida e está totalmente dentro da imagem.",
                parent=parent,
            )
        except Exception:
            pass
        return False

    return True


def _invalidar_tracking_apos_salvar(app) -> None:
    """Força o próximo F2 a reconstruir a geometria a partir do contorno salvo."""
    try:
        app._f2_tracking_visual_geometry_cache = None
    except Exception:
        pass

    tracker = getattr(app, "_f2_object_tracker", None)
    reset = getattr(tracker, "reset", None)
    if callable(reset):
        try:
            reset()
        except Exception:
            pass


def instalar_correcao_confirmacao_contorno_placa_f2() -> None:
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return

    current = board_shape_editor._salvar_e_fechar_editor_placa
    if bool(getattr(current, "_odin_f2_board_shape_confirm_fix", False)):
        _PATCH_INSTALADO = True
        return

    previous = current

    def salvar_com_rascunho_materializado(app):
        contexto_antes = getattr(app, "_f2_board_shape_edit_context", None)
        if isinstance(contexto_antes, dict):
            if not finalizar_rascunho_contorno_placa_f2(app):
                return None

        result = previous(app)

        # O salvamento original limpa o contexto somente quando concluiu de fato.
        # Se ainda existe contexto, houve erro e não devemos invalidar o tracker.
        if (
            isinstance(contexto_antes, dict)
            and getattr(app, "_f2_board_shape_edit_context", None) is None
        ):
            _invalidar_tracking_apos_salvar(app)
        return result

    salvar_com_rascunho_materializado._odin_f2_board_shape_confirm_fix = True
    salvar_com_rascunho_materializado._odin_f2_board_shape_confirm_fix_base = previous
    board_shape_editor._salvar_e_fechar_editor_placa = salvar_com_rascunho_materializado
    _PATCH_INSTALADO = True
