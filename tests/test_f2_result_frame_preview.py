import unittest
from types import SimpleNamespace

import numpy as np

from src.platform.f2_automatic_analysis import F2AutomaticAnalysisMixin
from src.platform.raspberry_pi3_profile import RaspberryPi3ODINApp


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


class _CanonicalWindow(_FakeWindow):
    def __init__(self):
        super().__init__()
        self.result_calls = []

    def set_preview_paused(self, _paused: bool):
        return None

    def show_processing(self, **_kwargs):
        return None

    def show_result(self, **kwargs):
        self._last_result_ok = bool(kwargs["is_ok"])
        self._failed_led_ids = frozenset(kwargs.get("failed_led_ids", ()))
        self.result_calls.append(dict(kwargs))


class _FakeRoot:
    def update_idletasks(self):
        return None


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

    def test_fluxo_base_f2_publica_frame_antes_de_renderizar_resultado(self):
        app = RaspberryPi3ODINApp.__new__(RaspberryPi3ODINApp)
        app.operacao_ativa = True
        app.operacao_processando = False
        app._operacao_resultado_after_id = None
        app.camera_desconectada = False
        app.camera_frame_atual = np.arange(
            8 * 10 * 3,
            dtype=np.uint8,
        ).reshape((8, 10, 3))
        app.operacao_engine = _FakeEngine(ok=False)
        app.operacao_window = _CanonicalWindow()
        app.operacao_total = 0
        app.operacao_ok = 0
        app.operacao_ng = 0
        app.root = _FakeRoot()
        app._cancelar_preview_operacao = lambda: None
        app._agendar_preview_operacao = lambda *_args, **_kwargs: None
        app._agendar_retorno_aguardando = lambda: None

        RaspberryPi3ODINApp.disparar_inspecao_operacao(app)

        self.assertEqual(1, len(app.operacao_engine.received_frames))
        self.assertEqual(1, len(app.operacao_window.preview_calls))
        self.assertEqual(1, len(app.operacao_window.result_calls))
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
