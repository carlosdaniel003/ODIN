from __future__ import annotations

import math
import threading
from dataclasses import dataclass

import cv2
import numpy as np

from config import (
    CAMERA_IMAGE_CONTROL_MAX,
    CAMERA_IMAGE_CONTROL_MIN,
    CAMERA_PAN_MAX,
    CAMERA_PAN_MIN,
    CAMERA_ROTATIONS,
    CAMERA_TILT_MAX,
    CAMERA_TILT_MIN,
    DEFAULT_CAMERA_SETTINGS,
)


@dataclass(frozen=True)
class CameraSnapshot:
    estado: str
    mensagem: str
    frame_id: int
    frame: object | None
    resolucao: tuple[int, int] | None


class CameraService:
    ESTADO_PARADA = "parada"
    ESTADO_CONECTANDO = "conectando"
    ESTADO_ESTABILIZANDO = "estabilizando"
    ESTADO_CONECTADA = "conectada"
    ESTADO_DESCONECTADA = "desconectada"

    def __init__(
        self,
        indice_camera: int,
        largura: int,
        altura: int,
        fps: int,
        intervalo_reconexao_s: float = 1.0,
        frames_aquecimento: int = 30,
        falhas_antes_reconexao: int = 3,
        largura_minima: int = 320,
        altura_minima: int = 240,
        limite_preto_media: float = 4.0,
        limite_preto_desvio: float = 3.0,
        frames_estabilidade: int = 8,
        espera_apos_abrir_s: float = 0.45,
        configuracoes_camera: dict | None = None,
    ) -> None:
        self.indice_camera = int(indice_camera)
        self.largura = int(largura)
        self.altura = int(altura)
        self.fps = int(fps)
        self.intervalo_reconexao_s = max(0.25, float(intervalo_reconexao_s))
        self.frames_aquecimento = max(60, int(frames_aquecimento))
        self.falhas_antes_reconexao = max(5, int(falhas_antes_reconexao))
        self.largura_minima = max(1, int(largura_minima))
        self.altura_minima = max(1, int(altura_minima))
        self.limite_preto_media = float(limite_preto_media)
        self.limite_preto_desvio = float(limite_preto_desvio)
        self.frames_estabilidade = max(15, int(frames_estabilidade))
        self.espera_apos_abrir_s = max(0.8, float(espera_apos_abrir_s))

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._estado = self.ESTADO_PARADA
        self._mensagem = "Câmera parada."
        self._ultimo_frame = None
        self._frame_id = 0
        self._resolucao: tuple[int, int] | None = None
        self._configuracoes_camera = self._normalizar_configuracoes_camera(
            configuracoes_camera
        )
        self._versao_configuracoes_camera = 0
        self._versao_configuracoes_aplicada = -1
        self._status_controles_camera = {
            nome: {
                "status": "aguardando_camera",
                "valor_solicitado": None,
                "valor_lido": None,
            }
            for nome in (
                "pan",
                "tilt",
                "contrast",
                "sharpness",
                "saturation",
                "rotation",
            )
        }

    def iniciar(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._definir_estado(self.ESTADO_CONECTANDO, "Conectando câmera...")
        self._thread = threading.Thread(
            target=self._executar,
            name="LumusPCI-CameraService",
            daemon=True,
        )
        self._thread.start()

    def parar(self) -> None:
        self._stop_event.set()
        self._definir_estado(self.ESTADO_PARADA, "Câmera parada.")

    @staticmethod
    def _limitar_float(
        valor,
        minimo: float,
        maximo: float,
        padrao: float,
    ) -> float:
        try:
            numero = float(valor)
        except (TypeError, ValueError):
            numero = float(padrao)

        return min(float(maximo), max(float(minimo), numero))

    @classmethod
    def _normalizar_configuracoes_camera(
        cls,
        configuracoes_camera: dict | None,
    ) -> dict:
        origem = (
            configuracoes_camera
            if isinstance(configuracoes_camera, dict)
            else {}
        )
        padrao = DEFAULT_CAMERA_SETTINGS

        try:
            rotacao = int(
                origem.get("rotation", padrao["rotation"])
            )
        except (TypeError, ValueError):
            rotacao = int(padrao["rotation"])

        if rotacao not in CAMERA_ROTATIONS:
            rotacao = int(padrao["rotation"])

        return {
            "pan_enabled": bool(
                origem.get("pan_enabled", padrao["pan_enabled"])
            ),
            "pan": cls._limitar_float(
                origem.get("pan", padrao["pan"]),
                CAMERA_PAN_MIN,
                CAMERA_PAN_MAX,
                padrao["pan"],
            ),
            "tilt_enabled": bool(
                origem.get("tilt_enabled", padrao["tilt_enabled"])
            ),
            "tilt": cls._limitar_float(
                origem.get("tilt", padrao["tilt"]),
                CAMERA_TILT_MIN,
                CAMERA_TILT_MAX,
                padrao["tilt"],
            ),
            "contrast_enabled": bool(
                origem.get(
                    "contrast_enabled",
                    padrao["contrast_enabled"],
                )
            ),
            "contrast": cls._limitar_float(
                origem.get("contrast", padrao["contrast"]),
                CAMERA_IMAGE_CONTROL_MIN,
                CAMERA_IMAGE_CONTROL_MAX,
                padrao["contrast"],
            ),
            "sharpness_enabled": bool(
                origem.get(
                    "sharpness_enabled",
                    padrao["sharpness_enabled"],
                )
            ),
            "sharpness": cls._limitar_float(
                origem.get("sharpness", padrao["sharpness"]),
                CAMERA_IMAGE_CONTROL_MIN,
                CAMERA_IMAGE_CONTROL_MAX,
                padrao["sharpness"],
            ),
            "saturation_enabled": bool(
                origem.get(
                    "saturation_enabled",
                    padrao["saturation_enabled"],
                )
            ),
            "saturation": cls._limitar_float(
                origem.get("saturation", padrao["saturation"]),
                CAMERA_IMAGE_CONTROL_MIN,
                CAMERA_IMAGE_CONTROL_MAX,
                padrao["saturation"],
            ),
            "rotation": rotacao,
        }

    def atualizar_configuracoes_camera(
        self,
        configuracoes_camera: dict | None,
    ) -> None:
        configuracoes = self._normalizar_configuracoes_camera(
            configuracoes_camera
        )

        with self._lock:
            self._configuracoes_camera = configuracoes
            self._versao_configuracoes_camera += 1

    def obter_configuracoes_camera(self) -> dict:
        with self._lock:
            return dict(self._configuracoes_camera)

    def obter_status_controles_camera(self) -> dict:
        with self._lock:
            return {
                nome: dict(status)
                for nome, status in self._status_controles_camera.items()
            }

    def _obter_configuracoes_camera_com_versao(
        self,
    ) -> tuple[dict, int]:
        with self._lock:
            return (
                dict(self._configuracoes_camera),
                int(self._versao_configuracoes_camera),
            )

    def _registrar_status_controle(
        self,
        nome: str,
        status: str,
        valor_solicitado=None,
        valor_lido=None,
    ) -> None:
        with self._lock:
            self._status_controles_camera[nome] = {
                "status": status,
                "valor_solicitado": valor_solicitado,
                "valor_lido": valor_lido,
            }

    def _aplicar_controle_hardware(
        self,
        capture,
        nome: str,
        propriedade: int | None,
        habilitado: bool,
        valor: float,
    ) -> None:
        if propriedade is None:
            self._registrar_status_controle(
                nome,
                "nao_suportado",
                valor_solicitado=valor,
            )
            return

        if not habilitado:
            valor_lido = None

            try:
                leitura = float(capture.get(propriedade))

                if math.isfinite(leitura):
                    valor_lido = leitura
            except Exception:
                pass

            self._registrar_status_controle(
                nome,
                "padrao_driver",
                valor_lido=valor_lido,
            )
            return

        try:
            aplicado = bool(capture.set(propriedade, float(valor)))
        except Exception:
            aplicado = False

        valor_lido = None

        try:
            leitura = float(capture.get(propriedade))

            if math.isfinite(leitura):
                valor_lido = leitura
        except Exception:
            pass

        self._registrar_status_controle(
            nome,
            "aplicado" if aplicado else "nao_suportado",
            valor_solicitado=float(valor),
            valor_lido=valor_lido,
        )

    def _aplicar_configuracoes_hardware(
        self,
        capture,
        forcar: bool = False,
    ) -> bool:
        configuracoes, versao = (
            self._obter_configuracoes_camera_com_versao()
        )

        if (
            not forcar
            and versao == self._versao_configuracoes_aplicada
        ):
            return False

        propriedades = {
            "pan": getattr(cv2, "CAP_PROP_PAN", None),
            "tilt": getattr(cv2, "CAP_PROP_TILT", None),
            "contrast": getattr(cv2, "CAP_PROP_CONTRAST", None),
            "sharpness": getattr(cv2, "CAP_PROP_SHARPNESS", None),
            "saturation": getattr(cv2, "CAP_PROP_SATURATION", None),
        }

        for nome in (
            "pan",
            "tilt",
            "contrast",
            "sharpness",
            "saturation",
        ):
            self._aplicar_controle_hardware(
                capture=capture,
                nome=nome,
                propriedade=propriedades[nome],
                habilitado=bool(
                    configuracoes.get(f"{nome}_enabled", False)
                ),
                valor=float(configuracoes.get(nome, 0.0)),
            )

        self._registrar_status_controle(
            "rotation",
            "aplicado_software",
            valor_solicitado=int(
                configuracoes.get("rotation", 0)
            ),
            valor_lido=int(configuracoes.get("rotation", 0)),
        )
        self._versao_configuracoes_aplicada = versao
        return True

    def _aplicar_rotacao(self, frame):
        configuracoes, _ = (
            self._obter_configuracoes_camera_com_versao()
        )
        rotacao = int(configuracoes.get("rotation", 0))

        if rotacao == 90:
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)

        if rotacao == 180:
            return cv2.rotate(frame, cv2.ROTATE_180)

        if rotacao == 270:
            return cv2.rotate(
                frame,
                cv2.ROTATE_90_COUNTERCLOCKWISE,
            )

        return frame

    def obter_snapshot(self, ultimo_frame_id: int = -1) -> CameraSnapshot:
        with self._lock:
            frame = None

            if self._ultimo_frame is not None and self._frame_id != ultimo_frame_id:
                frame = self._ultimo_frame.copy()

            return CameraSnapshot(
                estado=self._estado,
                mensagem=self._mensagem,
                frame_id=self._frame_id,
                frame=frame,
                resolucao=self._resolucao,
            )

    def _definir_estado(self, estado: str, mensagem: str) -> None:
        with self._lock:
            self._estado = estado
            self._mensagem = mensagem

    def _publicar_frame(self, frame) -> None:
        altura_frame, largura_frame = frame.shape[:2]

        with self._lock:
            self._ultimo_frame = frame.copy()
            self._frame_id += 1
            self._resolucao = (largura_frame, altura_frame)
            self._estado = self.ESTADO_CONECTADA
            self._mensagem = "Câmera conectada."

    def _abrir_camera(self):
        capture = cv2.VideoCapture(self.indice_camera, cv2.CAP_DSHOW)

        if not capture.isOpened():
            try:
                capture.release()
            except Exception:
                pass
            capture = cv2.VideoCapture(self.indice_camera)

        if not capture.isOpened():
            try:
                capture.release()
            except Exception:
                pass
            return None

        # O formato é negociado antes da resolução. Isso reduz frames MJPG
        # parcialmente decodificados após reconectar o USB.
        capture.set(
            cv2.CAP_PROP_FOURCC,
            cv2.VideoWriter_fourcc(*"MJPG"),
        )
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.largura)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.altura)
        capture.set(cv2.CAP_PROP_FPS, self.fps)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        # Nem todo backend respeita estas propriedades, mas são seguras quando
        # disponíveis e evitam leituras muito longas após retirar o USB.
        if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
            capture.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 700)

        if self.espera_apos_abrir_s > 0:
            if self._stop_event.wait(self.espera_apos_abrir_s):
                try:
                    capture.release()
                except Exception:
                    pass
                return None

        self._aplicar_configuracoes_hardware(
            capture,
            forcar=True,
        )

        return capture

    @staticmethod
    def _possui_metade_duplicada(frame_cinza) -> bool:
        altura, largura = frame_cinza.shape[:2]
        metade = largura // 2

        if metade < 32:
            return False

        esquerda = frame_cinza[:, :metade]
        direita = frame_cinza[:, largura - metade:]

        largura_teste = min(esquerda.shape[1], direita.shape[1], 320)
        altura_teste = min(altura, 180)

        esquerda = cv2.resize(esquerda, (largura_teste, altura_teste))
        direita = cv2.resize(direita, (largura_teste, altura_teste))

        diferenca_media = float(
            np.mean(
                np.abs(
                    esquerda.astype(np.int16) - direita.astype(np.int16)
                )
            )
        )

        return diferenca_media <= 1.2

    @staticmethod
    def _reduzir_frame_cinza(
        frame_cinza,
        largura_maxima: int = 640,
    ):
        altura, largura = frame_cinza.shape[:2]

        if largura <= largura_maxima:
            return frame_cinza

        largura_reduzida = int(largura_maxima)
        altura_reduzida = max(
            1,
            int(altura * (largura_reduzida / largura)),
        )
        return cv2.resize(
            frame_cinza,
            (largura_reduzida, altura_reduzida),
            interpolation=cv2.INTER_AREA,
        )

    @staticmethod
    def _contar_cortes_retilineos(
        diferencas,
        vertical: bool,
    ) -> int:
        if vertical:
            tamanho_eixo = diferencas.shape[1]
            perfil = diferencas.mean(axis=0)
        else:
            tamanho_eixo = diferencas.shape[0]
            perfil = diferencas.mean(axis=1)

        if tamanho_eixo < 40:
            return 0

        mediana = float(np.median(perfil)) + 1.0
        percentil_95 = float(np.percentile(perfil, 95)) + 1.0
        limite_perfil = max(22.0, mediana * 5.5, percentil_95 * 1.65)
        limite_pixel = max(24.0, mediana * 4.0)

        inicio = int(tamanho_eixo * 0.08)
        fim = int(tamanho_eixo * 0.92)
        candidatos = []

        for indice in range(inicio, fim):
            valor = float(perfil[indice])

            if valor < limite_perfil:
                continue

            if vertical:
                fracao_forte = float(
                    np.mean(diferencas[:, indice] >= limite_pixel)
                )
            else:
                fracao_forte = float(
                    np.mean(diferencas[indice, :] >= limite_pixel)
                )

            if fracao_forte >= 0.36:
                candidatos.append(indice)

        if not candidatos:
            return 0

        grupos = 1
        anterior = candidatos[0]

        for indice in candidatos[1:]:
            if indice - anterior > 5:
                grupos += 1
            anterior = indice

        return grupos

    @staticmethod
    def _possui_corte_retilineo_suspeito(frame_cinza) -> bool:
        cinza = CameraService._reduzir_frame_cinza(
            frame_cinza,
            largura_maxima=640,
        ).astype(np.int16)

        diferencas_x = np.abs(np.diff(cinza, axis=1))
        diferencas_y = np.abs(np.diff(cinza, axis=0))

        cortes_verticais = CameraService._contar_cortes_retilineos(
            diferencas_x,
            vertical=True,
        )
        cortes_horizontais = CameraService._contar_cortes_retilineos(
            diferencas_y,
            vertical=False,
        )

        return cortes_verticais >= 2 or cortes_horizontais >= 2

    @staticmethod
    def _possui_faixa_interna_suspeita(frame_cinza) -> bool:
        cinza = CameraService._reduzir_frame_cinza(
            frame_cinza,
            largura_maxima=640,
        ).astype(np.float32)

        altura, largura = cinza.shape[:2]

        if altura < 120 or largura < 160:
            return False

        # Frames parcialmente decodificados costumam apresentar blocos com
        # textura/luminosidade muito diferente separados por linhas retas.
        # A checagem abaixo compara faixas internas com suas vizinhas.
        faixas_x = 12
        largura_faixa = max(8, largura // faixas_x)
        medias_x = []
        desvios_x = []

        for indice in range(faixas_x):
            x1 = indice * largura_faixa
            x2 = largura if indice == faixas_x - 1 else (indice + 1) * largura_faixa
            trecho = cinza[:, x1:x2]
            medias_x.append(float(trecho.mean()))
            desvios_x.append(float(trecho.std()))

        saltos_media_x = np.abs(np.diff(np.array(medias_x)))
        saltos_desvio_x = np.abs(np.diff(np.array(desvios_x)))

        if (
            float(np.max(saltos_media_x)) >= 42.0
            and float(np.percentile(saltos_media_x, 85)) >= 18.0
            and float(np.max(saltos_desvio_x)) >= 18.0
        ):
            return True

        faixas_y = 8
        altura_faixa = max(8, altura // faixas_y)
        medias_y = []
        desvios_y = []

        for indice in range(faixas_y):
            y1 = indice * altura_faixa
            y2 = altura if indice == faixas_y - 1 else (indice + 1) * altura_faixa
            trecho = cinza[y1:y2, :]
            medias_y.append(float(trecho.mean()))
            desvios_y.append(float(trecho.std()))

        saltos_media_y = np.abs(np.diff(np.array(medias_y)))
        saltos_desvio_y = np.abs(np.diff(np.array(desvios_y)))

        return (
            float(np.max(saltos_media_y)) >= 42.0
            and float(np.percentile(saltos_media_y, 85)) >= 18.0
            and float(np.max(saltos_desvio_y)) >= 18.0
        )

    @staticmethod
    def _possui_emenda_suspeita(frame_cinza) -> bool:
        altura, largura = frame_cinza.shape[:2]

        if largura < 160 or altura < 120:
            return False

        largura_reduzida = min(480, largura)
        altura_reduzida = max(1, int(altura * (largura_reduzida / largura)))
        cinza = cv2.resize(
            frame_cinza,
            (largura_reduzida, altura_reduzida),
            interpolation=cv2.INTER_AREA,
        )
        cinza = cinza.astype(np.int16)

        diferencas_x = np.abs(np.diff(cinza, axis=1))
        pontuacao_colunas = diferencas_x.mean(axis=0)
        mediana_x = float(np.median(pontuacao_colunas)) + 1.0

        inicio_x = int(len(pontuacao_colunas) * 0.20)
        fim_x = int(len(pontuacao_colunas) * 0.80)

        if fim_x > inicio_x:
            trecho = pontuacao_colunas[inicio_x:fim_x]
            indice_local = int(np.argmax(trecho))
            indice = inicio_x + indice_local
            valor = float(pontuacao_colunas[indice])
            fracao_linhas_fortes = float(
                np.mean(diferencas_x[:, indice] >= 30)
            )

            if (
                valor >= max(28.0, mediana_x * 5.0)
                and fracao_linhas_fortes >= 0.42
            ):
                return True

        diferencas_y = np.abs(np.diff(cinza, axis=0))
        pontuacao_linhas = diferencas_y.mean(axis=1)
        mediana_y = float(np.median(pontuacao_linhas)) + 1.0

        inicio_y = int(len(pontuacao_linhas) * 0.20)
        fim_y = int(len(pontuacao_linhas) * 0.80)

        if fim_y > inicio_y:
            trecho = pontuacao_linhas[inicio_y:fim_y]
            indice_local = int(np.argmax(trecho))
            indice = inicio_y + indice_local
            valor = float(pontuacao_linhas[indice])
            fracao_colunas_fortes = float(
                np.mean(diferencas_y[indice, :] >= 30)
            )

            if (
                valor >= max(28.0, mediana_y * 5.0)
                and fracao_colunas_fortes >= 0.42
            ):
                return True

        # Os filtros abaixo foram mantidos no arquivo para diagnóstico futuro,
        # mas não são usados como bloqueio no modo estável. Em placas PCI reais,
        # trilhas, bordas de componentes e divisões naturais podem parecer
        # cortes para esses filtros e impedir a transmissão contínua.
        #
        # if CameraService._possui_corte_retilineo_suspeito(frame_cinza):
        #     return True
        #
        # if CameraService._possui_faixa_interna_suspeita(frame_cinza):
        #     return True

        return False

    @staticmethod
    def _calcular_assinatura_estabilidade(frame_cinza):
        assinatura = cv2.resize(
            frame_cinza,
            (96, 54),
            interpolation=cv2.INTER_AREA,
        )
        assinatura = cv2.GaussianBlur(assinatura, (5, 5), 0)
        return assinatura.astype(np.int16)

    @staticmethod
    def _diferenca_assinaturas(assinatura_atual, assinatura_anterior) -> float:
        if assinatura_atual is None or assinatura_anterior is None:
            return 0.0

        return float(
            np.mean(
                np.abs(assinatura_atual - assinatura_anterior)
            )
        )

    def _frame_valido(
        self,
        frame,
        resolucao_obrigatoria: tuple[int, int] | None,
    ) -> bool:
        if frame is None or frame.size == 0:
            return False

        if len(frame.shape) != 3 or frame.shape[2] != 3:
            return False

        altura_frame, largura_frame = frame.shape[:2]

        if (
            largura_frame < self.largura_minima
            or altura_frame < self.altura_minima
        ):
            return False

        if resolucao_obrigatoria is not None:
            largura_esperada, altura_esperada = resolucao_obrigatoria

            if (
                largura_frame != largura_esperada
                or altura_frame != altura_esperada
            ):
                return False

        frame_cinza = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        media_luminosidade = float(frame_cinza.mean())
        desvio_luminosidade = float(frame_cinza.std())

        if (
            media_luminosidade <= self.limite_preto_media
            and desvio_luminosidade <= self.limite_preto_desvio
        ):
            return False

        metade = largura_frame // 2

        if metade > 0:
            esquerda = frame_cinza[:, :metade]
            direita = frame_cinza[:, metade:]
            desvio_esquerda = float(esquerda.std())
            desvio_direita = float(direita.std())

            if (
                desvio_esquerda <= 1.0 and desvio_direita >= 8.0
            ) or (
                desvio_direita <= 1.0 and desvio_esquerda >= 8.0
            ):
                return False

        if self._possui_metade_duplicada(frame_cinza):
            return False

        if self._possui_emenda_suspeita(frame_cinza):
            return False

        return True

    def _aguardar_reconexao(self) -> bool:
        return self._stop_event.wait(self.intervalo_reconexao_s)

    def _executar(self) -> None:
        ja_conectou_antes = False
        resolucao_preferida: tuple[int, int] | None = None

        while not self._stop_event.is_set():
            self._definir_estado(
                self.ESTADO_CONECTANDO if not ja_conectou_antes else self.ESTADO_DESCONECTADA,
                (
                    "Conectando câmera..."
                    if not ja_conectou_antes
                    else "Câmera desconectada. Reconectando automaticamente..."
                ),
            )

            capture = self._abrir_camera()

            if capture is None:
                if self._stop_event.is_set():
                    break

                self._definir_estado(
                    self.ESTADO_DESCONECTADA,
                    "Câmera desconectada. Reconectando automaticamente...",
                )

                if self._aguardar_reconexao():
                    break
                continue

            self._definir_estado(
                self.ESTADO_ESTABILIZANDO,
                (
                    "Câmera reconectada. Estabilizando imagem..."
                    if ja_conectou_antes
                    else "Câmera conectada. Estabilizando imagem..."
                ),
            )

            resolucao_candidata: tuple[int, int] | None = None
            frames_descartar = self.frames_aquecimento
            frames_validos_consecutivos = 0
            falhas_leitura_consecutivas = 0
            frames_invalidos_consecutivos = 0
            limite_frames_invalidos = max(90, self.falhas_antes_reconexao * 20)
            camera_estabilizada = False
            assinatura_estabilidade_anterior = None

            while not self._stop_event.is_set():
                configuracao_alterada = (
                    self._aplicar_configuracoes_hardware(capture)
                )

                if configuracao_alterada:
                    self._definir_estado(
                        self.ESTADO_ESTABILIZANDO,
                        "Aplicando configurações da câmera...",
                    )
                    frames_descartar = max(frames_descartar, 15)
                    frames_validos_consecutivos = 0
                    camera_estabilizada = False
                    assinatura_estabilidade_anterior = None

                sucesso, frame = capture.read()

                resolucao_obrigatoria = (
                    resolucao_preferida
                    if ja_conectou_antes and resolucao_preferida is not None
                    else resolucao_candidata
                )

                if not sucesso or frame is None:
                    falhas_leitura_consecutivas += 1
                    frames_validos_consecutivos = 0
                    assinatura_estabilidade_anterior = None

                    if falhas_leitura_consecutivas >= self.falhas_antes_reconexao:
                        break
                    continue

                if not self._frame_valido(
                    frame,
                    resolucao_obrigatoria,
                ):
                    frames_invalidos_consecutivos += 1
                    frames_validos_consecutivos = 0
                    assinatura_estabilidade_anterior = None

                    self._definir_estado(
                        self.ESTADO_ESTABILIZANDO,
                        "Câmera conectada. Aguardando frame estável...",
                    )

                    # Frame inválido não significa necessariamente câmera
                    # desconectada. Pode ser apenas um frame parcial, preto,
                    # borrado ou instável no início. Só força reconexão se
                    # isso persistir por muitos frames.
                    if frames_invalidos_consecutivos >= limite_frames_invalidos:
                        break
                    continue

                altura_frame, largura_frame = frame.shape[:2]
                resolucao_atual = (largura_frame, altura_frame)

                if resolucao_candidata is None:
                    resolucao_candidata = resolucao_atual

                falhas_leitura_consecutivas = 0
                frames_invalidos_consecutivos = 0

                if frames_descartar > 0:
                    frames_descartar -= 1
                    continue

                frame_cinza_estabilidade = cv2.cvtColor(
                    frame,
                    cv2.COLOR_BGR2GRAY,
                )
                assinatura_atual = self._calcular_assinatura_estabilidade(
                    frame_cinza_estabilidade
                )

                if not camera_estabilizada:
                    if assinatura_estabilidade_anterior is None:
                        assinatura_estabilidade_anterior = assinatura_atual
                        frames_validos_consecutivos = 1
                        continue

                    diferenca_estabilidade = self._diferenca_assinaturas(
                        assinatura_atual,
                        assinatura_estabilidade_anterior,
                    )
                    assinatura_estabilidade_anterior = assinatura_atual

                    if diferenca_estabilidade > 45.0:
                        frames_validos_consecutivos = 1
                        continue

                    frames_validos_consecutivos += 1

                    if frames_validos_consecutivos < self.frames_estabilidade:
                        continue

                    camera_estabilizada = True
                    resolucao_preferida = resolucao_atual

                frame_processado = self._aplicar_rotacao(frame)
                self._publicar_frame(frame_processado)
                ja_conectou_antes = True

            try:
                capture.release()
            except Exception:
                pass

            if self._stop_event.is_set():
                break

            self._definir_estado(
                self.ESTADO_DESCONECTADA,
                "Câmera desconectada. Reconectando automaticamente...",
            )

            if self._aguardar_reconexao():
                break

        self._definir_estado(self.ESTADO_PARADA, "Câmera parada.")
