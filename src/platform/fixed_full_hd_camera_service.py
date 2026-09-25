from __future__ import annotations

import sys

from src.platform.linux_camera_backend import (
    LinuxCameraBackendCandidate,
    construir_candidatos_linux,
    descobrir_dispositivos_video,
    opencv_tem_gstreamer,
)
from src.platform.desktop_settings import (
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_SCAN_MAX_INDEX,
    CAMERA_WIDTH,
)
from src.platform.threaded_camera_service import (
    ThreadedDesktopCameraService,
)


class FixedFullHdCameraService(ThreadedDesktopCameraService):
    """1080p fixo no Linux e captura nativa/negociada no Windows.

    No Linux desktop a operação continua estritamente em 1920x1080 a 20 FPS.
    No Windows o driver escolhe resolução, FPS e formato como nas APIs nativas
    do sistema. Isso evita ciclos de reconexão em câmeras USB que funcionam no
    Windows, mas não aceitam imediatamente o perfil MJPG 1080p imposto pelo
    OpenCV.
    """

    RESOLUTION_MISMATCH_BEFORE_SWITCH = 3
    RESOLUTION_PROBE_FRAMES = 4
    WINDOWS_FAILURES_BEFORE_RECONNECT = 60
    WINDOWS_CORRUPTED_BEFORE_RECONNECT = 60

    def __init__(
        self,
        indice_camera: int,
        largura: int = CAMERA_WIDTH,
        altura: int = CAMERA_HEIGHT,
        fps: int = CAMERA_FPS,
        **kwargs,
    ) -> None:
        self._windows_native_mode = sys.platform.startswith("win")
        configuracoes_origem = kwargs.pop("configuracoes_camera", None)
        configuracoes = (
            self._windows_native_settings(configuracoes_origem)
            if self._windows_native_mode
            else self._fixed_settings(configuracoes_origem)
        )
        self._resolution_mismatch_count = 0
        super().__init__(
            indice_camera=indice_camera,
            largura=CAMERA_WIDTH,
            altura=CAMERA_HEIGHT,
            fps=CAMERA_FPS,
            configuracoes_camera=configuracoes,
            **kwargs,
        )

        if self._windows_native_mode:
            # Câmeras USB podem levar alguns ciclos para começar a entregar
            # quadros estáveis. Não tratamos pequenos engasgos como desconexão.
            self.falhas_antes_reconexao = max(
                int(self.falhas_antes_reconexao),
                self.WINDOWS_FAILURES_BEFORE_RECONNECT,
            )
            self.FRAMES_CORROMPIDOS_ANTES_RECONEXAO = max(
                int(self.FRAMES_CORROMPIDOS_ANTES_RECONEXAO),
                self.WINDOWS_CORRUPTED_BEFORE_RECONNECT,
            )

    @staticmethod
    def _fixed_settings(configuracoes_camera: dict | None) -> dict:
        configuracoes = dict(configuracoes_camera or {})
        configuracoes.update(
            {
                "resolution_mode": "full_hd",
                "width": CAMERA_WIDTH,
                "height": CAMERA_HEIGHT,
                "fps_mode": "manual",
                "fps": CAMERA_FPS,
                "format": "MJPG",
            }
        )
        return configuracoes

    @staticmethod
    def _windows_native_settings(configuracoes_camera: dict | None) -> dict:
        configuracoes = dict(configuracoes_camera or {})
        configuracoes.update(
            {
                "resolution_mode": "auto",
                "width": CAMERA_WIDTH,
                "height": CAMERA_HEIGHT,
                "fps_mode": "auto",
                "fps": 0,
                "format": "AUTO",
            }
        )
        return configuracoes

    @staticmethod
    def _windows_tem_controle_manual_explicito(configuracoes: dict) -> bool:
        if any(
            bool(configuracoes.get(chave, False))
            for chave in (
                "pan_enabled",
                "tilt_enabled",
                "contrast_enabled",
                "sharpness_enabled",
                "saturation_enabled",
                "gain_enabled",
                "brightness_enabled",
                "gamma_enabled",
            )
        ):
            return True

        if (
            not bool(configuracoes.get("exposure_auto", True))
            and bool(configuracoes.get("exposure_enabled", False))
        ):
            return True
        if (
            not bool(configuracoes.get("focus_auto", True))
            and bool(configuracoes.get("focus_enabled", False))
        ):
            return True
        if (
            not bool(configuracoes.get("white_balance_auto", True))
            and bool(configuracoes.get("white_balance_enabled", False))
        ):
            return True
        return False

    @staticmethod
    def _is_fixed_candidate(
        candidato: LinuxCameraBackendCandidate,
    ) -> bool:
        return (
            int(candidato.largura) == CAMERA_WIDTH
            and int(candidato.altura) == CAMERA_HEIGHT
        )

    def atualizar_configuracoes_camera(
        self,
        configuracoes_camera: dict | None,
    ) -> None:
        if self._windows_native_mode:
            super().atualizar_configuracoes_camera(
                self._windows_native_settings(configuracoes_camera)
            )
            # atualizar_configuracoes_camera marca controles pendentes, mas não
            # recalcula sozinho o perfil de transporte. Mantemos o transporte
            # em modo automático mesmo após salvar as configurações da câmera.
            self._aplicar_perfil_camera_inicial()
            return

        self.largura = CAMERA_WIDTH
        self.altura = CAMERA_HEIGHT
        self.fps = CAMERA_FPS
        super().atualizar_configuracoes_camera(
            self._fixed_settings(configuracoes_camera)
        )

    def _aplicar_configuracoes_hardware(self) -> None:
        if not self._windows_native_mode:
            super()._aplicar_configuracoes_hardware()
            return

        if not self._controles_pendentes:
            return

        configuracoes = self.obter_configuracoes_camera()
        if self._windows_tem_controle_manual_explicito(configuracoes):
            # Se o usuário pediu algum controle manual, respeitamos a
            # configuração e usamos o caminho completo já existente.
            super()._aplicar_configuracoes_hardware()
            return

        # Sem pedido manual, não fazemos capture.set() nos controles da câmera.
        # Isso replica melhor o Windows, evita drivers USB sensíveis a escritas
        # de propriedades logo após a abertura e mantém os automáticos do
        # próprio dispositivo funcionando livremente.
        for nome in tuple(self._status_controles_camera.keys()):
            self._registrar_status_controle(
                nome,
                "padrao_driver_windows",
                valor_solicitado=None,
                valor_lido=None,
            )
        self._controles_pendentes = False

    def _candidatos_linux(
        self,
    ) -> tuple[LinuxCameraBackendCandidate, ...]:
        dispositivos = descobrir_dispositivos_video(
            indice_solicitado=self._indice_camera_solicitado,
            indice_ativo=self._indice_camera_ativo,
            indice_maximo=CAMERA_SCAN_MAX_INDEX,
        )
        candidatos = construir_candidatos_linux(
            dispositivos=dispositivos,
            largura=CAMERA_WIDTH,
            altura=CAMERA_HEIGHT,
            fps=CAMERA_FPS,
            gstreamer_disponivel=opencv_tem_gstreamer(),
            resolucoes_preferidas=((CAMERA_WIDTH, CAMERA_HEIGHT),),
        )
        return tuple(
            candidato
            for candidato in candidatos
            if self._is_fixed_candidate(candidato)
        )

    def _abrir_candidato_linux(
        self,
        candidato: LinuxCameraBackendCandidate,
    ):
        if not self._is_fixed_candidate(candidato):
            return None

        capture = super()._abrir_candidato_linux(candidato)
        if capture is None:
            return None

        frames_na_resolucao = 0
        for _ in range(self.RESOLUTION_PROBE_FRAMES):
            try:
                sucesso, frame = capture.read()
            except Exception:
                sucesso, frame = False, None
            frame = self._normalizar_frame(frame) if sucesso else None
            if not self._frame_basico_valido(frame):
                continue
            altura_real, largura_real = frame.shape[:2]
            if (
                int(largura_real) == CAMERA_WIDTH
                and int(altura_real) == CAMERA_HEIGHT
            ):
                frames_na_resolucao += 1

        if frames_na_resolucao > 0:
            return capture

        try:
            capture.release()
        except Exception:
            pass
        return None

    def _reiniciar_estado_fluxo(self) -> None:
        super()._reiniciar_estado_fluxo()
        self._resolution_mismatch_count = 0

    def _travar_controles_automaticos_atuais(self) -> None:
        if self._windows_native_mode:
            # No modo de compatibilidade Windows mantemos exposição, foco e
            # balanço de branco sob responsabilidade do driver, como acontece
            # na experiência nativa do Windows. Controles manuais explicitamente
            # configurados ainda são aplicados no primeiro frame.
            return
        super()._travar_controles_automaticos_atuais()

    def _publicar_frame_otimizado(self, frame, estavel: bool) -> None:
        if self._windows_native_mode:
            # Aceita a resolução realmente negociada pelo driver. As ROIs já
            # possuem adaptação por resolução, então não há razão para derrubar
            # uma câmera funcional por não entregar exatamente 1920x1080.
            self._resolution_mismatch_count = 0
            super()._publicar_frame_otimizado(frame, estavel=estavel)
            return

        altura_real, largura_real = frame.shape[:2]
        if (
            int(largura_real) != CAMERA_WIDTH
            or int(altura_real) != CAMERA_HEIGHT
        ):
            self._resolution_mismatch_count += 1
            self._ultimo_motivo_descarte = (
                "A câmera entregou "
                f"{largura_real}x{altura_real}; esperado "
                f"{CAMERA_WIDTH}x{CAMERA_HEIGHT}."
            )
            if (
                self._resolution_mismatch_count
                >= self.RESOLUTION_MISMATCH_BEFORE_SWITCH
            ):
                self._resolution_mismatch_count = 0
                if sys.platform.startswith("linux"):
                    self._trocar_backend_linux(
                        "A pipeline alterou a resolução fixa."
                    )
                else:
                    self._agendar_reconexao(
                        "A câmera não manteve 1920x1080."
                    )
                    self._reiniciar_estado_fluxo()
            return

        self._resolution_mismatch_count = 0
        super()._publicar_frame_otimizado(frame, estavel=estavel)

    def obter_diagnostico_fluxo(self) -> dict:
        diagnostico = super().obter_diagnostico_fluxo()
        diagnostico.update(
            {
                "perfil_camera_fixo": not self._windows_native_mode,
                "windows_native_mode": bool(self._windows_native_mode),
                "resolucao_fixa": (
                    None
                    if self._windows_native_mode
                    else (CAMERA_WIDTH, CAMERA_HEIGHT)
                ),
                "fps_fixo": (
                    None if self._windows_native_mode else CAMERA_FPS
                ),
                "divergencias_resolucao": int(
                    self._resolution_mismatch_count
                ),
            }
        )
        return diagnostico
