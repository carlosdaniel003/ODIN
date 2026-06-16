from __future__ import annotations

import threading
from dataclasses import dataclass

import cv2


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
        intervalo_reconexao_s: float = 2.0,
        frames_aquecimento: int = 12,
        falhas_antes_reconexao: int = 15,
        largura_minima: int = 320,
        altura_minima: int = 240,
        limite_preto_media: float = 4.0,
        limite_preto_desvio: float = 3.0,
    ) -> None:
        self.indice_camera = int(indice_camera)
        self.largura = int(largura)
        self.altura = int(altura)
        self.fps = int(fps)
        self.intervalo_reconexao_s = max(0.5, float(intervalo_reconexao_s))
        self.frames_aquecimento = max(0, int(frames_aquecimento))
        self.falhas_antes_reconexao = max(1, int(falhas_antes_reconexao))
        self.largura_minima = max(1, int(largura_minima))
        self.altura_minima = max(1, int(altura_minima))
        self.limite_preto_media = float(limite_preto_media)
        self.limite_preto_desvio = float(limite_preto_desvio)

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
        self._definir_estado(
            self.ESTADO_CONECTANDO,
            "Conectando câmera...",
        )
        self._thread = threading.Thread(
            target=self._executar,
            name="LumusPCI-CameraService",
            daemon=True,
        )
        self._thread.start()

    def parar(self) -> None:
        self._stop_event.set()
        self._definir_estado(
            self.ESTADO_PARADA,
            "Câmera parada.",
        )

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
        capture = cv2.VideoCapture(
            self.indice_camera,
            cv2.CAP_DSHOW,
        )

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

        capture.set(
            cv2.CAP_PROP_FOURCC,
            cv2.VideoWriter_fourcc(*"MJPG"),
        )
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.largura)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.altura)
        capture.set(cv2.CAP_PROP_FPS, self.fps)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        return capture

    def _frame_valido(
        self,
        frame,
        resolucao_estavel: tuple[int, int] | None,
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

        if resolucao_estavel is not None:
            largura_estavel, altura_estavel = resolucao_estavel

            if (
                largura_frame != largura_estavel
                or altura_frame != altura_estavel
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
                desvio_esquerda <= 1.0
                and desvio_direita >= 8.0
            ) or (
                desvio_direita <= 1.0
                and desvio_esquerda >= 8.0
            ):
                return False

        return True

    def _aguardar_reconexao(self) -> bool:
        return self._stop_event.wait(self.intervalo_reconexao_s)

    def _executar(self) -> None:
        ja_conectou_antes = False

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

            resolucao_estavel: tuple[int, int] | None = None
            frames_descartar = self.frames_aquecimento
            falhas_consecutivas = 0

            while not self._stop_event.is_set():
                sucesso, frame = capture.read()

                if not sucesso or not self._frame_valido(frame, resolucao_estavel):
                    falhas_consecutivas += 1

                    if falhas_consecutivas >= self.falhas_antes_reconexao:
                        break

                    continue

                altura_frame, largura_frame = frame.shape[:2]

                if resolucao_estavel is None:
                    resolucao_estavel = (
                        largura_frame,
                        altura_frame,
                    )

                falhas_consecutivas = 0

                if frames_descartar > 0:
                    frames_descartar -= 1
                    continue

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

        self._definir_estado(
            self.ESTADO_PARADA,
            "Câmera parada.",
        )
