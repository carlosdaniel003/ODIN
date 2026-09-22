from __future__ import annotations

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
        baseline = self._garantir_baseline(capture, nome)
        if propriedade is None or baseline is None:
            self._status_verificado(
                nome,
                "nao_suportado",
                bloqueado=True,
                motivo="O driver não oferece leitura segura para este controle.",
            )
            return

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
                "Autofocus desligado; ajuste manual pronto para o DirectShow.",
            )
            return

        aceito, lido = self._definir_propriedade_capture(capture, propriedade, baseline)
        if not aceito:
            self._status_verificado(
                nome,
                "nao_suportado",
                baseline,
                lido,
                True,
                "O driver recusou este controle; o ajuste foi bloqueado.",
            )
            return

        self._status_verificado(
            nome,
            "manual_pronto",
            baseline,
            baseline if lido is None else lido,
            False,
            "Controle aceito pelo driver.",
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

        foco_directshow = None
        if nome == "focus":
            foco_directshow = self._definir_foco_manual_directshow(
                capture,
                solicitado,
            )

        if foco_directshow is not None:
            aceito, lido, valor_efetivo = foco_directshow
        else:
            aceito, lido = self._definir_propriedade_capture(
                capture,
                propriedade,
                solicitado,
            )
            valor_efetivo = solicitado

        if not aceito:
            self._status_verificado(
                nome,
                "nao_suportado",
                solicitado,
                lido,
                True,
                "O driver recusou o novo valor.",
            )
            return
        if lido is not None:
            with self._lock:
                self._camera_live_valores_hardware[nome] = float(lido)
        ignorado = (
            lido is not None
            and baseline is not None
            and abs(float(lido) - float(baseline)) <= 1.0
            and abs(solicitado - float(baseline)) > 1.0
        )
        ajustado_driver = bool(
            nome == "focus"
            and foco_directshow is not None
            and valor_efetivo is not None
            and abs(float(valor_efetivo) - float(solicitado)) > 0.5
        )
        status = (
            "ignorado_driver"
            if ignorado
            else ("ajustado_driver" if ajustado_driver else "aplicado")
        )
        motivo = None
        if ignorado:
            motivo = "O driver não confirmou mudança do valor."
        elif ajustado_driver:
            motivo = (
                f"DirectShow ajustou o foco solicitado {solicitado:g} "
                f"para o passo aceito {float(valor_efetivo):g}."
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
