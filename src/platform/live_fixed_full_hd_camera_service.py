from __future__ import annotations

import sys

from src.platform.camera_live_control_service import (
    CameraLiveControlServiceMixin,
)
from src.platform.fixed_full_hd_camera_service import (
    FixedFullHdCameraService,
)
from src.platform.linux_camera_compatibility import (
    LinuxCameraCompatibilityMixin,
)
from src.platform.threaded_camera_service import (
    ThreadedDesktopCameraService,
)
from src.platform.windows_camera_compatibility import (
    WindowsCameraCompatibilityMixin,
)


LINUX_CAMERA_START_RESOLUTION = (640, 480)


class LiveFixedFullHdCameraService(
    CameraLiveControlServiceMixin,
    WindowsCameraCompatibilityMixin,
    LinuxCameraCompatibilityMixin,
    FixedFullHdCameraService,
):
    """Perfil final com controles ao vivo e resolução mestre opcional."""

    def __init__(self, *args, **kwargs) -> None:
        self._resolucao_mestra_travada: tuple[int, int] | None = None
        super().__init__(*args, **kwargs)

        # No JIG Linux o primeiro pipeline já precisa nascer no mesmo sistema
        # de coordenadas usado pelas ROIs do F2. A trava é definida antes de
        # ``iniciar()`` abrir qualquer backend, portanto a lista de candidatos
        # Linux já é construída exclusivamente para 640x480 e não existe mais
        # a transição inicial 1280/1920 -> 640 que distorcia a geometria.
        if sys.platform.startswith("linux"):
            self.definir_resolucao_travada(*LINUX_CAMERA_START_RESOLUTION)

    def definir_resolucao_travada(
        self,
        largura: int | None = None,
        altura: int | None = None,
    ) -> tuple[int, int] | None:
        """Define a resolução única que pode ser publicada pelo serviço.

        O método altera somente o alvo interno. Ele não chama ``capture.set`` e
        não reinicia a câmera; o aplicativo decide se um restart é necessário.
        """
        if largura is None or altura is None:
            with self._lock:
                self._resolucao_mestra_travada = None
            return None

        resolucao = (max(1, int(largura)), max(1, int(altura)))
        with self._lock:
            self._resolucao_mestra_travada = resolucao
            self.largura, self.altura = resolucao
            self.modo_resolucao = "custom"
            self.perfil_automatico = False
            self._resolucao_solicitada = resolucao

            configuracoes = dict(self._configuracoes_camera or {})
            configuracoes.update(
                {
                    "resolution_mode": "custom",
                    "width": resolucao[0],
                    "height": resolucao[1],
                }
            )
            self._configuracoes_camera = configuracoes
        return resolucao

    def obter_resolucao_travada(self) -> tuple[int, int] | None:
        with self._lock:
            return self._resolucao_mestra_travada

    def atualizar_configuracoes_camera(
        self,
        configuracoes_camera: dict | None,
    ) -> None:
        """Salva controles sem deixar o perfil legado trocar a resolução.

        No Linux deste perfil a resolução já nasce travada em 640x480. Enquanto
        existe uma resolução mestre, pulamos apenas a normalização de transporte
        do perfil legado e mantemos todo o restante da configuração da câmera.
        Nenhum ``capture.set`` de largura/altura e nenhum restart ocorre aqui.
        """
        travada = self.obter_resolucao_travada()
        if travada is None:
            return super().atualizar_configuracoes_camera(configuracoes_camera)

        configuracoes = dict(configuracoes_camera or {})
        configuracoes.update(
            {
                "resolution_mode": "custom",
                "width": int(travada[0]),
                "height": int(travada[1]),
            }
        )
        ThreadedDesktopCameraService.atualizar_configuracoes_camera(
            self,
            configuracoes,
        )
        self.definir_resolucao_travada(*travada)

    def _preparar_configuracoes_camera_ao_vivo(
        self,
        configuracoes_camera: dict | None,
    ) -> dict:
        travada = self.obter_resolucao_travada()
        if travada is not None:
            configuracoes = dict(configuracoes_camera or {})
            configuracoes.update(
                {
                    "resolution_mode": "custom",
                    "width": travada[0],
                    "height": travada[1],
                }
            )
            if sys.platform.startswith("win"):
                return self._windows_native_settings(configuracoes)
            configuracoes.setdefault("fps_mode", "manual")
            configuracoes.setdefault("fps", int(getattr(self, "fps", 0) or 20))
            configuracoes.setdefault("format", "MJPG")
            return configuracoes

        if getattr(self, "_windows_native_mode", False):
            return self._windows_native_settings(configuracoes_camera)
        return self._fixed_settings(configuracoes_camera)

    def _publicar_frame_otimizado(self, frame, estavel: bool) -> None:
        travada = self.obter_resolucao_travada()
        if travada is not None:
            altura_real, largura_real = frame.shape[:2]
            atual = (int(largura_real), int(altura_real))
            if atual != travada:
                self._resolution_mismatch_count += 1
                self._ultimo_motivo_descarte = (
                    "Frame descartado: a câmera entregou "
                    f"{atual[0]}x{atual[1]}, mas o projeto exige "
                    f"{travada[0]}x{travada[1]}."
                )
                try:
                    self._definir_estado(
                        self.ESTADO_ESTABILIZANDO,
                        self._ultimo_motivo_descarte,
                    )
                except Exception:
                    pass
                if (
                    self._resolution_mismatch_count
                    >= self.RESOLUTION_MISMATCH_BEFORE_SWITCH
                ):
                    self._resolution_mismatch_count = 0
                    if sys.platform.startswith("linux"):
                        self._trocar_backend_linux(
                            "A resolução mestre do projeto não foi mantida."
                        )
                    else:
                        self._agendar_reconexao(
                            "A resolução mestre do projeto não foi mantida."
                        )
                        self._reiniciar_estado_fluxo()
                return

            self._resolution_mismatch_count = 0
            self._ultimo_motivo_descarte = ""

        super()._publicar_frame_otimizado(frame, estavel=estavel)

    def obter_diagnostico_fluxo(self) -> dict:
        diagnostico = super().obter_diagnostico_fluxo()
        diagnostico["resolucao_mestra_travada"] = self.obter_resolucao_travada()
        return diagnostico
