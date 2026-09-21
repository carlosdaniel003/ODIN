from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


DISPLAY_PROJECT_CONFIG_FILE = Path("data/config/odin_display_projects.json")
DISPLAY_PROJECT_SCHEMA_VERSION = 2

DISPLAY_CHECK_STATE_ON = "on"
DISPLAY_CHECK_STATE_OFF = "off"
DISPLAY_CHECK_STATE_IGNORE = "ignore"
DISPLAY_CHECK_STATES = (
    DISPLAY_CHECK_STATE_ON,
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_IGNORE,
)
DISPLAY_DEFAULT_CHECK_NAMES = ("H1", "BLUE", "AUX", "USB")


def normalizar_nome_projeto_display(nome: str | None) -> str:
    texto = re.sub(r"\s+", " ", str(nome or "").strip())
    return texto.upper()


def normalizar_nome_check_display(nome: str | None) -> str:
    texto = re.sub(r"\s+", " ", str(nome or "").strip())
    return texto.upper()


def normalizar_resolucao_display(valor) -> tuple[int, int] | None:
    largura = altura = None
    if isinstance(valor, dict):
        largura = valor.get("width", valor.get("largura"))
        altura = valor.get("height", valor.get("altura"))
    elif isinstance(valor, (list, tuple)) and len(valor) >= 2:
        largura, altura = valor[0], valor[1]
    elif isinstance(valor, str):
        match = re.fullmatch(r"\s*(\d+)\s*[xX×]\s*(\d+)\s*", valor)
        if match:
            largura, altura = match.group(1), match.group(2)

    try:
        largura = int(largura)
        altura = int(altura)
    except (TypeError, ValueError):
        return None

    if largura < 1 or altura < 1:
        return None
    return largura, altura


def _resolucao_dict(resolucao: tuple[int, int] | None) -> dict | None:
    if resolucao is None:
        return None
    return {"width": int(resolucao[0]), "height": int(resolucao[1])}


def normalizar_mascara_display(mascara: dict, indice: int = 1) -> dict | None:
    if not isinstance(mascara, dict):
        return None

    tipo = str(mascara.get("type", mascara.get("tipo", ""))).strip().lower()
    identificador = str(mascara.get("id") or f"MASK_{indice:03d}").strip()
    if not identificador:
        identificador = f"MASK_{indice:03d}"

    try:
        if tipo == "rectangle":
            x = int(mascara.get("x"))
            y = int(mascara.get("y"))
            width = int(mascara.get("width"))
            height = int(mascara.get("height"))
            if width < 1 or height < 1:
                return None
            return {
                "id": identificador,
                "type": "rectangle",
                "x": x,
                "y": y,
                "width": width,
                "height": height,
            }

        if tipo == "circle":
            cx = int(mascara.get("cx"))
            cy = int(mascara.get("cy"))
            radius = int(mascara.get("radius"))
            if radius < 1:
                return None
            return {
                "id": identificador,
                "type": "circle",
                "cx": cx,
                "cy": cy,
                "radius": radius,
            }

        if tipo == "polygon":
            pontos_origem = mascara.get("points", [])
            if not isinstance(pontos_origem, (list, tuple)):
                return None
            pontos: list[list[int]] = []
            for ponto in pontos_origem:
                if not isinstance(ponto, (list, tuple)) or len(ponto) < 2:
                    return None
                pontos.append([int(ponto[0]), int(ponto[1])])
            if len(pontos) < 3:
                return None
            return {
                "id": identificador,
                "type": "polygon",
                "points": pontos,
            }
    except (TypeError, ValueError):
        return None

    return None


