import inspect
import unittest
from unittest.mock import patch

from src.platform.analysis_response_metrics import AnalysisResponseMetricsMixin
from src.platform.desktop_production_app import DesktopProductionApp
from src.platform.segment_display_runtime import SegmentDisplayRuntimeMixin
from src.ui.main_window_parts.layout.criar_barra_metadados import criar_barra_metadados
from src.ui.main_window_parts.updates.atualizar_metricas_desempenho import (
    atualizar_metricas_desempenho,
)


class _LabelFake:
    def __init__(self):
        self.texto = None

    def configure(self, **kwargs):
        self.texto = kwargs.get("text", self.texto)


class _RootFake:
    def __init__(self):
        self.update_idletasks_calls = 0

    def update_idletasks(self):
        self.update_idletasks_calls += 1


class _ViewFake:
    def __init__(self):
        self.metricas = []

    def atualizar_metricas_desempenho(self, **kwargs):
        self.metricas.append(dict(kwargs))


class _AnaliseBaseFake:
    def __init__(self):
        self.root = _RootFake()
        self.view = _ViewFake()
        self.resultados_led_atual = []

    def analisar_led_selecionado(self):
        self.resultados_led_atual = [object(), object(), object()]


class _AnaliseFake(AnalysisResponseMetricsMixin, _AnaliseBaseFake):
    pass


class AnalysisResponseMetricsTests(unittest.TestCase):
    def test_perfil_display_mede_antes_do_runtime_de_segmentos(self):
        mro = DesktopProductionApp.__mro__
        self.assertIn(AnalysisResponseMetricsMixin, mro)
        self.assertIn(SegmentDisplayRuntimeMixin, mro)
        self.assertLess(
            mro.index(AnalysisResponseMetricsMixin),
            mro.index(SegmentDisplayRuntimeMixin),
        )

    def test_tempo_vai_do_disparo_ate_depois_do_render_idle(self):
        app = _AnaliseFake()
        with patch(
            "src.platform.analysis_response_metrics.time.perf_counter",
            side_effect=[10.0, 10.125],
        ):
            app.analisar_led_selecionado()

        self.assertEqual(1, app.root.update_idletasks_calls)
        self.assertEqual(1, len(app.view.metricas))
        self.assertAlmostEqual(
            125.0,
            app.view.metricas[0]["tempo_resposta_ms"],
            places=5,
        )
        self.assertEqual(3, app.view.metricas[0]["rois_analisadas"])

    def test_barra_substitui_lado_por_rois_analisadas(self):
        fonte = inspect.getsource(criar_barra_metadados)
        self.assertIn('"ROIs analisadas"', fonte)
        self.assertIn("label_meta_rois_analisadas", fonte)
        self.assertNotIn('"Lado"', fonte)

    def test_atualizador_preenche_tempo_e_total_de_rois(self):
        view = type("ViewFake", (), {})()
        view.label_meta_tempo = _LabelFake()
        view.label_meta_rois_analisadas = _LabelFake()

        atualizar_metricas_desempenho(
            view,
            tempo_resposta_ms=87.6,
            rois_analisadas=4,
        )

        self.assertEqual("88 ms", view.label_meta_tempo.texto)
        self.assertEqual("4", view.label_meta_rois_analisadas.texto)


if __name__ == "__main__":
    unittest.main()
