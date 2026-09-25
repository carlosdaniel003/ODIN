import inspect
import unittest

import numpy as np

from src.core.roi_geometry import criar_mascara_roi_global, pontos_segmento
from src.models.led_selection import LedSelection
from src.platform.fixed_mask_geometry_guard import copiar_mascara_absoluta
from src.platform.freeform_segment_persistence import (
    assinatura_geometria_segmento_livre,
    copiar_led_geometria_completa_segmento_livre,
)
from src.platform.freeform_segment_roi import (
    FECHAR_SEGMENTO_DISTANCIA_CANVAS_PX,
    FreeformSegmentDrawingMixin,
    copiar_led_com_segmento_livre,
    criar_segmento_livre_por_pontos,
)
from src.platform.fullscreen_led_selection import FullscreenLedSelectionMixin
from src.platform.desktop_production_app import DesktopProductionApp
from src.platform.segment_display_roi_editor import criar_segmento_por_arrasto


class FreeformSegmentRoiTests(unittest.TestCase):
    def test_segmento_livre_reconstroi_exatamente_os_vertices(self):
        pontos = [(20, 20), (80, 18), (86, 42), (54, 31), (20, 46)]
        led = criar_segmento_livre_por_pontos(pontos, "SEG_LIVRE")
        reconstruidos = pontos_segmento(led)
        esperado = np.asarray(pontos, dtype=np.float32)
        self.assertEqual(5, len(reconstruidos))
        np.testing.assert_allclose(reconstruidos, esperado, atol=1.0)
        self.assertTrue(led.eh_segmento)
        self.assertTrue(led.eh_segmento_livre)

    def test_mascara_usa_poligono_real_inclusive_concavo(self):
        led = criar_segmento_livre_por_pontos(
            [(10, 10), (50, 10), (50, 50), (30, 28), (10, 50)],
            "SEG_CONCAVO",
        )
        mascara = criar_mascara_roi_global(led, 80, 80)
        self.assertGreater(int(np.count_nonzero(mascara)), 0)
        self.assertEqual(255, int(mascara[20, 20]))
        self.assertEqual(0, int(mascara[40, 30]))

    def test_segmento_livre_persiste_no_json(self):
        led = criar_segmento_livre_por_pontos(
            [(11, 12), (41, 10), (48, 27), (20, 35)],
            "SEG_JSON",
        )
        dados = led.to_dict()
        self.assertEqual("segmento", dados["tipo_roi"])
        self.assertIn("pontos_segmento_livre", dados)
        recarregado = LedSelection.from_dict(dados)
        self.assertIsNotNone(recarregado)
        self.assertTrue(recarregado.eh_segmento_livre)
        np.testing.assert_allclose(
            pontos_segmento(recarregado),
            pontos_segmento(led),
            atol=1e-5,
        )

    def test_segmento_livre_adapta_vertices_para_nova_resolucao(self):
        led = criar_segmento_livre_por_pontos(
            [(20, 20), (80, 20), (80, 40), (20, 40)],
            "SEG_SCALE",
        ).com_normalizacao(100, 100)
        adaptado = led.adaptar_para_resolucao(200, 150, 2, 100)
        self.assertTrue(adaptado.eh_segmento_livre)
        self.assertEqual(100, adaptado.centro_x)
        self.assertEqual(45, adaptado.centro_y)
        pontos = pontos_segmento(adaptado)
        xs = [float(p[0]) for p in pontos]
        ys = [float(p[1]) for p in pontos]
        self.assertAlmostEqual(40.0, min(xs), delta=1.0)
        self.assertAlmostEqual(160.0, max(xs), delta=1.0)
        self.assertAlmostEqual(30.0, min(ys), delta=1.0)
        self.assertAlmostEqual(60.0, max(ys), delta=1.0)

    def test_segmento_convencional_continua_existindo(self):
        led = criar_segmento_por_arrasto(20, 30, 90, 30, altura_segmento=12)
        self.assertTrue(led.eh_segmento)
        self.assertFalse(led.eh_segmento_livre)
        self.assertIsNone(led.pontos_segmento_livre)
        self.assertEqual(8, len(pontos_segmento(led)))

    def test_copias_do_editor_e_guard_preservam_vertices(self):
        led = criar_segmento_livre_por_pontos(
            [(15, 20), (55, 18), (61, 40), (22, 45)],
            "SEG_COPY",
        )
        copia_editor = copiar_led_com_segmento_livre(led)
        copia_guard = copiar_mascara_absoluta(led)
        copia_projeto = copiar_led_geometria_completa_segmento_livre(led)
        for copia in (copia_editor, copia_guard, copia_projeto):
            self.assertTrue(copia.eh_segmento_livre)
            self.assertEqual(
                list(led.pontos_segmento_livre),
                list(copia.pontos_segmento_livre),
            )

    def test_assinatura_muda_quando_vertice_muda(self):
        led_a = criar_segmento_livre_por_pontos(
            [(10, 10), (40, 10), (40, 30), (10, 30)],
            "SEG_SIG",
        )
        led_b = criar_segmento_livre_por_pontos(
            [(10, 10), (42, 10), (40, 30), (10, 30)],
            "SEG_SIG",
        )
        self.assertNotEqual(
            assinatura_geometria_segmento_livre([led_a]),
            assinatura_geometria_segmento_livre([led_b]),
        )

    def test_perfil_final_inclui_desenho_livre_antes_do_fullscreen(self):
        mro = DesktopProductionApp.__mro__
        self.assertIn(FreeformSegmentDrawingMixin, mro)
        self.assertLess(
            mro.index(FreeformSegmentDrawingMixin),
            mro.index(FullscreenLedSelectionMixin),
        )

    def test_interacao_tem_linha_dinamica_e_fechamento_proximo_da_origem(self):
        classe_fonte = getattr(
            FreeformSegmentDrawingMixin,
            "_odin_freeform_original_class",
            FreeformSegmentDrawingMixin,
        )
        fonte = inspect.getsource(classe_fonte)
        self.assertIn("Segmento por pontos", fonte)
        self.assertIn("_evento_motion_selecao", fonte)
        self.assertIn("_segmento_livre_mouse", fonte)
        self.assertIn("FECHAR_SEGMENTO_DISTANCIA_CANVAS_PX", fonte)
        self.assertGreaterEqual(FECHAR_SEGMENTO_DISTANCIA_CANVAS_PX, 12)
        self.assertLessEqual(FECHAR_SEGMENTO_DISTANCIA_CANVAS_PX, 24)


if __name__ == "__main__":
    unittest.main()
