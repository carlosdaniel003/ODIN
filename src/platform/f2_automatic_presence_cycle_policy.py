from __future__ import annotations

from src.core.segment_low_light import STATUS_APAGADO
from src.platform.f2_automatic_analysis import estados_resultado_operacao
from src.platform.f2_board_presence_references import (
    F2_BOARD_PRESENCE_EMPTY,
    F2_BOARD_PRESENCE_PRESENT,
)


F2_AUTO_NEW_BOARD_PRESENT_FRAMES_REQUIRED = 2
# Compatibilidade com extensões/testes anteriores. O nome antigo dizia "OFF",
# mas o rearme atual depende apenas da nova placa PRESENTE após o vazio confirmado.
F2_AUTO_NEW_BOARD_OFF_FRAMES_REQUIRED = F2_AUTO_NEW_BOARD_PRESENT_FRAMES_REQUIRED

# O classificador de presença roda em uma cadência menor que a câmera. Uma troca
# física rápida pode produzir apenas 1-3 frames de SUPORTE VAZIO antes de a nova
# placa entrar. O ciclo normal continua conservador, mas guardamos evidência forte
# do vazio para reconhecer a transição VAZIO -> PRESENTE sem perder o rearme.
F2_AUTO_QUICK_SWAP_EMPTY_FRAMES_REQUIRED = 2
F2_AUTO_QUICK_SWAP_STRONG_EMPTY_MARGIN = 0.040
F2_AUTO_QUICK_SWAP_STRONG_EMPTY_RATIO = 0.72
# A confirmação da nova placa tolera poucos frames AMBÍGUOS entre dois PRESENTE.
# EMPTY continua zerando imediatamente a tentativa de entrada.
F2_AUTO_NEW_BOARD_AMBIGUOUS_GAP_FRAMES = 3


