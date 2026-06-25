from __future__ import annotations

import math
import threading
from dataclasses import dataclass

import cv2

from config import (
    CAMERA_FORMATS,
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
    resolucao_solicitada: tuple[int, int] | None = None
    fps_solicitado: int | None = None
    fps_real: float | None = None
    formato_solicitado: str | None = None
    formato_real: str | None = None


class CameraService:
    """
    Captura de câmera USB com negociação estável no Windows.

    No perfil automático, o driver escolhe resolução, FPS e formato.
    A câmera só é considerada desconectada após falhas reais e consecutivas
    de leitura. O conteúdo visual do frame não é usado para reiniciar o
    dispositivo.
    """

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
        self.largura = max(1, int(largura))
        self.altura = max(1, int(altura))
        self.fps = max(0, int(fps))

        self.intervalo_reconexao_s = max(
            0.5,
            float(intervalo_reconexao_s),
        )
        self.frames_aquecimento = min(
            15,
            max(3, int(frames_aquecimento)),
        )
        self.falhas_antes_reconexao = max(
            24,
            int(falhas_antes_reconexao) * 8,
        )
        self.largura_minima = max(1, int(largura_minima))
        self.altura_minima = max(1, int(altura_minima))

        # Mantidos por compatibilidade com a assinatura usada pelo app.
        self.limite_preto_media = float(limite_preto_media)
        self.limite_preto_desvio = float(limite_preto_desvio)
        self.frames_estabilidade = max(1, int(frames_estabilidade))
        self.espera_apos_abrir_s = min(
            1.0,
            max(0.10, float(espera_apos_abrir_s)),
        )

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._estado = self.ESTADO_PARADA
        self._mensagem = "Câmera parada."
        self._ultimo_frame = None
        self._frame_id = 0
        self._resolucao: tuple[int, int] | None = None
        self._resolucao_solicitada: tuple[int, int] | None = None
        self._fps_solicitado: int | None = None
        self._fps_real: float | None = None
        self._formato_solicitado: str | None = None
        self._formato_real: str | None = None
        self._backend_atual: str | None = None

        self._configuracoes_camera = self._normalizar_configuracoes_camera(
            configuracoes_camera
        )
        self._aplicar_perfil_camera_inicial()

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
            largura = int(origem.get("width", padrao["width"]))
        except (TypeError, ValueError):
            largura = int(padrao["width"])

        try:
            altura = int(origem.get("height", padrao["height"]))
        except (TypeError, ValueError):
            altura = int(padrao["height"])

        try:
            fps = int(origem.get("fps", padrao["fps"]))
        except (TypeError, ValueError):
            fps = int(padrao["fps"])

        fps_mode = str(
            origem.get("fps_mode", padrao["fps_mode"])
        ).lower()
        if fps_mode not in ("auto", "manual"):
            fps_mode = str(padrao["fps_mode"]).lower()

        if fps_mode == "auto":
            fps = 0

        formato = str(
            origem.get("format", padrao["format"])
        ).upper()
        if formato not in CAMERA_FORMATS:
            formato = str(padrao["format"]).upper()

        try:
            rotacao = int(
                origem.get("rotation", padrao["rotation"])
            )
        except (TypeError, ValueError):
            rotacao = int(padrao["rotation"])

        if rotacao not in CAMERA_ROTATIONS:
            rotacao = int(padrao["rotation"])

        return {
            "resolution_mode": str(
                origem.get(
                    "resolution_mode",
                    padrao["resolution_mode"],
                )
            ),
            "width": max(1, largura),
            "height": max(1, altura),
            "fps_mode": fps_mode,
            "fps": max(0, fps),
            "format": formato,
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

    def _aplicar_perfil_camera_inicial(self) -> None:
        configuracoes = self._configuracoes_camera

        self.modo_resolucao = str(
            configuracoes.get("resolution_mode", "auto")
        ).lower()
        self.perfil_automatico = self.modo_resolucao == "auto"

        self.largura = max(
            1,
            int(configuracoes.get("width", self.largura)),
        )
        self.altura = max(
            1,
            int(configuracoes.get("height", self.altura)),
        )

        fps_mode = str(
            configuracoes.get("fps_mode", "auto")
        ).lower()
        fps_configurado = max(
            0,
            int(configuracoes.get("fps", self.fps)),
        )

        formato = str(
            configuracoes.get("format", "AUTO")
        ).upper()
        if formato not in CAMERA_FORMATS:
            formato = "AUTO"

        if self.perfil_automatico:
            self.fps = 0
            self.formato_camera = "AUTO"
            self._resolucao_solicitada = None
            self._fps_solicitado = None
            self._formato_solicitado = "AUTO"
        else:
            self.fps = 0 if fps_mode == "auto" else fps_configurado
            self.formato_camera = formato
            self._resolucao_solicitada = (
                self.largura,
                self.altura,
            )
            self._fps_solicitado = (
                None if self.fps <= 0 else self.fps
            )
            self._formato_solicitado = self.formato_camera

    @staticmethod
    def _decodificar_fourcc(valor) -> str | None:
        try:
            numero = int(valor)
        except (TypeError, ValueError):
            return None

        if numero <= 0:
            return None

        caracteres = []

        for deslocamento in (0, 8, 16, 24):
            codigo = (numero >> deslocamento) & 255
            if 32 <= codigo <= 126:
                caracteres.append(chr(codigo))

        texto = "".join(caracteres).strip()
        return texto or None

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

        thread = self._thread
        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=1.5)

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
            aplicado = bool(
                capture.set(propriedade, float(valor))
            )
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

        rotacao = int(configuracoes.get("rotation", 0))
        self._registrar_status_controle(
            "rotation",
            "aplicado_software",
            valor_solicitado=rotacao,
            valor_lido=rotacao,
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

    def obter_snapshot(
        self,
        ultimo_frame_id: int = -1,
    ) -> CameraSnapshot:
        with self._lock:
            frame = None

            if (
                self._ultimo_frame is not None
                and self._frame_id != ultimo_frame_id
            ):
                frame = self._ultimo_frame.copy()

            return CameraSnapshot(
                estado=self._estado,
                mensagem=self._mensagem,
                frame_id=self._frame_id,
                frame=frame,
                resolucao=self._resolucao,
                resolucao_solicitada=self._resolucao_solicitada,
                fps_solicitado=self._fps_solicitado,
                fps_real=self._fps_real,
                formato_solicitado=self._formato_solicitado,
                formato_real=self._formato_real,
            )

    def _definir_estado(
        self,
        estado: str,
        mensagem: str,
    ) -> None:
        with self._lock:
            self._estado = estado
            self._mensagem = mensagem

    def _publicar_frame(self, frame) -> None:
        altura_frame, largura_frame = frame.shape[:2]

        backend_texto = (
            f" via {self._backend_atual}"
            if self._backend_atual
            else ""
        )

        with self._lock:
            self._ultimo_frame = frame.copy()
            self._frame_id += 1
            self._resolucao = (
                largura_frame,
                altura_frame,
            )
            self._estado = self.ESTADO_CONECTADA
            self._mensagem = (
                f"Câmera conectada{backend_texto}. "
                f"Resolução real: {largura_frame}x{altura_frame}."
            )

    @staticmethod
    def _normalizar_frame(frame):
        if frame is None:
            return None

        try:
            if frame.size == 0:
                return None
        except Exception:
            return None

        if len(frame.shape) == 2:
            return cv2.cvtColor(
                frame,
                cv2.COLOR_GRAY2BGR,
            )

        if len(frame.shape) != 3:
            return None

        if frame.shape[2] == 4:
            return cv2.cvtColor(
                frame,
                cv2.COLOR_BGRA2BGR,
            )

        if frame.shape[2] != 3:
            return None

        return frame

    def _frame_basico_valido(self, frame) -> bool:
        frame = self._normalizar_frame(frame)

        if frame is None:
            return False

        altura_frame, largura_frame = frame.shape[:2]

        return (
            largura_frame >= self.largura_minima
            and altura_frame >= self.altura_minima
        )

    def _obter_backends_candidatos(self) -> list[tuple[str, int]]:
        candidatos = []

        def adicionar(nome: str, valor: int) -> None:
            if all(item[1] != valor for item in candidatos):
                candidatos.append((nome, valor))

        if self.perfil_automatico:
            if hasattr(cv2, "CAP_MSMF"):
                adicionar("MSMF", cv2.CAP_MSMF)
            if hasattr(cv2, "CAP_DSHOW"):
                adicionar("DSHOW", cv2.CAP_DSHOW)
        else:
            if hasattr(cv2, "CAP_DSHOW"):
                adicionar("DSHOW", cv2.CAP_DSHOW)
            if hasattr(cv2, "CAP_MSMF"):
                adicionar("MSMF", cv2.CAP_MSMF)

        adicionar("AUTO", cv2.CAP_ANY)
        return candidatos

    def _abrir_video_capture(self, backend: int):
        if backend == cv2.CAP_ANY:
            return cv2.VideoCapture(self.indice_camera)

        return cv2.VideoCapture(
            self.indice_camera,
            backend,
        )

    def _aplicar_perfil_capture(self, capture) -> None:
        # Automático: deixa o driver negociar tudo.
        if self.perfil_automatico:
            return

        if self.formato_camera in ("MJPG", "YUY2"):
            try:
                capture.set(
                    cv2.CAP_PROP_FOURCC,
                    cv2.VideoWriter_fourcc(
                        *self.formato_camera
                    ),
                )
            except Exception:
                pass

        try:
            capture.set(
                cv2.CAP_PROP_FRAME_WIDTH,
                self.largura,
            )
            capture.set(
                cv2.CAP_PROP_FRAME_HEIGHT,
                self.altura,
            )
        except Exception:
            pass

        if self.fps > 0:
            try:
                capture.set(
                    cv2.CAP_PROP_FPS,
                    self.fps,
                )
            except Exception:
                pass

    def _registrar_parametros_reais(
        self,
        capture,
        backend_nome: str,
        frame,
    ) -> None:
        frame = self._normalizar_frame(frame)

        if frame is not None:
            altura_real, largura_real = frame.shape[:2]
        else:
            largura_real = int(
                capture.get(cv2.CAP_PROP_FRAME_WIDTH)
            )
            altura_real = int(
                capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
            )

        try:
            fps_real = float(
                capture.get(cv2.CAP_PROP_FPS)
            )
            if not math.isfinite(fps_real) or fps_real <= 0:
                fps_real = None
        except Exception:
            fps_real = None

        try:
            formato_real = self._decodificar_fourcc(
                capture.get(cv2.CAP_PROP_FOURCC)
            )
        except Exception:
            formato_real = None

        with self._lock:
            self._resolucao = (
                largura_real,
                altura_real,
            )
            self._fps_real = fps_real
            self._formato_real = formato_real
            self._backend_atual = backend_nome

    def _abrir_camera(self):
        for backend_nome, backend in self._obter_backends_candidatos():
            if self._stop_event.is_set():
                return None, None

            capture = None

            try:
                capture = self._abrir_video_capture(backend)
            except Exception:
                capture = None

            if capture is None or not capture.isOpened():
                if capture is not None:
                    try:
                        capture.release()
                    except Exception:
                        pass
                continue

            self._aplicar_perfil_capture(capture)

            if self._stop_event.wait(self.espera_apos_abrir_s):
                try:
                    capture.release()
                except Exception:
                    pass
                return None, None

            self._aplicar_configuracoes_hardware(
                capture,
                forcar=True,
            )

            primeiro_frame = None
            sucessos_consecutivos = 0

            for _ in range(self.frames_aquecimento):
                if self._stop_event.is_set():
                    break

                try:
                    sucesso, frame = capture.read()
                except Exception:
                    sucesso, frame = False, None

                frame = (
                    self._normalizar_frame(frame)
                    if sucesso
                    else None
                )

                if self._frame_basico_valido(frame):
                    sucessos_consecutivos += 1
                    primeiro_frame = frame

                    if sucessos_consecutivos >= 2:
                        break
                else:
                    sucessos_consecutivos = 0
                    self._stop_event.wait(0.02)

            if primeiro_frame is not None:
                self._registrar_parametros_reais(
                    capture,
                    backend_nome,
                    primeiro_frame,
                )
                return capture, primeiro_frame

            try:
                capture.release()
            except Exception:
                pass

        return None, None

    def _aguardar_reconexao(self) -> bool:
        return self._stop_event.wait(
            self.intervalo_reconexao_s
        )

    def _executar(self) -> None:
        ja_conectou_antes = False

        try:
            while not self._stop_event.is_set():
                self._definir_estado(
                    (
                        self.ESTADO_CONECTANDO
                        if not ja_conectou_antes
                        else self.ESTADO_DESCONECTADA
                    ),
                    (
                        "Conectando câmera..."
                        if not ja_conectou_antes
                        else (
                            "Câmera desconectada. "
                            "Reconectando automaticamente..."
                        )
                    ),
                )

                capture, primeiro_frame = self._abrir_camera()

                if capture is None or primeiro_frame is None:
                    if self._stop_event.is_set():
                        break

                    self._definir_estado(
                        self.ESTADO_DESCONECTADA,
                        (
                            "Câmera indisponível. "
                            "Reconectando automaticamente..."
                        ),
                    )

                    if self._aguardar_reconexao():
                        break

                    continue

                frame_processado = self._aplicar_rotacao(
                    primeiro_frame
                )
                self._publicar_frame(frame_processado)
                ja_conectou_antes = True
                falhas_consecutivas = 0

                while not self._stop_event.is_set():
                    self._aplicar_configuracoes_hardware(
                        capture
                    )

                    try:
                        sucesso, frame = capture.read()
                    except Exception:
                        sucesso, frame = False, None

                    frame = (
                        self._normalizar_frame(frame)
                        if sucesso
                        else None
                    )

                    if not self._frame_basico_valido(frame):
                        falhas_consecutivas += 1

                        if (
                            falhas_consecutivas
                            >= self.falhas_antes_reconexao
                        ):
                            break

                        self._stop_event.wait(0.02)
                        continue

                    falhas_consecutivas = 0
                    frame_processado = self._aplicar_rotacao(
                        frame
                    )
                    self._publicar_frame(frame_processado)

                try:
                    capture.release()
                except Exception:
                    pass

                if self._stop_event.is_set():
                    break

                self._definir_estado(
                    self.ESTADO_DESCONECTADA,
                    (
                        "Câmera sem resposta. "
                        "Reconectando automaticamente..."
                    ),
                )

                if self._aguardar_reconexao():
                    break
        finally:
            with self._lock:
                self._thread = None

            self._definir_estado(
                self.ESTADO_PARADA,
                "Câmera parada.",
            )
