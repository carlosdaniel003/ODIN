import unittest

from src.platform.display_theme import (
    DISPLAY_BLUE,
    DISPLAY_BLUE_DARK,
    DISPLAY_BLUE_LIGHT,
    DISPLAY_BORDER,
    DISPLAY_DANGER_DARK,
    DISPLAY_DANGER_LIGHT,
    DISPLAY_DARK,
    DISPLAY_DARK_ALT,
    DISPLAY_DARK_CARD,
    DISPLAY_DARK_RAISED,
    DISPLAY_INK,
    DISPLAY_PURPLE_DARK,
    DISPLAY_PURPLE_LIGHT,
    DISPLAY_WHITE,
    DISPLAY_YELLOW,
    DISPLAY_YELLOW_DARK,
    DisplayThemeMixin,
    aplicar_tema_arvore,
    classificar_acao_botao,
    instalar_paleta_display,
    mapear_cor_display,
    obter_estilo_botao_display,
)
from src.platform.desktop_production_app import (
    DesktopProductionApp,
)
from src.ui.main_window import ODINView
from src.ui.desktop_operation_window import DesktopOperationWindow


class FakeWidget:
    def __init__(self, classe="Frame", opcoes=None, filhos=None):
        self._classe = classe
        self._opcoes = dict(opcoes or {})
        self._filhos = list(filhos or ())
        self.bindings = {}

    def winfo_class(self):
        return self._classe

    def winfo_children(self):
        return tuple(self._filhos)

    def cget(self, opcao):
        if opcao not in self._opcoes:
            raise KeyError(opcao)
        return self._opcoes[opcao]

    def configure(self, **opcoes):
        self._opcoes.update(opcoes)

    def bind(self, sequence, callback, add=None):
        self.bindings[sequence] = callback


