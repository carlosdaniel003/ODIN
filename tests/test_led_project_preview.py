import inspect
import json
import tempfile
import unittest
from pathlib import Path

from src.infra.config_repository import ConfigRepository
from src.models.led_selection import LedSelection
from src.platform.led_project_preview import (
    LedProjectPreviewMixin,
    calcular_transformacao_preview,
)
from src.platform.led_project_preview_store import (
    CHAVE_PREVIEWS_PROJETO,
    definir_preview_projeto_led,
    instalar_preview_projeto_led_store,
    obter_preview_projeto_led,
)
from src.platform.desktop_production_app import DesktopProductionApp


class LedProjectPreviewMathTests(unittest.TestCase):
    def test_preview_preserva_proporcao_da_base_1080p(self):
        led = LedSelection(
            id="SEG_001",
            centro_x=960,
            centro_y=540,
            raio=20,
        )
        escala, offset_x, offset_y, largura, altura = calcular_transformacao_preview(
            [led],
            largura_canvas=220,
            altura_canvas=150,
            largura_base=1920,
            altura_base=1080,
        )

        self.assertAlmostEqual(200.0 / 1920.0, escala, places=6)
        self.assertAlmostEqual(10.0, offset_x, places=4)
        self.assertAlmostEqual(18.75, offset_y, places=4)
        self.assertEqual(1920, largura)
        self.assertEqual(1080, altura)

    def test_roi_fora_da_base_expande_preview_sem_cortar(self):
        led = LedSelection(
            id="SEG_FORA",
            centro_x=2050,
            centro_y=1180,
            raio=30,
        )
        _escala, _offset_x, _offset_y, largura, altura = calcular_transformacao_preview(
            [led],
            largura_canvas=220,
            altura_canvas=150,
            largura_base=1920,
            altura_base=1080,
        )

        self.assertGreaterEqual(largura, 2090)
        self.assertGreaterEqual(altura, 1220)

    def test_segmento_rotacionado_participa_dos_limites(self):
        led = LedSelection(
            id="SEG_ROT",
            centro_x=1900,
            centro_y=1040,
            raio=10,
            tipo_roi="segmento",
            largura=180,
            altura=30,
            angulo=45,
        )
        _escala, _offset_x, _offset_y, largura, altura = calcular_transformacao_preview(
            [led],
            largura_canvas=220,
            altura_canvas=150,
            largura_base=1920,
            altura_base=1080,
        )

        self.assertGreater(largura, 1920)
        self.assertGreater(altura, 1080)


class LedProjectPreviewStoreTests(unittest.TestCase):
    def test_snapshot_fica_vinculado_ao_nome_do_projeto(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "config.json"
            arquivo.write_text(
                json.dumps(
                    {
                        "project": "ODIN",
                        "led_projects": {
                            "DISPLAY_7": {
                                "name": "DISPLAY_7",
                                "fixed_leds": [],
                                "references": {},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            repository = ConfigRepository(arquivo)

            self.assertTrue(
                definir_preview_projeto_led(
                    repository,
                    "DISPLAY_7",
                    "/tmp/display_7.jpg",
                )
            )
            dados = obter_preview_projeto_led(repository, "DISPLAY_7")
            self.assertEqual("/tmp/display_7.jpg", dados["image_path"])
            configuracao = repository.carregar_configuracao_existente_sem_alerta()
            self.assertIn(CHAVE_PREVIEWS_PROJETO, configuracao)

    def test_store_instala_acompanhamento_de_renomear_e_remover(self):
        fonte = inspect.getsource(instalar_preview_projeto_led_store)
        self.assertIn("renomear_projeto_led_com_preview", fonte)
        self.assertIn("remover_projeto_led_com_preview", fonte)
        self.assertIn("previews[novo] = previews.pop(atual)", fonte)
        self.assertIn("previews.pop(nome, None)", fonte)


class LedProjectPreviewIntegrationTests(unittest.TestCase):
    def test_perfil_display_inclui_mixin_de_preview(self):
        mro = DesktopProductionApp.__mro__
        self.assertIn(LedProjectPreviewMixin, mro)

    def test_preview_intercepta_seletor_e_delega_fluxo_existente(self):
        fonte = inspect.getsource(
            LedProjectPreviewMixin._selecionar_projeto_led_existente
        )
        self.assertIn("_instalar_preview_gerenciador_leds", fonte)
        self.assertIn("super()._selecionar_projeto_led_existente", fonte)

    def test_salvar_projeto_anexa_snapshot_real_sem_mudar_fluxo(self):
        fonte = inspect.getsource(LedProjectPreviewMixin._salvar_leds_no_projeto)
        self.assertIn("super()._salvar_leds_no_projeto", fonte)
        self.assertIn("_anexar_snapshot_real_ao_projeto", fonte)

        fonte_snapshot = inspect.getsource(
            LedProjectPreviewMixin._anexar_snapshot_real_ao_projeto
        )
        self.assertIn("cv2.imwrite", fonte_snapshot)
        self.assertIn("definir_preview_projeto_led", fonte_snapshot)

    def test_preview_usa_imagem_real_com_rois_desenhadas_por_cima(self):
        fonte = inspect.getsource(LedProjectPreviewMixin._desenhar_preview_projeto)
        pos_imagem = fonte.index("canvas.create_image")
        pos_segmento = fonte.index("canvas.create_polygon")
        pos_circulo = fonte.index("canvas.create_oval")
        self.assertLess(pos_imagem, pos_segmento)
        self.assertLess(pos_imagem, pos_circulo)
        self.assertIn('outline="#FACC15"', fonte)
        self.assertIn('fill=""', fonte)

    def test_projeto_antigo_sem_snapshot_pede_novo_salvamento(self):
        fonte = inspect.getsource(LedProjectPreviewMixin._desenhar_preview_projeto)
        self.assertIn("SEM IMAGEM REAL", fonte)
        self.assertIn("Salve os LEDs deste projeto", fonte)

    def test_preview_acompanha_selecao_sem_mudar_lista(self):
        fonte = inspect.getsource(
            LedProjectPreviewMixin._instalar_preview_gerenciador_leds
        )
        self.assertIn('"<<ListboxSelect>>"', fonte)
        self.assertIn("acompanhar_selecao", fonte)
        self.assertIn("carregar_leds_fixos(projeto=nome)", fonte)


if __name__ == "__main__":
    unittest.main()
