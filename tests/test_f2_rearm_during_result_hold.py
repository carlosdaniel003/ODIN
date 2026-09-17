from __future__ import annotations

from types import SimpleNamespace
import unittest

import numpy as np

from src.platform.f2_automatic_cycle_guard import (
    F2_AUTO_REFERENCE_EMPTY_FRAMES_REQUIRED,
    F2AutomaticCycleGuardMixin,
    F2AutomaticCycleState,
    F2VisualBoardRemovalDetector,
)
from src.platform.f2_automatic_presence_cycle_policy import (
    F2_AUTO_NEW_BOARD_PRESENT_FRAMES_REQUIRED,
    F2AutomaticPresenceCyclePolicyMixin,
)
from src.platform.f2_board_presence_references import (
    F2_BOARD_PRESENCE_EMPTY,
    F2_BOARD_PRESENCE_PRESENT,
)


class _Engine:
    ready = True

    def __init__(self) -> None:
        self.status = "ACESO"

    def analyze(self, _frame):
        return SimpleNamespace(
            results=[SimpleNamespace(id="LED_001", status=self.status)]
        )


class _Base:
    def disparar_inspecao_operacao(self) -> None:
        self.operacao_total += 1
        self.operacao_ok += 1


class _Harness(
    F2AutomaticPresenceCyclePolicyMixin,
    F2AutomaticCycleGuardMixin,
    _Base,
):
    def __init__(self) -> None:
        self.operacao_engine = _Engine()
        self.camera_frame_atual = np.zeros((20, 20, 3), dtype=np.uint8)
        self.operacao_leds_preview = ()
        self.operacao_processando = False
        self.operacao_total = 0
        self.operacao_ok = 0
        self.operacao_ng = 0
        self._presence = F2_BOARD_PRESENCE_PRESENT
        self.result_hold_active = False
        self._operacao_resultado_after_id = None

        self._f2_auto_cycle = F2AutomaticCycleState(trigger_on_frames_required=2)
        self._f2_auto_visual_removal = F2VisualBoardRemovalDetector()
        self._f2_auto_reference_empty_frames = 0
        self._f2_auto_last_raw_states = {}
        self._f2_auto_last_states = {}
        self._f2_auto_last_presence = None
        self._f2_auto_cycle_locked = False
        self._f2_auto_waiting_new_board_off = False
        self._f2_auto_new_board_off_frames = 0
        self._f2_auto_last_inspection_result = None
        self._f2_board_presence_refs = None

    def _f2_auto_enabled(self) -> bool:
        return True

    def _f2_auto_fresh_analysis_due(self) -> bool:
        return True

    def _f2_auto_presence(self, _frame):
        return self._presence, {}

    def _f2_auto_result_hold_active(self) -> bool:
        return self.result_hold_active

    def _f2_auto_publish_states(self, states, _presence) -> None:
        self._f2_auto_last_states = dict(states)

    def _f2_auto_can_trigger(self) -> bool:
        # Produção bloqueia o novo disparo enquanto o cartão de resultado está
        # em hold. O teste preserva exatamente esse contrato.
        return not self.result_hold_active


class F2RearmDuringResultHoldTests(unittest.TestCase):
    def test_troca_completa_durante_hold_nao_perde_proxima_placa(self):
        app = _Harness()

        # Placa 1 ligada: análise automática normal.
        self.assertFalse(app._f2_auto_analyze_current_frame())
        self.assertTrue(app._f2_auto_analyze_current_frame())
        self.assertEqual(1, app.operacao_total)
        self.assertTrue(app._f2_auto_cycle.waiting_removal)
        self.assertTrue(app._f2_auto_cycle_locked)

        # A mensagem "PLACA JÁ ANALISADA / COLOQUE OUTRA PLACA" ainda está na
        # tela. Mesmo assim, a retirada física precisa continuar sendo observada.
        app.result_hold_active = True
        app._presence = F2_BOARD_PRESENCE_EMPTY
        app.operacao_engine.status = "APAGADO"
        for _ in range(F2_AUTO_REFERENCE_EMPTY_FRAMES_REQUIRED):
            self.assertFalse(app._f2_auto_analyze_current_frame())

        self.assertFalse(app._f2_auto_cycle.waiting_removal)
        self.assertTrue(app._f2_auto_waiting_new_board_off)
        self.assertTrue(app._f2_auto_cycle_locked)
        self.assertIsNone(app._f2_auto_last_inspection_result)
        self.assertEqual(1, app.operacao_total)

        # O operador coloca a placa 2 antes do hold terminar. A presença estável
        # já rearma o ciclo, mas ainda não pode disparar enquanto o resultado da
        # placa 1 estiver sendo apresentado.
        app._presence = F2_BOARD_PRESENCE_PRESENT
        app.operacao_engine.status = "ACESO"
        for _ in range(F2_AUTO_NEW_BOARD_PRESENT_FRAMES_REQUIRED):
            self.assertFalse(app._f2_auto_analyze_current_frame())

        self.assertFalse(app._f2_auto_waiting_new_board_off)
        self.assertFalse(app._f2_auto_cycle_locked)
        self.assertEqual(1, app.operacao_total)

        # Assim que o hold acaba, dois frames ACESO estáveis disparam a placa 2.
        app.result_hold_active = False
        self.assertFalse(app._f2_auto_analyze_current_frame())
        self.assertTrue(app._f2_auto_analyze_current_frame())
        self.assertEqual(2, app.operacao_total)
        self.assertTrue(app._f2_auto_cycle_locked)


if __name__ == "__main__":
    unittest.main()
