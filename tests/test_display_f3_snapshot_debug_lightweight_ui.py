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

    def test_janela_debug_usa_somente_o_print_capturado(self):
        source = inspect.getsource(debug_ui._open_lightweight_snapshot_debug)
        self.assertIn("_screen_capture_photo(window, top)", source)
        self.assertIn("PRINT DA TELA ANALISADA", source)
        self.assertNotIn("_frame_photo(", source)
        self.assertNotIn("_draw_debug_readout(", source)
        self.assertNotIn("renderizar_overlay_rois_display_f3", source)
        self.assertNotIn("camera_frame_atual", source)

    def test_debug_pode_abrir_enquanto_relatorio_esta_sendo_gerado(self):
        source = inspect.getsource(debug_ui._open_lightweight_snapshot_debug)
        self.assertNotIn("if not report:", source)
        self.assertIn("_refresh_lightweight_debug_state(window)", source)
        refresh = inspect.getsource(debug_ui._refresh_lightweight_debug_state)
        self.assertIn("_display_f3_debug_analysis_running", refresh)
        self.assertIn("GERANDO RELATÓRIO TÉCNICO", refresh)
        self.assertIn("_display_f3_manual_snapshot_report", refresh)

    def test_preview_e_derivada_exclusivamente_da_imagem_do_print(self):
        source = inspect.getsource(debug_ui._screen_capture_photo)
        self.assertIn("_display_f3_manual_screen_capture_image", source)
        self.assertIn('preview.save(buffer, format="PNG")', source)
        self.assertNotIn("cv2.", source)
        self.assertNotIn("camera_frame_atual", source)

    def test_rodape_tem_copiar_debug_copiar_imagem_e_fechar(self):
        source = inspect.getsource(debug_ui._open_lightweight_snapshot_debug)
        self.assertIn('text="COPIAR DEBUG"', source)
        self.assertIn('text="COPIAR IMAGEM"', source)
        self.assertIn('text="FECHAR"', source)
        self.assertIn("_schedule_copy_report", source)
        self.assertIn("_schedule_copy_image", source)

    def test_copiar_imagem_windows_publica_cf_dib(self):
        source = inspect.getsource(debug_ui._copy_screen_image_windows)
        self.assertIn("CF_DIB = 8", source)
        self.assertIn("GlobalAlloc", source)
        self.assertIn("GlobalLock", source)
        self.assertIn("SetClipboardData", source)
        self.assertIn('image.convert("RGB").save', source)

    def test_copiar_imagem_nao_windows_publica_png_nativo(self):
        source = inspect.getsource(debug_ui._copy_screen_image_to_clipboard)
        self.assertIn('sys.platform.startswith("win")', source)
        self.assertIn('"image/png"', source)
        self.assertNotIn("base64.b64encode", source)

    def test_copias_nao_reentram_sincronamente_no_event_loop(self):
        source = "\n".join((
            inspect.getsource(debug_ui._schedule_copy_report),
            inspect.getsource(debug_ui._schedule_copy_image),
        ))
        self.assertNotIn(".update(", source)
        self.assertNotIn("update_idletasks(", source)
        self.assertIn("COPY_START_DELAY_MS", source)
        self.assertIn("top.after(COPY_START_DELAY_MS", source)

    def test_relatorio_visual_continua_diagnostico_e_nao_produtivo(self):
        source = inspect.getsource(debug_ui._visual_report_block)
        self.assertIn("NÃO participa de OK/NG", source)
        self.assertIn("score_margin", source)
        self.assertIn("roi=", source)

    def test_instalacao_expoe_refresh_sem_novo_scheduler(self):
        source = inspect.getsource(debug_ui.instalar_debug_snapshot_leve_display_f3)
        self.assertIn("refresh_f3_snapshot_debug_state", source)
        self.assertNotIn("threading", source)
        self.assertNotIn("while True", source)

    def test_modulo_permanece_isolado_do_f2(self):
        source = inspect.getsource(debug_ui).lower()
        self.assertNotIn("src.platform.f2_", source)


if __name__ == "__main__":
    unittest.main()
