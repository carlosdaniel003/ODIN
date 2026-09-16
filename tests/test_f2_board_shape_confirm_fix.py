from __future__ import annotations

import inspect
import unittest

from src.models.led_selection import LedSelection
from src.platform.f2_board_shape_confirm_fix import (
    finalizar_rascunho_contorno_placa_f2,
    instalar_correcao_confirmacao_contorno_placa_f2,
)


class _DummyApp:
    def __init__(self, points):
        self._segmento_livre_pontos = list(points)
        self.leds_selecionados = []
        self._selecao_tela_cheia_window = None
        self._f2_board_shape_edit_context = {"settings_window": None}

    def _finalizar_segmento_livre(self):
        pontos = list(self._segmento_livre_pontos)
        if len(pontos) < 3:
            return
        centro_x = int(round(sum(p[0] for p in pontos) / len(pontos)))
        centro_y = int(round(sum(p[1] for p in pontos) / len(pontos)))
        relativos = [
            (float(x - centro_x), float(y - centro_y))
            for x, y in pontos
        ]
        self.leds_selecionados.append(
            LedSelection(
                id="BOARD_001",
                centro_x=centro_x,
                centro_y=centro_y,
                raio=2,
                tipo_roi="segmento",
                pontos_segmento_livre=relativos,
            )
        )
        self._segmento_livre_pontos = []


class F2BoardShapeConfirmFixTests(unittest.TestCase):
    def test_ok_materializa_poligono_aberto_com_tres_ou_mais_vertices(self):
        app = _DummyApp([(10, 10), (110, 10), (110, 80), (10, 80)])

        self.assertTrue(finalizar_rascunho_contorno_placa_f2(app))
        self.assertEqual([], app._segmento_livre_pontos)
        self.assertEqual(1, len(app.leds_selecionados))
        self.assertTrue(app.leds_selecionados[0].eh_segmento_livre)

    def test_sem_rascunho_nao_altera_geometria_existente(self):
        app = _DummyApp([])
        existente = LedSelection(id="BOARD", centro_x=40, centro_y=40, raio=8)
        app.leds_selecionados = [existente]

        self.assertTrue(finalizar_rascunho_contorno_placa_f2(app))
        self.assertEqual(1, len(app.leds_selecionados))
        self.assertIs(existente, app.leds_selecionados[0])

    def test_instalador_intercepta_apenas_salvamento_do_editor_f2(self):
        source = inspect.getsource(instalar_correcao_confirmacao_contorno_placa_f2)
        self.assertIn("_salvar_e_fechar_editor_placa", source)
        self.assertIn("finalizar_rascunho_contorno_placa_f2", source)
        self.assertNotIn("display_f3", source)


if __name__ == "__main__":
    unittest.main()
