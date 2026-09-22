from __future__ import annotations

import math
import sys

import cv2


class CameraLiveControlServiceMixin:
    """Aplica ajustes pontuais sem somar/reaplicar todos os controles.

    Regras do modo ao vivo:
    - marcar um controle manual apenas captura o valor atual como baseline;
    - mover o slider altera somente aquele controle;
    - desmarcar restaura o valor que existia antes de ativar o manual;
    - autofocus/exposição automática/white balance automático são comandos
      explícitos ao driver, inclusive no modo nativo do Windows.
    """

    _PROPRIEDADES_MANUAIS = {
        "pan": "CAP_PROP_PAN",
        "tilt": "CAP_PROP_TILT",
        "contrast": "CAP_PROP_CONTRAST",
        "sharpness": "CAP_PROP_SHARPNESS",
        "saturation": "CAP_PROP_SATURATION",
        "exposure": "CAP_PROP_EXPOSURE",
        "gain": "CAP_PROP_GAIN",
        "focus": "CAP_PROP_FOCUS",
        "white_balance": "CAP_PROP_WB_TEMPERATURE",
        "brightness": "CAP_PROP_BRIGHTNESS",
        "gamma": "CAP_PROP_GAMMA",
    }

    _PASSOS_DIRECTSHOW = {
        "pan": (1.0, 5.0, 10.0),
        "tilt": (1.0, 5.0, 10.0),
        "contrast": (1.0, 5.0, 10.0),
        "sharpness": (1.0, 5.0, 10.0),
        "saturation": (1.0, 5.0, 10.0),
        "exposure": (1.0,),
        "gain": (1.0, 5.0, 10.0),
        "focus": (5.0, 10.0, 17.0),
        "white_balance": (10.0, 50.0, 100.0),
        "brightness": (1.0, 5.0, 10.0),
        "gamma": (1.0, 5.0, 10.0),
    }

    _TOLERANCIA_CONTROLE = {
        "white_balance": 25.0,
        "focus": 1.0,
        "exposure": 0.26,
    }

    _CONTROLES_AUTOMATICOS = {
        "exposure_auto": (
            "exposure",
            "auto_exposure",
            "CAP_PROP_AUTO_EXPOSURE",
        ),
        "focus_auto": (
            "focus",
            "autofocus",
            "CAP_PROP_AUTOFOCUS",
        ),
        "white_balance_auto": (
            "white_balance",
            "auto_white_balance",
            "CAP_PROP_AUTO_WB",
        ),
    }

    def __init__(self, *args, **kwargs) -> None:
        self._camera_live_chaves_pendentes: list[str] = []
        self._camera_live_baselines: dict[str, float] = {}
        self._camera_live_valores_hardware: dict[str, float] = {}
        super().__init__(*args, **kwargs)

    def _preparar_configuracoes_camera_ao_vivo(
        self,
        configuracoes_camera: dict | None,
    ) -> dict:
        return dict(configuracoes_camera or {})

    def atualizar_configuracoes_camera_ao_vivo(
        self,
        configuracoes_camera: dict | None,
        chaves_alteradas=None,
    ) -> None:
        origem = self._preparar_configuracoes_camera_ao_vivo(
            configuracoes_camera
        )
        configuracoes = self._normalizar_configuracoes_camera(origem)
        chaves = [str(chave) for chave in (chaves_alteradas or ())]

        with self._lock:
            self._configuracoes_camera = configuracoes
            for chave in chaves:
                if chave not in self._camera_live_chaves_pendentes:
                    self._camera_live_chaves_pendentes.append(chave)
            self._controles_pendentes = bool(
                self._camera_live_chaves_pendentes
            )

    def obter_valores_controles_camera_ao_vivo(self) -> dict:
        with self._lock:
            return dict(self._camera_live_valores_hardware)

    def tem_configuracoes_camera_ao_vivo_pendentes(self) -> bool:
        with self._lock:
            return bool(self._camera_live_chaves_pendentes)

    def _consumir_chaves_camera_ao_vivo(self) -> list[str]:
        with self._lock:
            chaves = list(self._camera_live_chaves_pendentes)
            self._camera_live_chaves_pendentes.clear()
        return chaves

    @staticmethod
    def _ler_propriedade_capture(capture, propriedade):
        if capture is None or propriedade is None:
            return None
        try:
            valor = float(capture.get(propriedade))
        except Exception:
            return None
        return valor if math.isfinite(valor) else None

    @staticmethod
    def _definir_propriedade_capture(capture, propriedade, valor):
        if capture is None or propriedade is None or valor is None:
            return False, None
        try:
            aplicado = bool(capture.set(propriedade, float(valor)))
        except Exception:
            aplicado = False
        lido = CameraLiveControlServiceMixin._ler_propriedade_capture(
            capture,
            propriedade,
        )
        return aplicado, lido

    def _directshow_ativo(self) -> bool:
        backend = str(
            getattr(self, "_backend_atual", "")
            or getattr(self, "_backend_name", "")
            or ""
        ).strip().lower()
        return "directshow" in backend

    @classmethod
    def _candidatos_controle_directshow(
        cls,
        nome: str,
        valor: float,
    ) -> list[float]:
        """Gera valores próximos respeitando controles DirectShow discretos."""
        try:
            solicitado = float(valor)
        except (TypeError, ValueError):
            return []

        if nome == "focus":
            solicitado = min(255.0, max(0.0, solicitado))

        candidatos = [solicitado]
        arredondado = float(round(solicitado))
        candidatos.append(arredondado)

        for passo in cls._PASSOS_DIRECTSHOW.get(nome, (1.0,)):
            passo = float(passo)
            if passo <= 0:
                continue
            base = round(solicitado / passo) * passo
            candidatos.extend((base, base - passo, base + passo))

        unicos = []
        vistos = set()
        for candidato in candidatos:
            candidato = float(candidato)
            if nome == "focus":
                candidato = min(255.0, max(0.0, candidato))
            chave = round(candidato, 6)
            if chave in vistos:
                continue
            vistos.add(chave)
            unicos.append(candidato)

        # Mantém o valor exato como primeira tentativa; os fallbacks seguintes
        # são ordenados pela menor distância ao que o operador pediu.
        if not unicos:
            return []
        primeiro = unicos[0]
        restantes = sorted(
            unicos[1:],
            key=lambda candidato: (
                abs(float(candidato) - solicitado),
                float(candidato),
            ),
        )
        return [primeiro, *restantes]

    @classmethod
    def _tolerancia_controle(cls, nome: str) -> float:
        return float(cls._TOLERANCIA_CONTROLE.get(nome, 1.0))

    def _definir_controle_manual_confirmado(
        self,
        capture,
        nome: str,
        valor,
    ):
        """Aplica controle manual com confirmação por leitura do hardware.

        No DirectShow, uma escrita False não prova ausência de suporte. O
        dispositivo pode aceitar apenas passos discretos ou até aplicar o valor
        apesar do retorno False. Retorna:
            (confirmado, valor_lido, valor_efetivo, ajustado_pelo_driver)
        """
        propriedade = self._propriedade_manual(nome)
        if capture is None or propriedade is None:
            return (False, None, None, False)

        if nome == "focus" and self._directshow_ativo():
            autofocus = getattr(cv2, "CAP_PROP_AUTOFOCUS", None)
            if autofocus is not None:
                try:
                    capture.set(autofocus, 0.0)
                except Exception:
                    pass

        try:
            solicitado = float(valor)
        except (TypeError, ValueError):
            return (False, None, None, False)

        antes = self._ler_propriedade_capture(capture, propriedade)
        candidatos = (
            self._candidatos_controle_directshow(nome, solicitado)
            if self._directshow_ativo()
            else [solicitado]
        )
        tolerancia = self._tolerancia_controle(nome)
        ultimo_lido = antes

        for candidato in candidatos:
            try:
                retorno = bool(capture.set(propriedade, float(candidato)))
            except Exception:
                retorno = False

            lido = self._ler_propriedade_capture(capture, propriedade)
            ultimo_lido = lido
            confirmou_alvo = (
                lido is not None
                and abs(float(lido) - float(candidato)) <= tolerancia
            )
            mudou_hardware = (
                lido is not None
                and antes is not None
                and abs(float(lido) - float(antes)) > tolerancia
            )
            if retorno or confirmou_alvo or mudou_hardware:
                efetivo = float(lido) if lido is not None else float(candidato)
                ajustado = abs(efetivo - solicitado) > tolerancia
                return (True, lido, efetivo, bool(ajustado))

        return (False, ultimo_lido, None, False)

    def _definir_foco_manual_directshow(self, capture, valor):
        """Compatibilidade com chamadas existentes do fallback de foco."""
        if not self._directshow_ativo():
            return None
        confirmado, lido, efetivo, _ajustado = (
            self._definir_controle_manual_confirmado(
                capture,
                "focus",
                valor,
            )
        )
        return (confirmado, lido, efetivo)

    def _candidatos_automaticos(self, chave: str, automatico: bool) -> list[float]:
        preferido = self._valor_controle_automatico(chave, automatico)
        candidatos = [float(preferido)]
        if self._directshow_ativo():
            if chave == "exposure_auto":
                candidatos.extend(
                    (0.75, 1.0, 3.0) if automatico else (0.25, 0.0)
                )
            else:
                candidatos.extend((1.0,) if automatico else (0.0,))

        resultado = []
        vistos = set()
        for valor in candidatos:
            chave_valor = round(float(valor), 6)
            if chave_valor in vistos:
                continue
            vistos.add(chave_valor)
            resultado.append(float(valor))
        return resultado

    def _definir_automatico_confirmado(
        self,
        capture,
        chave: str,
        automatico: bool,
    ):
        _nome_manual, _nome_status, atributo = self._CONTROLES_AUTOMATICOS[chave]
        propriedade = getattr(cv2, atributo, None)
        if capture is None or propriedade is None:
            return (False, None, None, True)

        antes = self._ler_propriedade_capture(capture, propriedade)
        candidatos = self._candidatos_automaticos(chave, automatico)
        ultimo_lido = antes

        for candidato in candidatos:
            try:
                retorno = bool(capture.set(propriedade, float(candidato)))
            except Exception:
                retorno = False
            lido = self._ler_propriedade_capture(capture, propriedade)
            ultimo_lido = lido

            ja_estava = (
                antes is not None
                and abs(float(antes) - float(candidato)) <= 0.01
            )
            confirmou = (
                lido is not None
                and abs(float(lido) - float(candidato)) <= 0.01
            )
            mudou = (
                lido is not None
                and antes is not None
                and abs(float(lido) - float(antes)) > 0.01
            )
            if retorno or confirmou or ja_estava or mudou:
                return (True, lido, float(candidato), False)

        return (False, ultimo_lido, None, False)

    def _propriedade_manual(self, nome: str):
        atributo = self._PROPRIEDADES_MANUAIS.get(nome)
        return getattr(cv2, atributo, None) if atributo else None

    def _valor_controle_automatico(self, chave: str, automatico: bool) -> float:
        if chave == "exposure_auto":
            metodo = getattr(self, "_valor_auto_exposure", None)
            if callable(metodo):
                return float(metodo(bool(automatico)))
            if sys.platform.startswith("linux"):
                return 3.0 if automatico else 1.0
            return 0.75 if automatico else 0.25
        return 1.0 if automatico else 0.0

    def _capturar_valor_hardware(self, capture, nome: str):
        propriedade = self._propriedade_manual(nome)
        valor = self._ler_propriedade_capture(capture, propriedade)
        if valor is not None:
            with self._lock:
                self._camera_live_valores_hardware[nome] = float(valor)
        return valor

    def _garantir_baseline(self, capture, nome: str):
        with self._lock:
            existente = self._camera_live_baselines.get(nome)
        if existente is not None:
            return existente

        atual = self._capturar_valor_hardware(capture, nome)
        if atual is None:
            return None
        with self._lock:
            self._camera_live_baselines[nome] = float(atual)
        return float(atual)

    def _capturar_estado_hardware_inicial(self, capture, configuracoes: dict) -> None:
        for nome in self._PROPRIEDADES_MANUAIS:
            atual = self._capturar_valor_hardware(capture, nome)
            if (
                atual is not None
                and bool(configuracoes.get(f"{nome}_enabled", False))
            ):
                with self._lock:
                    self._camera_live_baselines.setdefault(nome, float(atual))

    def _aplicar_habilitacao_manual(
        self,
        capture,
        nome: str,
        habilitado: bool,
    ) -> None:
        propriedade = self._propriedade_manual(nome)
        if propriedade is None:
            self._registrar_status_controle(nome, "nao_suportado")
            return

        if habilitado:
            baseline = self._garantir_baseline(capture, nome)
            if baseline is None:
                self._registrar_status_controle(nome, "nao_suportado")
                return
            # Importante: habilitar manual NÃO escreve o valor antigo do slider.
            # A imagem permanece exatamente como estava até o usuário mover o ajuste.
            self._registrar_status_controle(
                nome,
                "manual_pronto",
                valor_solicitado=baseline,
                valor_lido=baseline,
            )
            return

        with self._lock:
            baseline = self._camera_live_baselines.pop(nome, None)

        if baseline is None:
            atual = self._capturar_valor_hardware(capture, nome)
            self._registrar_status_controle(
                nome,
                "padrao_driver",
                valor_lido=atual,
            )
            return

        aplicado, lido, _efetivo, _ajustado = (
            self._definir_controle_manual_confirmado(
                capture,
                nome,
                baseline,
            )
        )
        if lido is not None:
            with self._lock:
                self._camera_live_valores_hardware[nome] = float(lido)
        self._registrar_status_controle(
            nome,
            "restaurado" if aplicado else "ignorado_driver",
            valor_solicitado=baseline,
            valor_lido=lido,
        )

    def _aplicar_valor_manual(
        self,
        capture,
        nome: str,
        configuracoes: dict,
    ) -> None:
        if not bool(configuracoes.get(f"{nome}_enabled", False)):
            return

        propriedade = self._propriedade_manual(nome)
        if propriedade is None:
            self._registrar_status_controle(nome, "nao_suportado")
            return

        self._garantir_baseline(capture, nome)
        try:
            valor = float(configuracoes.get(nome))
        except (TypeError, ValueError):
            return

        aplicado, lido, valor_efetivo, ajustado = (
            self._definir_controle_manual_confirmado(
                capture,
                nome,
                valor,
            )
        )

        if lido is not None:
            with self._lock:
                self._camera_live_valores_hardware[nome] = float(lido)

        self._registrar_status_controle(
            nome,
            (
                "ajustado_driver"
                if aplicado and ajustado
                else ("aplicado" if aplicado else "ignorado_driver")
            ),
            valor_solicitado=valor,
            valor_lido=lido,
        )

    def _aplicar_automatico(
        self,
        capture,
        chave: str,
        automatico: bool,
    ) -> None:
        nome_manual, nome_status, atributo = self._CONTROLES_AUTOMATICOS[chave]
        propriedade = getattr(cv2, atributo, None)
        valor = self._valor_controle_automatico(chave, automatico)

        if propriedade is None:
            aplicado, lido, valor_efetivo, ausente = (
                False,
                None,
                None,
                True,
            )
        else:
            aplicado, lido, valor_efetivo, ausente = (
                self._definir_automatico_confirmado(
                    capture,
                    chave,
                    automatico,
                )
            )

        if ausente:
            status_auto = "nao_suportado"
            status_manual = "nao_suportado"
        elif aplicado:
            status_auto = "aplicado"
            status_manual = "automatico" if automatico else "manual_disponivel"
        else:
            # Uma escrita recusada não prova falta de suporte; mantém o controle
            # disponível para novas tentativas/valores.
            status_auto = "ignorado_driver"
            status_manual = "ignorado_driver"

        self._registrar_status_controle(
            nome_status,
            status_auto,
            valor_solicitado=valor,
            valor_lido=lido,
        )
        self._registrar_status_controle(
            nome_manual,
            status_manual,
            valor_solicitado=(
                valor if valor_efetivo is None else valor_efetivo
            ),
            valor_lido=self._capturar_valor_hardware(capture, nome_manual),
        )

    @staticmethod
    def _prioridade_chave_ao_vivo(chave: str, configuracoes: dict) -> tuple[int, str]:
        if chave.endswith("_enabled"):
            habilitado = bool(configuracoes.get(chave, False))
            return (0 if not habilitado else 2, chave)
        if chave.endswith("_auto"):
            return (1, chave)
        return (3, chave)

    def _aplicar_chave_ao_vivo(
        self,
        capture,
        chave: str,
        configuracoes: dict,
    ) -> None:
        if chave in self._CONTROLES_AUTOMATICOS:
            self._aplicar_automatico(
                capture,
                chave,
                bool(configuracoes.get(chave, True)),
            )
            return

        if chave == "rotation":
            rotacao = int(configuracoes.get("rotation", 0))
            self._registrar_status_controle(
                "rotation",
                "aplicado_software",
                valor_solicitado=rotacao,
                valor_lido=rotacao,
            )
            return

        if chave.endswith("_enabled"):
            nome = chave[: -len("_enabled")]
            if nome in self._PROPRIEDADES_MANUAIS:
                self._aplicar_habilitacao_manual(
                    capture,
                    nome,
                    bool(configuracoes.get(chave, False)),
                )
            return

        if chave in self._PROPRIEDADES_MANUAIS:
            self._aplicar_valor_manual(capture, chave, configuracoes)

    def _aplicar_configuracoes_hardware(self) -> None:
        capture = getattr(self, "_capture", None)
        if capture is None or not getattr(self, "_controles_pendentes", False):
            return

        configuracoes = self.obter_configuracoes_camera()
        chaves = self._consumir_chaves_camera_ao_vivo()

        if not chaves:
            # Na primeira aplicação completa, memoriza o estado verdadeiro do
            # dispositivo antes de qualquer configuração manual persistida.
            self._capturar_estado_hardware_inicial(capture, configuracoes)
            super()._aplicar_configuracoes_hardware()
            return

        chaves_ordenadas = sorted(
            chaves,
            key=lambda chave: self._prioridade_chave_ao_vivo(
                chave,
                configuracoes,
            ),
        )
        for chave in chaves_ordenadas:
            self._aplicar_chave_ao_vivo(capture, chave, configuracoes)

        self._controles_pendentes = False
