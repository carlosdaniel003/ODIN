from __future__ import annotations

from src.core.operation_engine import OperationPreparationError
from src.platform.operation_confirmation import (
    consolidar_capturas_operacao,
    dois_resultados_confirmam_ng,
)


class RaspberryCameraStabilityMixin:
    """Protege desenvolvimento e Produção F2 contra frames transitórios."""

    CONFIRMACAO_TIMEOUT_S = 0.35
    CONFIRMACAO_MAX_CAPTURAS = 3

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._instalar_confirmacao_temporal_operacao()

    def _obter_frame_estavel_atual(self):
        camera_service = getattr(self, "camera_service", None)
        obter = getattr(camera_service, "obter_ultimo_frame_estavel", None)
        if not callable(obter):
            return None
        try:
            return obter()
        except Exception:
            return None

    def preparar_tela_operacao(self) -> None:
        captura = self._obter_frame_estavel_atual()
        if captura is not None:
            _frame_id, frame = captura
            self.camera_frame_atual = frame
        super().preparar_tela_operacao()

    def capturar_frame_camera_para_analise(self, evento=None) -> None:
        if getattr(self, "camera_ativa", False):
            captura = self._obter_frame_estavel_atual()
            if captura is None:
                self.view.atualizar_status(
                    "Aguardando imagem estável da câmera. Mantenha a placa e "
                    "as mãos paradas por um instante."
                )
                return
            _frame_id, frame = captura
            self.camera_frame_atual = frame

        super().capturar_frame_camera_para_analise(evento)

    def _instalar_confirmacao_temporal_operacao(self) -> None:
        engine = getattr(self, "operacao_engine", None)
        analisar_original = getattr(engine, "analyze", None)
        if not callable(analisar_original):
            return
        if getattr(engine, "_odin_confirmacao_temporal_instalada", False):
            return

        def analisar_com_confirmacao(_frame_recebido):
            camera_service = getattr(self, "camera_service", None)
            obter_estavel = getattr(
                camera_service,
                "obter_ultimo_frame_estavel",
                None,
            )
            aguardar_estavel = getattr(
                camera_service,
                "aguardar_proximo_frame_estavel",
                None,
            )

            if not callable(obter_estavel) or not callable(aguardar_estavel):
                return analisar_original(_frame_recebido)

            captura_inicial = obter_estavel()
            if captura_inicial is None:
                raise OperationPreparationError(
                    "CAPTURA INSTÁVEL\n"
                    "Aguarde a câmera estabilizar antes da inspeção."
                )

            frame_id, frame = captura_inicial
            resultado = analisar_original(frame)
            capturas = [(frame_id, frame, resultado)]

            if not resultado.ok:
                while len(capturas) < self.CONFIRMACAO_MAX_CAPTURAS:
                    proxima = aguardar_estavel(
                        depois_frame_id=frame_id,
                        timeout_s=self.CONFIRMACAO_TIMEOUT_S,
                    )
                    if proxima is None:
                        raise OperationPreparationError(
                            "CAPTURA INSTÁVEL\n"
                            "Não foi possível confirmar o resultado. "
                            "A inspeção não foi contabilizada."
                        )

                    frame_id, frame = proxima
                    proximo_resultado = analisar_original(frame)
                    capturas.append(
                        (frame_id, frame, proximo_resultado)
                    )

                    if (
                        len(capturas) == 2
                        and dois_resultados_confirmam_ng(
                            capturas[0][2],
                            capturas[1][2],
                        )
                    ):
                        break

            (
                _frame_id_final,
                frame_final,
                resultado_final,
            ) = consolidar_capturas_operacao(capturas)

            # ProductionLogMixin memoriza cada análise interna. Substituímos pelos
            # dados consolidados para log e fotografia NG refletirem a decisão final.
            if hasattr(self, "ultimo_resultado_operacao"):
                self.ultimo_resultado_operacao = resultado_final
            if hasattr(self, "ultimo_frame_operacao"):
                self.ultimo_frame_operacao = frame_final

            return resultado_final

        engine.analyze = analisar_com_confirmacao
        engine._odin_confirmacao_temporal_instalada = True


# Nome canônico desktop; alias legado preservado.
DesktopCameraStabilityMixin = RaspberryCameraStabilityMixin
