from __future__ import annotations

import inspect
import unittest

import numpy as np

import src.platform.f2_board_shape_precision_magnifier as magnifier


class Controller:
    def __init__(self, mode="editar_contorno_placa_f2", active=True):
        self.modo_atual = mode
        self.active = active

    def _modo_segmento_livre_ativo(self):
        return self.active

    def click(self, _event=None):
        return None


class View:
    def __init__(self, controller):
        self.callbacks = {"evento_clique_esquerdo": controller.click}


class PrecisionMagnifierTests(unittest.TestCase):
    def test_ativa_somente_no_desenho_ponto_a_ponto_da_placa(self):
        self.assertTrue(magnifier._modo_ponto_a_ponto_placa_f2(View(Controller())))
        self.assertFalse(magnifier._modo_ponto_a_ponto_placa_f2(View(Controller("configurar_leds_fixos"))))
        self.assertFalse(magnifier._modo_ponto_a_ponto_placa_f2(View(Controller(active=False))))

    def test_mira_destaca_pixel_exato_sem_segmento_convencional(self):
        box = magnifier.calcular_caixa_pixel_lupa_f2(100, 60, 82, 42, 5.0, 5.0, 190)
        self.assertEqual((90, 90, 94, 94), box)
        image = np.zeros((190, 190, 3), dtype=np.uint8)
        magnifier._desenhar_mira_ponto_a_ponto(image, box, (92, 92))
        self.assertGreater(int(np.count_nonzero(image)), 0)
        source = inspect.getsource(magnifier.desenhar_lupa_ponto_a_ponto_placa_f2)
        self.assertNotIn("_criar_segmento_mira_preview", source)
        self.assertIn("PONTO A PONTO", source)
        self.assertIn("cv2.INTER_NEAREST", source)

    def test_preserva_lupa_normal_fora_do_modo(self):
        source = inspect.getsource(magnifier.instalar_lupa_precisao_contorno_placa_f2)
        self.assertIn("return previous", source)
        self.assertIn("_odin_f2_board_point_precision", source)


if __name__ == "__main__":
    unittest.main()
