from __future__ import annotations

import inspect
import unittest

import src.platform.display_f3_current_check_status_sync as sync_module
import src.platform.display_f3_visual_analysis_relative_fallback as fallback_module
import src.platform.display_reference_roi as reference_regions_module


class DisplayF3VisualAnalysisRelativeFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reference_regions_module.instalar_roi_referencias_display_f3()

    @staticmethod
    def _candidate(
        score: float,
        threshold: float = 0.72,
        *,
        kind: str = "",
        name: str = "",
        check_id: str = "",
    ):
        return {
            "score": score,
            "threshold": threshold,
            "matched": score >= threshold,
            "kind": kind,
            "name": name,
            "check_id": check_id,
        }

    def test_debug_real_classifica_placa_desligada_por_separacao_relativa(self):
        decision = fallback_module.resolver_analise_visual_relativa_f3(
            self._candidate(0.0888),
            self._candidate(0.5542),
        )
        self.assertEqual("board_off", decision["result_kind"])
        self.assertEqual("board_off", decision["selected_reference"])
        self.assertEqual("relative_fallback", decision["decision_mode"])
        self.assertTrue(decision["relative_fallback"])
        self.assertGreater(decision["score_margin"], 0.46)
        self.assertGreater(decision["score_ratio"], 6.0)

    def test_fallback_relativo_funciona_tambem_para_suporte_vazio(self):
        decision = fallback_module.resolver_analise_visual_relativa_f3(
            self._candidate(0.57),
            self._candidate(0.17),
        )
        self.assertEqual("empty_support", decision["result_kind"])
        self.assertEqual("relative_fallback", decision["decision_mode"])
        self.assertTrue(decision["relative_fallback"])

    def test_scores_baixos_e_proximos_continuam_nao_identificados(self):
        decision = fallback_module.resolver_analise_visual_relativa_f3(
            self._candidate(0.39),
            self._candidate(0.34),
        )
        self.assertEqual("unidentified", decision["result_kind"])
        self.assertIsNone(decision["selected_reference"])
        self.assertFalse(decision["relative_fallback"])

    def test_score_melhor_ainda_precisa_ter_forca_minima(self):
        decision = fallback_module.resolver_analise_visual_relativa_f3(
            self._candidate(0.08),
            self._candidate(0.31),
        )
        self.assertEqual("unidentified", decision["result_kind"])
        self.assertEqual("insufficient_relative_separation", decision["decision_mode"])

    def test_duas_referencias_absolutas_quase_empatadas_ficam_ambiguas(self):
        decision = fallback_module.resolver_analise_visual_relativa_f3(
            self._candidate(0.74),
            self._candidate(0.73),
        )
        self.assertEqual("ambiguous", decision["result_kind"])
        self.assertIsNone(decision["selected_reference"])
        self.assertFalse(decision["relative_fallback"])

    def test_status_informa_quando_decisao_veio_do_fallback_relativo(self):
        decision = fallback_module.resolver_analise_visual_relativa_f3(
            self._candidate(0.0888),
            self._candidate(0.5542),
        )
        text, _color = fallback_module._visual_text_from_decision(decision)
        self.assertIn("PLACA DESLIGADA NO SUPORTE", text)
        self.assertIn("55%", text)
        self.assertIn("comparação relativa", text)

    def test_placa_desligada_vence_checks_no_frame_real_do_debug(self):
        decision = fallback_module.resolver_analise_visual_candidatos_f3(
            {
                "empty_support": self._candidate(0.1690, kind="empty_support"),
                "board_off": self._candidate(0.5822, kind="board_off"),
                "check:CHECK_002": self._candidate(
                    0.4016, kind="check", name="BLUE", check_id="CHECK_002"
                ),
                "check:CHECK_001": self._candidate(
                    0.3990, kind="check", name="H1", check_id="CHECK_001"
                ),
                "check:CHECK_004": self._candidate(
                    0.3795, kind="check", name="USB", check_id="CHECK_004"
                ),
                "check:CHECK_003": self._candidate(
                    0.3612, kind="check", name="AUX", check_id="CHECK_003"
                ),
            }
        )
        self.assertEqual("board_off", decision["result_kind"])
        self.assertEqual("board_off", decision["selected_reference"])
        self.assertEqual("relative_fallback", decision["decision_mode"])
        self.assertGreater(decision["score_margin"], 0.18)

    def test_check_pode_ser_identificado_pelas_regioes_das_mascaras(self):
        decision = fallback_module.resolver_analise_visual_candidatos_f3(
            {
                "empty_support": self._candidate(0.22, kind="empty_support"),
                "board_off": self._candidate(0.48, kind="board_off"),
                "check:CHECK_001": self._candidate(
                    0.86, kind="check", name="H1", check_id="CHECK_001"
                ),
                "check:CHECK_002": self._candidate(
                    0.63, kind="check", name="BLUE", check_id="CHECK_002"
                ),
            }
        )
        self.assertEqual("check", decision["result_kind"])
        self.assertEqual("check:CHECK_001", decision["selected_reference"])
        self.assertEqual("CHECK_001", decision["check_id"])
        self.assertEqual("H1", decision["check_name"])
        self.assertEqual("absolute_threshold", decision["decision_mode"])
        text, _color = fallback_module._visual_text_from_decision(decision)
        self.assertIn("ANÁLISE VISUAL: CHECK H1", text)
        self.assertIn("86%", text)

    def test_checks_visualmente_quase_empatados_nao_inventam_um_vencedor(self):
        decision = fallback_module.resolver_analise_visual_candidatos_f3(
            {
                "board_off": self._candidate(0.44, kind="board_off"),
                "check:CHECK_001": self._candidate(
                    0.75, kind="check", name="H1", check_id="CHECK_001"
                ),
                "check:CHECK_002": self._candidate(
                    0.74, kind="check", name="BLUE", check_id="CHECK_002"
                ),
            }
        )
        self.assertEqual("ambiguous", decision["result_kind"])
        self.assertIsNone(decision["selected_reference"])

    def test_analise_visual_usa_regioes_das_mascaras_em_resolucao_cheia(self):
        source = inspect.getsource(reference_regions_module)
        self.assertIn("project_mask_regions_full_resolution", source)
        self.assertIn("criar_mascaras_roi", source)
        self.assertIn("_score_reference_full_roi = _score_exact_reference_by_masks", source)
        self.assertIn("mask_region_count", source)
        self.assertNotIn("SELECIONAR ÁREA", source)

    def test_camadas_continuam_informativas_sem_usar_estado_logico_do_check(self):
        fallback_source = inspect.getsource(fallback_module).lower()
        region_source = inspect.getsource(reference_regions_module).lower()
        for forbidden in (
            "src.platform.f2_",
            "registrar_resultado_check_display_f3(",
            "concluir_check_display_f3(",
            "descartar_placa_display_f3(",
        ):
            self.assertNotIn(forbidden, fallback_source)
            self.assertNotIn(forbidden, region_source)
        self.assertIn('"affects_result": false', fallback_source)
        self.assertIn('state["uses_masks"] = true', region_source)
        self.assertIn('state["uses_check_state"] = false', region_source)
        self.assertIn('"uses_check_references": true', fallback_source)

    def test_instalador_final_acopla_fallback_relativo(self):
        source = inspect.getsource(
            sync_module.instalar_sincronia_status_check_atual_display_f3
        )
        self.assertIn("instalar_fallback_relativo_analise_visual_display_f3", source)


if __name__ == "__main__":
    unittest.main()
