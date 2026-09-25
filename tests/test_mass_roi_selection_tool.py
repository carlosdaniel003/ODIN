from __future__ import annotations

import inspect
import unittest

from src.models.led_selection import LedSelection
from src.platform.display_theme import aplicar_tema_arvore
from src.platform.freeform_segment_roi import FreeformSegmentDrawingMixin
from src.platform.fullscreen_led_selection import FullscreenLedSelectionMixin
from src.platform.mass_roi_selection_tool import MassRoiSelectionToolMixin
from src.platform.desktop_production_app import DesktopProductionApp
from src.platform.roi_toolbar_theme import eh_botao_ferramenta_roi


class FakeToolbarButton:
    def __init__(self, texto: str, ativo: bool):
        self._opcoes = {
            "background": "#D6A900" if ativo else "#182231",
            "foreground": "#111318" if ativo else "#DCE5EF",
            "activebackground": "#F5C518" if ativo else "#243246",
            "activeforeground": "#111318" if ativo else "#FFFFFF",
            "highlightbackground": "#122033",
            "highlightcolor": "#122033",
            "text": texto,
            "state": "normal",
        }
        self.bindings = {}

    def winfo_class(self):
        return "Button"

    def winfo_children(self):
        return ()

    def cget(self, opcao):
        if opcao not in self._opcoes:
            raise KeyError(opcao)
        return self._opcoes[opcao]

    def configure(self, **opcoes):
        self._opcoes.update(opcoes)

    def bind(self, sequence, callback, add=None):
        self.bindings[sequence] = callback


class MassRoiSelectionToolTests(unittest.TestCase):
    def test_perfil_final_inclui_ferramenta_na_ordem_cooperativa(self):
        mro = DesktopProductionApp.__mro__
        self.assertIn(MassRoiSelectionToolMixin, mro)
        self.assertLess(mro.index(FreeformSegmentDrawingMixin), mro.index(MassRoiSelectionToolMixin))
        self.assertLess(mro.index(MassRoiSelectionToolMixin), mro.index(FullscreenLedSelectionMixin))

    def test_toolbar_expoe_selecao_em_massa_e_destaque_amarelo(self):
        fonte = inspect.getsource(MassRoiSelectionToolMixin)
        self.assertIn("▣ Seleção em massa", fonte)
        self.assertIn('bg="#D6A900" if ativo', fonte)
        self.assertIn("_botao_tipo_roi_segmento", fonte)
        self.assertIn("_botao_tipo_roi_circulo", fonte)

    def test_tema_nao_apaga_amarelo_da_ferramenta_ativa(self):
        textos = (
            "▰ Segmento",
            "● Círculo",
            "✎ Segmento por pontos",
            "▣ Seleção em massa",
        )
        for texto in textos:
            with self.subTest(texto=texto):
                self.assertTrue(eh_botao_ferramenta_roi(texto))
                botao = FakeToolbarButton(texto, ativo=True)
                aplicar_tema_arvore(botao)
                self.assertEqual("#D6A900", botao._opcoes["background"])
                self.assertEqual("#111318", botao._opcoes["foreground"])
                self.assertNotIn("<Leave>", botao.bindings)
                self.assertNotIn("<Enter>", botao.bindings)

    def test_tema_preserva_estado_escuro_das_ferramentas_inativas(self):
        botao = FakeToolbarButton("▰ Segmento", ativo=False)
        aplicar_tema_arvore(botao)
        self.assertEqual("#182231", botao._opcoes["background"])
        self.assertEqual("#DCE5EF", botao._opcoes["foreground"])

    def test_modo_massa_forca_caminho_de_marquee_sem_exigir_shift(self):
        fonte = inspect.getsource(MassRoiSelectionToolMixin.evento_clique_esquerdo)
        self.assertIn("SHIFT_MASK", fonte)
        self.assertIn("evento.state = estado_original | SHIFT_MASK", fonte)

    def test_clique_simples_no_vazio_nao_cria_roi_quando_massa_ativa(self):
        fonte = inspect.getsource(MassRoiSelectionToolMixin._evento_soltar_roi)
        self.assertIn('modo_antes == "pending_marquee"', fonte)
        self.assertIn("self._area_roi_ids = set()", fonte)
        self.assertNotIn("_evento_clique_original", fonte)

    def test_rotacao_em_massa_gira_centros_em_torno_do_grupo(self):
        ferramenta = object.__new__(MassRoiSelectionToolMixin)
        ferramenta._area_roi_mode = "rotate"
        ferramenta._area_roi_snapshot_selected = [
            LedSelection(id="A", centro_x=40, centro_y=50, raio=5),
            LedSelection(id="B", centro_x=60, centro_y=50, raio=5),
        ]
        ferramenta._area_roi_bbox_snapshot = (35, 45, 65, 55)
        ferramenta._area_roi_press_image = (50, 20)
        ferramenta.largura_original = 200
        ferramenta.altura_original = 200

        resultado = ferramenta._transformar_handle(80, 50)
        centros = {(led.centro_x, led.centro_y) for led in resultado}
        self.assertEqual({(50, 40), (50, 60)}, centros)

    def test_rotacao_em_massa_preserva_segmento_e_gira_angulo(self):
        ferramenta = object.__new__(MassRoiSelectionToolMixin)
        ferramenta._area_roi_mode = "rotate"
        ferramenta._area_roi_snapshot_selected = [
            LedSelection(
                id="S1",
                centro_x=40,
                centro_y=50,
                raio=10,
                tipo_roi="segmento",
                largura=20,
                altura=8,
                angulo=0,
            ),
            LedSelection(
                id="S2",
                centro_x=60,
                centro_y=50,
                raio=10,
                tipo_roi="segmento",
                largura=20,
                altura=8,
                angulo=15,
            ),
        ]
        ferramenta._area_roi_bbox_snapshot = (30, 40, 70, 60)
        ferramenta._area_roi_press_image = (50, 20)
        ferramenta.largura_original = 200
        ferramenta.altura_original = 200

        resultado = ferramenta._transformar_handle(80, 50)
        self.assertAlmostEqual(90.0, resultado[0].angulo, places=5)
        self.assertAlmostEqual(105.0, resultado[1].angulo, places=5)

    def test_individual_continua_delegado_quando_massa_desativada(self):
        fonte = inspect.getsource(MassRoiSelectionToolMixin.evento_clique_esquerdo)
        self.assertIn("return super().evento_clique_esquerdo(evento)", fonte)


if __name__ == "__main__":
    unittest.main()
