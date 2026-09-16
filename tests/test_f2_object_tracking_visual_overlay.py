from __future__ import annotations

import inspect
import unittest

import cv2
import numpy as np

from src.models.led_selection import LedSelection
from src.platform.f2_object_tracking_visual_overlay import (
    F2_TRACKING_BOARD_OUTLINE_BGR,
    desenhar_contorno_rastreado_f2,
    instalar_overlay_visual_rastreamento_f2,
    inverter_matriz_rastreamento_f2,
    transformar_pontos_rastreamento_f2,
    transformar_roi_para_frame_atual_f2,
)


class F2ObjectTrackingVisualOverlayTests(unittest.TestCase):
    def test_inverte_current_para_reference_em_reference_para_current(self):
        current_to_reference = np.float32(
            [[1.0, 0.0, -20.0], [0.0, 1.0, 10.0]]
        )
        reference_to_current = inverter_matriz_rastreamento_f2(
            current_to_reference
        )
        self.assertIsNotNone(reference_to_current)
        point = transformar_pontos_rastreamento_f2(
            [(100.0, 100.0)],
            reference_to_current,
        )[0]
        self.assertAlmostEqual(120.0, float(point[0]), delta=0.01)
        self.assertAlmostEqual(90.0, float(point[1]), delta=0.01)

    def test_roi_circular_acompanha_translacao_da_placa(self):
        roi = LedSelection(id="LED_001", centro_x=100, centro_y=100, raio=10)
        reference_to_current = np.float32(
            [[1.0, 0.0, 24.0], [0.0, 1.0, -8.0]]
        )
        tracked = transformar_roi_para_frame_atual_f2(
            roi,
            reference_to_current,
            320,
            240,
        )
        self.assertIsNotNone(tracked)
        self.assertEqual(124, tracked.centro_x)
        self.assertEqual(92, tracked.centro_y)
        self.assertEqual(10, tracked.raio)

    def test_segmento_ponto_a_ponto_acompanha_geometria(self):
        board = LedSelection(
            id="BOARD",
            centro_x=120,
            centro_y=100,
            raio=2,
            tipo_roi="segmento",
            pontos_segmento_livre=[
                (-40, -30),
                (40, -30),
                (40, 30),
                (-40, 30),
            ],
        )
        reference_to_current = cv2.getRotationMatrix2D((0, 0), 3.0, 1.02)
        reference_to_current[:, 2] += np.asarray([18.0, 11.0])
        tracked = transformar_roi_para_frame_atual_f2(
            board,
            reference_to_current,
            320,
            240,
        )
        self.assertIsNotNone(tracked)
        self.assertTrue(tracked.eh_segmento_livre)
        self.assertEqual(4, len(tracked.pontos_segmento_livre))
        self.assertGreater(tracked.centro_x, board.centro_x)
        self.assertGreater(tracked.centro_y, board.centro_y)

    def test_contorno_e_apenas_overlay_visual_em_copia(self):
        frame = np.zeros((180, 260, 3), dtype=np.uint8)
        board = LedSelection(
            id="BOARD",
            centro_x=130,
            centro_y=90,
            raio=2,
            tipo_roi="segmento",
            pontos_segmento_livre=[
                (-70, -45),
                (70, -45),
                (70, 45),
                (-70, 45),
            ],
        )
        decorated = desenhar_contorno_rastreado_f2(frame, [board])
        self.assertIsNot(decorated, frame)
        self.assertEqual(0, int(np.count_nonzero(frame)))
        self.assertGreater(int(np.count_nonzero(decorated)), 0)
        color = np.asarray(F2_TRACKING_BOARD_OUTLINE_BGR, dtype=np.uint8)
        self.assertTrue(np.any(np.all(decorated == color, axis=2)))

    def test_instalador_nao_cria_timer_nem_segunda_leitura_de_camera(self):
        source = inspect.getsource(instalar_overlay_visual_rastreamento_f2)
        self.assertNotIn("root.after", source)
        self.assertNotIn("camera_service", source)
        self.assertNotIn("obter_snapshot", source)
        self.assertIn("window.update_preview", source)
        self.assertIn("previous(self)", source)
        self.assertNotIn("display_f3", source)


if __name__ == "__main__":
    unittest.main()
