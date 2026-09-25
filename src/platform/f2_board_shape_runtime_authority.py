from __future__ import annotations

"""Autoridade final do editor de contorno físico da placa no F2.

Este módulo existe para eliminar dependência da ordem histórica de mixins/patches no
jig Linux. Ele é instalado somente depois que ``DesktopProductionApp`` terminou
de inicializar e depois que o renderer nativo das referências F2 já está ativo.

Responsabilidades:
- o botão de confirmação do editor de placa é sempre ``SALVAR``;
- o clique em SALVAR entra diretamente no fluxo de persistência do contorno F2;
- um editor sem nenhuma forma fechada não pode ser salvo silenciosamente como zero;
- o status do contorno fica visível acima dos três cards de presença, e não abaixo
  deles onde pode ficar cortado em telas menores;
- ligada e desligada continuam lendo a mesma geometria compartilhada do projeto.
"""

import tkinter as tk
from tkinter import messagebox

import src.platform.f2_board_shape_editor as board_shape_editor
from src.platform.f2_board_presence_references import (
    F2BoardPresenceReferenceController,
)
from src.platform.f2_board_shape_confirm_fix import (
    finalizar_rascunho_contorno_placa_f2,
)
from src.platform.f2_board_shape_editor import carregar_contorno_placa_leds


_PATCH_INSTALADO = False


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


def _percorrer_widgets(widget):
    try:
        filhos = tuple(widget.winfo_children())
    except Exception:
        filhos = ()
    for filho in filhos:
        yield filho
        yield from _percorrer_widgets(filho)


def _personalizar_editor_final(app) -> None:
    janela = getattr(app, "_selecao_tela_cheia_window", None)
    if janela is None:
        return

    try:
        janela.title("ODIN • Desenho da placa F2")
    except Exception:
        pass

    for widget in _percorrer_widgets(janela):
        try:
            texto = str(widget.cget("text"))
        except Exception:
            continue
        try:
            if texto == "OK":
                widget.configure(text="SALVAR")
            elif texto == "SELEÇÃO E AJUSTE DE ROIs":
                widget.configure(text="DESENHO DA PLACA • F2")
            elif texto.startswith("Segmento: arraste para criar"):
                widget.configure(
                    text=(
                        "Contorne a placa com Segmento por pontos. Feche no primeiro "
                        "vértice e pressione SALVAR para gravar o mesmo contorno nas "
                        "referências ligada e desligada."
                    )
                )
        except Exception:
            pass


def _mostrar_erro_sem_forma(app) -> None:
    parent = getattr(app, "_selecao_tela_cheia_window", None)
    try:
        messagebox.showwarning(
            "Contorno não salvo",
            (
                "Nenhuma forma fechada foi encontrada no editor. Feche o contorno "
                "ponto a ponto e pressione SALVAR novamente."
            ),
            parent=parent,
        )
    except Exception:
        pass


def _salvar_por_autoridade_final(app) -> None:
    contexto = _contexto_placa(app)
    if contexto is None:
        return

    # Se ainda existir um rascunho por pontos, materializa-o antes de conferir a
    # lista real de ROIs. Para um contorno já fechado esta função é um no-op.
    try:
        if not finalizar_rascunho_contorno_placa_f2(app):
            return
    except Exception:
        return

    rois = list(getattr(app, "leds_selecionados", []) or ())
    if not rois:
        # Nunca mais permitir o caso silencioso editor=0 / arquivo=0 que fechava a
        # janela parecendo sucesso embora nada tivesse sido salvo.
        _mostrar_erro_sem_forma(app)
        return

    salvar = getattr(board_shape_editor, "_salvar_e_fechar_editor_placa", None)
    if not callable(salvar):
        try:
            messagebox.showerror(
                "Falha ao salvar desenho da placa",
                "A rotina de persistência do contorno F2 não está disponível.",
                parent=getattr(app, "_selecao_tela_cheia_window", None),
            )
        except Exception:
            pass
        return

    salvar(app)


def _obter_contorno(controller) -> tuple[str, list]:
    projeto = str(controller.project_name() or "").strip()
    if not projeto:
        return "", []
    resolution = controller.master_resolution(projeto)
    if not resolution:
        return projeto, []
    try:
        contorno = list(
            carregar_contorno_placa_leds(
                controller,
                projeto,
                int(resolution[0]),
                int(resolution[1]),
            )
            or ()
        )
    except Exception:
        contorno = []
    return projeto, contorno


