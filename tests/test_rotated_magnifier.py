import inspect
import unittest
from unittest.mock import patch

import numpy as np

import src.ui.main_window_parts.magnifier.desenhar_lupa_canvas as lupa_module
from src.core.roi_geometry import TIPO_ROI_SEGMENTO
from src.models.led_selection import LedSelection
from src.platform.desktop_production_app import DesktopProductionApp
from src.platform.rotated_preview_roi_editor import (
    RotatedPreviewAreaRoiEditorMixin,
    converter_ponto_preview_lupa,
    converter_retangulo_preview_lupa,
)
from src.ui.main_window_parts.magnifier.desenhar_lupa_canvas import (
    _desenhar_forma_roi_no_recorte,
    _obter_tipo_roi_edicao_preview,
    pontos_segmento_preview_recorte,
    rotacionar_preview_lupa,
)


class RotatedMagnifierTests(unittest.TestCase):
    def test_preview_gira_90_sem_mudar_fonte(self):
        imagem = np.array(
            [
                [[1, 1, 1], [2, 2, 2], [3, 3, 3]],
                [[4, 4, 4], [5, 5, 5], [6, 6, 6]],
            ],
            dtype=np.uint8,
        )
        original = imagem.copy()

        preview = rotacionar_preview_lupa(imagem, 90)

        self.assertTrue(np.array_equal(imagem, original))
        self.assertEqual((3, 2, 3), preview.shape)
        self.assertEqual(4, int(preview[0, 0, 0]))
        self.assertEqual(1, int(preview[0, 1, 0]))

    def test_preview_segue_quatro_orientacoes(self):
        imagem = np.arange(27, dtype=np.uint8).reshape((3, 3, 3))

        self.assertTrue(np.array_equal(rotacionar_preview_lupa(imagem, 0), imagem))
        self.assertTrue(
            np.array_equal(
                rotacionar_preview_lupa(imagem, 90),
                np.rot90(imagem, k=3),
            )
        )
        self.assertTrue(
            np.array_equal(
                rotacionar_preview_lupa(imagem, 180),
                np.rot90(imagem, k=2),
            )
        )
        self.assertTrue(
            np.array_equal(
                rotacionar_preview_lupa(imagem, 270),
                np.rot90(imagem, k=1),
            )
        )

    def test_ponto_do_overlay_da_lupa_gira_com_preview(self):
        self.assertEqual((190.0, 0.0), converter_ponto_preview_lupa(0, 0, 190, 90))
        self.assertEqual((190.0, 190.0), converter_ponto_preview_lupa(0, 0, 190, 180))
        self.assertEqual((0.0, 190.0), converter_ponto_preview_lupa(0, 0, 190, 270))

    def test_retangulo_do_marquee_tambem_gira(self):
        self.assertEqual(
            (130.0, 10.0, 170.0, 50.0),
            converter_retangulo_preview_lupa(10, 20, 50, 60, 190, 90),
        )
        self.assertEqual(
            (140.0, 130.0, 180.0, 170.0),
            converter_retangulo_preview_lupa(10, 20, 50, 60, 190, 180),
        )

    def test_preview_projeta_poligono_chanfrado_do_segmento(self):
        segmento = LedSelection(
            "SEG_001",
            100,
            80,
            31,
            tipo_roi="segmento",
            largura=60,
            altura=14,
            angulo=0.0,
        )
        pontos = pontos_segmento_preview_recorte(
            segmento,
            x1=50,
            y1=40,
            escala_x=2.0,
            escala_y=2.0,
        )

        self.assertEqual((8, 1, 2), pontos.shape)
        largura = int(pontos[:, 0, 0].max() - pontos[:, 0, 0].min())
        altura = int(pontos[:, 0, 1].max() - pontos[:, 0, 1].min())
        self.assertGreater(largura, altura * 3)

    def test_segmento_confirmado_na_preview_nao_e_desenhado_com_circulo(self):
        imagem = np.zeros((190, 190, 3), dtype=np.uint8)
        segmento = LedSelection(
            "SEG_001",
            100,
            80,
            31,
            tipo_roi="segmento",
            largura=60,
            altura=14,
            angulo=12.0,
        )

        with patch.object(lupa_module.cv2, "polylines") as polylines, patch.object(
            lupa_module.cv2, "circle"
        ) as circle, patch.object(lupa_module.cv2, "drawMarker"):
            _desenhar_forma_roi_no_recorte(
                imagem,
                segmento,
                x1=50,
                y1=40,
                escala_x=2.0,
                escala_y=2.0,
                cor=(72, 255, 110),
                espessura=3,
            )

        polylines.assert_called_once()
        circle.assert_not_called()

    def test_circulo_legado_continua_circular_na_preview(self):
        imagem = np.zeros((190, 190, 3), dtype=np.uint8)
        circulo = LedSelection("LED_DP", 100, 80, 12)

        with patch.object(lupa_module.cv2, "polylines") as polylines, patch.object(
            lupa_module.cv2, "circle"
        ) as circle:
            _desenhar_forma_roi_no_recorte(
                imagem,
                circulo,
                x1=50,
                y1=40,
                escala_x=2.0,
                escala_y=2.0,
                cor=(72, 255, 110),
                espessura=3,
            )

        polylines.assert_not_called()
        self.assertEqual(2, circle.call_count)

    def test_mira_da_preview_le_tipo_de_roi_do_editor_display(self):
        class Controlador:
            tipo_roi_edicao = TIPO_ROI_SEGMENTO

            def evento_clique_esquerdo(self, _evento):
                return None

        class ViewFake:
            def __init__(self):
                controlador = Controlador()
                self.callbacks = {
                    "evento_clique_esquerdo": controlador.evento_clique_esquerdo
                }

        self.assertEqual(
            TIPO_ROI_SEGMENTO,
            _obter_tipo_roi_edicao_preview(ViewFake()),
        )

    def test_perfil_final_usa_editor_com_preview_rotacionada(self):
        self.assertIn(RotatedPreviewAreaRoiEditorMixin, DesktopProductionApp.__mro__)

    def test_lupa_nao_altera_camera_ou_mascaras(self):
        codigo = inspect.getsource(lupa_module)
        self.assertNotIn("camera_service", codigo)
        self.assertNotIn("config_repository", codigo)
        self.assertNotIn("salvar_leds_fixos", codigo)
        self.assertNotIn("leds_fixos_configurados =", codigo)


if __name__ == "__main__":
    unittest.main()
