import unittest
from types import SimpleNamespace

import numpy as np

from src.models.led_selection import LedSelection
from src.platform.f2_tracking_analysis_rois import (
    obter_contorno_rastreado_analise_f2,
    obter_rois_rastreadas_analise_f2,
    obter_mascaras_do_frame_analisado_f2,
)
from src.core.roi_geometry import pontos_segmento


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

    def test_contorno_do_resultado_usa_mesma_pose_das_mascaras(self):
        app = _TrackingHarness(locked=True)
        app.operacao_board_shape_preview = [
            LedSelection(
                id="BOARD_NEW", centro_x=80, centro_y=80, raio=2,
                tipo_roi="segmento",
                pontos_segmento_livre=[
                    (-10, -10), (10, -10), (10, 10), (-10, 10),
                ],
            )
        ]
        frame = np.zeros((240, 320, 3), dtype=np.uint8)

        projected = obter_contorno_rastreado_analise_f2(app, frame)

        self.assertEqual(1, len(projected))
        self.assertEqual(90, int(round(pontos_segmento(projected[0])[0][0])))
        self.assertEqual(70, int(round(pontos_segmento(projected[0])[0][1])))
        app._f2_object_tracking_last_status["locked"] = False
        self.assertEqual((), obter_contorno_rastreado_analise_f2(app, frame))

    def test_frame_analisado_utiliza_rois_do_motor_em_vez_das_fixas(self):
        app = _TrackingHarness()
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        frame[15, 20] = (48, 12, 200)
        tracked = tuple(obter_rois_rastreadas_analise_f2(app, frame))
        app.camera_ultimo_frame_id = 37
        app._f2_tracking_analysis_frame_id = 37
        app._f2_tracking_analysis_raw_frame = frame.copy()
        app._f2_tracking_analysis_rois = tracked
        app.operacao_engine = SimpleNamespace(
            _prepared_leds=(
                SimpleNamespace(
                    id=roi.id, centro_x=roi.centro_x, centro_y=roi.centro_y
                )
                for roi in tracked
            )
        )
        app.operacao_engine._prepared_leds = tuple(
            app.operacao_engine._prepared_leds
        )

        selected = obter_mascaras_do_frame_analisado_f2(app, frame.copy())

        self.assertEqual(tracked, selected)
        self.assertEqual(120, selected[0].centro_x)
        self.assertEqual(100, app.operacao_leds_preview[0].centro_x)

    def test_frame_analisado_rejeita_geometria_de_frame_antigo(self):
        app = _TrackingHarness()
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        tracked = tuple(obter_rois_rastreadas_analise_f2(app, frame))
        app.camera_ultimo_frame_id = 38
        app._f2_tracking_analysis_frame_id = 37
        app._f2_tracking_analysis_raw_frame = frame.copy()
        app._f2_tracking_analysis_rois = tracked
        app.operacao_engine = SimpleNamespace(
            _prepared_leds=(
                SimpleNamespace(
                    id=roi.id, centro_x=roi.centro_x, centro_y=roi.centro_y,
                )
                for roi in tracked
            )
        )
        app.operacao_engine._prepared_leds = tuple(
            app.operacao_engine._prepared_leds
        )
        self.assertEqual((), obter_mascaras_do_frame_analisado_f2(app, frame))

    def test_frame_analisado_rejeita_motor_com_coordenada_diferente(self):
        app = _TrackingHarness()
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        tracked = tuple(obter_rois_rastreadas_analise_f2(app, frame))
        app.camera_ultimo_frame_id = 37
        app._f2_tracking_analysis_frame_id = 37
        app._f2_tracking_analysis_raw_frame = frame.copy()
        app._f2_tracking_analysis_rois = tracked
        app.operacao_engine = SimpleNamespace(_prepared_leds=(
            SimpleNamespace(id="LED_001", centro_x=100, centro_y=80),
        ))
        self.assertEqual((), obter_mascaras_do_frame_analisado_f2(app, frame))

    def test_frame_analisado_desligado_preserva_mascaras_fixas(self):
        app = _TrackingHarness()
        app.rastreamento_automatico_f2 = False
        self.assertIsNone(
            obter_mascaras_do_frame_analisado_f2(
                app, np.zeros((240, 320, 3), dtype=np.uint8),
            )
        )

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
