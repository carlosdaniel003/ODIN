from __future__ import annotations

import unittest

from src.models.led_selection import LedSelection
from src.platform.f2_board_shape_state_isolation import (
    _definir_rois_editor,
    _rois_editor,
    filtrar_contaminacao_leds_f2,
)
from src.platform.freeform_segment_roi import criar_segmento_livre_por_pontos


class _Repository:
    def __init__(self, leds):
        self._leds = list(leds)

    def carregar_leds_fixos(self, projeto=None):
        return list(self._leds)


class _App:
    def __init__(self, leds=()):
        self.config_repository = _Repository(leds)
        self.leds_selecionados = []
        self.resultados_led_atual = []


class _Controller:
    def __init__(self, leds=()):
        self.app = _App(leds)


class F2BoardShapeStateIsolationTests(unittest.TestCase):
    def test_remove_copia_real_de_led_fixo_do_contorno(self):
        led = LedSelection(id="LED_001", centro_x=120, centro_y=80, raio=10)
        board = criar_segmento_livre_por_pontos(
            [(20, 20), (220, 20), (220, 140), (20, 140)],
            id_roi="SEG_001",
        )
        controller = _Controller([led])

        result = filtrar_contaminacao_leds_f2(
            controller,
            "TESTE",
            [led, board],
        )

        self.assertEqual(1, len(result))
        self.assertEqual("SEG_001", result[0].id)
        self.assertEqual(1, controller.app._f2_board_shape_legacy_led_contamination)

    def test_nao_remove_forma_apenas_por_reutilizar_id(self):
        led = LedSelection(id="SEG_001", centro_x=120, centro_y=80, raio=10)
        board = criar_segmento_livre_por_pontos(
            [(20, 20), (220, 20), (220, 140), (20, 140)],
            id_roi="SEG_001",
        )
        controller = _Controller([led])

        result = filtrar_contaminacao_leds_f2(controller, "TESTE", [board])

        self.assertEqual(1, len(result))
        self.assertTrue(getattr(result[0], "pontos_segmento_livre", None))

    def test_estado_dedicado_nao_e_substituido_pelo_espelho_global(self):
        app = _App()
        board = criar_segmento_livre_por_pontos(
            [(10, 10), (90, 10), (90, 70), (10, 70)],
            id_roi="SEG_001",
        )
        _definir_rois_editor(app, [board])

        # Simula a câmera Linux republicando as 42 máscaras no estado global.
        app.leds_selecionados = [
            LedSelection(id=f"LED_{i:03d}", centro_x=i, centro_y=i, raio=4)
            for i in range(1, 43)
        ]

        dedicated = _rois_editor(app)
        self.assertEqual(1, len(dedicated))
        self.assertEqual("SEG_001", dedicated[0].id)
        self.assertTrue(getattr(dedicated[0], "pontos_segmento_livre", None))


if __name__ == "__main__":
    unittest.main()
