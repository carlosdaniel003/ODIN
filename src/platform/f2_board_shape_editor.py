from __future__ import annotations

"""Editor compartilhado do contorno físico da placa para o F2.

O contorno pertence ao Projeto LED, não à foto ligada/desligada. O editor usa a
mesma infraestrutura fullscreen de ROIs do ODIN, mas mantém uma área de trabalho
própria para a placa. Isso é importante no jig Linux: callbacks da câmera e da
produção podem atualizar ``leds_selecionados`` enquanto o editor está aberto e
não podem contaminar o desenho da placa com as ROIs dos LEDs.

O contorno físico é uma única ROI poligonal criada por ``Segmento por pontos``.
As referências de presença não são alteradas em disco; somente a geometria do
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


def _copiar_lista_leds(leds):
    resultado = []
    for item in list(leds or []):
        try:
            resultado.append(copiar_led_com_segmento_livre(item))
        except Exception:
            resultado.append(item)
    return resultado


def _roi_e_contorno_placa_valido(roi) -> bool:
    """Aceita somente o polígono fechado criado por Segmento por pontos."""
    if roi is None:
        return False
    if not bool(getattr(roi, "eh_segmento_livre", False)):
        return False
    pontos = list(getattr(roi, "pontos_segmento_livre", None) or ())
    return len(pontos) >= 3


def _filtrar_rois_contorno_placa(rois) -> list[LedSelection]:
    """Mantém uma única forma de placa e rejeita ROIs de LEDs contaminadas.

    Versões anteriores podiam salvar as 42 ROIs do projeto como se fossem o
    contorno da placa no Linux. Um contorno da placa é um único polígono livre;
    portanto círculos/segmentos comuns e listas contaminadas são ignorados.
    Quando existem vários polígonos válidos, o último é o desenho mais recente.
    """
    validos = []
    for roi in list(rois or []):
        if not _roi_e_contorno_placa_valido(roi):
            continue
        try:
            validos.append(copiar_led_com_segmento_livre(roi))
        except Exception:
            validos.append(roi)
    return validos[-1:] if validos else []


def _filtrar_dados_contorno_placa(rois) -> list[dict]:
    validos: list[tuple[LedSelection, dict]] = []
    for dados in list(rois or []):
        if not isinstance(dados, dict):
            continue
        try:
            roi = LedSelection.from_dict(dados)
        except Exception:
            roi = None
        if not _roi_e_contorno_placa_valido(roi):
            continue
        validos.append((roi, copy.deepcopy(dados)))
    return [validos[-1][1]] if validos else []


def _normalizar_shape(valor) -> dict:
    origem = valor if isinstance(valor, dict) else {}
    rois = _filtrar_dados_contorno_placa(origem.get("rois", []))
    resolucao = origem.get("base_resolution", {})
    if not isinstance(resolucao, dict):
        resolucao = {}
    try:
        largura = max(0, int(resolucao.get("width") or 0))
        altura = max(0, int(resolucao.get("height") or 0))
    except (TypeError, ValueError):
        largura = altura = 0
    return {
        "rois": rois,
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

    dados_validos = _filtrar_dados_contorno_placa(rois)
    if len(dados_validos) != 1:
        raise ValueError(
            "O desenho da placa precisa conter um contorno fechado criado com "
            "Segmento por pontos."
        )

    agora = datetime.now(timezone.utc).isoformat()
    projeto_dados = dict(projetos[nome])
    projeto_dados[F2_BOARD_SHAPE_KEY] = {
        "rois": dados_validos,
        "base_resolution": {
            "width": max(1, int(largura)),
            "height": max(1, int(altura)),
        },
        "updated_at": agora,
    }
    projeto_dados["updated_at"] = agora
    projetos[nome] = projeto_dados
    dados["led_projects"] = projetos
    return dados


def instalar_preservacao_contorno_placa_f2() -> None:
    """Preserva e sanitiza o campo do contorno quando o repositório normaliza projetos."""
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
        if not _roi_e_contorno_placa_valido(led):
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
    return _filtrar_rois_contorno_placa(saida)


def _contexto_editor_placa_ativo(app) -> dict | None:
    contexto = getattr(app, "_f2_board_shape_edit_context", None)
    return contexto if isinstance(contexto, dict) else None


def _rois_trabalho_editor_placa(app) -> list[LedSelection]:
    contexto = _contexto_editor_placa_ativo(app)
    if contexto is None:
        return []

    # A camada de isolamento do F2 mantém uma coleção dedicada para impedir a
    # câmera de republicar as ROIs dos LEDs dentro deste editor. Ela é a fonte
    # mais recente quando existe. Sincronizamos o contexto legado para que o
    # salvamento nunca volte a ler o contorno antigo.
    dedicadas = getattr(app, "_f2_board_shape_editor_rois", None)
    if dedicadas is not None:
        validas = _filtrar_rois_contorno_placa(dedicadas)
        contexto["working_rois"] = _copiar_lista_leds(validas)
        return _copiar_lista_leds(validas)

    return _filtrar_rois_contorno_placa(contexto.get("working_rois", []))


def _definir_rois_trabalho_editor_placa(app, rois) -> list[LedSelection]:
    contexto = _contexto_editor_placa_ativo(app)
    if contexto is None:
        return []
    validos = _filtrar_rois_contorno_placa(rois)
    contexto["working_rois"] = _copiar_lista_leds(validos)

    # Se a camada dedicada já estiver ativa, mantenha as duas autoridades
    # sincronizadas. Isso elimina o caso "desenhei novo / salvou o antigo".
    if hasattr(app, "_f2_board_shape_editor_rois"):
        app._f2_board_shape_editor_rois = _copiar_lista_leds(validos)

    # O canvas legado ainda lê este atributo; ele é apenas um espelho visual.
    app.leds_selecionados = _copiar_lista_leds(validos)
    app.resultados_led_atual = []
    return _copiar_lista_leds(validos)


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
                        "Contorne a placa com Segmento por pontos: clique vértice a "
                        "vértice e feche no primeiro ponto. O projeto possui um único "
                        "contorno; um novo desenho substitui o anterior."
                    )
                )
        except Exception:
            pass


def abrir_editor_contorno_placa_f2(controller, slot: str, settings_window) -> None:
    if slot not in F2_BOARD_SHAPE_ALLOWED_SLOTS:
        return
    app = controller.app
    if _contexto_editor_placa_ativo(app) is not None:
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
    contorno_atual = carregar_contorno_placa_leds(
        controller,
        projeto,
        largura,
        altura,
    )
    app._f2_board_shape_edit_context = {
        "controller": controller,
        "settings_window": settings_window,
        "slot": slot,
        "project": projeto,
        "width": int(largura),
        "height": int(altura),
        "snapshot": snapshot,
        # "Desenhar placa" significa redesenhar. A geometria antiga permanece
        # persistida como fallback até o novo SALVAR concluir, mas não participa
        # do canvas nem da coleção que será gravada.
        "original_rois": _copiar_lista_leds(contorno_atual),
        "working_rois": [],
        "redraw_session": True,
    }

    if bool(getattr(app, "camera_ativa", False)):
        app.camera_em_pausa_analise = True

    app.imagem_original = imagem.copy()
    app.caminho_imagem_atual = caminho
    app.altura_original = int(altura)
    app.largura_original = int(largura)
    _definir_rois_trabalho_editor_placa(app, [])
    app.modo_atual = F2_BOARD_SHAPE_EDIT_MODE

    view = getattr(app, "view", None)
    if view is not None:
        try:
            view.atualizar_estado_selecao_led(True)
            view.preparar_imagem_para_exibicao(app.imagem_original)
            view.desenhar_canvas(app.leds_selecionados, app.resultados_led_atual)
            view.atualizar_status(
                "Desenho da placa F2: use Segmento por pontos e feche no primeiro vértice."
            )
        except Exception:
            pass

    app._abrir_selecao_tela_cheia()
    _personalizar_janela_editor_placa(app)

    selecionar_livre = getattr(app, "_selecionar_segmento_livre_toolbar", None)
    if callable(selecionar_livre):
        try:
            selecionar_livre()
        except Exception:
            pass


def _invalidar_cache_rastreamento_f2(app) -> None:
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


def _salvar_e_fechar_editor_placa(app) -> None:
    contexto = _contexto_editor_placa_ativo(app)
    if contexto is None:
        return

    controller = contexto.get("controller")
    settings_window = contexto.get("settings_window")
    projeto = str(contexto.get("project") or "").strip()
    largura = max(1, int(contexto.get("width") or 1))
    altura = max(1, int(contexto.get("height") or 1))
    snapshot = contexto.get("snapshot", {})

    # Se ainda existe rascunho, o usuário não fechou o polígono de fato.
    if list(getattr(app, "_segmento_livre_pontos", []) or []):
        messagebox.showwarning(
            "Feche o contorno da placa",
            "O desenho ainda está aberto. Clique próximo do primeiro ponto amarelo "
            "para fechar o contorno antes de pressionar OK.",
            parent=getattr(app, "_selecao_tela_cheia_window", None) or settings_window,
        )
        return

    rois = _rois_trabalho_editor_placa(app)
    if len(rois) != 1:
        messagebox.showwarning(
            "Contorno da placa necessário",
            "Nenhum contorno fechado válido foi encontrado. Use Segmento por pontos, "
            "feche no primeiro vértice e depois pressione OK.",
            parent=getattr(app, "_selecao_tela_cheia_window", None) or settings_window,
        )
        return

    dados_rois = []
    for roi in rois:
        normalizada = roi.com_normalizacao(largura, altura)
        dados_rois.append(normalizada.to_dict())

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

        configuracao_salva = repository.carregar_configuracao_existente_sem_alerta()
        shape_salvo = obter_contorno_placa_projeto(configuracao_salva, projeto)
        quantidade_salva = len(shape_salvo.get("rois", []))
        if quantidade_salva != 1:
            raise RuntimeError(
                "O contorno foi confirmado no editor, mas não foi encontrado como "
                "um único polígono no arquivo de configuração."
            )

        app._f2_board_shape_last_save = {
            "project": projeto,
            "editor_count": 1,
            "stored_count": 1,
            "config_file": str(getattr(repository, "config_file", "")),
        }
    except Exception as exc:
        messagebox.showerror(
            "Falha ao salvar desenho da placa",
            str(exc),
            parent=settings_window,
        )
        return

    _invalidar_cache_rastreamento_f2(app)

    try:
        app._fechar_interface_selecao_tela_cheia()
    finally:
        app._f2_board_shape_edit_context = None
        _restaurar_contexto_app(app, snapshot)

    if controller is not None and settings_window is not None:
        try:
            controller.render_settings(settings_window)
            settings_window.lift()
            settings_window.focus_force()
            try:
                settings_window.grab_set()
            except Exception:
                pass
        except Exception as exc:
            try:
                messagebox.showwarning(
                    "Contorno salvo",
                    "O contorno foi salvo no projeto, mas a prévia das Configurações "
                    f"não conseguiu ser redesenhada agora: {exc}",
                    parent=settings_window,
                )
            except Exception:
                pass

    atualizar = getattr(getattr(app, "view", None), "atualizar_status", None)
    if callable(atualizar):
        try:
            atualizar(f"Contorno da placa F2 salvo no projeto {projeto}.")
        except Exception:
            pass


def instalar_editor_contorno_placa_f2() -> None:
    """Integra o editor de placa ao editor completo de ROIs já existente."""
    global _PATCH_EDITOR_INSTALADO
    if _PATCH_EDITOR_INSTALADO:
        return

    instalar_preservacao_contorno_placa_f2()
    BulkRoiEditorMixin.MODOS_EDICAO.add(F2_BOARD_SHAPE_EDIT_MODE)

    from src.platform.desktop_production_app import DesktopProductionApp

    # O modo global pode mudar no Linux enquanto o fullscreen está aberto. O
    # contexto dedicado mantém o editor operacional mesmo assim.
    modo_atual = DesktopProductionApp._modo_edicao_roi_ativo
    if not bool(getattr(modo_atual, "_odin_f2_board_shape_mode", False)):
        modo_anterior = modo_atual

        def modo_edicao_roi_com_contorno(self):
            if _contexto_editor_placa_ativo(self) is not None:
                return True
            return modo_anterior(self)

        modo_edicao_roi_com_contorno._odin_f2_board_shape_mode = True
        DesktopProductionApp._modo_edicao_roi_ativo = modo_edicao_roi_com_contorno

    # Durante o desenho, a coleção autoritativa deixa de ser leds_selecionados.
    # Isso impede que as 42 ROIs dos LEDs substituam o contorno no jig Linux.
    leds_atual = DesktopProductionApp._leds_editaveis
    if not bool(getattr(leds_atual, "_odin_f2_board_shape_working", False)):
        leds_anterior = leds_atual

        def leds_editaveis_com_contorno(self):
            if _contexto_editor_placa_ativo(self) is not None:
                return _rois_trabalho_editor_placa(self)
            return leds_anterior(self)

        leds_editaveis_com_contorno._odin_f2_board_shape_working = True
        DesktopProductionApp._leds_editaveis = leds_editaveis_com_contorno

    substituir_atual = DesktopProductionApp._substituir_leds_editaveis
    if not bool(getattr(substituir_atual, "_odin_f2_board_shape_working", False)):
        substituir_anterior = substituir_atual

        def substituir_leds_editaveis_com_contorno(self, leds):
            if _contexto_editor_placa_ativo(self) is not None:
                _definir_rois_trabalho_editor_placa(self, leds)
                return None
            return substituir_anterior(self, leds)

        substituir_leds_editaveis_com_contorno._odin_f2_board_shape_working = True
        DesktopProductionApp._substituir_leds_editaveis = (
            substituir_leds_editaveis_com_contorno
        )

    current = DesktopProductionApp._confirmar_selecao_tela_cheia
    if bool(getattr(current, "_odin_f2_board_shape_confirm", False)):
        _PATCH_EDITOR_INSTALADO = True
        return

    previous = current

    def confirmar_selecao_tela_cheia_com_contorno(self):
        if _contexto_editor_placa_ativo(self) is not None:
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
    DesktopProductionApp._confirmar_selecao_tela_cheia = (
        confirmar_selecao_tela_cheia_com_contorno
    )
    _PATCH_EDITOR_INSTALADO = True
