from __future__ import annotations

"""Editor compartilhado do contorno físico da placa para o F2.

O contorno pertence ao Projeto LED, não à foto ligada/desligada. Qualquer um dos
botões "Desenhar placa" abre o mesmo editor de ROIs já usado pelo ODIN, sobre a
referência escolhida como fundo. Ao confirmar, a mesma geometria passa a ser
exibida nas duas referências com placa.

Nenhuma referência de presença é modificada em disco; somente a geometria do
contorno é persistida no JSON do projeto.
"""

import copy
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox

import cv2

from src.models.led_selection import LedSelection
from src.platform.bulk_roi_editor import BulkRoiEditorMixin
from src.platform.f2_board_presence_references import (
    F2_BOARD_REF_BOARD_OFF,
    F2_BOARD_REF_BOARD_ON,
)
from src.platform.freeform_segment_roi import copiar_led_com_segmento_livre
from src.platform.reference_project_store import escrever_configuracao


F2_BOARD_SHAPE_KEY = "f2_board_shape"
F2_BOARD_SHAPE_EDIT_MODE = "editar_contorno_placa_f2"
F2_BOARD_SHAPE_ALLOWED_SLOTS = {
    F2_BOARD_REF_BOARD_ON,
    F2_BOARD_REF_BOARD_OFF,
}

_PATCH_PRESERVACAO_INSTALADO = False
_PATCH_EDITOR_INSTALADO = False


def _normalizar_nome_projeto(nome: str | None) -> str:
    return " ".join(str(nome or "").strip().upper().split())


def _normalizar_shape(valor) -> dict:
    origem = valor if isinstance(valor, dict) else {}
    rois = origem.get("rois", [])
    if not isinstance(rois, list):
        rois = []
    resolucao = origem.get("base_resolution", {})
    if not isinstance(resolucao, dict):
        resolucao = {}
    try:
        largura = max(0, int(resolucao.get("width") or 0))
        altura = max(0, int(resolucao.get("height") or 0))
    except (TypeError, ValueError):
        largura = altura = 0
    return {
        "rois": copy.deepcopy(rois),
        "base_resolution": {
            "width": largura,
            "height": altura,
        },
        "updated_at": origem.get("updated_at"),
    }


def obter_contorno_placa_projeto(configuracao: dict | None, projeto: str | None) -> dict:
    dados = configuracao if isinstance(configuracao, dict) else {}
    projetos = dados.get("led_projects", {})
    if not isinstance(projetos, dict):
        return _normalizar_shape({})
    nome = _normalizar_nome_projeto(projeto)
    projeto_dados = projetos.get(nome, {})
    if not isinstance(projeto_dados, dict):
        return _normalizar_shape({})
    return _normalizar_shape(projeto_dados.get(F2_BOARD_SHAPE_KEY))


