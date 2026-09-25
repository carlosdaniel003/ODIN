import inspect
import unittest

from src.core.operation_engine import OperationEngine
from src.core.segment_low_light import (
    STATUS_POUCA_LUZ,
    aplicar_diagnostico_pouca_luz,
    avaliar_pouca_luz_segmento,
)
from src.infra.result_repository import ResultRepository
from src.models.analysis_result import LedAnalysisResult
from src.models.led_features import LedFeatures
from src.models.metric_evaluation import MetricEvaluation
import src.platform.desktop_production_app as production_module
import src.platform.segment_display_runtime as runtime_module


class SegmentLowLightTests(unittest.TestCase):
    # Valores extraídos do ensaio real do display em que J23/J25/J27/J28/J29
    # foram informados como falha de baixa luminosidade.
    AMOSTRAS = {
        23: (228.2136, 157.1398, 172.2100, 0.425247, 172.1560),
        25: (242.4779, 162.0700, 172.2909, 0.720751, 224.8949),
        27: (244.9417, 145.8825, 172.1364, 0.596094, 186.3462),
        28: (239.3210, 168.7270, 171.7660, 0.634354, 212.1918),
        29: (240.9204, 157.3820, 172.5555, 0.663455, 213.3783),
    }

    # SEG_028 do ensaio DISPLAY_7 de 2026-08-11. O classificador ACESO/APAGADO
    # deu 9 votos para ACESO e 0 para APAGADO, mas o diagnóstico calibrado de
    # pouca luz o sobrescrevia quando não existia nenhuma referência POUCA_LUZ.
    DISPLAY_7_SEG_028 = (250.7648, 223.4050, 166.3736, 0.761006, 213.0562)

    NORMAIS = {
        1: (254.7118, 92.9654, 27.6721, 0.986694, 249.0939),
        2: (254.0023, 74.4306, 29.4748, 0.970950, 249.3868),
        # SEG_015 tem brilho global menor por enquadramento, mas não é um dos
        # segmentos de pouca luz informados no ensaio. A assinatura cromática
        # evita o falso positivo.
        15: (218.2727, 167.3739, 78.6565, 0.575892, 203.5268),
        18: (254.4003, 56.5383, 29.1805, 0.983444, 250.5177),
    }

    @staticmethod
    def _features(valores):
        v_mean, s_mean, h_mean, hot_250, glow = valores
        return LedFeatures(
            v_mean=v_mean,
            v_max=255.0,
            v_p99=255.0,
            s_mean=s_mean,
            h_mean=h_mean,
            percent_hot_250=hot_250,
            glow_score=glow,
        )

    @staticmethod
    def _resultado(features, status="ACESO", tipo="segmento"):
        return LedAnalysisResult(
            id="SEG_TESTE",
            status=status,
            valor_binario=1 if status == "ACESO" else 0,
            centro_x=100,
            centro_y=100,
            raio=50,
            features=features,
            limite_v_mean=0.0,
            limite_v_std=0.0,
            limite_center_to_ring_v=0.0,
            limite_glow_score=0.0,
            limite_v_p99=0.0,
            distancia_on=0.0,
            distancia_off=0.0,
            brilho_indica_aceso=True,
            similaridade_indica_aceso=True,
            pico_indica_aceso=True,
            contraste_indica_aceso=True,
            metricas_indicam_aceso=True,
            avaliacao_metricas=MetricEvaluation(1.0, 1.0, 1.0, 1, 0, []),
            motivos=[],
            confianca=0.9,
            tipo_roi=tipo,
            largura=100 if tipo == "segmento" else None,
            altura=20 if tipo == "segmento" else None,
        )

    def test_amostras_reais_j23_j25_j27_j28_j29_sao_pouca_luz(self):
        detectados = set()
        for numero, valores in self.AMOSTRAS.items():
            avaliacao = avaliar_pouca_luz_segmento(self._features(valores))
            if avaliacao.falha:
                detectados.add(numero)
        self.assertEqual({23, 25, 27, 28, 29}, detectados)

    def test_segmentos_normais_do_mesmo_ensaio_nao_sao_reclassificados(self):
        for numero, valores in self.NORMAIS.items():
            with self.subTest(segmento=numero):
                avaliacao = avaliar_pouca_luz_segmento(self._features(valores))
                self.assertFalse(avaliacao.falha)

    def test_aplicar_diagnostico_muda_status_mas_mantem_presenca_de_luz(self):
        resultado = self._resultado(self._features(self.AMOSTRAS[23]))
        aplicar_diagnostico_pouca_luz(resultado, "segmento")
        self.assertEqual(STATUS_POUCA_LUZ, resultado.status)
        self.assertEqual(1, resultado.valor_binario)
        self.assertTrue(resultado.falha_luminosidade)
        self.assertGreater(resultado.score_falha_luminosidade, 0.8)
        self.assertLess(resultado.indice_luminosidade, 1.0)

    def test_display_7_sem_referencia_pouca_luz_permanece_aceso(self):
        resultado = self._resultado(self._features(self.DISPLAY_7_SEG_028))

        # Confirma que os limites ópticos antigos isoladamente tentariam marcar
        # esta amostra como POUCA_LUZ.
        self.assertTrue(avaliar_pouca_luz_segmento(resultado.features).falha)

        aplicar_diagnostico_pouca_luz(
            resultado,
            "segmento",
            habilitado=False,
        )

        self.assertEqual("ACESO", resultado.status)
        self.assertEqual(1, resultado.valor_binario)
        self.assertFalse(resultado.falha_luminosidade)
        self.assertEqual(0.0, resultado.score_falha_luminosidade)
        self.assertEqual(1.0, resultado.indice_luminosidade)
        self.assertEqual([], resultado.motivos)

    def test_circulo_nao_recebe_classificacao_de_segmento(self):
        resultado = self._resultado(
            self._features(self.AMOSTRAS[23]),
            tipo="circulo",
        )
        aplicar_diagnostico_pouca_luz(resultado, "circulo")
        self.assertEqual("ACESO", resultado.status)
        self.assertFalse(resultado.falha_luminosidade)

    def test_apagado_continua_apagado(self):
        resultado = self._resultado(
            self._features(self.AMOSTRAS[23]),
            status="APAGADO",
        )
        aplicar_diagnostico_pouca_luz(resultado, "segmento")
        self.assertEqual("APAGADO", resultado.status)
        self.assertEqual(0, resultado.valor_binario)

    def test_pouca_luz_e_ng_mesmo_com_binario_um(self):
        resultado = self._resultado(self._features(self.AMOSTRAS[25]))
        aplicar_diagnostico_pouca_luz(resultado, "segmento")
        self.assertTrue(ResultRepository._resultado_eh_ng(resultado))

    def test_runtime_aplica_diagnostico_antes_de_publicar_resultados(self):
        codigo = inspect.getsource(runtime_module.SegmentDisplayRuntimeMixin.analisar_led_selecionado)
        self.assertIn("aplicar_diagnostico_pouca_luz", codigo)
        self.assertLess(
            codigo.index("aplicar_diagnostico_pouca_luz"),
            codigo.index("resultados_led.append"),
        )

    def test_runtime_habilita_pouca_luz_somente_com_referencia_ativa(self):
        codigo = inspect.getsource(runtime_module.SegmentDisplayRuntimeMixin.analisar_led_selecionado)
        self.assertIn(
            "diagnostico_pouca_luz_habilitado = _referencia_pouca_luz_ativa(self)",
            codigo,
        )
        self.assertIn("habilitado=diagnostico_pouca_luz_habilitado", codigo)

    def test_motor_de_operacao_respeita_trava_de_pouca_luz(self):
        engine = OperationEngine()
        self.assertFalse(engine.diagnostico_pouca_luz_habilitado)
        engine.definir_diagnostico_pouca_luz_habilitado(True)
        self.assertTrue(engine.diagnostico_pouca_luz_habilitado)
        engine.invalidate()
        self.assertFalse(engine.diagnostico_pouca_luz_habilitado)

        codigo = inspect.getsource(OperationEngine.analyze)
        self.assertIn("habilitado=self._diagnostico_pouca_luz_habilitado", codigo)

    def test_perfil_producao_sincroniza_trava_com_referencia_ativa(self):
        codigo = inspect.getsource(
            production_module.DesktopProductionApp.preparar_tela_operacao
        )
        self.assertIn("_tem_referencia_pouca_luz_ativa", codigo)
        self.assertIn("definir_diagnostico_pouca_luz_habilitado", codigo)


if __name__ == "__main__":
    unittest.main()
