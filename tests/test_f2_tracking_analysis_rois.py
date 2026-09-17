import unittest
from types import SimpleNamespace

import numpy as np

from src.models.led_selection import LedSelection
from src.platform.f2_tracking_analysis_rois import (
    obter_rois_rastreadas_analise_f2,
)


class _TrackingHarness:
    def __init__(self, *, locked=True):
        self.rastreamento_automatico_f2 = True
        self._f2_object_tracking_last_status = {
            "enabled": True,
            "locked": bool(locked),
        }
        # CURRENT -> REFERÊNCIA. Uma placa 20 px à direita precisa subtrair
        # 20 px para voltar ao sistema canônico; a inversa projeta a ROI em +20.
        self._f2_object_tracker = SimpleNamespace(
            last_matrix=np.asarray(
                [[1.0, 0.0, -20.0], [0.0, 1.0, 0.0]],
                dtype=np.float32,
            )
        )
        self._f2_tracking_analysis_override_depth = 0
        self.operacao_leds_preview = [
            LedSelection(
                id="LED_001",
                centro_x=100,
                centro_y=80,
                raio=10,
            )
        ]

    def _f2_tracking_enabled(self):
        return bool(self.rastreamento_automatico_f2)


class F2TrackedAnalysisRoiTests(unittest.TestCase):
    def test_roi_de_analise_acompanha_translacao_do_tracking(self):
        app = _TrackingHarness(locked=True)
        frame = np.zeros((240, 320, 3), dtype=np.uint8)

        rois = obter_rois_rastreadas_analise_f2(app, frame)

        self.assertEqual(1, len(rois))
        self.assertEqual("LED_001", rois[0].id)
        self.assertEqual(120, rois[0].centro_x)
        self.assertEqual(80, rois[0].centro_y)
        self.assertEqual(10, rois[0].raio)

    def test_sem_lock_nao_reutiliza_mascara_fixa(self):
        app = _TrackingHarness(locked=False)
        frame = np.zeros((240, 320, 3), dtype=np.uint8)

        rois = obter_rois_rastreadas_analise_f2(app, frame)

        self.assertEqual((), rois)

    def test_tracking_desligado_preserva_caminho_legado(self):
        app = _TrackingHarness(locked=True)
        app.rastreamento_automatico_f2 = False
        frame = np.zeros((240, 320, 3), dtype=np.uint8)

        rois = obter_rois_rastreadas_analise_f2(app, frame)

        self.assertEqual((), rois)


if __name__ == "__main__":
    unittest.main()
