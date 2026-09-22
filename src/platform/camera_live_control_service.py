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

    @staticmethod
    def _candidatos_foco_directshow(valor: float) -> list[float]:
        """Valores próximos para drivers que expõem foco em passos discretos."""
        try:
            solicitado = min(255.0, max(0.0, float(valor)))
        except (TypeError, ValueError):
            return []

        candidatos = [solicitado]
        for passo in (5.0, 10.0, 17.0):
            base = round(solicitado / passo) * passo
            candidatos.extend((base, base - passo, base + passo))

        unicos = []
        vistos = set()
        for candidato in candidatos:
            candidato = min(255.0, max(0.0, float(candidato)))
            chave = round(candidato, 6)
            if chave in vistos:
                continue
            vistos.add(chave)
            unicos.append(candidato)
        return unicos

    def _definir_foco_manual_directshow(self, capture, valor):
        """Fallback sem dependência externa para foco manual no DirectShow.

        Fora do DirectShow retorna None. No DirectShow garante autofocus OFF,
        tenta o valor solicitado e depois os passos discretos mais próximos.
        A leitura de volta também confirma aplicação quando o backend retorna
        False apesar de o dispositivo ter aceitado o valor.
        """
        if not self._directshow_ativo():
            return None

        foco = getattr(cv2, "CAP_PROP_FOCUS", None)
        autofocus = getattr(cv2, "CAP_PROP_AUTOFOCUS", None)
        if capture is None or foco is None:
            return (False, None, None)

        if autofocus is not None:
            try:
                capture.set(autofocus, 0.0)
            except Exception:
                pass

        ultimo_lido = self._ler_propriedade_capture(capture, foco)
        for candidato in self._candidatos_foco_directshow(valor):
            try:
                retorno = bool(capture.set(foco, float(candidato)))
            except Exception:
                retorno = False

            lido = self._ler_propriedade_capture(capture, foco)
            ultimo_lido = lido
            confirmado = (
                lido is not None
                and abs(float(lido) - float(candidato)) <= 1.0
            )
            if retorno or confirmado:
                return (True, lido, float(candidato))

        return (False, ultimo_lido, None)

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

        aplicado, lido = self._definir_propriedade_capture(
            capture,
            propriedade,
            baseline,
        )
        if lido is not None:
            with self._lock:
                self._camera_live_valores_hardware[nome] = float(lido)
        self._registrar_status_controle(
            nome,
            "restaurado" if aplicado else "nao_suportado",
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

        aplicado, lido = self._definir_propriedade_capture(
            capture,
            propriedade,
            valor,
        )
        if lido is not None:
            with self._lock:
                self._camera_live_valores_hardware[nome] = float(lido)
        self._registrar_status_controle(
            nome,
            "aplicado" if aplicado else "nao_suportado",
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
        aplicado, lido = self._definir_propriedade_capture(
            capture,
            propriedade,
            valor,
        )

        status = "automatico" if automatico else "manual_disponivel"
        if not aplicado:
            status = "nao_suportado"

        self._registrar_status_controle(
            nome_status,
            "aplicado" if aplicado else "nao_suportado",
            valor_solicitado=valor,
            valor_lido=lido,
        )
        self._registrar_status_controle(
            nome_manual,
            status,
            valor_solicitado=valor,
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
