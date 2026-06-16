from __future__ import annotations

import threading
from dataclasses import dataclass

import cv2
import numpy as np


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
    ) -> None:
        self.indice_camera = int(indice_camera)
        self.largura = int(largura)
        self.altura = int(altura)
        self.fps = int(fps)
        self.intervalo_reconexao_s = max(0.25, float(intervalo_reconexao_s))
        self.frames_aquecimento = max(0, int(frames_aquecimento))
        self.falhas_antes_reconexao = max(1, int(falhas_antes_reconexao))
        self.largura_minima = max(1, int(largura_minima))
        self.altura_minima = max(1, int(altura_minima))
        self.limite_preto_media = float(limite_preto_media)
        self.limite_preto_desvio = float(limite_preto_desvio)
        self.frames_estabilidade = max(1, int(frames_estabilidade))
        self.espera_apos_abrir_s = max(0.0, float(espera_apos_abrir_s))

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._estado = self.ESTADO_PARADA
        self._mensagem = "Câmera parada."
        self._ultimo_frame = None
        self._frame_id = 0
        self._resolucao: tuple[int, int] | None = None

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

        inicio_x = int(len(pontuacao_colunas) * 0.30)
        fim_x = int(len(pontuacao_colunas) * 0.70)

        if fim_x > inicio_x:
            trecho = pontuacao_colunas[inicio_x:fim_x]
            indice_local = int(np.argmax(trecho))
            indice = inicio_x + indice_local
            valor = float(pontuacao_colunas[indice])
            fracao_linhas_fortes = float(
                np.mean(diferencas_x[:, indice] >= 38)
            )

            if (
                valor >= max(34.0, mediana_x * 6.0)
                and fracao_linhas_fortes >= 0.62
            ):
                return True

        diferencas_y = np.abs(np.diff(cinza, axis=0))
        pontuacao_linhas = diferencas_y.mean(axis=1)
        mediana_y = float(np.median(pontuacao_linhas)) + 1.0

        inicio_y = int(len(pontuacao_linhas) * 0.30)
        fim_y = int(len(pontuacao_linhas) * 0.70)

        if fim_y > inicio_y:
            trecho = pontuacao_linhas[inicio_y:fim_y]
            indice_local = int(np.argmax(trecho))
            indice = inicio_y + indice_local
            valor = float(pontuacao_linhas[indice])
            fracao_colunas_fortes = float(
                np.mean(diferencas_y[indice, :] >= 38)
            )

            if (
                valor >= max(34.0, mediana_y * 6.0)
                and fracao_colunas_fortes >= 0.62
            ):
                return True

        return False

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
            falhas_consecutivas = 0
            camera_estabilizada = False

            while not self._stop_event.is_set():
                sucesso, frame = capture.read()

                resolucao_obrigatoria = (
                    resolucao_preferida
                    if ja_conectou_antes and resolucao_preferida is not None
                    else resolucao_candidata
                )

                if not sucesso or not self._frame_valido(
                    frame,
                    resolucao_obrigatoria,
                ):
                    falhas_consecutivas += 1
                    frames_validos_consecutivos = 0

                    if falhas_consecutivas >= self.falhas_antes_reconexao:
                        break
                    continue

                altura_frame, largura_frame = frame.shape[:2]
                resolucao_atual = (largura_frame, altura_frame)

                if resolucao_candidata is None:
                    resolucao_candidata = resolucao_atual

                falhas_consecutivas = 0

                if frames_descartar > 0:
                    frames_descartar -= 1
                    continue

                frames_validos_consecutivos += 1

                if not camera_estabilizada:
                    if frames_validos_consecutivos < self.frames_estabilidade:
                        continue

                    camera_estabilizada = True
                    resolucao_preferida = resolucao_atual

                self._publicar_frame(frame)
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
