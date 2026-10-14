from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

import src.platform.f2_inspection_optical_diagnostic as diagnostic
from src.platform.desktop_profile import DesktopODINApp


def _fixture():
    features_on = SimpleNamespace(to_dict=lambda: {"v_mean": 245.0})
    features_off = SimpleNamespace(to_dict=lambda: {"v_mean": 47.0})
    result_led = SimpleNamespace(
        to_dict=lambda: {
            "id": "LED_002",
            "status": "ACESO",
            "features": {
                "v_mean": 87.0,
                "percent_on": 0.20,
                "percent_hot_250": 0.03,
            },
            "motivos": ["votos favorecem aceso"],
        },
    )
    prepared = SimpleNamespace(
        id="LED_002", centro_x=101, centro_y=153, raio=9,
        x1=90, y1=142, x2=112, y2=165,
    )
    engine = SimpleNamespace(
        _classifier=SimpleNamespace(
            features_referencia_acesa=features_on,
            features_referencia_apagada=features_off,
        ),
        _prepared_leds=(prepared,),
    )
    result = SimpleNamespace(
        ok=True, failed_led_ids=(), results=(result_led,),
    )
    app = SimpleNamespace(
        _f2_tracking_enabled=lambda: True,
        operacao_engine=engine,
        camera_ultimo_frame_id=123,
        _f2_tracking_analysis_frame_id=123,
        _f2_tracking_analysis_raw_frame=np.zeros((240, 320, 3), dtype=np.uint8),
        _f2_object_tracking_last_status={"locked": True},
        _f2_object_tracker=SimpleNamespace(
            last_matrix=np.asarray([[1, 0, -12], [0, 1, 8]]),
            _f2_tracking_last_method="ORB",
        ),
        _f2_tracking_analysis_override_depth=1,
    )
    return app, result


class F2InspectionOpticalDiagnosticTests(unittest.TestCase):
    def test_registra_metricas_e_posicao_real_do_motor_sem_alterar_resultado(self):
        app, result = _fixture()
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "f2_inspection_optical_trace.jsonl"
            with patch.object(diagnostic, "F2_OPTICAL_TRACE_PATH", destination):
                self.assertTrue(
                    diagnostic.registrar_diagnostico_optico_inspecao_f2(
                        app, frame, result,
                    )
                )
                data = json.loads(destination.read_text(encoding="utf-8"))
        self.assertTrue(data["result_ok"])
        self.assertEqual(123, data["frame_id"])
        self.assertEqual(123, data["tracking_frame_id"])
        self.assertEqual("ORB", data["tracking_method"])
        self.assertEqual({"v_mean": 245.0}, data["reference_on"])
        self.assertEqual({"v_mean": 47.0}, data["reference_off"])
        self.assertEqual(1, data["prepared_count"])
        self.assertEqual(1, data["result_count"])
        self.assertEqual([90, 142, 112, 165], data["leds"][0]["prepared"]["bbox"])
        self.assertEqual("ACESO", data["leds"][0]["result"]["status"])
        self.assertEqual(0.20, data["leds"][0]["result"]["features"]["percent_on"])
        self.assertTrue(result.ok)
        self.assertEqual((), result.failed_led_ids)
        self.assertEqual(1, app._f2_optical_trace_count)

    def test_coleta_limita_oito_inspecoes_sem_registrar_sondagens_periodicas(self):
        app, result = _fixture()
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "f2_inspection_optical_trace.jsonl"
            with patch.object(diagnostic, "F2_OPTICAL_TRACE_PATH", destination):
                published = [
                    diagnostic.registrar_diagnostico_optico_inspecao_f2(
                        app, frame, result,
                    )
                    for _ in range(10)
                ]
                self.assertEqual([True] * 8 + [False, False], published)
                self.assertEqual(8, len(destination.read_text().splitlines()))

    def test_tracking_desligado_nao_registra_nem_interfere(self):
        app, result = _fixture()
        app._f2_tracking_enabled = lambda: False
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "trace.jsonl"
            with patch.object(diagnostic, "F2_OPTICAL_TRACE_PATH", destination):
                self.assertFalse(
                    diagnostic.registrar_diagnostico_optico_inspecao_f2(
                        app, np.zeros((3, 4, 3), dtype=np.uint8), result,
                    )
                )
                self.assertFalse(destination.exists())

    def test_falha_no_log_nao_altera_resultado(self):
        app, result = _fixture()
        with tempfile.TemporaryDirectory() as directory:
            path_that_is_a_file = Path(directory) / "not_a_directory"
            path_that_is_a_file.write_text("file", encoding="utf-8")
            destination = path_that_is_a_file / "trace.jsonl"
            with patch.object(
                diagnostic, "F2_OPTICAL_TRACE_PATH", destination,
            ), patch.object(
                diagnostic.logging.getLogger(diagnostic.__name__), "warning",
            ):
                self.assertFalse(
                    diagnostic.registrar_diagnostico_optico_inspecao_f2(
                        app, np.zeros((3, 4, 3), dtype=np.uint8), result,
                    )
                )
        self.assertTrue(result.ok)

    def test_inspecao_base_encaminha_resultado_oficial_ao_diagnostico(self):
        source = __import__("inspect").getsource(DesktopODINApp.disparar_inspecao_operacao)
        self.assertIn("registrar_diagnostico_optico_inspecao_f2(self, frame, resultado)", source)
        self.assertIn("resultado = self.operacao_engine.analyze(frame)", source)


if __name__ == "__main__":
    unittest.main()
