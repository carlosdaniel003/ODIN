from __future__ import annotations

from src.platform.desktop_settings import (
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_WIDTH,
)


class NativeResolutionConfigMixin:
    """Mantém toda a aplicação fixa em 1920x1080 a 20 FPS."""

    @staticmethod
    def _aplicar_perfil_camera_fixo(
        configuracoes_camera: dict | None,
    ) -> dict:
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

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._fixar_configuracao_camera()

    def _persistir_perfil_camera_fixo(self, configuracoes: dict) -> None:
        self.configuracoes_camera = dict(configuracoes)
        try:
            self.configuracao_atual = (
                self.config_repository.salvar_configuracoes_sistema(
                    salvar_resultados_analise=(
                        self.salvar_resultados_analise
                    ),
                    raio_atual_px=self.raio_atual_px,
                    configuracoes_camera=configuracoes,
                )
            )
            self.configuracoes_camera = (
                self.config_repository.obter_configuracoes_camera()
            )
        except Exception:
            # O perfil em memória continua fixo mesmo quando a configuração local
            # estiver temporariamente sem permissão de escrita.
            self.configuracoes_camera = dict(configuracoes)

    def _fixar_configuracao_camera(self) -> None:
        configuracoes_atuais = dict(
            getattr(self, "configuracoes_camera", {}) or {}
        )
        configuracoes = self._aplicar_perfil_camera_fixo(
            configuracoes_atuais
        )
        if configuracoes == configuracoes_atuais:
            self.configuracoes_camera = configuracoes
            return
        self._persistir_perfil_camera_fixo(configuracoes)

    def salvar_configuracoes_sistema(
        self,
        salvar_resultados_analise: bool,
        raio_configurado_px: int | None = None,
        configuracoes_camera: dict | None = None,
    ):
        configuracoes = self._aplicar_perfil_camera_fixo(
            configuracoes_camera
            if configuracoes_camera is not None
            else getattr(self, "configuracoes_camera", {})
        )
        resultado = super().salvar_configuracoes_sistema(
            salvar_resultados_analise=salvar_resultados_analise,
            raio_configurado_px=raio_configurado_px,
            configuracoes_camera=configuracoes,
        )

        # Alguns mixins legados ainda normalizam FPS ao salvar. O perfil fixo é
        # reaplicado por último para que arquivo, memória e próxima abertura
        # permaneçam obrigatoriamente em 1920x1080 a 20 FPS.
        configuracoes_finais = self._aplicar_perfil_camera_fixo(
            getattr(self, "configuracoes_camera", configuracoes)
        )
        self._persistir_perfil_camera_fixo(configuracoes_finais)
        return resultado
