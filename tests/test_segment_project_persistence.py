import unittest

import numpy as np

import src.platform.led_mask_resolution_sync as resolution_sync
from src.core.roi_geometry import TIPO_ROI_CIRCULO, TIPO_ROI_SEGMENTO
from src.models.led_selection import LedSelection
from src.platform.led_mask_editor import LedMaskEditorMixin
from src.platform.desktop_production_app import DesktopProductionApp
from src.platform.segment_project_geometry_persistence import (
    SegmentProjectGeometryPersistenceMixin,
    copiar_led_geometria_completa,
    instalar_preservacao_segmentos_resolution_sync,
)


class FakeRepository:
    def __init__(self, leds):
        self._leds = [copiar_led_geometria_completa(led) for led in leds]
        self.ultimo_projeto = None

    def obter_projeto_led_ativo(self):
        return "DISPLAY-7SEG"

    def carregar_leds_fixos(self, projeto=None):
        self.ultimo_projeto = projeto
        return [copiar_led_geometria_completa(led) for led in self._leds]

    def salvar_leds_fixos(
        self,
        leds_fixos,
        largura_base=None,
        altura_base=None,
        projeto=None,
    ):
        del largura_base, altura_base
        self.ultimo_projeto = projeto
        self._leds = [copiar_led_geometria_completa(led) for led in leds_fixos]
        return {"fixed_leds": [led.to_dict() for led in self._leds]}


class FakeView:
    def __init__(self):
        self.selecao_manual_camera_visivel = True
        self.desenhos = []

    def atualizar_estado_selecao_led(self, _ativo):
        return None

    def preparar_imagem_para_exibicao(self, _imagem):
        return None

    def desenhar_canvas(self, leds, resultados):
        self.desenhos.append((list(leds), list(resultados)))

    def atualizar_faixa_resultado(self):
        return None


class BaseQuePerdeGeometria:
    def __init__(self, leds):
        self.config_repository = FakeRepository(leds)
        self.view = FakeView()
        self.imagem_original = np.zeros((1080, 1920, 3), dtype=np.uint8)
        self.camera_ativa = False
        self.guias_leds_fixos_visiveis = False
        self.selecao_manual_camera_ativa = True
        self.leds_manuais_camera = []
        self.resultados_led_atual = []
        self.leds_fixos_configurados = []
        self.leds_selecionados = []
        self.projeto_led_ativo = "DISPLAY-7SEG"

    def carregar_leds_fixos(self):
        # Reproduz o defeito observado no fluxo legado: o projeto é carregado,
        # mas as ROIs são recriadas apenas com centro/raio e viram círculos.
        carregados = self.config_repository.carregar_leds_fixos(
            projeto=self.config_repository.obter_projeto_led_ativo()
        )
        self.leds_fixos_configurados = carregados
        self.leds_selecionados = [
            LedSelection(led.id, led.centro_x, led.centro_y, led.raio)
            for led in carregados
        ]
        self.view.desenhar_canvas(self.leds_selecionados, [])

    def _salvar_leds_no_projeto(
        self,
        nome_projeto,
        parent=None,
        confirmar_substituicao=True,
    ):
        # Reproduz exatamente o caminho do ODIN base alcançado pelo botão
        # "Salvar LEDs selecionados": antes de persistir, reconstrói somente
        # id/x/y/raio, convertendo segmentos em círculos.
        del parent, confirmar_substituicao
        circulos = [
            LedSelection(led.id, led.centro_x, led.centro_y, led.raio)
            for led in self.leds_selecionados
        ]
        self.config_repository.salvar_leds_fixos(
            circulos,
            projeto=nome_projeto,
        )
        self.leds_fixos_configurados = circulos
        self.leds_selecionados = circulos
        return True

    def _atualizar_projeto_led_na_interface(self):
        return None

    def atualizar_renderizacoes_visuais(self, _leds):
        return None


class RuntimeFake(SegmentProjectGeometryPersistenceMixin, BaseQuePerdeGeometria):
    pass


