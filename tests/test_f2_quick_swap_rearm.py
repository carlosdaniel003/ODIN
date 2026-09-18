from __future__ import annotations

from types import SimpleNamespace
import unittest

import numpy as np

from src.platform.f2_automatic_cycle_guard import (
    F2AutomaticCycleGuardMixin,
    F2AutomaticCycleState,
    F2VisualBoardRemovalDetector,
)
from src.platform.f2_automatic_presence_cycle_policy import (
    F2_AUTO_NEW_BOARD_AMBIGUOUS_GAP_FRAMES,
    F2AutomaticPresenceCyclePolicyMixin,
)
from src.platform.f2_board_presence_references import (
    F2_BOARD_PRESENCE_EMPTY,
    F2_BOARD_PRESENCE_PRESENT,
    F2_BOARD_PRESENCE_UNKNOWN,
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
        self._operacao_resultado_after_id = None

        self._presence = F2_BOARD_PRESENCE_PRESENT
        self._scores = {"present": 0.05, "empty": 0.30}

        self._f2_auto_cycle = F2AutomaticCycleState(trigger_on_frames_required=2)
        self._f2_auto_visual_removal = F2VisualBoardRemovalDetector()
        self._f2_auto_reference_empty_frames = 0
        self._f2_auto_last_raw_states = {}
        self._f2_auto_last_states = {}
        self._f2_auto_last_presence = None
        self._f2_auto_cycle_locked = False
        self._f2_auto_waiting_new_board_off = False
        self._f2_auto_new_board_off_frames = 0
        self._f2_auto_new_board_gap_frames = 0
        self._f2_auto_quick_empty_frames = 0
        self._f2_auto_quick_empty_seen = False
        self._f2_auto_last_inspection_result = None
        self._f2_board_presence_refs = None

    def _f2_auto_enabled(self) -> bool:
        return True

    def _f2_auto_fresh_analysis_due(self) -> bool:
        return True

    def _f2_auto_presence(self, _frame):
        return self._presence, dict(self._scores)

    def _f2_auto_publish_states(self, states, _presence) -> None:
        self._f2_auto_last_states = dict(states)

    def _f2_auto_can_trigger(self) -> bool:
        return True


class F2QuickSwapRearmTests(unittest.TestCase):
    def _inspect_first_board(self, app: _Harness) -> None:
        app._presence = F2_BOARD_PRESENCE_PRESENT
        app._scores = {"present": 0.04, "empty": 0.30}
        self.assertFalse(app._f2_auto_analyze_current_frame())
        self.assertTrue(app._f2_auto_analyze_current_frame())
        self.assertEqual(1, app.operacao_total)
        self.assertTrue(app._f2_auto_cycle_locked)
        self.assertTrue(app._f2_auto_cycle.waiting_removal)

    def test_single_strong_empty_then_present_recovers_fast_swap(self):
        app = _Harness()
        self._inspect_first_board(app)

        # O suporte vazio apareceu por apenas um ciclo de análise, mas com uma
        # separação visual forte da referência de placa.
        app._presence = F2_BOARD_PRESENCE_EMPTY
        app._scores = {"present": 0.28, "empty": 0.05}
        self.assertFalse(app._f2_auto_analyze_current_frame())
        self.assertTrue(app._f2_auto_quick_empty_seen)
        self.assertTrue(app._f2_auto_cycle.waiting_removal)

        # A nova placa entra antes de completar o debounce conservador de EMPTY.
        # A transição VAZIO -> PRESENTE deve ser suficiente para não perder o ciclo.
        app._presence = F2_BOARD_PRESENCE_PRESENT
        app._scores = {"present": 0.05, "empty": 0.27}
        self.assertFalse(app._f2_auto_analyze_current_frame())
        self.assertFalse(app._f2_auto_cycle.waiting_removal)
        self.assertTrue(app._f2_auto_waiting_new_board_off)
        self.assertEqual(1, app._f2_auto_new_board_off_frames)

        # Um frame ambíguo de ORB/presença não deve apagar a primeira confirmação.
        app._presence = F2_BOARD_PRESENCE_UNKNOWN
        app._scores = {"present": 0.13, "empty": 0.14}
        self.assertFalse(app._f2_auto_analyze_current_frame())
        self.assertEqual(1, app._f2_auto_new_board_off_frames)

        # Segundo PRESENTE rearma; os dois frames ACESO seguintes disparam.
        app._presence = F2_BOARD_PRESENCE_PRESENT
        app._scores = {"present": 0.05, "empty": 0.27}
        self.assertFalse(app._f2_auto_analyze_current_frame())
        self.assertFalse(app._f2_auto_cycle_locked)
        self.assertFalse(app._f2_auto_waiting_new_board_off)

        self.assertFalse(app._f2_auto_analyze_current_frame())
        self.assertTrue(app._f2_auto_analyze_current_frame())
        self.assertEqual(2, app.operacao_total)

    def test_ambiguous_gap_is_bounded_and_does_not_accumulate_forever(self):
        app = _Harness()
        app._f2_auto_waiting_new_board_off = True
        app._f2_auto_cycle_locked = True

        self.assertFalse(
            app._f2_auto_observe_new_board_present(F2_BOARD_PRESENCE_PRESENT)
        )
        self.assertEqual(1, app._f2_auto_new_board_off_frames)

        for _ in range(F2_AUTO_NEW_BOARD_AMBIGUOUS_GAP_FRAMES + 1):
            self.assertFalse(
                app._f2_auto_observe_new_board_present(F2_BOARD_PRESENCE_UNKNOWN)
            )

        self.assertEqual(0, app._f2_auto_new_board_off_frames)
        self.assertEqual(0, app._f2_auto_new_board_gap_frames)
        self.assertTrue(app._f2_auto_waiting_new_board_off)
        self.assertTrue(app._f2_auto_cycle_locked)

    def test_weak_single_empty_does_not_unlock_same_board(self):
        app = _Harness()
        self._inspect_first_board(app)

        app._presence = F2_BOARD_PRESENCE_EMPTY
        app._scores = {"present": 0.18, "empty": 0.15}
        self.assertFalse(app._f2_auto_analyze_current_frame())
        self.assertFalse(app._f2_auto_quick_empty_seen)

        app._presence = F2_BOARD_PRESENCE_PRESENT
        app._scores = {"present": 0.05, "empty": 0.25}
        self.assertFalse(app._f2_auto_analyze_current_frame())
        self.assertTrue(app._f2_auto_cycle.waiting_removal)
        self.assertTrue(app._f2_auto_cycle_locked)
        self.assertFalse(app._f2_auto_waiting_new_board_off)


if __name__ == "__main__":
    unittest.main()