def definir_contorno_placa_projeto(
    configuracao: dict | None,
    projeto: str,
    rois: list[dict],
    largura: int,
    altura: int,
) -> dict:
    dados = copy.deepcopy(configuracao) if isinstance(configuracao, dict) else {}
    projetos = dados.get("led_projects", {})
    if not isinstance(projetos, dict):
        projetos = {}
    nome = _normalizar_nome_projeto(projeto)
    if not nome or nome not in projetos or not isinstance(projetos[nome], dict):
        raise ValueError("Projeto LED ativo não encontrado para salvar o contorno da placa.")

    projeto_dados = dict(projetos[nome])
    projeto_dados[F2_BOARD_SHAPE_KEY] = {
        "rois": copy.deepcopy(list(rois or [])),
        "base_resolution": {
            "width": max(1, int(largura)),
            "height": max(1, int(altura)),
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    projeto_dados["updated_at"] = datetime.now(timezone.utc).isoformat()
    projetos[nome] = projeto_dados
    dados["led_projects"] = projetos
    return dados


def instalar_preservacao_contorno_placa_f2() -> None:
    """Preserva o campo do contorno quando o repositório normaliza projetos."""
    global _PATCH_PRESERVACAO_INSTALADO
    if _PATCH_PRESERVACAO_INSTALADO:
        return

    import src.platform.led_project_repository as repository_module

    original = repository_module._normalizar_projetos

    def normalizar_com_contorno(configuracao: dict) -> dict:
        preservados: dict[str, dict] = {}
        origem = configuracao.get("led_projects", {})
        if isinstance(origem, dict):
            for chave, dados in origem.items():
                if not isinstance(dados, dict):
                    continue
                nome = repository_module.normalizar_nome_projeto_led(
                    dados.get("name", chave)
                )
                if nome:
                    preservados[nome] = _normalizar_shape(
                        dados.get(F2_BOARD_SHAPE_KEY)
                    )

        projetos = original(configuracao)
        for nome, shape in preservados.items():
            if nome in projetos and isinstance(projetos[nome], dict):
                projetos[nome][F2_BOARD_SHAPE_KEY] = shape
        configuracao["led_projects"] = projetos
        return projetos

    repository_module._normalizar_projetos = normalizar_com_contorno
    _PATCH_PRESERVACAO_INSTALADO = True


def carregar_contorno_placa_leds(controller, projeto: str, largura: int, altura: int):
    repository = getattr(controller.app, "config_repository", None)
    if repository is None:
        return []
    configuracao = repository.carregar_configuracao_existente_sem_alerta()
    shape = obter_contorno_placa_projeto(configuracao, projeto)
    saida = []
    for dados in shape.get("rois", []):
        if not isinstance(dados, dict):
            continue
        try:
            led = LedSelection.from_dict(dados)
        except Exception:
            led = None
        if led is None:
            continue
        try:
            if (
                int(getattr(led, "largura_base", 0) or 0) != int(largura)
                or int(getattr(led, "altura_base", 0) or 0) != int(altura)
            ):
                led = led.adaptar_para_resolucao(
                    int(largura),
                    int(altura),
                    raio_minimo=1,
                    raio_maximo=max(int(largura), int(altura)),
                )
        except Exception:
            pass
        saida.append(led)
    return saida


def _copiar_lista_leds(leds):
    resultado = []
    for item in list(leds or []):
        try:
            resultado.append(copiar_led_com_segmento_livre(item))
        except Exception:
            resultado.append(item)
    return resultado


def _snapshot_contexto_app(app) -> dict:
    return {
        "imagem_original": getattr(app, "imagem_original", None),
        "caminho_imagem_atual": getattr(app, "caminho_imagem_atual", None),
        "largura_original": getattr(app, "largura_original", 0),
        "altura_original": getattr(app, "altura_original", 0),
        "leds_selecionados": _copiar_lista_leds(getattr(app, "leds_selecionados", [])),
        "resultados_led_atual": copy.deepcopy(getattr(app, "resultados_led_atual", [])),
        "modo_atual": getattr(app, "modo_atual", "ocioso"),
        "camera_em_pausa_analise": getattr(app, "camera_em_pausa_analise", False),
        "tipo_roi_edicao": getattr(app, "tipo_roi_edicao", "segmento"),
        "segmento_livre_ativo": getattr(app, "_segmento_livre_ativo", False),
    }


def _restaurar_contexto_app(app, snapshot: dict) -> None:
    app.imagem_original = snapshot.get("imagem_original")
    app.caminho_imagem_atual = snapshot.get("caminho_imagem_atual")
    app.largura_original = int(snapshot.get("largura_original") or 0)
    app.altura_original = int(snapshot.get("altura_original") or 0)
    app.leds_selecionados = _copiar_lista_leds(snapshot.get("leds_selecionados", []))
    app.resultados_led_atual = copy.deepcopy(snapshot.get("resultados_led_atual", []))
    app.modo_atual = snapshot.get("modo_atual", "ocioso")
    app.camera_em_pausa_analise = bool(snapshot.get("camera_em_pausa_analise", False))
    app.tipo_roi_edicao = snapshot.get("tipo_roi_edicao", "segmento")
    app._segmento_livre_ativo = bool(snapshot.get("segmento_livre_ativo", False))
    app._segmento_livre_pontos = []
    app._segmento_livre_mouse = None

    view = getattr(app, "view", None)
    if view is not None:
        try:
            view.atualizar_estado_selecao_led(False)
        except Exception:
            pass
        imagem = getattr(app, "imagem_original", None)
        if imagem is not None and getattr(imagem, "size", 0):
            try:
                view.preparar_imagem_para_exibicao(imagem)
                view.desenhar_canvas(app.leds_selecionados, app.resultados_led_atual)
            except Exception:
                pass


def _personalizar_janela_editor_placa(app) -> None:
    janela = getattr(app, "_selecao_tela_cheia_window", None)
    if janela is None:
        return
    try:
        janela.title("ODIN • Desenho da placa F2")
    except Exception:
        pass

    def percorrer(widget):
        try:
            filhos = tuple(widget.winfo_children())
        except Exception:
            filhos = ()
        for filho in filhos:
            yield filho
            yield from percorrer(filho)

    for widget in percorrer(janela):
        try:
            texto = str(widget.cget("text"))
        except Exception:
            continue
        try:
            if texto == "SELEÇÃO E AJUSTE DE ROIs":
                widget.configure(text="DESENHO DA PLACA • F2")
            elif texto.startswith("Segmento: arraste para criar"):
                widget.configure(
                    text=(
                        "Contorne a placa. Use principalmente Segmento por pontos: "
                        "clique vértice a vértice e feche no primeiro ponto. "
                        "Zoom, mover, redimensionar, apagar e demais ferramentas continuam disponíveis."
                    )
                )
        except Exception:
            pass


def abrir_editor_contorno_placa_f2(controller, slot: str, settings_window) -> None:
    if slot not in F2_BOARD_SHAPE_ALLOWED_SLOTS:
        return
    app = controller.app
    if getattr(app, "_f2_board_shape_edit_context", None) is not None:
        return
    if bool(getattr(app, "_selecao_tela_cheia_esta_aberta", lambda: False)()):
        messagebox.showwarning(
            "Editor já aberto",
            "Feche o editor de ROIs atual antes de desenhar a placa.",
            parent=settings_window,
        )
        return

    projeto = str(controller.project_name() or "").strip()
    entries = controller._entries(projeto) if projeto else {}
    entry = entries.get(slot, {}) if isinstance(entries, dict) else {}
    caminho = str(entry.get("image_path") or "").strip()
    imagem = cv2.imread(caminho) if caminho and Path(caminho).exists() else None
    if imagem is None or getattr(imagem, "size", 0) == 0:
        messagebox.showwarning(
            "Referência necessária",
            "Capture ou carregue primeiro esta referência da placa antes de desenhar o contorno.",
            parent=settings_window,
        )
        return

    altura, largura = imagem.shape[:2]
    snapshot = _snapshot_contexto_app(app)
    app._f2_board_shape_edit_context = {
        "controller": controller,
        "settings_window": settings_window,
        "slot": slot,
        "project": projeto,
        "width": int(largura),
        "height": int(altura),
        "snapshot": snapshot,
    }

    # Congela somente a publicação da câmera sobre imagem_original enquanto o
    # editor usa uma referência estática como fundo. O stream não é reiniciado.
    if bool(getattr(app, "camera_ativa", False)):
        app.camera_em_pausa_analise = True

    app.imagem_original = imagem.copy()
    app.caminho_imagem_atual = caminho
    app.altura_original = int(altura)
    app.largura_original = int(largura)
    app.leds_selecionados = carregar_contorno_placa_leds(
        controller,
        projeto,
        largura,
        altura,
    )
    app.resultados_led_atual = []
    app.modo_atual = F2_BOARD_SHAPE_EDIT_MODE

    view = getattr(app, "view", None)
    if view is not None:
        try:
            view.atualizar_estado_selecao_led(True)
            view.preparar_imagem_para_exibicao(app.imagem_original)
            view.desenhar_canvas(app.leds_selecionados, app.resultados_led_atual)
            view.atualizar_status(
                "Desenho da placa F2: contorne a placa; Segmento por pontos é a ferramenta recomendada."
            )
        except Exception:
            pass

    app._abrir_selecao_tela_cheia()
    _personalizar_janela_editor_placa(app)

    # Abre diretamente na ferramenta principal solicitada pelo usuário, mas as
    # demais funcionalidades do editor continuam disponíveis na mesma toolbar.
    selecionar_livre = getattr(app, "_selecionar_segmento_livre_toolbar", None)
    if callable(selecionar_livre):
        try:
            selecionar_livre()
        except Exception:
            pass


def _salvar_e_fechar_editor_placa(app) -> None:
    contexto = getattr(app, "_f2_board_shape_edit_context", None)
    if not isinstance(contexto, dict):
        return

    controller = contexto.get("controller")
    settings_window = contexto.get("settings_window")
    projeto = str(contexto.get("project") or "").strip()
    largura = max(1, int(contexto.get("width") or 1))
    altura = max(1, int(contexto.get("height") or 1))
    snapshot = contexto.get("snapshot", {})

    rois = _copiar_lista_leds(getattr(app, "leds_selecionados", []))
    dados_rois = []
    for roi in rois:
        try:
            normalizada = roi.com_normalizacao(largura, altura)
            dados_rois.append(normalizada.to_dict())
        except Exception:
            try:
                dados_rois.append(roi.to_dict())
            except Exception:
                pass

    try:
        repository = getattr(app, "config_repository", None)
        if repository is None:
            raise RuntimeError("Repositório de configuração indisponível.")
        configuracao = repository.carregar_configuracao_existente_sem_alerta()
        configuracao = definir_contorno_placa_projeto(
            configuracao,
            projeto,
            dados_rois,
            largura,
            altura,
        )
        escrever_configuracao(repository, configuracao)
    except Exception as exc:
        messagebox.showerror(
            "Falha ao salvar desenho da placa",
            str(exc),
            parent=settings_window,
        )
        return

    try:
        app._fechar_interface_selecao_tela_cheia()
    finally:
        app._f2_board_shape_edit_context = None
        _restaurar_contexto_app(app, snapshot)

    # O contorno é único por projeto. Renderizar novamente a seção faz a mesma
    # alteração aparecer simultaneamente em PLACA LIGADA e PLACA DESLIGADA.
    if controller is not None and settings_window is not None:
        try:
            controller.render_settings(settings_window)
            settings_window.lift()
            settings_window.focus_force()
            try:
                settings_window.grab_set()
            except Exception:
                pass
        except Exception:
            pass

    atualizar = getattr(getattr(app, "view", None), "atualizar_status", None)
    if callable(atualizar):
        try:
            atualizar(
                f"Contorno da placa F2 salvo no projeto {projeto}: {len(dados_rois)} forma(s)."
            )
        except Exception:
            pass


def instalar_editor_contorno_placa_f2() -> None:
    """Integra o editor de placa ao editor completo de ROIs já existente."""
    global _PATCH_EDITOR_INSTALADO
    if _PATCH_EDITOR_INSTALADO:
        return

    instalar_preservacao_contorno_placa_f2()
    BulkRoiEditorMixin.MODOS_EDICAO.add(F2_BOARD_SHAPE_EDIT_MODE)

    from src.platform.raspberry_pi3_production_app import RaspberryPi3ProductionApp

    current = RaspberryPi3ProductionApp._confirmar_selecao_tela_cheia
    if bool(getattr(current, "_odin_f2_board_shape_confirm", False)):
        _PATCH_EDITOR_INSTALADO = True
        return

    previous = current

    def confirmar_selecao_tela_cheia_com_contorno(self):
        if str(getattr(self, "modo_atual", "")) == F2_BOARD_SHAPE_EDIT_MODE:
            if bool(getattr(self, "_selecao_tela_cheia_fechando", False)):
                return
            self._selecao_tela_cheia_fechando = True
            try:
                _salvar_e_fechar_editor_placa(self)
            finally:
                self._selecao_tela_cheia_fechando = False
            return
        return previous(self)

    confirmar_selecao_tela_cheia_com_contorno._odin_f2_board_shape_confirm = True
    confirmar_selecao_tela_cheia_com_contorno._odin_f2_board_shape_confirm_base = previous
    RaspberryPi3ProductionApp._confirmar_selecao_tela_cheia = (
        confirmar_selecao_tela_cheia_com_contorno
    )
    _PATCH_EDITOR_INSTALADO = True
