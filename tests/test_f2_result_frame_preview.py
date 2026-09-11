import unittest
from types import SimpleNamespace

import numpy as np

from src.platform.f2_automatic_analysis import F2AutomaticAnalysisMixin


class _FakeWindow:
    def __init__(self):
        self.preview_calls = []
        self._failed_led_ids = frozenset()
        self._last_result_ok = None

    def set_result_preview_frame(
        self,
        frame,
        *,
        is_ok: bool,
        failed_led_ids=(),
    ):
        self.preview_calls.append(
            {
                "frame": frame.copy(),
                "is_ok": bool(is_ok),
                "failed_led_ids": tuple(failed_led_ids or ()),
            }
        )
        return True


class _FakeEngine:
    def __init__(self, ok: bool):
        self.ready = True
        self.ok = bool(ok)
        self.received_frames = []

    def analyze(self, frame):
        self.received_frames.append(frame.copy())
        return SimpleNamespace(
            ok=self.ok,
            failed_led_ids=() if self.ok else ("LED_002",),
            elapsed_seconds=0.01,
            results=(),
        )


class _BaseF2Inspection:
    def disparar_inspecao_operacao(self):
        frame = self.camera_frame_atual.copy()
        result = self.operacao_engine.analyze(frame)
        self.operacao_total += 1
        if result.ok:
            self.operacao_ok += 1
        else:
            self.operacao_ng += 1
            self.operacao_window._failed_led_ids = frozenset(
                result.failed_led_ids
            )
        self.operacao_window._last_result_ok = bool(result.ok)
        return result


class _F2PreviewHarness(F2AutomaticAnalysisMixin, _BaseF2Inspection):
    def __init__(self, *, ok: bool):
        # O teste isola somente o wrapper de disparo; não há Tk/configuração.
        self.analise_automatica_f2 = False
        self.operacao_total = 0
        self.operacao_ok = 0
        self.operacao_ng = 0
        self.camera_frame_atual = np.arange(
            4 * 6 * 3,
            dtype=np.uint8,
        ).reshape((4, 6, 3))
        self.operacao_engine = _FakeEngine(ok=ok)
        self.operacao_window = _FakeWindow()


class F2ResultFramePreviewTests(unittest.TestCase):
    def test_preview_ok_recebe_exatamente_o_frame_entregue_ao_motor(self):
        app = _F2PreviewHarness(ok=True)

        app.disparar_inspecao_operacao()

        self.assertEqual(1, len(app.operacao_engine.received_frames))
        self.assertEqual(1, len(app.operacao_window.preview_calls))
        np.testing.assert_array_equal(
            app.operacao_engine.received_frames[0],
            app.operacao_window.preview_calls[0]["frame"],
        )
        self.assertTrue(app.operacao_window.preview_calls[0]["is_ok"])
        self.assertEqual(1, app.operacao_total)
        self.assertEqual(1, app.operacao_ok)
        self.assertEqual(0, app.operacao_ng)

    def test_preview_ng_preserva_resultado_e_ids_reprovados(self):
        app = _F2PreviewHarness(ok=False)

        app.disparar_inspecao_operacao()

        self.assertEqual(1, len(app.operacao_window.preview_calls))
        call = app.operacao_window.preview_calls[0]
        self.assertFalse(call["is_ok"])
        self.assertEqual(("LED_002",), call["failed_led_ids"])
        np.testing.assert_array_equal(
            app.operacao_engine.received_frames[0],
            call["frame"],
        )
        self.assertEqual(1, app.operacao_total)
        self.assertEqual(0, app.operacao_ok)
        self.assertEqual(1, app.operacao_ng)


if __name__ == "__main__":
    unittest.main()
