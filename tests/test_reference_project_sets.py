import json
import tempfile
import unittest
from pathlib import Path

from src.infra.config_repository import ConfigRepository
from src.models.led_selection import LedSelection
from src.platform.led_project_repository import instalar_repositorio_projetos_led
from src.platform.desktop_production_app import DesktopProductionApp
from src.platform.reference_capture import ReferenceCaptureMixin
from src.platform.reference_project_sets import (
    ProjectReferenceSetsMixin,
    agregar_features_referencias,
)
from src.platform.reference_project_store import (
    LimiteReferenciasError,
    mover_escopo_referencia,
    normalizar_biblioteca_referencias,
    obter_referencias_ativas,
    salvar_amostra_referencia,
)


def amostra(valor: float, identificador: str) -> dict:
    return {
        "id": identificador,
        "image_path": f"/tmp/{identificador}.png",
        "features": {
            "v_mean": float(valor),
            "v_max": float(valor),
            "h_mean": 1.0,
            "area_pixels": 100,
        },
        "roi": {
            "id": identificador,
            "centro_x": 100,
            "centro_y": 100,
            "raio": 10,
        },
    }


class ReferenceProjectStoreTests(unittest.TestCase):
    def _config_dois_projetos(self):
        return {
            "settings": {
                "active_led_project": "PLACA-A",
                "led_project_order": ["PLACA-A", "PLACA-B"],
            },
            "led_projects": {
                "PLACA-A": {
                    "name": "PLACA-A",
                    "fixed_leds": [],
                    "references": {},
                },
                "PLACA-B": {
                    "name": "PLACA-B",
                    "fixed_leds": [],
                    "references": {},
                },
            },
        }

    def test_migra_referencias_legadas_como_globais(self):
        config = self._config_dois_projetos()
        config["reference_on"] = amostra(220, "LEGADO_ON")
        config["reference_off"] = amostra(20, "LEGADO_OFF")
        config["reference_low_light"] = amostra(120, "LEGADO_LOW")

        normalizado, alterado = normalizar_biblioteca_referencias(config)

        self.assertTrue(alterado)
        globais = normalizado["reference_sets"]["global"]
        self.assertEqual(1, len(globais["on"]))
        self.assertEqual(1, len(globais["off"]))
        self.assertEqual(1, len(globais["low_light"]))
        self.assertEqual("LEGADO_ON", globais["on"][0]["id"])

    def test_referencia_de_projeto_nao_vaza_para_outro_projeto(self):
        config = salvar_amostra_referencia(
            self._config_dois_projetos(),
            "PLACA-A",
            "on",
            amostra(200, "A_ON"),
            scope="project",
        )

        refs_a = obter_referencias_ativas(config, "PLACA-A", "on")
        refs_b = obter_referencias_ativas(config, "PLACA-B", "on")

        self.assertEqual(["A_ON"], [item["sample"]["id"] for item in refs_a])
        self.assertEqual([], refs_b)

    def test_referencia_global_serve_para_todos_os_projetos(self):
        config = salvar_amostra_referencia(
            self._config_dois_projetos(),
            "PLACA-A",
            "on",
            amostra(210, "GLOBAL_ON"),
            scope="global",
        )

        for projeto in ("PLACA-A", "PLACA-B"):
            refs = obter_referencias_ativas(config, projeto, "on")
            self.assertEqual(1, len(refs))
            self.assertEqual("global", refs[0]["scope"])
            self.assertEqual("GLOBAL_ON", refs[0]["sample"]["id"])

    def test_limite_e_tres_referencias_ativas_somando_global_e_projeto(self):
        config = self._config_dois_projetos()
        config = salvar_amostra_referencia(
            config, "PLACA-A", "on", amostra(100, "G1"), scope="global"
        )
        config = salvar_amostra_referencia(
            config, "PLACA-A", "on", amostra(110, "A1"), scope="project"
        )
        config = salvar_amostra_referencia(
            config, "PLACA-A", "on", amostra(120, "A2"), scope="project"
        )

        self.assertEqual(3, len(obter_referencias_ativas(config, "PLACA-A", "on")))
        with self.assertRaises(LimiteReferenciasError):
            salvar_amostra_referencia(
                config,
                "PLACA-A",
                "on",
                amostra(130, "A3"),
                scope="project",
            )

    def test_global_nao_pode_fazer_outro_projeto_ultrapassar_tres(self):
        config = self._config_dois_projetos()
        for indice in range(3):
            config = salvar_amostra_referencia(
                config,
                "PLACA-B",
                "off",
                amostra(20 + indice, f"B{indice}"),
                scope="project",
            )

        with self.assertRaises(LimiteReferenciasError):
            salvar_amostra_referencia(
                config,
                "PLACA-A",
                "off",
                amostra(25, "GLOBAL_OFF"),
                scope="global",
            )

    def test_alternar_serve_para_tudo_move_amostra_sem_duplicar(self):
        config = salvar_amostra_referencia(
            self._config_dois_projetos(),
            "PLACA-A",
            "low_light",
            amostra(140, "LOW_A"),
            scope="project",
        )
        config = mover_escopo_referencia(
            config,
            "PLACA-A",
            "low_light",
            "project",
            0,
        )

        refs_a = obter_referencias_ativas(config, "PLACA-A", "low_light")
        refs_b = obter_referencias_ativas(config, "PLACA-B", "low_light")
        self.assertEqual(1, len(refs_a))
        self.assertEqual("global", refs_a[0]["scope"])
        self.assertEqual("LOW_A", refs_b[0]["sample"]["id"])

    def test_agregador_usa_as_tres_amostras(self):
        entradas = [
            {"sample": amostra(90, "R1")},
            {"sample": amostra(150, "R2")},
            {"sample": amostra(240, "R3")},
        ]
        agregado = agregar_features_referencias(entradas)
        self.assertIsNotNone(agregado)
        self.assertAlmostEqual(160.0, agregado.v_mean)
        self.assertAlmostEqual(160.0, agregado.v_max)
        self.assertEqual(100, agregado.area_pixels)

    def test_media_de_hue_vermelho_e_circular(self):
        primeira = amostra(100, "H1")
        segunda = amostra(100, "H2")
        primeira["features"]["h_mean"] = 1.0
        segunda["features"]["h_mean"] = 179.0
        agregado = agregar_features_referencias(
            [{"sample": primeira}, {"sample": segunda}]
        )
        self.assertTrue(agregado.h_mean < 5.0 or agregado.h_mean > 175.0)


