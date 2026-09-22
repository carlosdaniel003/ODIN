from __future__ import annotations

import cv2

from src.platform.camera_live_control_service import CameraLiveControlServiceMixin
from src.platform.responsive_camera_selection_installer import (
    instalar_seletor_camera_responsivo,
)


class VerifiedCameraControlMixin:
    """Confirma se o driver aceita o controle antes de liberar o ajuste."""

    def _status_verificado(self, nome, status, solicitado=None, lido=None, bloqueado=False, motivo=None):
        self._registrar_status_controle(
            nome,
            status,
            valor_solicitado=solicitado,
            valor_lido=lido,
        )
        with self._lock:
            dados = self._status_controles_camera.setdefault(nome, {})
            dados["bloqueado"] = bool(bloqueado)
            dados["motivo"] = motivo

    def _aplicar_habilitacao_manual(self, capture, nome: str, habilitado: bool) -> None:
        if not habilitado:
            return CameraLiveControlServiceMixin._aplicar_habilitacao_manual(
                self,
                capture,
                nome,
                False,
            )

        propriedade = self._propriedade_manual(nome)
        if propriedade is None:
            self._status_verificado(
                nome,
                "nao_suportado",
                bloqueado=True,
                motivo="OpenCV/backend não expõe esta propriedade.",
            )
            return

        baseline = self._garantir_baseline(capture, nome)

        # Habilitar manual não escreve o baseline para "testar" suporte. Essa
        # escrita era a origem dos falsos negativos. O teste real acontece no
        # primeiro movimento do slider e é confirmado por leitura do hardware.
        if nome == "focus" and self._directshow_ativo():
            autofocus = getattr(cv2, "CAP_PROP_AUTOFOCUS", None)
            if autofocus is not None:
                try:
                    capture.set(autofocus, 0.0)
                except Exception:
                    pass

        self._status_verificado(
            nome,
            "manual_pronto",
            baseline,
            baseline,
            False,
            (
                "Leitura inicial indisponível; suporte será confirmado "
                "no primeiro ajuste."
                if baseline is None
                else "Controle disponível; aguardando ajuste manual."
            ),
        )

    def _aplicar_valor_manual(self, capture, nome: str, configuracoes: dict) -> None:
        if not bool(configuracoes.get(f"{nome}_enabled", False)):
            return
        propriedade = self._propriedade_manual(nome)
        if propriedade is None:
            self._status_verificado(nome, "nao_suportado", bloqueado=True)
            return
        solicitado = float(configuracoes.get(nome, 0.0))
        baseline = self._garantir_baseline(capture, nome)
        aceito, lido, valor_efetivo, ajustado_driver = (
            self._definir_controle_manual_confirmado(
                capture,
                nome,
                solicitado,
            )
        )

        if lido is not None:
            with self._lock:
                self._camera_live_valores_hardware[nome] = float(lido)

        if not aceito:
            self._status_verificado(
                nome,
                "ignorado_driver",
                solicitado,
                lido,
                False,
                (
                    "O driver não confirmou este valor. O controle permanece "
                    "habilitado para tentar outro valor."
                ),
            )
            return

        tolerancia = self._tolerancia_controle(nome)
        ignorado = (
            lido is not None
            and baseline is not None
            and abs(float(lido) - float(baseline)) <= tolerancia
            and abs(solicitado - float(baseline)) > tolerancia
        )
        status = (
            "ignorado_driver"
            if ignorado
            else ("ajustado_driver" if ajustado_driver else "aplicado")
        )
        motivo = None
        if ignorado:
            motivo = "O driver não confirmou mudança do valor."
        elif ajustado_driver and valor_efetivo is not None:
            motivo = (
                f"DirectShow aplicou o passo suportado "
                f"{float(valor_efetivo):g} para o valor solicitado "
                f"{solicitado:g}."
            )
        self._status_verificado(
            nome,
            status,
            solicitado,
            lido,
            False,
            motivo,
        )


def instalar_validacao_controles_camera() -> None:
    """Aplica validação de câmera e a seleção visual não bloqueante."""
    instalar_seletor_camera_responsivo()

    from src.platform.live_fixed_full_hd_camera_service import (
        LiveFixedFullHdCameraService,
    )

    LiveFixedFullHdCameraService._status_verificado = (
        VerifiedCameraControlMixin._status_verificado
    )
    LiveFixedFullHdCameraService._aplicar_habilitacao_manual = (
        VerifiedCameraControlMixin._aplicar_habilitacao_manual
    )
    LiveFixedFullHdCameraService._aplicar_valor_manual = (
        VerifiedCameraControlMixin._aplicar_valor_manual
    )
