import inspect
import unittest

import src.platform.display_f3_snapshot_debug_lightweight_ui as debug_ui


class DisplayF3SnapshotDebugLightweightUiTests(unittest.TestCase):
    def test_debug_nao_renderiza_relatorio_completo(self):
        source = inspect.getsource(debug_ui)
        self.assertNotIn("tk.Text(", source)
        self.assertNotIn("Scrollbar(", source)
        self.assertNotIn("text.insert(", source)
        self.assertIn("COPIAR DEBUG", source)
        self.assertIn("_display_f3_manual_snapshot_report", source)

    def test_debug_maximiza_uma_vez_depois_da_montagem(self):
        source = inspect.getsource(debug_ui)
        self.assertNotIn("maximizar_janela_workspace_f3(top)", source)
        self.assertIn("after_idle", source)
        self.assertIn("maximizar_janela_workspace_f3(current)", source)
        self.assertIn("wraplength", source)
        self.assertIn("<Configure>", source)

    def test_copia_nao_reentra_sincronamente_no_event_loop(self):
        source = "\n".join(
            (
                inspect.getsource(debug_ui._copy_report),
                inspect.getsource(debug_ui._schedule_copy_report),
            )
        )
        self.assertNotIn(".update(", source)
        self.assertNotIn("update_idletasks(", source)
        self.assertIn("COPY_START_DELAY_MS", source)
        self.assertIn("top.after(COPY_START_DELAY_MS, do_copy)", source)

    def test_copia_tem_feedback_visual_de_inicio_e_sucesso(self):
        source = inspect.getsource(debug_ui)
        for text in (
            "COPIANDO DEBUG...",
            "COPIANDO...",
            "DEBUG COPIADO COM SUCESSO",
            "COPIADO",
            "NÃO FOI POSSÍVEL COPIAR O DEBUG",
        ):
            self.assertIn(text, source)
        self.assertGreater(debug_ui.COPY_FEEDBACK_RESET_MS, 0)

    def test_mensagem_explica_o_conteudo_disponivel(self):
        summary = debug_ui.DEBUG_SUMMARY.lower()
        for term in (
            "análise visual",
            "estado físico",
            "scores",
            "check",
            "máscaras",
            "aceso/apagado",
            "energia",
        ):
            self.assertIn(term, summary)

    def test_analise_visual_usa_o_mesmo_frame_congelado(self):
        source = inspect.getsource(debug_ui._install_visual_analysis_snapshot_extension)
        self.assertIn("original_freeze", source)
        self.assertIn("_display_f3_manual_snapshot_frozen_frame = frame", source)
        self.assertIn("frame = getattr(app, \"_display_f3_manual_snapshot_frozen_frame\"", source)
        self.assertNotIn("camera_frame_atual", source)

    def test_snapshot_visual_declara_que_nao_participa_do_julgamento(self):
        source = inspect.getsource(debug_ui._build_visual_analysis_snapshot)
        self.assertIn('"informational_only": True', source)
        self.assertIn('"affects_result": False', source)
        self.assertIn('"uses_masks": False', source)
        self.assertIn('"uses_check_state": False', source)
        self.assertIn("F3_OPERATIONAL_PHYSICAL_MARGIN", source)

    def test_debug_exibe_frame_e_evidencias_da_analise_visual(self):
        source = inspect.getsource(debug_ui._open_lightweight_snapshot_debug)
        self.assertIn("FRAME CONGELADO • MESMA CÓPIA USADA NA ANÁLISE", source)
        self.assertIn("ANÁLISE VISUAL • SOMENTE DIAGNÓSTICO", source)
        self.assertIn("PLACA FORA DO SUPORTE", source)
        self.assertIn("PLACA DESLIGADA NO SUPORTE", source)
        self.assertIn("Margem entre referências", source)

    def test_relatorio_copiado_recebe_bloco_visual_do_mesmo_frame(self):
        source = inspect.getsource(debug_ui._visual_report_block)
        self.assertIn("[ANÁLISE VISUAL INFORMATIVA - MESMO FRAME CONGELADO]", source)
        self.assertIn("NÃO participa de OK/NG", source)
        self.assertIn("score_margin", source)
        self.assertIn("minimum_margin", source)
        self.assertIn("roi=", source)

    def test_modulo_permanece_isolado_do_f2(self):
        source = inspect.getsource(debug_ui).lower()
        self.assertNotIn("f2_", source)


if __name__ == "__main__":
    unittest.main()
