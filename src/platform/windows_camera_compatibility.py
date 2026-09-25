from __future__ import annotations

import sys
import threading

from src.platform.desktop_settings import CAMERA_FPS, CAMERA_HEIGHT, CAMERA_WIDTH


class WindowsCameraCompatibilityMixin:
    """Compatibilidade de transporte exclusiva do Windows.

    Quando existe uma resolução explícita, o Windows continua obrigado a
    entregar exatamente essa resolução, mas FPS e FOURCC ficam sob negociação
    do próprio driver. Isso evita travamentos observados em webcams Logitech
    UVC/MSMF ao escrever MJPG/FPS imediatamente após a reabertura.
    """

    WINDOWS_RESOLUTION_PROBE_FRAMES = 12
    WINDOWS_PROBE_TIMEOUT_S = 3.0

    def __init__(self, *args, **kwargs) -> None:
        self._windows_exigir_resolucao_solicitada = False
        self._windows_fallback_automatico_ativo = False
        self._windows_ultima_resolucao_probe: tuple[int, int] | None = None
        self._windows_probe_timeout_total = 0
        self._windows_ultimo_probe_timeout = False
        super().__init__(*args, **kwargs)

    @staticmethod
    def _windows_native_settings(configuracoes_camera: dict | None) -> dict:
        configuracoes = dict(configuracoes_camera or {})
        modo = str(configuracoes.get("resolution_mode", "auto")).lower()

        if modo == "auto":
            configuracoes.update(
                {
                    "resolution_mode": "auto",
                    "width": int(configuracoes.get("width", CAMERA_WIDTH)),
                    "height": int(configuracoes.get("height", CAMERA_HEIGHT)),
                    "fps_mode": "auto",
                    "fps": 0,
                    "format": "AUTO",
                }
            )
            return configuracoes

        # A resolução continua sendo uma exigência real do ODIN, porém não
        # forçamos MJPG nem 20 FPS no Windows. Logitech/Media Foundation pode
        # abrir normalmente e travar justamente durante essas escritas. O app
        # Câmera do Windows também negocia formato/FPS com o driver.
        configuracoes.update(
            {
                "width": int(configuracoes.get("width", CAMERA_WIDTH)),
                "height": int(configuracoes.get("height", CAMERA_HEIGHT)),
                "fps_mode": "auto",
                "fps": 0,
                "format": "AUTO",
            }
        )
        return configuracoes

    def _executar_probe_windows_com_timeout(self, capture, callback) -> bool:
        """Impede que um ``capture.read()`` do Windows prenda a captura para sempre.

        O probe continua executando na própria thread de captura. Um watchdog
        auxiliar apenas chama ``release()`` se o driver não devolver o controle
        dentro do prazo. Isso preserva a afinidade de thread do Media Foundation
        e do DirectShow e permite que o serviço tente o próximo backend.
        """
        if not sys.platform.startswith("win"):
            return bool(callback())

        concluido = threading.Event()
        expirou = threading.Event()

        def liberar_se_travou() -> None:
            if concluido.is_set():
                return
            expirou.set()
            try:
                capture.release()
            except Exception:
                pass

        watchdog = threading.Timer(
            max(0.05, float(self.WINDOWS_PROBE_TIMEOUT_S)),
            liberar_se_travou,
        )
        watchdog.daemon = True
        watchdog.start()
        try:
            resultado = bool(callback())
        finally:
            concluido.set()
            try:
                watchdog.cancel()
            except Exception:
                pass

        if expirou.is_set():
            self._windows_probe_timeout_total += 1
            self._windows_ultimo_probe_timeout = True
            return False

        self._windows_ultimo_probe_timeout = False
        return resultado

    def _capture_entrega_frame_inicial(self, capture) -> bool:
        if not sys.platform.startswith("win"):
            return super()._capture_entrega_frame_inicial(capture)

        def probe() -> bool:
            if not self._windows_exigir_resolucao_solicitada:
                return bool(super(WindowsCameraCompatibilityMixin, self)._capture_entrega_frame_inicial(capture))

            esperado = (int(self.largura), int(self.altura))
            self._windows_ultima_resolucao_probe = None

            for _ in range(max(1, int(self.WINDOWS_RESOLUTION_PROBE_FRAMES))):
                try:
                    sucesso, frame = capture.read()
                except Exception:
                    sucesso, frame = False, None

                frame = self._normalizar_frame(frame) if sucesso else None
                if not self._frame_basico_valido(frame):
                    continue

                altura_real, largura_real = frame.shape[:2]
                atual = (int(largura_real), int(altura_real))
                self._windows_ultima_resolucao_probe = atual
                if atual == esperado:
                    return True

            return False

        return self._executar_probe_windows_com_timeout(capture, probe)

    def _abrir_camera(self) -> bool:
        if not sys.platform.startswith("win") or self.perfil_automatico:
            self._windows_exigir_resolucao_solicitada = False
            self._windows_fallback_automatico_ativo = False
            return super()._abrir_camera()

        perfil = {
            "perfil_automatico": bool(self.perfil_automatico),
            "fps": int(self.fps),
            "formato_camera": str(self.formato_camera),
            "resolucao_solicitada": self._resolucao_solicitada,
            "fps_solicitado": self._fps_solicitado,
            "formato_solicitado": self._formato_solicitado,
        }

        self._windows_exigir_resolucao_solicitada = True
        self._windows_fallback_automatico_ativo = False
        if super()._abrir_camera():
            self._windows_exigir_resolucao_solicitada = False
            return True

        # Com resolução mestre de projeto não existe fallback para outro modo.
        # Se uma resolução foi salva com as ROIs, somente ela é aceita.
        resolucao_travada = getattr(
            self,
            "_resolucao_mestra_travada",
            None,
        )
        if resolucao_travada is not None:
            self._windows_exigir_resolucao_solicitada = False
            self._windows_fallback_automatico_ativo = False
            try:
                self._definir_estado(
                    self.ESTADO_DESCONECTADA,
                    (
                        "A câmera não confirmou a resolução mestre "
                        f"{resolucao_travada[0]}x{resolucao_travada[1]}. "
                        "Aguardando reconexão no mesmo modo."
                    ),
                )
            except Exception:
                pass
            return False

        self._windows_exigir_resolucao_solicitada = False
        self.perfil_automatico = True
        self.fps = 0
        self.formato_camera = "AUTO"

        try:
            abriu = super()._abrir_camera()
        finally:
            self.perfil_automatico = perfil["perfil_automatico"]
            self.fps = perfil["fps"]
            self.formato_camera = perfil["formato_camera"]
            self._resolucao_solicitada = perfil["resolucao_solicitada"]
            self._fps_solicitado = perfil["fps_solicitado"]
            self._formato_solicitado = perfil["formato_solicitado"]

        self._windows_fallback_automatico_ativo = bool(abriu)
        if abriu:
            try:
                self._definir_estado(
                    self.ESTADO_ESTABILIZANDO,
                    (
                        "A resolução solicitada não foi confirmada pelos "
                        "backends do Windows. Usando negociação automática "
                        "compatível com a câmera."
                    ),
                )
            except Exception:
                pass
        return bool(abriu)

    def obter_diagnostico_fluxo(self) -> dict:
        diagnostico = super().obter_diagnostico_fluxo()
        diagnostico.update(
            {
                "windows_resolucao_solicitada_prioritaria": bool(
                    sys.platform.startswith("win")
                    and not self.perfil_automatico
                ),
                "windows_fallback_automatico": bool(
                    self._windows_fallback_automatico_ativo
                ),
                "windows_ultima_resolucao_probe": (
                    self._windows_ultima_resolucao_probe
                ),
                "windows_probe_timeout_total": int(
                    self._windows_probe_timeout_total
                ),
                "windows_ultimo_probe_timeout": bool(
                    self._windows_ultimo_probe_timeout
                ),
            }
        )
        return diagnostico