def normalizar_mascaras_display(mascaras) -> list[dict]:
    if not isinstance(mascaras, (list, tuple)):
        return []
    resultado: list[dict] = []
    ids_usados: set[str] = set()
    for indice, mascara in enumerate(mascaras, start=1):
        normalizada = normalizar_mascara_display(mascara, indice)
        if normalizada is None:
            continue
        identificador = normalizada["id"]
        if identificador in ids_usados:
            candidato = f"MASK_{indice:03d}"
            sufixo = indice
            while candidato in ids_usados:
                sufixo += 1
                candidato = f"MASK_{sufixo:03d}"
            identificador = candidato
            normalizada["id"] = identificador
        ids_usados.add(identificador)
        resultado.append(normalizada)
    return resultado


def mascaras_geometria_check_display(
    project: dict | None,
    check: dict | None,
) -> list[dict]:
    """CHECKS usam sempre a geometria canônica atual do Projeto Display.

    O CHECK guarda somente estado lógico por máscara. Geometria pertence à tela
    "Desenhar placa e máscaras"; assim qualquer ajuste nela é refletido em todos
    os CHECKS e no runtime sem overrides locais divergentes.
    """
    del check
    if not isinstance(project, dict):
        return []
    return [
        deepcopy(mask)
        for mask in (project.get("masks", []) or [])
        if isinstance(mask, dict)
    ]


def normalizar_estado_check_display(valor) -> str:
    texto = str(valor or "").strip().lower()
    aliases = {
        "on": DISPLAY_CHECK_STATE_ON,
        "aceso": DISPLAY_CHECK_STATE_ON,
        "ligado": DISPLAY_CHECK_STATE_ON,
        "1": DISPLAY_CHECK_STATE_ON,
        "off": DISPLAY_CHECK_STATE_OFF,
        "apagado": DISPLAY_CHECK_STATE_OFF,
        "desligado": DISPLAY_CHECK_STATE_OFF,
        "0": DISPLAY_CHECK_STATE_OFF,
        "ignore": DISPLAY_CHECK_STATE_IGNORE,
        "ignorar": DISPLAY_CHECK_STATE_IGNORE,
        "ignored": DISPLAY_CHECK_STATE_IGNORE,
        "": DISPLAY_CHECK_STATE_IGNORE,
    }
    return aliases.get(texto, DISPLAY_CHECK_STATE_IGNORE)


def normalizar_estados_check_display(estados, mask_ids) -> dict[str, str]:
    origem = estados if isinstance(estados, dict) else {}
    resultado: dict[str, str] = {}
    for mask_id in mask_ids:
        identificador = str(mask_id)
        resultado[identificador] = normalizar_estado_check_display(
            origem.get(identificador)
        )
    return resultado


def _proximo_id_check(ids_usados: set[str]) -> str:
    indice = 1
    while True:
        candidato = f"CHECK_{indice:03d}"
        if candidato not in ids_usados:
            return candidato
        indice += 1


def _checks_padrao(mask_ids) -> list[dict]:
    ids = [str(mask_id) for mask_id in mask_ids]
    return [
        {
            "id": f"CHECK_{indice:03d}",
            "name": nome,
            "mask_states": normalizar_estados_check_display({}, ids),
        }
        for indice, nome in enumerate(DISPLAY_DEFAULT_CHECK_NAMES, start=1)
    ]


def normalizar_pontos_geometria_check(valor, minimo: int = 3) -> list[list[float]]:
    if not isinstance(valor, (list, tuple)):
        return []
    pontos = []
    for item in valor:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            x = float(item[0])
            y = float(item[1])
        except (TypeError, ValueError):
            continue
        pontos.append([x, y])
    return pontos if len(pontos) >= int(minimo) else []


def normalizar_overrides_mascaras_check(valor, mascaras) -> dict[str, dict]:
    base = normalizar_mascaras_display(mascaras)
    ids = {str(mask["id"]) for mask in base}
    origem = valor if isinstance(valor, dict) else {}
    resultado = {}
    for mask_id in ids:
        raw = origem.get(mask_id)
        if not isinstance(raw, dict):
            continue
        normalized = normalizar_mascara_display(
            {**raw, "id": mask_id},
            1,
        )
        if normalized is not None:
            normalized["id"] = mask_id
            resultado[mask_id] = normalized
    return resultado