class ReferenceProjectRepositoryTests(unittest.TestCase):
    def setUp(self):
        instalar_repositorio_projetos_led()
        self.temp = tempfile.TemporaryDirectory()
        self.arquivo = Path(self.temp.name) / "config.json"
        self.repo = ConfigRepository(config_file=self.arquivo)
        base = {
            "settings": {
                "active_led_project": "PLACA-A",
                "led_project_order": ["PLACA-A"],
            },
            "led_projects": {
                "PLACA-A": {
                    "name": "PLACA-A",
                    "fixed_leds": [],
                    "updated_at": None,
                    "references": {
                        "on": [amostra(200, "LOCAL_ON")],
                        "off": [],
                        "low_light": [],
                    },
                }
            },
        }
        self.arquivo.write_text(json.dumps(base), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def _ler(self):
        return json.loads(self.arquivo.read_text(encoding="utf-8"))

    def test_salvar_leds_preserva_referencias_do_mesmo_projeto(self):
        self.repo.salvar_leds_fixos(
            [LedSelection("LED_1", 100, 100, 10)],
            projeto="PLACA-A",
        )
        dados = self._ler()
        refs = dados["led_projects"]["PLACA-A"]["references"]["on"]
        self.assertEqual("LOCAL_ON", refs[0]["id"])

    def test_renomear_projeto_leva_referencias_junto(self):
        self.assertTrue(self.repo.renomear_projeto_led("PLACA-A", "PLACA-X"))
        dados = self._ler()
        self.assertNotIn("PLACA-A", dados["led_projects"])
        self.assertEqual(
            "LOCAL_ON",
            dados["led_projects"]["PLACA-X"]["references"]["on"][0]["id"],
        )

    def test_remover_projeto_remove_referencias_locais_com_ele(self):
        self.assertTrue(self.repo.remover_projeto_led("PLACA-A"))
        dados = self._ler()
        self.assertNotIn("PLACA-A", dados.get("led_projects", {}))


class ReferenceProjectMroTests(unittest.TestCase):
    def test_perfil_display_prioriza_multiplas_referencias_sobre_captura_legada(self):
        mro = DesktopProductionApp.__mro__
        self.assertIn(ProjectReferenceSetsMixin, mro)
        self.assertIn(ReferenceCaptureMixin, mro)
        self.assertLess(
            mro.index(ProjectReferenceSetsMixin),
            mro.index(ReferenceCaptureMixin),
        )


if __name__ == "__main__":
    unittest.main()
