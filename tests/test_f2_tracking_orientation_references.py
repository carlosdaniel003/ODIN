import unittest

import cv2
import numpy as np

from src.platform.f2_object_tracking_real_orientations import (
    _mapear_keypoints_para_canonico,
)
from src.platform.f2_tracking_orientation_references import (
    F2_ORIENTATION_90,
    definir_referencia_orientacao_projeto,
    matriz_orientacao_np,
    obter_referencias_orientacao_projeto,
    referencia_orientacao_calibrada,
)


class F2TrackingOrientationReferencesTests(unittest.TestCase):
    def test_persiste_imagem_matriz_e_calibracao_por_projeto(self):
        config = {
            "led_projects": {
                "PROJETO A": {
                    "name": "PROJETO A",
                }
            }
        }
        matrix = [[0.0, 1.0, 100.0], [-1.0, 0.0, 300.0]]
        config = definir_referencia_orientacao_projeto(
            config,
            "PROJETO A",
            F2_ORIENTATION_90,
            {
                "image_path": "/tmp/orientation_90.png",
                "width": 640,
                "height": 480,
                "canonical_to_reference": matrix,
                "calibrated": True,
                "base_shape_updated_at": "shape-v1",
                "updated_at": "ref-v1",
            },
        )

        entries = obter_referencias_orientacao_projeto(config, "PROJETO A")
        entry = entries[F2_ORIENTATION_90]
        self.assertEqual(entry["image_path"], "/tmp/orientation_90.png")
        self.assertTrue(entry["calibrated"])
        self.assertEqual(entry["base_shape_updated_at"], "shape-v1")
        np.testing.assert_allclose(
            matriz_orientacao_np(entry),
            np.asarray(matrix, dtype=np.float32),
        )
        self.assertTrue(referencia_orientacao_calibrada(entry, "shape-v1"))
        self.assertFalse(referencia_orientacao_calibrada(entry, "shape-v2"))

    def test_keypoint_da_foto_real_volta_ao_sistema_canonico(self):
        center = (320.0, 240.0)
        canonical_to_reference = cv2.getRotationMatrix2D(center, 90.0, 1.0).astype(
            np.float32
        )
        canonical = np.asarray([180.0, 210.0, 1.0], dtype=np.float32)
        reference = canonical_to_reference @ canonical
        keypoint = cv2.KeyPoint(float(reference[0]), float(reference[1]), 12.0)

        mapped = _mapear_keypoints_para_canonico(
            [keypoint],
            canonical_to_reference,
        )
        self.assertEqual(len(mapped), 1)
        self.assertAlmostEqual(mapped[0].pt[0], float(canonical[0]), places=3)
        self.assertAlmostEqual(mapped[0].pt[1], float(canonical[1]), places=3)


if __name__ == "__main__":
    unittest.main()
