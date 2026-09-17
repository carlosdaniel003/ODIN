import unittest

import cv2
import numpy as np

from src.platform.f2_object_tracking_cardinal_rotation_fix import (
    _criar_vistas_referencia_sem_clipping,
    _dispersao_inliers_valida,
    _preparar_canvas_rotacao,
)


class F2ObjectTrackingCardinalRotationFixTests(unittest.TestCase):
    def _synthetic_board(self):
        height, width = 360, 640
        gray = np.full((height, width), 35, dtype=np.uint8)
        mask = np.zeros((height, width), dtype=np.uint8)

        left, top, right, bottom = 105, 130, 535, 230
        cv2.rectangle(mask, (left, top), (right, bottom), 255, thickness=-1)
        cv2.rectangle(gray, (left, top), (right, bottom), 90, thickness=-1)

        # Textura assimétrica e repetível para o ORB continuar tendo features
        # depois de 90° e 180°.
        for x in range(left + 15, right - 10, 28):
            cv2.line(gray, (x, top + 8), (x + 12, bottom - 8), 210, 2)
        for x, y, radius in (
            (145, 155, 8),
            (205, 205, 11),
            (315, 165, 7),
            (410, 210, 9),
            (500, 150, 6),
        ):
            cv2.circle(gray, (x, y), radius, 240, thickness=2)
        cv2.putText(
            gray,
            "ODIN",
            (250, 205),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            245,
            2,
            cv2.LINE_AA,
        )
        return gray, mask

    def test_canvas_quadrado_nao_recorta_mascara_em_90_graus(self):
        gray, mask = self._synthetic_board()
        prepared = _preparar_canvas_rotacao(gray, mask)
        self.assertIsNotNone(prepared)
        gray_canvas, mask_canvas, _matrix, _major, _minor = prepared
        self.assertEqual(gray_canvas.shape, mask_canvas.shape)
        self.assertEqual(gray_canvas.shape[0], gray_canvas.shape[1])

        side = mask_canvas.shape[0]
        center = ((side - 1) / 2.0, (side - 1) / 2.0)
        rotation = cv2.getRotationMatrix2D(center, 90.0, 1.0)
        rotated = cv2.warpAffine(
            mask_canvas,
            rotation,
            (side, side),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )

        original_area = int(cv2.countNonZero(mask_canvas))
        rotated_area = int(cv2.countNonZero(rotated))
        self.assertGreater(original_area, 0)
        self.assertLessEqual(abs(rotated_area - original_area), original_area * 0.02)

    def test_banco_gera_vistas_explicitas_de_90_e_180(self):
        gray, mask = self._synthetic_board()
        views = _criar_vistas_referencia_sem_clipping(gray, mask)
        angles = {round(float(view["angle"])) for view in views}
        self.assertIn(90, angles)
        self.assertIn(-90, angles)
        self.assertIn(180, angles)
        for view in views:
            if round(float(view["angle"])) in {-90, 90, 180}:
                self.assertTrue(view["cardinal"])
                self.assertGreater(len(view["keypoints"]), 0)

    def test_dispersao_geometrica_e_invariante_a_rotacao_de_90(self):
        # Placa 400x80: após 90°, a largura X fica pequena. A validação antiga
        # baseada em X/Y podia rejeitar este caso; PCA deve aceitá-lo.
        points = []
        for x in np.linspace(-180.0, 180.0, 8):
            for y in np.linspace(-32.0, 32.0, 4):
                points.append((x, y))
        points = np.asarray(points, dtype=np.float32)
        rotated_90 = np.column_stack((-points[:, 1], points[:, 0]))

        view = {
            "cardinal": True,
            "board_major": 400.0,
            "board_minor": 80.0,
        }
        self.assertTrue(_dispersao_inliers_valida(rotated_90, view))


if __name__ == "__main__":
    unittest.main()
