import unittest

import cv2
import numpy as np

from src.models.led_selection import LedSelection
from src.platform.f2_tracking_orientation_precision_roi_editor import (
    F2_ORIENTATION_CIRCLE_OVERRIDES_KEY,
    _apply_reference_overrides,
    _correct_canonical_circles,
    normalizar_correcoes_circulares_orientacao,
)


class F2TrackingOrientationPrecisionRoiEditorTests(unittest.TestCase):
    def test_normaliza_somente_correcoes_circulares_validas(self):
        value = {
            "LED_01": {"x": 101.5, "y": 202.25, "radius": 14.0},
            "INVALID_RADIUS": {"x": 10, "y": 20, "radius": 0},
            "INVALID_DATA": {"x": "abc", "y": 20, "radius": 4},
        }
        normalized = normalizar_correcoes_circulares_orientacao(value)
        self.assertEqual(set(normalized), {"LED_01"})
        self.assertAlmostEqual(normalized["LED_01"]["x"], 101.5)
        self.assertAlmostEqual(normalized["LED_01"]["y"], 202.25)
        self.assertAlmostEqual(normalized["LED_01"]["radius"], 14.0)

    def test_aplica_correcao_na_foto_real_sem_mudar_roi_original(self):
        original = LedSelection(id="LED_01", centro_x=100, centro_y=80, raio=12)
        entry = {
            F2_ORIENTATION_CIRCLE_OVERRIDES_KEY: {
                "LED_01": {"x": 124.0, "y": 91.0, "radius": 15.0}
            }
        }
        corrected = _apply_reference_overrides([original], entry)
        self.assertEqual(len(corrected), 1)
        self.assertEqual(corrected[0].centro_x, 124)
        self.assertEqual(corrected[0].centro_y, 91)
        self.assertEqual(corrected[0].raio, 15)
        self.assertEqual(original.centro_x, 100)
        self.assertEqual(original.centro_y, 80)
        self.assertEqual(original.raio, 12)

    def test_correcao_da_referencia_volta_ao_sistema_canonico(self):
        canonical = LedSelection(id="LED_01", centro_x=180, centro_y=210, raio=10)
        matrix = cv2.getRotationMatrix2D((320.0, 240.0), 90.0, 1.0).astype(
            np.float32
        )
        desired_canonical = np.asarray([184.0, 207.0, 1.0], dtype=np.float32)
        desired_reference = matrix @ desired_canonical
        entry = {
            "canonical_to_reference": matrix.tolist(),
            F2_ORIENTATION_CIRCLE_OVERRIDES_KEY: {
                "LED_01": {
                    "x": float(desired_reference[0]),
                    "y": float(desired_reference[1]),
                    "radius": 13.0,
                }
            },
        }
        corrected = _correct_canonical_circles([canonical], entry)
        self.assertEqual(len(corrected), 1)
        self.assertAlmostEqual(corrected[0].centro_x, 184, delta=1)
        self.assertAlmostEqual(corrected[0].centro_y, 207, delta=1)
        self.assertEqual(corrected[0].raio, 13)


if __name__ == "__main__":
    unittest.main()
