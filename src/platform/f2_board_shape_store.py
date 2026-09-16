from __future__ import annotations

import copy
from datetime import datetime, timezone

from src.models.led_selection import LedSelection
from src.platform.reference_project_store import escrever_configuracao


F2_BOARD_SHAPE_KEY = "f2_board_shape"
_PATCH_INSTALADO = False


def _normalizar_nome_projeto(nome: str | None) -> str:
    return " ".join(str(nome or "").strip().upper().split())


def normalizar_forma_placa_f2(valor) -> dict:
    origem = valor if isinstance(valor, dict) else {}
    rois = origem.get("rois", [])
    if not isinstance(rois, list):
        rois = []

    try:
        largura = max(0, int(origem.get("width") or 0))
        altura = max(0, int(origem.get("height") or 0))
    except (TypeError, ValueError):
        largura = altura = 0

    return {
        "rois": [dict(item) for item in rois if isinstance(item, dict)],
        "width": largura,
        "height": altura,
        "updated_at": origem.get("updated_at"),
    }


def obter_forma_placa_projeto_f2(
    configuracao: dict | None,
    projeto: str | None,
) -> list[LedSelection]:
    dados = configuracao if isinstance(configuracao, dict) else {}
    projetos = dados.get("led_projects", {})
    if not isinstance(projetos, dict):
        return []

    nome = _normalizar_nome_projeto(projeto)
    projeto_dados = projetos.get(nome, {})
    if not isinstance(projeto_dados, dict):
        return []

    forma = normalizar_forma_placa_f2(projeto_dados.get(F2_BOARD_SHAPE_KEY))
    resultado: list[LedSelection] = []
    for item in forma.get("rois", []):
        try:
            roi = LedSelection.from_dict(item)
        except Exception:
            roi = None
        if roi is not None:
            resultado.append(roi)
    return resultado


def definir_forma_placa_projeto_f2(
    configuracao: dict | None,
    projeto: str,
    rois,
    largura: int,
    altura: int,
) -> dict:
    dados = copy.deepcopy(configuracao) if isinstance(configuracao, dict) else {}
    projetos = dados.get("led_projects", {})
    if not isinstance(projetos, dict):
        projetos = {}

    nome = _normalizar_nome_projeto(projeto)
    if not nome or nome not in projetos or not isinstance(projetos[nome], dict):
        raise ValueError("carregue um projeto de LEDs antes de salvar o desenho da placa")

    largura = max(1, int(largura))
    altura = max(1, int(altura))
    serializados = []
    for roi in list(rois or ()):
        try:
            normalizada = roi.com_normalizacao(largura, altura)
        except Exception:
            normalizada = roi
        to_dict = getattr(normalizada, "to_dict", None)
        if callable(to_dict):
            item = to_dict()
            if isinstance(item, dict):
                serializados.append(item)

    projeto_dados = dict(projetos[nome])
    projeto_dados[F2_BOARD_SHAPE_KEY] = {
        "rois": serializados,
        "width": largura,
        "height": altura,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    projeto_dados["updated_at"] = datetime.now(timezone.utc).isoformat()
    projetos[nome] = projeto_dados
    dados["led_projects"] = projetos
    return dados


def salvar_forma_placa_repositorio_f2(
    repository,
    projeto: str,
    rois,
    largura: int,
    altura: int,
) -> list[LedSelection]:
    configuracao = repository.carregar_configuracao_existente_sem_alerta()
    atualizada = definir_forma_placa_projeto_f2(
        configuracao,
        projeto,
        rois,
        largura,
        altura,
    )
    escrever_configuracao(repository, atualizada)
    return obter_forma_placa_projeto_f2(atualizada, projeto)


def carregar_forma_placa_repositorio_f2(repository, projeto: str) -> list[LedSelection]:
    if repository is None:
        return []
    configuracao = repository.carregar_configuracao_existente_sem_alerta()
    return obter_forma_placa_projeto_f2(configuracao, projeto)


def instalar_preservacao_forma_placa_f2() -> None:
    """Preserva a geometria compartilhada ao normalizar/renomear Projetos LED."""
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return

    import src.platform.led_project_repository as repository_module

    original = repository_module._normalizar_projetos

    def normalizar_com_forma_placa(configuracao: dict) -> dict:
        preservadas: dict[str, dict] = {}
        origem = configuracao.get("led_projects", {})
        if isinstance(origem, dict):
            for chave, projeto_dados in origem.items():
                if not isinstance(projeto_dados, dict):
                    continue
                nome = repository_module.normalizar_nome_projeto_led(
                    projeto_dados.get("name", chave)
                )
                if nome:
                    preservadas[nome] = normalizar_forma_placa_f2(
                        projeto_dados.get(F2_BOARD_SHAPE_KEY)
                    )

        projetos = original(configuracao)
        for nome, forma in preservadas.items():
            if nome in projetos and isinstance(projetos[nome], dict):
                projetos[nome][F2_BOARD_SHAPE_KEY] = forma
        configuracao["led_projects"] = projetos
        return projetos

    repository_module._normalizar_projetos = normalizar_com_forma_placa
    _PATCH_INSTALADO = True
