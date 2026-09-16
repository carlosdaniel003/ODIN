from __future__ import annotations

import inspect
import unittest

import src.platform.f2_object_tracking_settings_placeholder as placeholder


class F2ObjectTrackingSettingsPlaceholderTests(unittest.TestCase):
    def test_texto_da_opcao_e_exclusivo_do_f2(self):
        self.assertEqual(
            "Ativar rastreamento automático de objetos",
            placeholder.F2_OBJECT_TRACKING_OPTION_TEXT,
        )
        self.assertEqual(
            "Produção F2",
            placeholder.F2_OBJECT_TRACKING_SECTION_TITLE,
        )
        self.assertIn("somente ao modo Produção F2", placeholder.F2_OBJECT_TRACKING_NOT_IMPLEMENTED_TEXT)

    def test_placeholder_fica_desabilitado_ate_funcionalidade_existir(self):
        source = inspect.getsource(
            placeholder.adicionar_opcao_rastreamento_automatico_f2
        )
        self.assertIn("state=tk.DISABLED", source)
        self.assertIn("F2_OBJECT_TRACKING_NOT_IMPLEMENTED_TEXT", source)

    def test_opcao_entra_no_card_f2_existente(self):
        source = inspect.getsource(placeholder)
        self.assertIn("_encontrar_card_producao_f2", source)
        self.assertIn("f2_auto_module._add_auto_analysis_setting", source)
        self.assertNotIn("ODINView.abrir_janela_configuracoes", source)
        self.assertNotIn("_encontrar_conteudo_sistema", source)

    def test_placeholder_nao_conecta_runtime_nem_persistencia(self):
        source = inspect.getsource(
            placeholder.adicionar_opcao_rastreamento_automatico_f2
        )
        self.assertNotIn("callback_salvar", source)
        self.assertNotIn("_process_display_auto_check", source)
        self.assertNotIn("display_f3_", source)

    def test_instalador_e_idempotente(self):
        source = inspect.getsource(
            placeholder.instalar_opcao_rastreamento_automatico_f2
        )
        self.assertIn(
            "_odin_f2_object_tracking_settings_placeholder",
            source,
        )


if __name__ == "__main__":
    unittest.main()
