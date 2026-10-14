from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import numpy as np

from src.core.f2_led_physical_guard import (
    F2_PHYSICAL_MIN_HOT_245,
    F2_PHYSICAL_MIN_HOT_250,
    F2_PHYSICAL_MIN_PERCENT_ON,
    F2_PHYSICAL_STRONG_PERCENT_ON,
    aplicar_guarda_emissao_fisica_f2,
    avaliar_emissao_fisica_f2,
)
from src.models.led_features import LedFeatures
from src.core.operation_engine import OperationEngine
from src.models.led_selection import LedSelection


class F2LedPhysicalGuardTests(unittest.TestCase):
    @staticmethod
    def reference_on() -> LedFeatures:
        # hot250 vem da referência ACESO registrada no Debug Tecnico (2).
        return LedFeatures(
            percent_on=0.80,
            percent_hot_245=0.12,
            percent_hot_250=0.107383,
        )

    @staticmethod
    def result(status: str, features: LedFeatures):
        return SimpleNamespace(
            status=status,
            valor_binario=1 if status == "ACESO" else 0,
            features=features,
            motivos=[],
            falha_luminosidade=False,
            indice_luminosidade=1.0,
            score_falha_luminosidade=0.0,
        )

    def test_envelope_do_debug_com_placa_desligada_nao_e_emissao(self):
        # LED_010 foi um dos casos mais permissivos do novo debug: 25,8% da
        # ROI acima de V=160, hot245=3,8% e hot250=3,5%, mesmo assim era apenas
        # reflexo com a placa totalmente desligada.
        features = LedFeatures(
            percent_on=0.258110,
            percent_hot_245=0.038082,
            percent_hot_250=0.035261,
            v_max=255.0,
            v_p99=255.0,
            glow_score=111.6579,
            center_to_ring_v=25.7641,
        )

        evaluation = avaliar_emissao_fisica_f2(
            features,
            reference_on=self.reference_on(),
        )

        self.assertFalse(evaluation.emitted)
        self.assertLess(features.percent_on, evaluation.min_percent_on)
        self.assertLess(features.percent_hot_245, evaluation.min_hot_245)
        self.assertLess(features.percent_hot_250, evaluation.min_hot_250)

    def test_reflexo_com_glow_muito_alto_continua_apagado(self):
        # LED_019/035/040 do debug chegavam a glow ~177..180 sem emissão real.
        features = LedFeatures(
            percent_on=0.095,
            percent_hot_245=0.034,
            percent_hot_250=0.030,
            v_max=255.0,
            v_p99=255.0,
            glow_score=180.141,
            center_to_ring_v=53.3146,
        )
        result = self.result("ACESO", features)

        aplicar_guarda_emissao_fisica_f2(
            result,
            reference_on=self.reference_on(),
        )

        self.assertEqual("APAGADO", result.status)
        self.assertEqual(0, result.valor_binario)
        self.assertTrue(any("sem emissão física" in reason for reason in result.motivos))

    def test_led_realmente_aceso_mantem_aceso(self):
        features = LedFeatures(
            percent_on=0.92,
            percent_hot_245=0.16,
            percent_hot_250=0.11,
            v_max=255.0,
            v_p99=255.0,
            glow_score=170.0,
        )
        result = self.result("ACESO", features)

        aplicar_guarda_emissao_fisica_f2(
            result,
            reference_on=self.reference_on(),
        )

        self.assertEqual("ACESO", result.status)
        self.assertEqual(1, result.valor_binario)

    def test_area_muito_ampla_preserva_aceso_mesmo_com_hot_core_variavel(self):
        features = LedFeatures(
            percent_on=F2_PHYSICAL_STRONG_PERCENT_ON + 0.05,
            percent_hot_245=0.025,
            percent_hot_250=0.020,
            v_max=255.0,
            v_p99=250.0,
        )
        evaluation = avaliar_emissao_fisica_f2(
            features,
            reference_on=self.reference_on(),
        )
        self.assertTrue(evaluation.emitted)

    def test_pouca_luz_nao_e_sobrescrita_pela_guarda_de_aceso_saudavel(self):
        result = self.result(
            "POUCA_LUZ",
            LedFeatures(
                percent_on=0.20,
                percent_hot_245=0.02,
                percent_hot_250=0.01,
            ),
        )

        aplicar_guarda_emissao_fisica_f2(
            result,
            reference_on=self.reference_on(),
        )

        self.assertEqual("POUCA_LUZ", result.status)

    @staticmethod
    def reference_white_core() -> LedFeatures:
        # Referência ON da inspeção física: núcleo branco + anel vermelho.
        return LedFeatures(
            inner_s_mean=5.8407,
            ring_s_mean=185.7717,
            percent_on=1.0,
            percent_hot_245=0.801128,
            percent_hot_250=0.624824,
        )

    @staticmethod
    def recorded_led_features(inner_s, ring_s, hot245, hot250) -> LedFeatures:
        return LedFeatures(
            percent_on=1.0,
            percent_hot_245=hot245,
            percent_hot_250=hot250,
            inner_s_mean=inner_s,
            ring_s_mean=ring_s,
        )

    def test_nucleo_cromatico_tampado_040_e_041_vira_apagado(self):
        reference = self.reference_white_core()
        # Métricas da segunda inspeção com dois LEDs tampados e brilho ~250.
        blocked = (
            ("LED_040", 249.9735, 247.9087, 0.977433, 0.854725),
            ("LED_041", 250.0619, 238.5152, 0.913963, 0.770099),
        )
        for name, inner, ring, hot245, hot250 in blocked:
            with self.subTest(led=name):
                features = self.recorded_led_features(
                    inner, ring, hot245, hot250,
                )
                evaluation = avaliar_emissao_fisica_f2(features, reference)
                self.assertFalse(evaluation.emitted)
                self.assertTrue(evaluation.chromatic_mismatch)

                result = self.result("ACESO", features)
                aplicar_guarda_emissao_fisica_f2(result, reference)
                self.assertEqual("APAGADO", result.status)
                self.assertEqual(0, result.valor_binario)
                self.assertTrue(any(
                    "núcleo cromático incompatível" in reason
                    for reason in result.motivos
                ))

    def test_leds_reais_acesos_040_041_e_vizinho_019_continuam_acesos(self):
        reference = self.reference_white_core()
        cases = (
            # LED_040 e LED_041 antes da obstrução.
            (33.3894, 120.3913, 0.856135, 0.653032),
            (20.1150, 115.9283, 0.868829, 0.691114),
            # LED_019: núcleo mais saturado, porém ainda apresenta halo.
            (104.6, 204.0, 0.801128, 0.624824),
            # LED_042 adjacente aos dois tampados na segunda inspeção.
            (73.6, 204.8, 0.801128, 0.624824),
        )
        for inner, ring, hot245, hot250 in cases:
            with self.subTest(inner=inner):
                result = self.result(
                    "ACESO",
                    self.recorded_led_features(inner, ring, hot245, hot250),
                )
                aplicar_guarda_emissao_fisica_f2(result, reference)
                self.assertEqual("ACESO", result.status)
                self.assertEqual(1, result.valor_binario)

    def test_led_colorido_sem_assinatura_branca_na_referencia_nao_e_bloqueado(self):
        # A guarda não pode forçar núcleo branco em projeto com LED colorido.
        reference = LedFeatures(
            inner_s_mean=220, ring_s_mean=240, percent_hot_250=0.30,
        )
        features = self.recorded_led_features(248, 246, 0.90, 0.70)
        result = self.result("ACESO", features)
        aplicar_guarda_emissao_fisica_f2(result, reference)
        self.assertEqual("ACESO", result.status)

    def test_sem_assinatura_na_referencia_preserva_guarda_luminosa(self):
        reference = LedFeatures(
            inner_s_mean=50, ring_s_mean=75, percent_hot_250=0.30,
        )
        features = self.recorded_led_features(250, 247, 0.90, 0.70)
        evaluation = avaliar_emissao_fisica_f2(features, reference)
        self.assertTrue(evaluation.emitted)
        self.assertFalse(evaluation.chromatic_mismatch)

    def test_motor_oficial_converte_led_tampado_em_ng(self):
        reference = self.reference_white_core()
        engine = OperationEngine()
        engine.prepare(
            reference,
            LedFeatures(),
            [
                LedSelection(id="LED_040", centro_x=20, centro_y=20, raio=8),
                LedSelection(id="LED_041", centro_x=60, centro_y=20, raio=8),
            ],
            100, 60,
        )
        features_on = self.recorded_led_features(
            33.3894, 120.3913, 0.856135, 0.653032,
        )
        features_blocked = self.recorded_led_features(
            250.0619, 238.5152, 0.913963, 0.770099,
        )

        def upstream_result(*_args, **_kwargs):
            # Simula exatamente o falso ACESO produzido pelo classificador.
            return self.result("ACESO", _kwargs["features_atual"])

        with patch.object(
            engine, "_extract_prepared_features",
            side_effect=(features_on, features_blocked),
        ), patch.object(
            engine._classifier,
            "classificar_led_por_referencia",
            side_effect=upstream_result,
        ):
            inspected = engine.analyze(
                np.zeros((60, 100, 3), dtype=np.uint8),
            )

        self.assertFalse(inspected.ok)
        self.assertEqual(("LED_041",), inspected.failed_led_ids)
        self.assertEqual(
            ["ACESO", "APAGADO"],
            [led.status for led in inspected.results],
        )

    def test_limites_tem_margem_sobre_o_debug_desligado(self):
        self.assertGreater(F2_PHYSICAL_MIN_PERCENT_ON, 0.258110)
        self.assertGreater(F2_PHYSICAL_MIN_HOT_245, 0.038082)
        self.assertGreater(F2_PHYSICAL_MIN_HOT_250, 0.035261)
        self.assertGreater(F2_PHYSICAL_STRONG_PERCENT_ON, 0.258110)

    def test_modulo_nao_altera_display_f3(self):
        import src.core.f2_led_physical_guard as module

        source = inspect.getsource(module)
        self.assertNotIn("DisplayAutomaticCheckF3Mixin", source)
        self.assertNotIn("DisplayProductionF3Mixin", source)
        self.assertNotIn("display_auto_check", source)


if __name__ == "__main__":
    unittest.main()
