from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from src.platform.display_auto_check_policy import (
    DISPLAY_AUTO_DECISION_NG,
    DISPLAY_AUTO_DECISION_SEARCHING,
    decidir_analise_display_f3,
)
from src.platform.display_f3_same_mask_reference_fix import (
    F3SameMaskReferenceAnalyzer,
)
from src.platform.display_f3_strict_mask_conformity import (
    F3StrictMaskConformityAnalyzer,
    F3_STRICT_MASK_AUTHORITY,
    filtrar_aprendizado_sem_check_atual_f3,
    resumir_falhas_mascaras_f3,
)
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
)


def _source(check_id: str, mask_id: str, state: str):
    return {
        "check_id": check_id,
        "check_name": check_id,
        "mask_id": mask_id,
        "state": state,
    }


class DisplayF3StrictMaskConformityTests(TestCase):
    def test_remove_foto_do_proprio_check_dos_pools_local_e_global(self):
        learning = {
            "by_mask": {
                "MASK_001": {
                    "on": ["usb_on", "blue_on"],
                    "off": ["aux_off"],
                    "sources": {
                        "on": [
                            _source("CHECK_004", "MASK_001", "on"),
                            _source("CHECK_002", "MASK_001", "on"),
                        ],
                        "off": [_source("CHECK_003", "MASK_001", "off")],
                    },
                }
            },
            "by_state": {
                "on": ["usb_on", "blue_on"],
                "off": ["usb_off_other", "aux_off"],
            },
            "state_sources": {
                "on": [
                    _source("CHECK_004", "MASK_001", "on"),
                    _source("CHECK_002", "MASK_001", "on"),
                ],
                "off": [
                    _source("CHECK_004", "MASK_002", "off"),
                    _source("CHECK_003", "MASK_001", "off"),
                ],
            },
            "photo_count": 3,
            "sample_count": 5,
        }

        filtered = filtrar_aprendizado_sem_check_atual_f3(
            learning,
            "CHECK_004",
        )

        self.assertEqual(["blue_on"], filtered["by_mask"]["MASK_001"]["on"])
        self.assertEqual(["aux_off"], filtered["by_mask"]["MASK_001"]["off"])
        self.assertEqual(["blue_on"], filtered["by_state"]["on"])
        self.assertEqual(["aux_off"], filtered["by_state"]["off"])
        self.assertTrue(filtered["self_reference_excluded"])
        self.assertEqual("CHECK_004", filtered["excluded_check_id"])

    def test_uma_unica_mascara_divergente_impede_aprovacao(self):
        base_analysis = {
            "ready": True,
            "approved": True,
            "reason": "antigo_ok",
            "mask_results": [
                {
                    "mask_id": "MASK_008",
                    "expected": DISPLAY_CHECK_STATE_ON,
                    "expected_label": "ACESO",
                    "classified": DISPLAY_CHECK_STATE_ON,
                    "classified_label": "ACESO",
                    "matched": True,
                    "confidence": 0.99,
                },
                {
                    "mask_id": "MASK_026",
                    "expected": DISPLAY_CHECK_STATE_ON,
                    "expected_label": "ACESO",
                    "classified": DISPLAY_CHECK_STATE_OFF,
                    "classified_label": "APAGADO",
                    "matched": False,
                    "confidence": 0.98,
                },
            ],
        }
        analyzer = F3StrictMaskConformityAnalyzer.__new__(
            F3StrictMaskConformityAnalyzer
        )
        analyzer._strict_current_check_id = ""

        with patch.object(
            F3SameMaskReferenceAnalyzer,
            "analyze",
            return_value=base_analysis,
        ):
            result = analyzer.analyze(
                frame=object(),
                project_name="CM-550-L",
                check_id="CHECK_004",
                visual_rotation=180,
            )

        self.assertFalse(result["approved"])
        self.assertEqual("check_diverge_mascara_configurada", result["reason"])
        self.assertEqual(["MASK_026"], result["failed_mask_ids"])
        self.assertEqual(["MASK_026"], result["missing_on_mask_ids"])
        self.assertEqual(F3_STRICT_MASK_AUTHORITY, result["reference_authority"])
        self.assertTrue(result["self_reference_excluded"])

    def test_resumo_expoe_contagem_esperada_e_mascara_faltante(self):
        summary = resumir_falhas_mascaras_f3(
            {
                "mask_results": [
                    {
                        "mask_id": "MASK_001",
                        "expected": "on",
                        "classified": "on",
                        "matched": True,
                    },
                    {
                        "mask_id": "MASK_026",
                        "expected": "on",
                        "classified": "off",
                        "matched": False,
                    },
                    {
                        "mask_id": "MASK_003",
                        "expected": "off",
                        "classified": "off",
                        "matched": True,
                    },
                ]
            }
        )
        self.assertEqual(2, summary["expected_on_mask_count"])
        self.assertEqual(1, summary["expected_off_mask_count"])
        self.assertEqual(["MASK_026"], summary["missing_on_mask_ids"])

    def test_check_posterior_vira_ng_com_um_segmento_apagado_e_placa_ligada(self):
        analysis = {
            "ready": True,
            "approved": False,
            "mask_results": [
                {
                    "mask_id": "MASK_008",
                    "expected": "on",
                    "classified": "on",
                    "matched": True,
                    "confidence": 0.99,
                },
                {
                    "mask_id": "MASK_026",
                    "expected": "on",
                    "classified": "off",
                    "matched": False,
                    "confidence": 0.98,
                },
            ],
        }
        decision = decidir_analise_display_f3(analysis, reference_gate=False)
        self.assertEqual(DISPLAY_AUTO_DECISION_NG, decision["decision"])
        self.assertTrue(decision["confirmed_ng"])
        self.assertEqual("MASK_026", decision["failed_mask_id"])

    def test_h1_continua_sem_ng_automatico(self):
        analysis = {
            "ready": True,
            "approved": False,
            "mask_results": [
                {
                    "mask_id": "MASK_008",
                    "expected": "on",
                    "classified": "on",
                    "matched": True,
                    "confidence": 0.99,
                },
                {
                    "mask_id": "MASK_011",
                    "expected": "on",
                    "classified": "off",
                    "matched": False,
                    "confidence": 0.98,
                },
            ],
        }
        decision = decidir_analise_display_f3(analysis, reference_gate=True)
        self.assertEqual(DISPLAY_AUTO_DECISION_SEARCHING, decision["decision"])
        self.assertFalse(decision["confirmed_ng"])

    def test_instalacao_estrita_e_a_ultima_autoridade_de_analisador(self):
        source = Path("src/platform/raspberry_pi3_production_app.py").read_text(
            encoding="utf-8"
        )
        exact_call = source.index("instalar_gabarito_exato_checks_display_f3()")
        fast_gate_call = source.index("instalar_gate_rapido_check_esperado_display_f3()")
        strict_call = source.index(
            "instalar_conformidade_estrita_mascaras_display_f3()"
        )
        self.assertLess(exact_call, fast_gate_call)
        self.assertLess(fast_gate_call, strict_call)

    def test_sonda_positiva_tambem_recebe_analisador_estrito(self):
        source = Path(
            "src/platform/display_f3_strict_mask_conformity.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "trace_module.F3ExactCheckTemplateAnalyzer = F3StrictMaskConformityAnalyzer",
            source,
        )
        self.assertIn(
            "probe_module.LearnedDisplayAutomaticCheckAnalyzer",
            source,
        )

    def test_overlay_e_status_expoem_a_mascara_ng(self):
        source = Path(
            "src/platform/display_f3_strict_mask_conformity.py"
        ).read_text(encoding="utf-8")
        self.assertIn('f"NG {mask_id}"', source)
        self.assertIn('f" • FALHA {first_id}: {expected}→{classified}"', source)
        self.assertIn("AZUL FORTE: MÁSCARA NG", source)

    def test_modulo_estrito_nao_depende_do_f2(self):
        source = Path(
            "src/platform/display_f3_strict_mask_conformity.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("src.platform.f2_", source)
        self.assertNotIn("registrar_resultado_check_display_f3(", source)
        self.assertNotIn("concluir_check_display_f3(", source)


if __name__ == "__main__":
    import unittest

    unittest.main()