class DisplayThemeTests(unittest.TestCase):
    def test_cores_principais_sao_exatamente_as_solicitadas(self):
        self.assertEqual("#F5C518", DISPLAY_YELLOW)
        self.assertEqual("#2596BE", DISPLAY_BLUE)
        self.assertEqual("#0B0F14", DISPLAY_DARK)

    def test_fundos_sao_escuros_e_bordas_sao_discretas(self):
        self.assertEqual(
            DISPLAY_DARK,
            mapear_cor_display("background", "#030712"),
        )
        self.assertEqual(
            DISPLAY_DARK_CARD,
            mapear_cor_display("background", "#07111F"),
        )
        self.assertEqual(
            DISPLAY_DARK_RAISED,
            mapear_cor_display("background", "#0B1626"),
        )
        self.assertEqual(
            DISPLAY_BORDER,
            mapear_cor_display("highlightbackground", "#122033"),
        )
        self.assertEqual(
            DISPLAY_BLUE_LIGHT,
            mapear_cor_display("foreground", "#38BDF8"),
        )

    def test_nao_substitui_cores_semanticas_ok_e_ng(self):
        self.assertEqual(
            "#16A34A",
            mapear_cor_display("background", "#16A34A"),
        )
        self.assertEqual(
            "#DC2626",
            mapear_cor_display("background", "#DC2626"),
        )

    def test_classifica_acoes_com_hierarquia_visual(self):
        self.assertEqual("primary", classificar_acao_botao("Analisar"))
        self.assertEqual("primary", classificar_acao_botao("PRODUÇÃO  F2"))
        self.assertEqual("info", classificar_acao_botao("Tela ao vivo"))
        self.assertEqual(
            "selection",
            classificar_acao_botao("Selecionar LEDs"),
        )
        self.assertEqual(
            "danger",
            classificar_acao_botao("Limpar seleção"),
        )
        self.assertEqual("neutral", classificar_acao_botao("Fechar"))

    def test_estilos_de_acao_usam_cores_distintas(self):
        principal = obter_estilo_botao_display("Analisar")
        informacao = obter_estilo_botao_display("Tela ao vivo")
        selecao = obter_estilo_botao_display("Selecionar LEDs")
        perigo = obter_estilo_botao_display("Remover")

        self.assertEqual(DISPLAY_YELLOW_DARK, principal.background)
        self.assertEqual(DISPLAY_INK, principal.foreground)
        self.assertEqual(DISPLAY_BLUE_DARK, informacao.background)
        self.assertEqual(DISPLAY_BLUE_LIGHT, informacao.foreground)
        self.assertEqual(DISPLAY_PURPLE_DARK, selecao.background)
        self.assertEqual(DISPLAY_PURPLE_LIGHT, selecao.foreground)
        self.assertEqual(DISPLAY_DANGER_DARK, perigo.background)
        self.assertEqual(DISPLAY_DANGER_LIGHT, perigo.foreground)

    def test_botao_recebe_estilo_e_hover_conforme_a_acao(self):
        botao = FakeWidget(
            classe="Button",
            opcoes={
                "background": "#16A34A",
                "foreground": "#FFFFFF",
                "activebackground": "#15803D",
                "activeforeground": "#FFFFFF",
                "highlightbackground": "#122033",
                "highlightcolor": "#122033",
                "text": "PRODUÇÃO  F2",
                "state": "normal",
            },
        )

        aplicar_tema_arvore(botao)

        self.assertEqual(DISPLAY_YELLOW_DARK, botao._opcoes["background"])
        self.assertEqual(DISPLAY_INK, botao._opcoes["foreground"])
        self.assertEqual(DISPLAY_YELLOW, botao._opcoes["activebackground"])
        self.assertEqual(1, botao._opcoes["highlightthickness"])
        self.assertIn("<Enter>", botao.bindings)
        self.assertIn("<Leave>", botao.bindings)

    def test_arvore_tematiza_janela_e_legenda_ng(self):
        legenda = FakeWidget(
            classe="Label",
            opcoes={
                "background": "#07111F",
                "foreground": "#2563EB",
                "text": "CÍRCULO AZUL: LED APAGADO",
            },
        )
        raiz = FakeWidget(
            classe="Toplevel",
            opcoes={
                "background": "#020617",
            },
            filhos=[legenda],
        )

        aplicar_tema_arvore(raiz)

        self.assertEqual(DISPLAY_DARK, raiz._opcoes["background"])
        self.assertEqual(DISPLAY_DARK_CARD, legenda._opcoes["background"])
        self.assertEqual(DISPLAY_BLUE_LIGHT, legenda._opcoes["foreground"])
        self.assertEqual(
            "CÍRCULO VERMELHO: LED APAGADO",
            legenda._opcoes["text"],
        )

    def test_instalacao_atualiza_constantes_das_telas(self):
        instalar_paleta_display()

        self.assertEqual(DISPLAY_DARK, ODINView.COR_FUNDO_APP)
        self.assertEqual(DISPLAY_DARK_ALT, ODINView.COR_TOPO)
        self.assertEqual(DISPLAY_DARK_CARD, ODINView.COR_CARD)
        self.assertEqual(DISPLAY_DARK_RAISED, ODINView.COR_CARD_2)
        self.assertEqual(DISPLAY_BORDER, ODINView.COR_BORDA)
        self.assertEqual(DISPLAY_BLUE_LIGHT, ODINView.COR_AZUL)
        self.assertEqual(DISPLAY_YELLOW, ODINView.COR_AMARELO)
        self.assertEqual(DISPLAY_YELLOW, ODINView.COR_VERDE_CLARO)
        self.assertEqual(DISPLAY_WHITE, ODINView.COR_TEXTO)
        self.assertEqual(
            DISPLAY_DARK,
            DesktopOperationWindow.PREVIEW_BACKGROUND,
        )
        self.assertEqual(
            DISPLAY_BORDER,
            DesktopOperationWindow.PREVIEW_BORDER,
        )

    def test_perfil_display_inclui_mixin_de_tema(self):
        self.assertIn(DisplayThemeMixin, DesktopProductionApp.__mro__)


if __name__ == "__main__":
    unittest.main()