def _injetar_status_contorno_visivel(controller, window) -> None:
    """Mostra o estado do contorno acima dos cards para não ficar cortado no Linux."""
    if window is None:
        return
    container = getattr(window, "_odin_f2_board_presence_container", None)
    if container is None:
        return

    anterior = getattr(window, "_odin_f2_board_shape_status_prominent", None)
    if anterior is not None:
        try:
            anterior.destroy()
        except Exception:
            pass

    projeto, contorno = _obter_contorno(controller)
    quantidade = len(contorno)
    if quantidade:
        texto = f"Contorno da placa: {quantidade} forma(s) compartilhada(s) • SALVO"
        cor = "#7DD3FC"
    else:
        texto = "Contorno da placa: NÃO SALVO • use 'Desenhar placa' em ligada ou desligada"
        cor = "#FBBF24"

    view = controller.app.view
    label = tk.Label(
        container,
        text=texto,
        font=("Segoe UI", 8, "bold"),
        fg=cor,
        bg=view.COR_CARD_2,
        anchor="w",
        justify=tk.LEFT,
    )

    # O renderer nativo cria como filhos diretos: separador, título, descrição,
    # grid de 3 cards e status inferiores. Insere antes do grid, onde permanece
    # visível mesmo em telas baixas do jig.
    grid = None
    try:
        for filho in tuple(container.winfo_children()):
            if filho is label:
                continue
            try:
                if isinstance(filho, tk.Frame) and len(filho.winfo_children()) >= 3:
                    grid = filho
                    break
            except Exception:
                continue
    except Exception:
        grid = None

    try:
        if grid is not None:
            label.pack(fill=tk.X, pady=(0, 8), before=grid)
        else:
            label.pack(fill=tk.X, pady=(4, 8))
    except Exception:
        return

    window._odin_f2_board_shape_status_prominent = label
    window._odin_f2_board_shape_status_count = quantidade
    window._odin_f2_board_shape_status_project = projeto


def instalar_autoridade_final_editor_contorno_f2() -> None:
    """Instala a autoridade por último, após toda a composição do app/renderer."""
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return

    from src.platform.desktop_production_app import DesktopProductionApp

    # 1) Confirmação final do fullscreen. Em contexto F2 não delega para a cadeia
    # histórica de seleção de LEDs; chama diretamente a persistência do contorno.
    confirmar_atual = DesktopProductionApp._confirmar_selecao_tela_cheia
    if not bool(getattr(confirmar_atual, "_odin_f2_board_shape_final_authority", False)):
        confirmar_anterior = confirmar_atual

        def confirmar_com_autoridade_final(self):
            if _contexto_placa(self) is not None:
                if bool(getattr(self, "_selecao_tela_cheia_fechando", False)):
                    return None
                self._selecao_tela_cheia_fechando = True
                try:
                    return _salvar_por_autoridade_final(self)
                finally:
                    self._selecao_tela_cheia_fechando = False
            return confirmar_anterior(self)

        confirmar_com_autoridade_final._odin_f2_board_shape_final_authority = True
        confirmar_com_autoridade_final._odin_f2_board_shape_final_authority_base = (
            confirmar_anterior
        )
        DesktopProductionApp._confirmar_selecao_tela_cheia = (
            confirmar_com_autoridade_final
        )

    # 2) Personaliza o botão durante a própria criação da janela. Assim o Linux
    # nunca chega a exibir um botão OK para este editor específico.
    criar_atual = DesktopProductionApp._criar_interface_selecao_tela_cheia
    if not bool(getattr(criar_atual, "_odin_f2_board_shape_save_button", False)):
        criar_anterior = criar_atual

        def criar_interface_com_salvar(self, *args, **kwargs):
            janela, canvas = criar_anterior(self, *args, **kwargs)
            if _contexto_placa(self) is not None:
                # Atributos já são definidos pelo chamador logo após este retorno;
                # personalizamos usando a janela retornada diretamente também.
                try:
                    self._selecao_tela_cheia_window = janela
                    _personalizar_editor_final(self)
                except Exception:
                    pass
            return janela, canvas

        criar_interface_com_salvar._odin_f2_board_shape_save_button = True
        criar_interface_com_salvar._odin_f2_board_shape_save_button_base = criar_anterior
        DesktopProductionApp._criar_interface_selecao_tela_cheia = (
            criar_interface_com_salvar
        )

    # 3) O status do contorno é desenhado depois do renderer nativo final. Isso
    # evita depender do status inferior, que pode ficar fora da área visível.
    render_atual = F2BoardPresenceReferenceController.render_settings
    if not bool(getattr(render_atual, "_odin_f2_board_shape_visible_status", False)):
        render_anterior = render_atual

        def render_com_status_visivel(self, window):
            resultado = render_anterior(self, window)
            try:
                _injetar_status_contorno_visivel(self, window)
            except Exception:
                pass
            return resultado

        render_com_status_visivel._odin_f2_board_shape_visible_status = True
        render_com_status_visivel._odin_f2_board_shape_visible_status_base = render_anterior
        F2BoardPresenceReferenceController.render_settings = render_com_status_visivel

    _PATCH_INSTALADO = True
