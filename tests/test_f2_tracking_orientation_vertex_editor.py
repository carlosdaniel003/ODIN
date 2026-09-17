import unittest

import numpy as np

from src.core.roi_geometry import pontos_segmento
from src.platform.freeform_segment_roi import criar_segmento_livre_por_pontos
from src.platform.f2_tracking_orientation_references import (
    F2_ORIENTATION_90,
    F2_ORIENTATION_180,
    definir_referencia_orientacao_projeto,
    obter_referencias_orientacao_projeto,
)
from src.platform.f2_tracking_orientation_vertex_editor import (
    F2_ORIENTATION_BOARD_POINTS_KEY,
    _matrix_key,
    contorno_referencia_orientacao_f2,
    instalar_editor_vertices_referencias_orientacao_f2,
)
from src.platform.f2_tracking_orientation_vertex_transform_fix import (
    instalar_transformacao_base_editor_vertices_orientacao_f2,
)
import src.platform.f2_tracking_orientation_references as orientation_refs


class F2TrackingOrientationVertexEditorTests(unittest.TestCase):
    def _shape(self):
        return [
            criar_segmento_livre_por_pontos(
                [(20, 20), (120, 20), (120, 80), (20, 80)],
                id_roi="BOARD",
            )
        ]

    def test_pontos_finos_sao_persistidos_independentemente_por_slot(self):
        config = {
            "led_projects": {
                "PROJETO A": {
                    "name": "PROJETO A",
                }
            }
        }
        matrix_90 = [[1.0, 0.0, 10.0], [0.0, 1.0, 15.0]]
        matrix_180 = [[1.0, 0.0, 30.0], [0.0, 1.0, 25.0]]
        points_90 = [[30.0, 35.0], [130.0, 35.0], [129.0, 95.0], [30.0, 95.0]]
        points_180 = [[50.0, 45.0], [150.0, 45.0], [150.0, 105.0], [49.0, 105.0]]

        for slot, matrix, points in (
            (F2_ORIENTATION_90, matrix_90, points_90),
            (F2_ORIENTATION_180, matrix_180, points_180),
        ):
            config = definir_referencia_orientacao_projeto(
                config,
                "PROJETO A",
                slot,
                {
                    "image_path": f"/tmp/{slot}.png",
                    "width": 200,
                    "height": 140,
                    "canonical_to_reference": matrix,
                    "calibrated": True,
                    "base_shape_updated_at": "shape-v1",
                    "updated_at": f"{slot}-v1",
                    F2_ORIENTATION_BOARD_POINTS_KEY: points,
                },
            )

        entries = obter_referencias_orientacao_projeto(config, "PROJETO A")
        self.assertEqual(
            entries[F2_ORIENTATION_90][F2_ORIENTATION_BOARD_POINTS_KEY],
            points_90,
        )
        self.assertEqual(
            entries[F2_ORIENTATION_180][F2_ORIENTATION_BOARD_POINTS_KEY],
            points_180,
        )

    def test_correcao_local_move_so_o_vertice_editado(self):
        shape = self._shape()
        matrix = np.asarray([[1.0, 0.0, 10.0], [0.0, 1.0, 5.0]], dtype=np.float32)
        base = orientation_refs.transformar_rois_para_frame_atual_f2(
            shape,
            matrix,
            220,
            160,
        )
        base_points = np.asarray(pontos_segmento(base[0]), dtype=np.float32)
        corrected_points = base_points.copy()
        corrected_points[2] += np.asarray([7.0, -4.0], dtype=np.float32)

        corrected = contorno_referencia_orientacao_f2(
            shape,
            matrix,
            {F2_ORIENTATION_BOARD_POINTS_KEY: corrected_points.tolist()},
            220,
            160,
        )
        actual = np.asarray(pontos_segmento(corrected[0]), dtype=np.float32)

        np.testing.assert_allclose(actual, corrected_points, atol=0.6)
        np.testing.assert_allclose(actual[:2], base_points[:2], atol=0.6)
        np.testing.assert_allclose(actual[3:], base_points[3:], atol=0.6)
        self.assertFalse(np.allclose(actual[2], base_points[2]))
        np.testing.assert_allclose(
            np.asarray(pontos_segmento(shape[0]), dtype=np.float32),
            np.asarray([(20, 20), (120, 20), (120, 80), (20, 80)], dtype=np.float32),
            atol=0.6,
        )

    def test_preview_com_contexto_de_vertices_nao_entra_em_recursao(self):
        instalar_editor_vertices_referencias_orientacao_f2()
        instalar_transformacao_base_editor_vertices_orientacao_f2()

        shape = self._shape()
        matrix = np.asarray([[1.0, 0.0, 8.0], [0.0, 1.0, 6.0]], dtype=np.float32)
        base = orientation_refs.transformar_rois_para_frame_atual_f2(
            shape,
            matrix,
            220,
            160,
        )
        base_points = np.asarray(pontos_segmento(base[0]), dtype=np.float32)
        corrected_points = base_points.copy()
        corrected_points[0] += np.asarray([5.0, 3.0], dtype=np.float32)
        entry = {F2_ORIENTATION_BOARD_POINTS_KEY: corrected_points.tolist()}

        old_context = getattr(
            orientation_refs,
            "_odin_orientation_vertex_preview_context",
            None,
        )
        orientation_refs._odin_orientation_vertex_preview_context = {
            "shape_id": "BOARD",
            "entries_by_matrix": {_matrix_key(matrix): entry},
        }
        try:
            corrected = orientation_refs.transformar_rois_para_frame_atual_f2(
                shape,
                matrix,
                220,
                160,
            )
        finally:
            orientation_refs._odin_orientation_vertex_preview_context = old_context

        actual = np.asarray(pontos_segmento(corrected[0]), dtype=np.float32)
        np.testing.assert_allclose(actual, corrected_points, atol=0.6)


if __name__ == "__main__":
    unittest.main()