class F2AutomaticPresenceCyclePolicyMixin:
    """Liga o disparo por LED ao ciclo físico de troca da placa.

    A primeira análise automática continua sendo disparada pela evidência já
    validada no F2: pelo menos um LED ACESO. Depois de uma inspeção bem-sucedida,
    porém, a placa fica travada e não pode disparar novamente. O rearme exige a
    sequência física SUPORTE VAZIO -> NOVA PLACA PRESENTE. A nova placa pode já
    entrar ligada; não é necessário capturar um estado APAGADO antes do próximo
    disparo automático.

    Enter/GPIO continuam independentes: uma ação manual sempre pode solicitar
    uma análise, mesmo quando o ciclo automático está travado.
    """

    def _f2_auto_reset_runtime(self) -> None:
        result = super()._f2_auto_reset_runtime()
        self._f2_auto_cycle_locked = False
        self._f2_auto_waiting_new_board_off = False
        self._f2_auto_new_board_off_frames = 0
        self._f2_auto_new_board_gap_frames = 0
        self._f2_auto_quick_empty_frames = 0
        self._f2_auto_quick_empty_seen = False
        self._f2_auto_last_inspection_result = None
        return result

    @staticmethod
    def _f2_auto_all_leds_off(states: dict[str, str] | None) -> bool:
        """Compatibilidade: o estado OFF deixou de ser requisito de rearme."""
        current = dict(states or {})
        return bool(current) and all(
            str(status).strip().upper() == STATUS_APAGADO
            for status in current.values()
        )

    @staticmethod
    def _f2_auto_empty_evidence_is_strong(scores: dict | None) -> bool:
        """Distingue um vazio claro de um EMPTY apenas marginal/instável."""
        current = dict(scores or {})
        try:
            empty_distance = float(current.get("empty"))
            present_distance = float(current.get("present"))
        except (TypeError, ValueError):
            return False
        if empty_distance < 0.0 or present_distance <= 0.0:
            return False
        return bool(
            empty_distance + F2_AUTO_QUICK_SWAP_STRONG_EMPTY_MARGIN
            <= present_distance
            or empty_distance
            <= present_distance * F2_AUTO_QUICK_SWAP_STRONG_EMPTY_RATIO
        )

    def _f2_auto_reset_quick_empty_evidence(self) -> None:
        self._f2_auto_quick_empty_frames = 0
        self._f2_auto_quick_empty_seen = False

    def _f2_auto_observe_quick_swap_transition(
        self,
        presence: str,
        scores: dict | None,
    ) -> bool:
        """Recupera VAZIO -> PRESENTE rápido sem exigir 4 frames vazios.

        O caminho conservador de _f2_auto_observe_removal() continua existindo.
        Esta rota só confirma a retirada ao observar depois uma nova cena PRESENTE,
        e exige antes 2 amostras EMPTY ou 1 EMPTY com separação visual forte.
        """
        if not bool(getattr(self._f2_auto_cycle, "waiting_removal", False)):
            self._f2_auto_reset_quick_empty_evidence()
            return False

        if presence == F2_BOARD_PRESENCE_EMPTY:
            self._f2_auto_quick_empty_frames = int(
                getattr(self, "_f2_auto_quick_empty_frames", 0) or 0
            ) + 1
            if (
                self._f2_auto_quick_empty_frames
                >= F2_AUTO_QUICK_SWAP_EMPTY_FRAMES_REQUIRED
                or self._f2_auto_empty_evidence_is_strong(scores)
            ):
                self._f2_auto_quick_empty_seen = True
            return False

        if presence != F2_BOARD_PRESENCE_PRESENT:
            # UNKNOWN/UNAVAILABLE não apagam uma evidência de vazio já vista no
            # intervalo curto da troca física. O caminho normal ainda decide a
            # retirada se o suporte permanecer vazio.
            return False

        if not bool(getattr(self, "_f2_auto_quick_empty_seen", False)):
            self._f2_auto_quick_empty_frames = 0
            return False

        removed = bool(self._f2_auto_cycle.confirm_removal())
        self._f2_auto_reference_empty_frames = 0
        self._f2_auto_reset_quick_empty_evidence()
        return removed

    def _f2_auto_observe_new_board_present(self, presence: str) -> bool:
        """Rearma após vazio confirmado e nova placa PRESENTE por frames estáveis."""
        if not bool(getattr(self, "_f2_auto_waiting_new_board_off", False)):
            return False

        if presence == F2_BOARD_PRESENCE_EMPTY:
            self._f2_auto_new_board_off_frames = 0
            self._f2_auto_new_board_gap_frames = 0
            return False

        if presence != F2_BOARD_PRESENCE_PRESENT:
            # O tracking/presença pode produzir um frame AMBÍGUO durante a
            # aquisição da nova placa. Preserve a primeira confirmação por uma
            # janela curta em vez de exigir PRESENTE estritamente consecutivo.
            if int(getattr(self, "_f2_auto_new_board_off_frames", 0) or 0) > 0:
                self._f2_auto_new_board_gap_frames = int(
                    getattr(self, "_f2_auto_new_board_gap_frames", 0) or 0
                ) + 1
                if (
                    self._f2_auto_new_board_gap_frames
                    > F2_AUTO_NEW_BOARD_AMBIGUOUS_GAP_FRAMES
                ):
                    self._f2_auto_new_board_off_frames = 0
                    self._f2_auto_new_board_gap_frames = 0
            return False

        self._f2_auto_new_board_gap_frames = 0
        self._f2_auto_new_board_off_frames = int(
            getattr(self, "_f2_auto_new_board_off_frames", 0) or 0
        ) + 1
        if (
            self._f2_auto_new_board_off_frames
            < F2_AUTO_NEW_BOARD_PRESENT_FRAMES_REQUIRED
        ):
            return False

        # Este é o ÚNICO ponto de rearme do ciclo automático: a placa anterior
        # já saiu, o suporte vazio já foi confirmado e agora outra placa foi
        # vista PRESENTE de forma estável. Não exigir LEDs apagados evita perder
        # o ciclo quando o operador liga a nova placa antes do próximo frame.
        self._f2_auto_cycle_locked = False
        self._f2_auto_waiting_new_board_off = False
        self._f2_auto_new_board_off_frames = 0
        self._f2_auto_new_board_gap_frames = 0
        return True

    def _f2_auto_observe_new_board_off(
        self,
        states: dict[str, str],
        presence: str,
    ) -> bool:
        """Alias legado; o rearme não exige mais que a nova placa esteja OFF."""
        _ = states
        return self._f2_auto_observe_new_board_present(presence)

    def _f2_auto_mark_cycle_inspected(self) -> None:
        """Trava o automático imediatamente para a placa corrente."""
        # A trava independente é autoritativa. Ela não depende de contador,
        # timer de resultado nem da cadeia de super() do F2/GPIO.
        self._f2_auto_cycle_locked = True

        marker = getattr(self, "_f2_auto_mark_inspected", None)
        if callable(marker):
            marker()
        else:
            self._f2_auto_cycle.mark_inspected()
            self._f2_auto_reference_empty_frames = 0
        self._f2_auto_waiting_new_board_off = False
        self._f2_auto_new_board_off_frames = 0
        self._f2_auto_new_board_gap_frames = 0
        self._f2_auto_reset_quick_empty_evidence()

    def _f2_auto_rollback_failed_trigger(self) -> None:
        """Desfaz a trava somente quando a inspeção nem chegou a iniciar."""
        self._f2_auto_cycle_locked = False
        self._f2_auto_waiting_new_board_off = False
        self._f2_auto_new_board_off_frames = 0
        self._f2_auto_new_board_gap_frames = 0
        self._f2_auto_reset_quick_empty_evidence()
        self._f2_auto_reference_empty_frames = 0
        self._f2_auto_cycle.waiting_removal = False
        self._f2_auto_cycle.trigger_on_frames = 0

        detector = getattr(self, "_f2_auto_visual_removal", None)
        reset = getattr(detector, "reset", None)
        if callable(reset):
            reset()

    def disparar_inspecao_operacao(self) -> None:
        """Mantém Enter livre, mas registra placa e último resultado analisado."""
        total_before = int(getattr(self, "operacao_total", 0) or 0)
        ok_before = int(getattr(self, "operacao_ok", 0) or 0)
        ng_before = int(getattr(self, "operacao_ng", 0) or 0)

        result = super().disparar_inspecao_operacao()
        successful = int(getattr(self, "operacao_total", 0) or 0) > total_before
        if self._f2_auto_enabled() and successful:
            ok_after = int(getattr(self, "operacao_ok", 0) or 0)
            ng_after = int(getattr(self, "operacao_ng", 0) or 0)
            if ok_after > ok_before:
                self._f2_auto_last_inspection_result = "OK"
            elif ng_after > ng_before:
                self._f2_auto_last_inspection_result = "NG"
            else:
                self._f2_auto_last_inspection_result = None
            self._f2_auto_mark_cycle_inspected()
        return result

    def _f2_auto_analyze_current_frame(self) -> bool:
        if not self._f2_auto_enabled():
            return False

        engine = getattr(self, "operacao_engine", None)
        frame = getattr(self, "camera_frame_atual", None)
        if (
            engine is None
            or not engine.ready
            or frame is None
            or getattr(frame, "size", 0) == 0
            or getattr(self, "operacao_processando", False)
            or not self._f2_auto_fresh_analysis_due()
        ):
            return False

        try:
            result = engine.analyze(frame)
        except Exception:
            return False

        states = estados_resultado_operacao(result)
        self._f2_auto_last_raw_states = states
        presence, _scores = self._f2_auto_presence(frame)
        self._f2_auto_last_presence = presence

        # O hold do resultado é apenas apresentação. A troca física da placa não
        # pode ficar cega durante "PLACA JÁ ANALISADA / COLOQUE OUTRA PLACA".
        # Caso o operador retire e já coloque a próxima placa antes do hold acabar,
        # precisamos consumir a sequência VAZIO -> PRESENTE agora; o disparo em si
        # continua bloqueado por _f2_auto_can_trigger() enquanto o hold estiver ativo.
        was_waiting_removal = bool(self._f2_auto_cycle.waiting_removal)
        quick_removed = self._f2_auto_observe_quick_swap_transition(
            presence,
            _scores,
        )
        removed = (
            quick_removed
            or self._f2_auto_observe_removal(frame, presence)
        )
        if was_waiting_removal and removed:
            # O vazio confirmado é a fronteira física entre duas placas. Na rota
            # rápida ele pode ter sido visto 1-2 frames antes e a confirmação
            # ocorre justamente quando a NOVA placa já reapareceu.
            self._f2_auto_last_inspection_result = None
            self._f2_auto_waiting_new_board_off = True
            self._f2_auto_new_board_off_frames = 0
            self._f2_auto_new_board_gap_frames = 0
            self._f2_auto_reset_quick_empty_evidence()

        self._f2_auto_observe_new_board_present(presence)

        self._f2_auto_publish_states(states, presence)

        can_trigger = (
            self._f2_auto_can_trigger()
            and not bool(getattr(self, "_f2_auto_cycle_locked", False))
            and not bool(getattr(self, "_f2_auto_waiting_new_board_off", False))
        )
        if not self._f2_auto_cycle.should_trigger(
            states,
            can_trigger=can_trigger,
        ):
            return False

        # Consome o ciclo ANTES de chamar a inspeção oficial. Assim a mesma
        # placa não consegue gerar um segundo disparo mesmo se o resultado
        # desaparecer, algum wrapper não retornar valor ou o contador mudar em
        # outro ponto da cadeia de execução.
        self._f2_auto_mark_cycle_inspected()

        total_before = int(getattr(self, "operacao_total", 0) or 0)
        self.disparar_inspecao_operacao()
        fired = int(getattr(self, "operacao_total", 0) or 0) > total_before
        if not fired:
            self._f2_auto_rollback_failed_trigger()
        return fired