def normalizar_checks_display(
    checks,
    mascaras,
    usar_padrao_se_ausente: bool = False,
) -> list[dict]:
    masks = normalizar_mascaras_display(mascaras)
    mask_ids = [str(mask["id"]) for mask in masks]
    if not isinstance(checks, (list, tuple)):
        return _checks_padrao(mask_ids) if usar_padrao_se_ausente else []

    resultado: list[dict] = []
    ids_usados: set[str] = set()
    for indice, check in enumerate(checks, start=1):
        if not isinstance(check, dict):
            continue
        nome = normalizar_nome_check_display(check.get("name", check.get("nome")))
        if not nome:
            nome = f"CHECK {indice}"
        identificador = str(check.get("id") or "").strip().upper()
        if not identificador or identificador in ids_usados:
            identificador = _proximo_id_check(ids_usados)
        ids_usados.add(identificador)
        estados = check.get("mask_states", check.get("estados_mascaras", {}))
        item = {
            "id": identificador,
            "name": nome,
            "mask_states": normalizar_estados_check_display(estados, mask_ids),
        }
        # Geometria local por CHECK foi removida: somente mask_states pertence
        # ao CHECK. A geometria é sempre herdada de projeto["masks"].
        resultado.append(item)
    return resultado


class DisplayProjectRepository:
    """Persistência exclusiva do F3.

    Projeto Display, resolução mestre, máscaras e CHECKS permanecem em arquivo
    próprio. Nenhuma operação deste repositório usa ``ConfigRepository``,
    ``led_projects`` ou estado da Produção F2.
    """

    def __init__(self, config_file: str | Path | None = None) -> None:
        self.config_file = Path(config_file or DISPLAY_PROJECT_CONFIG_FILE)

    @staticmethod
    def _estrutura_vazia() -> dict:
        return {
            "schema_version": DISPLAY_PROJECT_SCHEMA_VERSION,
            "active_project": "",
            "project_order": [],
            "projects": {},
        }

    def _carregar(self) -> dict:
        if not self.config_file.exists():
            return self._estrutura_vazia()
        try:
            with open(self.config_file, "r", encoding="utf-8") as arquivo:
                dados = json.load(arquivo)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return self._estrutura_vazia()
        return self._normalizar_estrutura(dados)

    def _normalizar_estrutura(self, dados) -> dict:
        if not isinstance(dados, dict):
            dados = {}
        projetos_origem = dados.get("projects", {})
        projetos: dict[str, dict] = {}
        if isinstance(projetos_origem, dict):
            for chave, projeto in projetos_origem.items():
                if not isinstance(projeto, dict):
                    continue
                nome = normalizar_nome_projeto_display(projeto.get("name", chave))
                if not nome:
                    continue
                resolucao = normalizar_resolucao_display(
                    projeto.get("master_resolution")
                )
                mascaras = normalizar_mascaras_display(projeto.get("masks", []))
                tem_checks = "checks" in projeto
                checks = normalizar_checks_display(
                    projeto.get("checks"),
                    mascaras,
                    usar_padrao_se_ausente=not tem_checks,
                )
                projetos[nome] = {
                    "name": nome,
                    "master_resolution": _resolucao_dict(resolucao),
                    "masks": mascaras,
                    "checks": checks,
                    "updated_at": projeto.get("updated_at"),
                }

        ordem: list[str] = []
        ordem_origem = dados.get("project_order", [])
        if isinstance(ordem_origem, list):
            for item in ordem_origem:
                nome = normalizar_nome_projeto_display(item)
                if nome in projetos and nome not in ordem:
                    ordem.append(nome)
        for nome in projetos:
            if nome not in ordem:
                ordem.append(nome)

        ativo = normalizar_nome_projeto_display(dados.get("active_project"))
        if ativo not in projetos:
            ativo = ordem[0] if ordem else ""

        return {
            "schema_version": DISPLAY_PROJECT_SCHEMA_VERSION,
            "active_project": ativo,
            "project_order": ordem,
            "projects": projetos,
        }

    def _escrever(self, dados: dict) -> None:
        normalizados = self._normalizar_estrutura(dados)
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        temporario = self.config_file.with_suffix(self.config_file.suffix + ".tmp")
        with open(temporario, "w", encoding="utf-8") as arquivo:
            json.dump(normalizados, arquivo, indent=4, ensure_ascii=False)
            arquivo.flush()
        temporario.replace(self.config_file)

    @staticmethod
    def _atualizar_timestamp(projeto: dict) -> None:
        projeto["updated_at"] = datetime.now(timezone.utc).isoformat()

    def listar_projetos(self) -> list[str]:
        return list(self._carregar()["project_order"])

    def obter_projeto_ativo(self) -> str:
        return str(self._carregar()["active_project"])

    def carregar_projeto(self, nome: str | None = None) -> dict | None:
        dados = self._carregar()
        nome_normalizado = normalizar_nome_projeto_display(nome)
        if not nome_normalizado:
            nome_normalizado = dados["active_project"]
        projeto = dados["projects"].get(nome_normalizado)
        return deepcopy(projeto) if projeto is not None else None

    def adicionar_projeto(
        self,
        nome: str,
        resolucao_mestra=None,
    ) -> bool:
        nome_normalizado = normalizar_nome_projeto_display(nome)
        if not nome_normalizado:
            return False
        dados = self._carregar()
        if nome_normalizado in dados["projects"]:
            return False
        resolucao = normalizar_resolucao_display(resolucao_mestra)
        mascaras: list[dict] = []
        dados["projects"][nome_normalizado] = {
            "name": nome_normalizado,
            "master_resolution": _resolucao_dict(resolucao),
            "masks": mascaras,
            "checks": _checks_padrao([]),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        dados["project_order"].append(nome_normalizado)
        if not dados["active_project"]:
            dados["active_project"] = nome_normalizado
        self._escrever(dados)
        return True

    def definir_projeto_ativo(self, nome: str) -> bool:
        nome_normalizado = normalizar_nome_projeto_display(nome)
        dados = self._carregar()
        if nome_normalizado not in dados["projects"]:
            return False
        dados["active_project"] = nome_normalizado
        self._escrever(dados)
        return True

    def renomear_projeto(self, nome_atual: str, novo_nome: str) -> bool:
        atual = normalizar_nome_projeto_display(nome_atual)
        novo = normalizar_nome_projeto_display(novo_nome)
        dados = self._carregar()
        if not atual or not novo or atual not in dados["projects"]:
            return False
        if novo != atual and novo in dados["projects"]:
            return False
        if novo == atual:
            return True
        projeto = dados["projects"].pop(atual)
        projeto["name"] = novo
        self._atualizar_timestamp(projeto)
        dados["projects"][novo] = projeto
        dados["project_order"] = [
            novo if item == atual else item for item in dados["project_order"]
        ]
        if dados["active_project"] == atual:
            dados["active_project"] = novo
        self._escrever(dados)
        return True

    def remover_projeto(self, nome: str) -> bool:
        nome_normalizado = normalizar_nome_projeto_display(nome)
        dados = self._carregar()
        if nome_normalizado not in dados["projects"]:
            return False
        dados["projects"].pop(nome_normalizado)
        dados["project_order"] = [
            item for item in dados["project_order"] if item != nome_normalizado
        ]
        if dados["active_project"] == nome_normalizado:
            dados["active_project"] = (
                dados["project_order"][0] if dados["project_order"] else ""
            )
        self._escrever(dados)
        return True

    def salvar_resolucao_mestra(self, nome: str, largura: int, altura: int) -> bool:
        projeto = self.carregar_projeto(nome)
        resolucao = normalizar_resolucao_display((largura, altura))
        if projeto is None or resolucao is None:
            return False
        return self.salvar_configuracao_projeto(
            nome,
            resolucao,
            projeto.get("masks", []),
        )

    def salvar_mascaras(self, nome: str, mascaras) -> bool:
        projeto = self.carregar_projeto(nome)
        if projeto is None:
            return False
        resolucao = normalizar_resolucao_display(
            projeto.get("master_resolution")
        )
        if resolucao is None:
            return False
        return self.salvar_configuracao_projeto(nome, resolucao, mascaras)

    def salvar_configuracao_projeto(
        self,
        nome: str,
        resolucao_mestra,
        mascaras,
    ) -> bool:
        nome_normalizado = normalizar_nome_projeto_display(nome)
        resolucao = normalizar_resolucao_display(resolucao_mestra)
        if not nome_normalizado or resolucao is None:
            return False
        dados = self._carregar()
        projeto_atual = dados["projects"].get(nome_normalizado)
        if projeto_atual is None:
            return False
        mascaras_normalizadas = normalizar_mascaras_display(mascaras)
        checks = normalizar_checks_display(
            projeto_atual.get("checks", []),
            mascaras_normalizadas,
        )
        dados["projects"][nome_normalizado] = {
            "name": nome_normalizado,
            "master_resolution": _resolucao_dict(resolucao),
            "masks": mascaras_normalizadas,
            "checks": checks,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        dados["active_project"] = nome_normalizado
        self._escrever(dados)
        return True

    def listar_checks(self, nome_projeto: str) -> list[dict]:
        projeto = self.carregar_projeto(nome_projeto)
        if projeto is None:
            return []
        return deepcopy(projeto.get("checks", []))

    def carregar_check(self, nome_projeto: str, check_id: str) -> dict | None:
        identificador = str(check_id or "").strip().upper()
        for check in self.listar_checks(nome_projeto):
            if str(check.get("id", "")).upper() == identificador:
                return deepcopy(check)
        return None

    def adicionar_check(self, nome_projeto: str, nome_check: str) -> str | None:
        projeto_nome = normalizar_nome_projeto_display(nome_projeto)
        nome = normalizar_nome_check_display(nome_check)
        if not projeto_nome or not nome:
            return None
        dados = self._carregar()
        projeto = dados["projects"].get(projeto_nome)
        if projeto is None:
            return None
        checks = list(projeto.get("checks", []))
        if any(normalizar_nome_check_display(item.get("name")) == nome for item in checks):
            return None
        ids_usados = {str(item.get("id", "")).upper() for item in checks}
        check_id = _proximo_id_check(ids_usados)
        mask_ids = [str(mask["id"]) for mask in projeto.get("masks", [])]
        checks.append(
            {
                "id": check_id,
                "name": nome,
                "mask_states": normalizar_estados_check_display({}, mask_ids),
            }
        )
        projeto["checks"] = normalizar_checks_display(checks, projeto.get("masks", []))
        self._atualizar_timestamp(projeto)
        self._escrever(dados)
        return check_id

    def renomear_check(
        self,
        nome_projeto: str,
        check_id: str,
        novo_nome: str,
    ) -> bool:
        projeto_nome = normalizar_nome_projeto_display(nome_projeto)
        identificador = str(check_id or "").strip().upper()
        nome = normalizar_nome_check_display(novo_nome)
        if not projeto_nome or not identificador or not nome:
            return False
        dados = self._carregar()
        projeto = dados["projects"].get(projeto_nome)
        if projeto is None:
            return False
        checks = list(projeto.get("checks", []))
        if any(
            str(item.get("id", "")).upper() != identificador
            and normalizar_nome_check_display(item.get("name")) == nome
            for item in checks
        ):
            return False
        encontrado = False
        for check in checks:
            if str(check.get("id", "")).upper() == identificador:
                check["name"] = nome
                encontrado = True
                break
        if not encontrado:
            return False
        projeto["checks"] = normalizar_checks_display(checks, projeto.get("masks", []))
        self._atualizar_timestamp(projeto)
        self._escrever(dados)
        return True

    def remover_check(self, nome_projeto: str, check_id: str) -> bool:
        projeto_nome = normalizar_nome_projeto_display(nome_projeto)
        identificador = str(check_id or "").strip().upper()
        dados = self._carregar()
        projeto = dados["projects"].get(projeto_nome)
        if projeto is None or not identificador:
            return False
        checks = list(projeto.get("checks", []))
        novos = [
            check
            for check in checks
            if str(check.get("id", "")).upper() != identificador
        ]
        if len(novos) == len(checks):
            return False
        projeto["checks"] = normalizar_checks_display(novos, projeto.get("masks", []))
        self._atualizar_timestamp(projeto)
        self._escrever(dados)
        return True

    def mover_check(
        self,
        nome_projeto: str,
        check_id: str,
        deslocamento: int,
    ) -> bool:
        projeto_nome = normalizar_nome_projeto_display(nome_projeto)
        identificador = str(check_id or "").strip().upper()
        passo = -1 if int(deslocamento) < 0 else 1
        dados = self._carregar()
        projeto = dados["projects"].get(projeto_nome)
        if projeto is None or not identificador:
            return False
        checks = list(projeto.get("checks", []))
        indice = next(
            (
                i
                for i, check in enumerate(checks)
                if str(check.get("id", "")).upper() == identificador
            ),
            None,
        )
        if indice is None:
            return False
        destino = indice + passo
        if destino < 0 or destino >= len(checks):
            return False
        checks[indice], checks[destino] = checks[destino], checks[indice]
        projeto["checks"] = normalizar_checks_display(checks, projeto.get("masks", []))
        self._atualizar_timestamp(projeto)
        self._escrever(dados)
        return True

    def salvar_geometria_check(
        self,
        nome_projeto: str,
        check_id: str,
        board_points,
        mask_overrides,
    ) -> bool:
        projeto_nome = normalizar_nome_projeto_display(nome_projeto)
        identificador = str(check_id or "").strip().upper()
        dados = self._carregar()
        projeto = dados["projects"].get(projeto_nome)
        if projeto is None or not identificador:
            return False

        # Compatibilidade com chamadas antigas: a geometria de CHECK não é mais
        # persistida. Limpe qualquer override legado e mantenha apenas estados.
        del board_points, mask_overrides
        encontrado = False
        for check in projeto.get("checks", []):
            if str(check.get("id", "")).upper() != identificador:
                continue
            check.pop("board_points_reference", None)
            check.pop("mask_overrides_reference", None)
            encontrado = True
            break
        if not encontrado:
            return False

        projeto["checks"] = normalizar_checks_display(
            projeto.get("checks", []),
            projeto.get("masks", []),
        )
        self._atualizar_timestamp(projeto)
        self._escrever(dados)
        return True

    def salvar_estados_check(
        self,
        nome_projeto: str,
        check_id: str,
        estados,
    ) -> bool:
        projeto_nome = normalizar_nome_projeto_display(nome_projeto)
        identificador = str(check_id or "").strip().upper()
        dados = self._carregar()
        projeto = dados["projects"].get(projeto_nome)
        if projeto is None or not identificador:
            return False
        mask_ids = [str(mask["id"]) for mask in projeto.get("masks", [])]
        encontrado = False
        for check in projeto.get("checks", []):
            if str(check.get("id", "")).upper() == identificador:
                check["mask_states"] = normalizar_estados_check_display(
                    estados,
                    mask_ids,
                )
                encontrado = True
                break
        if not encontrado:
            return False
        projeto["checks"] = normalizar_checks_display(
            projeto.get("checks", []),
            projeto.get("masks", []),
        )
        self._atualizar_timestamp(projeto)
        self._escrever(dados)
        return True
