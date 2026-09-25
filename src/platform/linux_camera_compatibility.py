from __future__ import annotations

import sys

import cv2

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


LINUX_CAMERA_COMPATIBILITY_RESOLUTIONS = (
    (CAMERA_WIDTH, CAMERA_HEIGHT),
    (1280, 720),
    (640, 480),
    (640, 360),
)


class LinuxCameraCompatibilityMixin:
    """Compatibilidade Linux com suporte a resolução mestre estrita."""

    def __init__(self, *args, **kwargs) -> None:
        self._linux_compat_expected_resolution: tuple[int, int] | None = None
        self._linux_compat_candidate_key = ""
        super().__init__(*args, **kwargs)

    @staticmethod
    def _prioridade_candidato_linux(
        candidato: LinuxCameraBackendCandidate,
    ) -> tuple[int, int, int]:
        resolucoes = {
            resolucao: indice
            for indice, resolucao in enumerate(
                LINUX_CAMERA_COMPATIBILITY_RESOLUTIONS
            )
        }
        resolucao = (int(candidato.largura), int(candidato.altura))
        prioridade_resolucao = resolucoes.get(resolucao, 100)
        if candidato.tipo == "auto":
            prioridade_resolucao = 200

        prioridade_backend = {
            "gstreamer": 0,
            "v4l2": 1,
            "auto": 2,
        }.get(str(candidato.tipo), 3)
        prioridade_formato = {
            "MJPG": 0,
            "YUY2": 1,
            "AUTO": 2,
        }.get(str(candidato.formato).upper(), 3)
        return (
            prioridade_resolucao,
            prioridade_backend,
            prioridade_formato,
        )

    def _candidatos_linux(
        self,
    ) -> tuple[LinuxCameraBackendCandidate, ...]:
        if not sys.platform.startswith("linux"):
            return super()._candidatos_linux()

        dispositivos = descobrir_dispositivos_video(
            indice_solicitado=self._indice_camera_solicitado,
            indice_ativo=self._indice_camera_ativo,
            indice_maximo=CAMERA_SCAN_MAX_INDEX,
        )
        travada = getattr(self, "_resolucao_mestra_travada", None)

        if travada is not None:
            largura_alvo, altura_alvo = int(travada[0]), int(travada[1])
            candidatos = construir_candidatos_linux(
                dispositivos=dispositivos,
                largura=largura_alvo,
                altura=altura_alvo,
                fps=max(1, int(getattr(self, "fps", 0) or CAMERA_FPS)),
                gstreamer_disponivel=opencv_tem_gstreamer(),
                resolucoes_preferidas=((largura_alvo, altura_alvo),),
            )
            # Sem AUTO nem resoluções menores: um projeto mestre 640x480 só
            # pode abrir pipelines que confirmem exatamente 640x480.
            candidatos = tuple(
                candidato
                for candidato in candidatos
                if candidato.tipo != "auto"
                and int(candidato.largura) == largura_alvo
                and int(candidato.altura) == altura_alvo
            )
            return tuple(
                sorted(candidatos, key=self._prioridade_candidato_linux)
            )

        candidatos = construir_candidatos_linux(
            dispositivos=dispositivos,
            largura=CAMERA_WIDTH,
            altura=CAMERA_HEIGHT,
            fps=CAMERA_FPS,
            gstreamer_disponivel=opencv_tem_gstreamer(),
            resolucoes_preferidas=LINUX_CAMERA_COMPATIBILITY_RESOLUTIONS,
        )
        return tuple(
            sorted(
                candidatos,
                key=self._prioridade_candidato_linux,
            )
        )

    def _configurar_capture_direto(
        self,
        capture,
        candidato: LinuxCameraBackendCandidate,
    ) -> None:
        if not sys.platform.startswith("linux"):
            super()._configurar_capture_direto(capture, candidato)
            return

        if candidato.tipo == "auto":
            try:
                capture.set(cv2.CAP_PROP_BUFFERSIZE, 2)
            except Exception:
                pass
            return

        if candidato.formato in ("MJPG", "YUY2"):
            fourcc = "MJPG" if candidato.formato == "MJPG" else "YUYV"
            try:
                capture.set(
                    cv2.CAP_PROP_FOURCC,
                    cv2.VideoWriter_fourcc(*fourcc),
                )
            except Exception:
                pass

        largura = max(1, int(candidato.largura or CAMERA_WIDTH))
        altura = max(1, int(candidato.altura or CAMERA_HEIGHT))
        fps = max(1, int(getattr(self, "fps", 0) or CAMERA_FPS))
        for propriedade, valor in (
            (cv2.CAP_PROP_FRAME_WIDTH, largura),
            (cv2.CAP_PROP_FRAME_HEIGHT, altura),
            (cv2.CAP_PROP_FPS, fps),
        ):
            try:
                capture.set(propriedade, valor)
            except Exception:
                pass

        try:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 2)
        except Exception:
            pass

    def _abrir_candidato_linux(
        self,
        candidato: LinuxCameraBackendCandidate,
    ):
        if not sys.platform.startswith("linux"):
            return super()._abrir_candidato_linux(candidato)

        capture = ThreadedDesktopCameraService._abrir_candidato_linux(
            self,
            candidato,
        )
        if capture is None:
            return None

        if candidato.tipo == "auto":
            self._linux_compat_expected_resolution = None
            self._linux_compat_candidate_key = str(candidato.key)
            return capture

        esperado = (
            max(1, int(candidato.largura)),
            max(1, int(candidato.altura)),
        )
        encontrou_resolucao = False
        for _ in range(self.RESOLUTION_PROBE_FRAMES):
            try:
                sucesso, frame = capture.read()
            except Exception:
                sucesso, frame = False, None
            frame = self._normalizar_frame(frame) if sucesso else None
            if not self._frame_basico_valido(frame):
                continue
            altura_real, largura_real = frame.shape[:2]
            if (int(largura_real), int(altura_real)) == esperado:
                encontrou_resolucao = True
                break

        if encontrou_resolucao:
            self._linux_compat_expected_resolution = esperado
            self._linux_compat_candidate_key = str(candidato.key)
            return capture

        try:
            capture.release()
        except Exception:
            pass
        return None

    def _publicar_frame_otimizado(self, frame, estavel: bool) -> None:
        if not sys.platform.startswith("linux"):
            super()._publicar_frame_otimizado(frame, estavel=estavel)
            return

        altura_real, largura_real = frame.shape[:2]
        atual = (int(largura_real), int(altura_real))
        esperado = self._linux_compat_expected_resolution

        if esperado is None:
            esperado = atual
            self._linux_compat_expected_resolution = esperado

        if atual != esperado:
            self._resolution_mismatch_count += 1
            self._ultimo_motivo_descarte = (
                "A câmera entregou "
                f"{atual[0]}x{atual[1]}; esperado "
                f"{esperado[0]}x{esperado[1]}."
            )
            if (
                self._resolution_mismatch_count
                >= self.RESOLUTION_MISMATCH_BEFORE_SWITCH
            ):
                self._resolution_mismatch_count = 0
                self._trocar_backend_linux(
                    "A pipeline alterou a resolução negociada."
                )
            return

        self._resolution_mismatch_count = 0
        ThreadedDesktopCameraService._publicar_frame_otimizado(
            self,
            frame,
            estavel=estavel,
        )

    def obter_diagnostico_fluxo(self) -> dict:
        diagnostico = super().obter_diagnostico_fluxo()
        esperado = self._linux_compat_expected_resolution
        travada = getattr(self, "_resolucao_mestra_travada", None)
        fallback = bool(
            sys.platform.startswith("linux")
            and travada is None
            and esperado is not None
            and esperado != (CAMERA_WIDTH, CAMERA_HEIGHT)
        )
        diagnostico.update(
            {
                "resolucao_alvo_linux": esperado,
                "fallback_compatibilidade_linux": fallback,
                "candidato_compatibilidade_linux": str(
                    self._linux_compat_candidate_key or ""
                ),
            }
        )
        return diagnostico
