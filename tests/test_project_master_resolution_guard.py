import unittest

from src.platform.project_master_resolution_guard import (
    ProjectMasterResolutionGuardMixin,
)
from src.platform.desktop_production_app import DesktopProductionApp
from src.platform.project_master_resolution import ProjectMasterResolutionMixin


class FakeBase:
    def __init__(self):
        self.events = []
        self.largura_original = 1920
        self.altura_original = 1080
        self.selected = "PLACA 640"
        self.real_resolution = (640, 480)
        self._resolucao_mestra_projeto_ativa = (640, 480)

    def _selecionar_projeto_led_existente(self, _projetos):
        self.events.append("dialogo_confirmado")
        return self.selected

    def _aplicar_resolucao_mestra_projeto(
        self,
        projeto,
        reiniciar_se_necessario=True,
    ):
        self.events.append(
            ("resolucao_aplicada", projeto, reiniciar_se_necessario)
        )
        return True

    def _atualizar_resolucao_mestra_projeto_ativa(self):
        return self._resolucao_mestra_projeto_ativa

    def _obter_resolucao_edicao_atual(self):
        return self.real_resolution

    def _salvar_leds_no_projeto(self, nome_projeto, **_kwargs):
        self.events.append(
            (
                "salvamento_base",
                nome_projeto,
                self.largura_original,
                self.altura_original,
            )
        )
        return True

    def salvar_configuracoes_sistema(
        self,
        salvar_resultados_analise,
        raio_configurado_px=None,
        configuracoes_camera=None,
    ):
        self.events.append(
            (
                "config_salva",
                bool(salvar_resultados_analise),
                raio_configurado_px,
                dict(configuracoes_camera or {}),
            )
        )


class GuardFake(ProjectMasterResolutionGuardMixin, FakeBase):
    pass


class ProjectMasterResolutionGuardTests(unittest.TestCase):
    def test_resolucao_e_aplicada_antes_do_gerenciador_receber_projeto(self):
        app = GuardFake()

        escolhido = app._selecionar_projeto_led_existente(["PLACA 640"])

        self.assertEqual("PLACA 640", escolhido)
        self.assertEqual("dialogo_confirmado", app.events[0])
        self.assertEqual(
            ("resolucao_aplicada", "PLACA 640", True),
            app.events[1],
        )

    def test_cancelar_nao_aplica_resolucao(self):
        app = GuardFake()
        app.selected = None

        self.assertIsNone(app._selecionar_projeto_led_existente(["PLACA 640"]))
        self.assertEqual(["dialogo_confirmado"], app.events)

    def test_salvar_reafirma_base_com_resolucao_real(self):
        app = GuardFake()
        app.real_resolution = (640, 480)

        self.assertTrue(app._salvar_leds_no_projeto("PLACA 640"))

        self.assertEqual(640, app.largura_original)
        self.assertEqual(480, app.altura_original)
        self.assertEqual(
            ("salvamento_base", "PLACA 640", 640, 480),
            app.events[-1],
        )

    def test_configuracoes_nao_conseguem_substituir_resolucao_mestra(self):
        app = GuardFake()
        app.salvar_configuracoes_sistema(
            True,
            raio_configurado_px=22,
            configuracoes_camera={
                "resolution_mode": "custom",
                "width": 1920,
                "height": 1080,
                "gain_enabled": True,
                "gain": 17,
            },
        )

        evento = app.events[-1]
        config = evento[3]
        self.assertEqual("config_salva", evento[0])
        self.assertEqual("custom", config["resolution_mode"])
        self.assertEqual((640, 480), (config["width"], config["height"]))
        self.assertTrue(config["gain_enabled"])
        self.assertEqual(17, config["gain"])

    def test_mro_final_coloca_guard_antes_da_resolucao_mestra(self):
        mro = DesktopProductionApp.__mro__
        self.assertIn(ProjectMasterResolutionGuardMixin, mro)
        self.assertIn(ProjectMasterResolutionMixin, mro)
        self.assertLess(
            mro.index(ProjectMasterResolutionGuardMixin),
            mro.index(ProjectMasterResolutionMixin),
        )


if __name__ == "__main__":
    unittest.main()
