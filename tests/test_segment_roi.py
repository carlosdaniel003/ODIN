import unittest

import numpy as np

from src.core.feature_extractor import extrair_features_selecao
from src.core.operation_engine import OperationEngine
from src.core.roi_geometry import (
    TIPO_ROI_CIRCULO,
    TIPO_ROI_SEGMENTO,
    bbox_roi,
    criar_mascara_roi_global,
    ponto_dentro_roi,
    roi_dentro_imagem,
)
from src.core.visual_renderer import criar_imagem_mascara_multiplos
from src.models.led_features import LedFeatures
from src.models.led_selection import LedSelection
from src.platform.bulk_roi_editor import copiar_led, mover_rois
from src.platform.fixed_mask_geometry_guard import (
    assinatura_geometria,
    copiar_mascara_absoluta,
)
from src.platform.desktop_production_app import DesktopProductionApp
from src.platform.segment_display_roi_editor import (
    SegmentDisplayRoiEditorMixin,
    criar_segmento_por_arrasto,
    redimensionar_segmento_por_handle,
)
from src.platform.segment_display_runtime import SegmentDisplayRuntimeMixin


class SegmentRoiTests(unittest.TestCase):
    def test_json_antigo_sem_tipo_continua_circular(self):
        led = LedSelection.from_dict(
            {"id": "LED_001", "centro_x": 40, "centro_y": 50, "raio": 8}
        )
        self.assertIsNotNone(led)
        self.assertEqual(TIPO_ROI_CIRCULO, led.tipo_roi)
        self.assertIsNone(led.largura)
        self.assertIsNone(led.altura)

    def test_segmento_persiste_largura_altura_angulo(self):
        led = LedSelection(
            "SEG_001", 100, 90, 1,
            tipo_roi="segmento", largura=60, altura=14, angulo=-7.5,
        )
        dados = led.to_dict()
        recarregado = LedSelection.from_dict(dados)
        self.assertEqual(TIPO_ROI_SEGMENTO, recarregado.tipo_roi)
        self.assertEqual(60, recarregado.largura)
        self.assertEqual(14, recarregado.altura)
        self.assertAlmostEqual(-7.5, recarregado.angulo)

    def test_mascara_segmento_e_chanfrada_e_menor_que_bbox(self):
        led = LedSelection(
            "SEG_001", 80, 60, 1,
            tipo_roi="segmento", largura=70, altura=18, angulo=0,
        )
        mascara = criar_mascara_roi_global(led, 180, 120)
        x1, y1, x2, y2 = bbox_roi(led)
        area_bbox = (x2 - x1 + 1) * (y2 - y1 + 1)
        area_mascara = int(np.count_nonzero(mascara))
        self.assertGreater(area_mascara, 0)
        self.assertLess(area_mascara, area_bbox)
        self.assertTrue(ponto_dentro_roi(led, 80, 60))
        self.assertFalse(ponto_dentro_roi(led, x1, y1))

    def test_segmento_rotacionado_respeita_limites(self):
        led = LedSelection(
            "SEG_001", 100, 80, 1,
            tipo_roi="segmento", largura=80, altura=16, angulo=45,
        )
        self.assertTrue(roi_dentro_imagem(led, 200, 160))
        led.centro_x = 4
        self.assertFalse(roi_dentro_imagem(led, 200, 160))

    def test_criacao_por_arrasto_define_centro_largura_e_angulo(self):
        led = criar_segmento_por_arrasto(20, 30, 100, 30, id_roi="SEG_010")
        self.assertEqual("SEG_010", led.id)
        self.assertEqual(60, led.centro_x)
        self.assertEqual(30, led.centro_y)
        self.assertEqual(80, led.largura)
        self.assertEqual(14, led.altura)
        self.assertAlmostEqual(0.0, led.angulo)

    def test_handles_alteram_largura_altura_e_rotacao(self):
        led = LedSelection(
            "SEG_001", 100, 100, 1,
            tipo_roi="segmento", largura=50, altura=12, angulo=0,
        )
        largo = redimensionar_segmento_por_handle(led, "e", 140, 100)
        alto = redimensionar_segmento_por_handle(led, "s", 100, 115)
        girado = redimensionar_segmento_por_handle(led, "rotate", 130, 100)
        self.assertEqual(80, largo.largura)
        self.assertEqual(30, alto.altura)
        self.assertAlmostEqual(90.0, girado.angulo)

    def test_copias_e_movimento_nao_perdem_geometria(self):
        led = LedSelection(
            "SEG_001", 100, 100, 1,
            tipo_roi="segmento", largura=50, altura=12, angulo=15,
        )
        copia = copiar_led(led)
        movido = mover_rois([led], 3, -2, 300, 300)[0]
        for item in (copia, movido):
            self.assertEqual(TIPO_ROI_SEGMENTO, item.tipo_roi)
            self.assertEqual(50, item.largura)
            self.assertEqual(12, item.altura)
            self.assertAlmostEqual(15, item.angulo)
        self.assertEqual((103, 98), (movido.centro_x, movido.centro_y))

    def test_guard_inclui_dimensoes_e_angulo_na_assinatura(self):
        led = LedSelection(
            "SEG_001", 100, 100, 1,
            tipo_roi="segmento", largura=50, altura=12, angulo=15,
        )
        copia = copiar_mascara_absoluta(led)
        self.assertEqual(assinatura_geometria([led]), assinatura_geometria([copia]))
        copia.angulo = 16
        self.assertNotEqual(assinatura_geometria([led]), assinatura_geometria([copia]))

    def test_feature_extractor_usa_apenas_pixels_do_segmento(self):
        imagem = np.zeros((120, 180, 3), dtype=np.uint8)
        led = LedSelection(
            "SEG_001", 90, 60, 1,
            tipo_roi="segmento", largura=80, altura=18, angulo=0,
        )
        mascara = criar_mascara_roi_global(led, 180, 120)
        imagem[mascara > 0] = (0, 0, 255)
        features = extrair_features_selecao(imagem, led)
        self.assertGreater(features.area_pixels, 500)
        self.assertGreater(features.v_mean, 245)
        self.assertGreater(features.percent_hot_245, 0.95)

    def test_renderer_mistura_circulo_e_segmento(self):
        imagem = np.zeros((120, 180, 3), dtype=np.uint8)
        circulo = LedSelection("LED_001", 30, 30, 8)
        segmento = LedSelection(
            "SEG_001", 100, 70, 1,
            tipo_roi="segmento", largura=60, altura=14, angulo=20,
        )
        mascara = criar_imagem_mascara_multiplos(imagem, [circulo, segmento])
        self.assertEqual(255, int(mascara[30, 30]))
        self.assertEqual(255, int(mascara[70, 100]))

    def test_operation_engine_prepara_segmento(self):
        on = LedFeatures(v_mean=220, v_std=30, v_p99=255, glow_score=80)
        off = LedFeatures(v_mean=20, v_std=5, v_p99=40, glow_score=2)
        led = LedSelection(
            "DIGITO_1_A", 90, 60, 1,
            tipo_roi="segmento", largura=70, altura=16, angulo=-4,
        )
        engine = OperationEngine()
        engine.prepare(on, off, [led], 180, 120)
        self.assertTrue(engine.ready)
        self.assertEqual(1, engine.led_count)
        preparado = engine._prepared_leds[0]
        self.assertEqual(TIPO_ROI_SEGMENTO, preparado.tipo_roi)
        self.assertEqual(70, preparado.largura)
        self.assertEqual(16, preparado.altura)

    def test_perfil_display_ativa_editor_e_runtime_de_segmentos(self):
        self.assertIn(SegmentDisplayRoiEditorMixin, DesktopProductionApp.__mro__)
        self.assertIn(SegmentDisplayRuntimeMixin, DesktopProductionApp.__mro__)


if __name__ == "__main__":
    unittest.main()
