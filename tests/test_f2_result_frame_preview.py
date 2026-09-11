import unittest
from types import SimpleNamespace

import numpy as np

from src.platform.f2_automatic_analysis import F2AutomaticAnalysisMixin
from src.platform.raspberry_pi3_profile import RaspberryPi3ODINApp
from src.platform.segment_display_operation_window import (
    calcular_tamanho_quadro_resultado_f2,
    renderizar_mascaras_resultado_f2,
)


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
        leds=None,
    ):
        self.preview_calls.append(
            {
                "frame": frame.copy(),
                "is_ok": bool(is_ok),
                "failed_led_ids": tuple(failed_led_ids or ()),
                "leds": None if leds is None else tuple(leds or ()),
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

    def test_fluxo_base_f2_publica_frame_e_geometria_das_mascaras(self):
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
        app.operacao_leds_preview = (
            SimpleNamespace(id="LED_001"),
            SimpleNamespace(id="LED_002"),
        )
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
        self.assertEqual(app.operacao_leds_preview, call["leds"])
        np.testing.assert_array_equal(
            app.operacao_engine.received_frames[0],
            call["frame"],
        )
        self.assertEqual(1, app.operacao_total)
        self.assertEqual(0, app.operacao_ok)
        self.assertEqual(1, app.operacao_ng)

    def test_quadro_resultado_preserva_proporcao_da_camera(self):
        width, height = calcular_tamanho_quadro_resultado_f2(
            panel_width=640,
            frame_width=640,
            frame_height=480,
        )

        self.assertGreaterEqual(width, 150)
        self.assertEqual(round(width * 480 / 640), height)
        self.assertAlmostEqual(4 / 3, width / height, places=2)

    def test_overlay_resultado_destaca_ng_sem_alterar_frame_original(self):
        frame = np.zeros((100, 120, 3), dtype=np.uint8)
        leds = (
            SimpleNamespace(
                id="LED_001",
                centro_x=30,
                centro_y=50,
                raio=10,
                tipo_roi=None,
            ),
            SimpleNamespace(
                id="LED_002",
                centro_x=90,
                centro_y=50,
                raio=10,
                tipo_roi=None,
            ),
        )

        rendered = renderizar_mascaras_resultado_f2(
            frame,
            leds,
            failed_led_ids=("LED_002",),
        )

        np.testing.assert_array_equal(frame, np.zeros_like(frame))
        self.assertGreater(int(rendered[50, 90, 0]), 0)
        self.assertGreater(
            int(rendered[50, 90, 0]),
            int(rendered[50, 90, 2]),
        )
        self.assertEqual(0, int(rendered[50, 30].sum()))
        self.assertGreater(int(rendered[50, 40].sum()), 0)


if __name__ == "__main__":
    unittest.main()
