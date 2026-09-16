from __future__ import annotations

import inspect
import unittest

import numpy as np

import src.platform.f2_board_shape_editor_main_canvas_isolation as isolation


class _LabelFake:
    def __init__(self):
        self.text = None

    def configure(self, **kwargs):
        self.text = kwargs.get("text")


class _ViewFake:
    def __init__(self):
        self.imagem_canvas_original = np.ones((10, 10, 3), dtype=np.uint8)
        self.imagem_exibicao = object()
        self.imagem_tk = object()
        self.lupa_tk = object()
        self._imagem_tk_largura = 10
        self._imagem_tk_altura = 10
        self._imagem_render_largura = 10
        self._imagem_render_altura = 10
        self._imagem_render_offset_x = 3
        self._imagem_render_offset_y = 4
        self.escala_exibicao = 2.0
        self.deslocamento_imagem_x = 8
        self.deslocamento_imagem_y = 9
        self.largura_imagem_exibida = 10
        self.altura_imagem_exibida = 10
        self.ultimo_led_selecionado = ["x"]
        self.ultimo_resultado_led_atual = ["y"]
        self.resolucao_atual = "640 x 480"
        self.label_meta_resolucao = _LabelFake()
        self.desenhos = []

    def limpar_lupa_canvas(self):
        return None

    def desenhar_canvas(self, leds, resultados):
        self.desenhos.append((list(leds), list(resultados)))


class F2BoardShapeMainCanvasIsolationTests(unittest.TestCase):
    def test_limpa_referencia_temporaria_quando_tela_principal_era_vazia(self):
        view = _ViewFake()
        isolation._limpar_imagem_principal_view(view, "--")

        self.assertIsNone(view.imagem_canvas_original)
        self.assertIsNone(view.imagem_exibicao)
        self.assertIsNone(view.imagem_tk)
        self.assertIsNone(view.lupa_tk)
        self.assertEqual(0, view.largura_imagem_exibida)
        self.assertEqual(0, view.altura_imagem_exibida)
        self.assertEqual("--", view.resolucao_atual)
        self.assertEqual("--", view.label_meta_resolucao.text)
        self.assertEqual([([], [])], view.desenhos)

    def test_patch_guarda_imagem_da_view_antes_do_editor(self):
        source = inspect.getsource(
            isolation.instalar_isolamento_imagem_principal_editor_placa_f2
        )
        self.assertIn("imagem_canvas_original", source)
        self.assertIn("_snapshot_contexto_app", source)
        self.assertIn("_restaurar_contexto_app", source)
        self.assertIn("_limpar_imagem_principal_view", source)

    def test_correcao_nao_toca_f3(self):
        source = inspect.getsource(isolation)
        self.assertNotIn("display_f3", source)
        self.assertNotIn("F3", source)


if __name__ == "__main__":
    unittest.main()
