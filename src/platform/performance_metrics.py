from __future__ import annotations

import time

from src.platform.production_log import ProductionLogMixin
from src.platform.desktop_settings import (
    OPERATION_PREVIEW_INTERVAL_MS,
)


class PerformanceMetricsMixin(ProductionLogMixin):
    """Mede somente o tempo percebido entre o gatilho e o resultado visível."""

    def __init__(self, *args, **kwargs) -> None:
        self._tempo_resposta_inicio_s: float | None = None
        super().__init__(*args, **kwargs)

        fps_preview = 1000.0 / max(
            1,
            int(OPERATION_PREVIEW_INTERVAL_MS),
        )
        self.view.atualizar_metricas_desempenho(
            fps_preview=fps_preview,
        )

    def _iniciar_medicao_tempo_resposta(self) -> bool:
        if self._tempo_resposta_inicio_s is not None:
            return False

        self._tempo_resposta_inicio_s = time.perf_counter()
        return True

    def _cancelar_medicao_tempo_resposta(self) -> None:
        self._tempo_resposta_inicio_s = None

    def _finalizar_medicao_tempo_resposta(self) -> float | None:
        inicio_s = self._tempo_resposta_inicio_s
        if inicio_s is None:
            return None

        # Processa primeiro as alterações visuais pendentes. A medição termina
        # somente depois que o estado de resultado foi enviado ao Tkinter.
        self.root.update_idletasks()
        tempo_resposta_ms = (
            time.perf_counter() - inicio_s
        ) * 1000.0
        self._tempo_resposta_inicio_s = None
        self.view.atualizar_metricas_desempenho(
            tempo_resposta_ms=tempo_resposta_ms,
        )
        return tempo_resposta_ms

    def capturar_frame_camera_para_analise(self, evento=None) -> None:
        iniciou_agora = self._iniciar_medicao_tempo_resposta()
        super().capturar_frame_camera_para_analise(evento)

        if (
            iniciou_agora
            and self._tempo_resposta_inicio_s is not None
            and not self.camera_em_pausa_analise
        ):
            self._cancelar_medicao_tempo_resposta()

    def analisar_led_selecionado(self) -> None:
        iniciou_agora = self._iniciar_medicao_tempo_resposta()
        resultados_antes = self.resultados_led_atual
        super().analisar_led_selecionado()

        resultado_novo_renderizado = (
            self.resultados_led_atual is not resultados_antes
            and bool(self.resultados_led_atual)
        )

        if resultado_novo_renderizado:
            self._finalizar_medicao_tempo_resposta()
        elif (
            iniciou_agora
            and self._tempo_resposta_inicio_s is not None
            and not self.camera_em_pausa_analise
        ):
            self._cancelar_medicao_tempo_resposta()

    def disparar_inspecao_operacao(self) -> None:
        self._iniciar_medicao_tempo_resposta()
        resultado_after_antes = self._operacao_resultado_after_id
        total_antes = self.operacao_total

        super().disparar_inspecao_operacao()

        resultado_renderizado = (
            self.operacao_total > total_antes
            and self._operacao_resultado_after_id != resultado_after_antes
        )

        if resultado_renderizado:
            self._finalizar_medicao_tempo_resposta()
        elif (
            self._tempo_resposta_inicio_s is not None
            and not self.operacao_processando
            and self._operacao_resultado_after_id is None
        ):
            self._cancelar_medicao_tempo_resposta()

    def _mostrar_erro_operacao(self, mensagem: str) -> None:
        self._cancelar_medicao_tempo_resposta()
        super()._mostrar_erro_operacao(mensagem)