class SegmentProjectPersistenceTests(unittest.TestCase):
    def _segmento(self):
        return LedSelection(
            "DIGITO_1_A",
            600,
            300,
            1,
            tipo_roi="segmento",
            largura=150,
            altura=28,
            angulo=-4.5,
        )

    def test_copia_completa_preserva_segmento(self):
        origem = self._segmento()
        copia = copiar_led_geometria_completa(origem)
        self.assertEqual(TIPO_ROI_SEGMENTO, copia.tipo_roi)
        self.assertEqual(150, copia.largura)
        self.assertEqual(28, copia.altura)
        self.assertAlmostEqual(-4.5, copia.angulo)

    def test_copia_completa_preserva_circulo_legado(self):
        origem = LedSelection("LED_DP", 100, 120, 12)
        copia = copiar_led_geometria_completa(origem)
        self.assertEqual(TIPO_ROI_CIRCULO, copia.tipo_roi)
        self.assertEqual(12, copia.raio)
        self.assertIsNone(copia.largura)
        self.assertIsNone(copia.altura)

    def test_carregar_projeto_repara_segmento_convertido_em_bolinha(self):
        app = RuntimeFake([self._segmento()])
        app.carregar_leds_fixos()

        self.assertEqual(1, len(app.leds_selecionados))
        led = app.leds_selecionados[0]
        self.assertEqual(TIPO_ROI_SEGMENTO, led.tipo_roi)
        self.assertEqual(150, led.largura)
        self.assertEqual(28, led.altura)
        self.assertAlmostEqual(-4.5, led.angulo)
        self.assertTrue(app.guias_leds_fixos_visiveis)
        self.assertFalse(app.selecao_manual_camera_ativa)
        self.assertEqual([], app.leds_manuais_camera)
        self.assertGreaterEqual(len(app.view.desenhos), 2)
        ultimo = app.view.desenhos[-1][0][0]
        self.assertEqual(TIPO_ROI_SEGMENTO, ultimo.tipo_roi)

    def test_salvar_leds_selecionados_regrava_geometria_completa(self):
        app = RuntimeFake([])
        app.leds_selecionados = [self._segmento()]

        salvo = app._salvar_leds_no_projeto("DISPLAY-7SEG")

        self.assertTrue(salvo)
        persistido = app.config_repository.carregar_leds_fixos(
            projeto="DISPLAY-7SEG"
        )[0]
        self.assertEqual(TIPO_ROI_SEGMENTO, persistido.tipo_roi)
        self.assertEqual(150, persistido.largura)
        self.assertEqual(28, persistido.altura)
        self.assertAlmostEqual(-4.5, persistido.angulo)
        self.assertEqual(TIPO_ROI_SEGMENTO, app.leds_selecionados[0].tipo_roi)

    def test_ciclo_real_salvar_selecionados_e_carregar_projeto_nao_vira_bolinha(self):
        app = RuntimeFake([])
        app.leds_selecionados = [self._segmento()]

        self.assertTrue(app._salvar_leds_no_projeto("DISPLAY-7SEG"))

        # Simula a tela sendo limpa antes de o operador clicar em
        # "Carregar projeto". O fluxo base tentará converter para círculo,
        # e a camada display precisa recuperar a geometria persistida.
        app.leds_selecionados = []
        app.leds_fixos_configurados = []
        app.view.desenhos.clear()
        app.carregar_leds_fixos()

        self.assertEqual(1, len(app.leds_selecionados))
        carregado = app.leds_selecionados[0]
        self.assertEqual(TIPO_ROI_SEGMENTO, carregado.tipo_roi)
        self.assertEqual(150, carregado.largura)
        self.assertEqual(28, carregado.altura)
        self.assertAlmostEqual(-4.5, carregado.angulo)
        self.assertEqual(
            TIPO_ROI_SEGMENTO,
            app.view.desenhos[-1][0][0].tipo_roi,
        )

    def test_carregamento_misto_preserva_segmento_e_circulo(self):
        circulo = LedSelection("LED_DP", 900, 400, 10)
        app = RuntimeFake([self._segmento(), circulo])
        app.carregar_leds_fixos()
        self.assertEqual(
            [TIPO_ROI_SEGMENTO, TIPO_ROI_CIRCULO],
            [led.tipo_roi for led in app.leds_selecionados],
        )

    def test_sync_de_resolucao_nao_descarta_geometria_segmento(self):
        instalar_preservacao_segmentos_resolution_sync()
        origem = self._segmento().com_normalizacao(1920, 1080)
        adaptacao = resolution_sync.adapt_led_masks_to_resolution(
            [origem],
            target_width=1920,
            target_height=1080,
            reference_width=1920,
            reference_height=1080,
        )
        self.assertEqual(1, len(adaptacao.adapted_leds))
        led = adaptacao.adapted_leds[0]
        self.assertEqual(TIPO_ROI_SEGMENTO, led.tipo_roi)
        self.assertEqual(150, led.largura)
        self.assertEqual(28, led.altura)
        self.assertAlmostEqual(-4.5, led.angulo)

    def test_perfil_display_prioriza_persistencia_antes_do_editor_legado(self):
        mro = DesktopProductionApp.__mro__
        self.assertIn(SegmentProjectGeometryPersistenceMixin, mro)
        self.assertIn(LedMaskEditorMixin, mro)
        self.assertLess(
            mro.index(SegmentProjectGeometryPersistenceMixin),
            mro.index(LedMaskEditorMixin),
        )


if __name__ == "__main__":
    unittest.main()
