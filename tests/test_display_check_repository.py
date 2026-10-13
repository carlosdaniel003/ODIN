from __future__ import annotations

import json
import inspect
import tempfile
import unittest
from pathlib import Path

from src.platform.display_check_editor import DisplayCheckManagerWindow
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_IGNORE,
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
    DISPLAY_DEFAULT_CHECK_NAMES,
    DISPLAY_PROJECT_SCHEMA_VERSION,
    DisplayProjectRepository,
)


class DisplayCheckRepositoryTests(unittest.TestCase):
    @staticmethod
    def _masks():
        return [
            {
                "id": "MASK_001",
                "type": "rectangle",
                "x": 10,
                "y": 20,
                "width": 120,
                "height": 40,
            },
            {
                "id": "MASK_002",
                "type": "circle",
                "cx": 240,
                "cy": 180,
                "radius": 22,
            },
        ]

    def test_novo_projeto_nasce_com_h1_blue_aux_usb_na_ordem(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = DisplayProjectRepository(Path(temp_dir) / "display.json")
            self.assertTrue(repository.adicionar_projeto("DISPLAY A", (1920, 1080)))
            checks = repository.listar_checks("DISPLAY A")
            self.assertEqual(
                list(DISPLAY_DEFAULT_CHECK_NAMES),
                [check["name"] for check in checks],
            )
            self.assertEqual(
                ["CHECK_001", "CHECK_002", "CHECK_003", "CHECK_004"],
                [check["id"] for check in checks],
            )

    def test_blue_padrao_e_migracao_legada_sao_intermitentes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = DisplayProjectRepository(Path(temp_dir) / "display.json")
            repository.adicionar_projeto("DISPLAY A", (640, 480))
            checks = repository.listar_checks("DISPLAY A")
            blue = next(check for check in checks if check["name"] == "BLUE")
            h1 = next(check for check in checks if check["name"] == "H1")
            self.assertTrue(blue["intermittent"])
            self.assertFalse(h1["intermittent"])

    def test_toggle_intermitente_persiste_e_false_tem_prioridade_sobre_nome_blue(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "display.json"
            repository = DisplayProjectRepository(config_file)
            repository.adicionar_projeto("DISPLAY A", (640, 480))
            blue = next(
                check
                for check in repository.listar_checks("DISPLAY A")
                if check["name"] == "BLUE"
            )
            self.assertTrue(
                repository.salvar_check_intermitente(
                    "DISPLAY A",
                    blue["id"],
                    False,
                )
            )
            reopened = DisplayProjectRepository(config_file)
            saved = reopened.carregar_check("DISPLAY A", blue["id"])
            self.assertFalse(saved["intermittent"])

            novo = repository.adicionar_check("DISPLAY A", "PISCA TESTE")
            self.assertTrue(
                repository.salvar_check_intermitente(
                    "DISPLAY A",
                    novo,
                    True,
                )
            )
            self.assertTrue(
                DisplayProjectRepository(config_file)
                .carregar_check("DISPLAY A", novo)["intermittent"]
            )

    def test_toggle_ativo_preserva_todas_as_configuracoes_e_reabre(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "display.json"
            repo = DisplayProjectRepository(path)
            repo.adicionar_projeto("DISPLAY A", (1920, 1080))
            repo.salvar_mascaras("DISPLAY A", self._masks())
            blue = next(
                item for item in repo.listar_checks("DISPLAY A")
                if item["name"] == "BLUE"
            )
            check_id = blue["id"]
            states = {"MASK_001": "on", "MASK_002": "off"}
            board = [[0, 0], [100, 0], [100, 100], [0, 100]]
            overrides = {
                "MASK_001": {
                    "id": "MASK_001",
                    "type": "rectangle",
                    "x": 22,
                    "y": 40,
                    "width": 120,
                    "height": 40,
                }
            }
            self.assertTrue(repo.salvar_estados_check("DISPLAY A", check_id, states))
            self.assertTrue(
                repo.salvar_geometria_check(
                    "DISPLAY A", check_id, board, overrides
                )
            )
            before = repo.carregar_check("DISPLAY A", check_id)
            self.assertTrue(before["enabled"])
            self.assertTrue(before["intermittent"])

            self.assertTrue(repo.salvar_check_ativo("DISPLAY A", check_id, False))
            inactive = DisplayProjectRepository(path)
            saved = inactive.carregar_check("DISPLAY A", check_id)
            self.assertFalse(saved["enabled"])
            self.assertEqual(
                {key: value for key, value in before.items() if key != "enabled"},
                {key: value for key, value in saved.items() if key != "enabled"},
            )
            self.assertEqual(4, len(inactive.listar_checks("DISPLAY A")))
            self.assertEqual(
                ["H1", "AUX", "USB"],
                [item["name"] for item in inactive.listar_checks_ativos("DISPLAY A")],
            )

            self.assertTrue(inactive.salvar_check_ativo("DISPLAY A", check_id, True))
            restored = DisplayProjectRepository(path)
            self.assertEqual(before, restored.carregar_check("DISPLAY A", check_id))
            self.assertEqual(
                list(DISPLAY_DEFAULT_CHECK_NAMES),
                [item["name"] for item in restored.listar_checks_ativos("DISPLAY A")],
            )
            self.assertFalse(restored.salvar_check_ativo("DISPLAY A", "INEXISTENTE", False))

    def test_json_legado_sem_flag_enabled_mantem_todos_os_checks_ativos(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "display.json"
            repo = DisplayProjectRepository(path)
            repo.adicionar_projeto("DISPLAY A", (640, 480))
            raw = json.loads(path.read_text(encoding="utf-8"))
            for check in raw["projects"]["DISPLAY A"]["checks"]:
                check.pop("enabled", None)
            path.write_text(json.dumps(raw), encoding="utf-8")
            legacy = DisplayProjectRepository(path)
            self.assertEqual(
                list(DISPLAY_DEFAULT_CHECK_NAMES),
                [item["name"] for item in legacy.listar_checks_ativos("DISPLAY A")],
            )
            self.assertTrue(
                all(item["enabled"] for item in legacy.listar_checks("DISPLAY A"))
            )

    def test_interface_toggle_f3_muda_flag_sem_abrir_editor_e_notifica(self):
        class _Var:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        class _Status:
            def __init__(self):
                self.options = {}

            def configure(self, **kwargs):
                self.options.update(kwargs)

        with tempfile.TemporaryDirectory() as temp_dir:
            repo = DisplayProjectRepository(Path(temp_dir) / "display.json")
            repo.adicionar_projeto("DISPLAY A", (640, 480))
            selected = repo.listar_checks("DISPLAY A")[2]["id"]
            manager = DisplayCheckManagerWindow.__new__(DisplayCheckManagerWindow)
            manager.repository = repo
            manager.project_name = "DISPLAY A"
            manager._selected_id = lambda: selected
            manager.check_enabled_var = _Var(False)
            manager.status = _Status()
            refreshes = []
            notifications = []
            manager.refresh = lambda check_id: refreshes.append(check_id)
            manager._notify_change = lambda: notifications.append(True)
            manager._toggle_enabled()

            self.assertFalse(repo.carregar_check("DISPLAY A", selected)["enabled"])
            self.assertEqual([selected], refreshes)
            self.assertEqual([True], notifications)
            self.assertIn("desativado", manager.status.options["text"])
            self.assertIn(
                "self.check_enabled_toggle = tk.Checkbutton(",
                inspect.getsource(DisplayCheckManagerWindow.__init__),
            )

    def test_salvar_mascaras_adiciona_estado_ignorar_em_todos_os_checks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = DisplayProjectRepository(Path(temp_dir) / "display.json")
            repository.adicionar_projeto("DISPLAY A", (1920, 1080))
            self.assertTrue(repository.salvar_mascaras("DISPLAY A", self._masks()))

            for check in repository.listar_checks("DISPLAY A"):
                self.assertEqual(
                    {
                        "MASK_001": DISPLAY_CHECK_STATE_IGNORE,
                        "MASK_002": DISPLAY_CHECK_STATE_IGNORE,
                    },
                    check["mask_states"],
                )

    def test_estado_on_off_ignore_persiste_apos_reabrir_odin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "display.json"
            repository = DisplayProjectRepository(config_file)
            repository.adicionar_projeto("DISPLAY A", (1920, 1080))
            repository.salvar_mascaras("DISPLAY A", self._masks())
            h1 = repository.listar_checks("DISPLAY A")[0]

            self.assertTrue(
                repository.salvar_estados_check(
                    "DISPLAY A",
                    h1["id"],
                    {
                        "MASK_001": DISPLAY_CHECK_STATE_ON,
                        "MASK_002": DISPLAY_CHECK_STATE_OFF,
                    },
                )
            )

            reopened = DisplayProjectRepository(config_file)
            check = reopened.carregar_check("DISPLAY A", h1["id"])
            self.assertEqual(
                {
                    "MASK_001": DISPLAY_CHECK_STATE_ON,
                    "MASK_002": DISPLAY_CHECK_STATE_OFF,
                },
                check["mask_states"],
            )
            self.assertEqual(self._masks(), reopened.carregar_projeto("DISPLAY A")["masks"])

    def test_adicionar_renomear_reordenar_e_remover_check(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = DisplayProjectRepository(Path(temp_dir) / "display.json")
            repository.adicionar_projeto("DISPLAY A", (640, 480))

            novo_id = repository.adicionar_check("DISPLAY A", "TESTE")
            self.assertEqual("CHECK_005", novo_id)
            self.assertTrue(repository.renomear_check("DISPLAY A", novo_id, "FINAL"))
            self.assertTrue(repository.mover_check("DISPLAY A", novo_id, -1))
            self.assertTrue(repository.mover_check("DISPLAY A", novo_id, -1))
            self.assertEqual(
                ["H1", "BLUE", "FINAL", "AUX", "USB"],
                [check["name"] for check in repository.listar_checks("DISPLAY A")],
            )

            aux = next(
                check for check in repository.listar_checks("DISPLAY A")
                if check["name"] == "AUX"
            )
            self.assertTrue(repository.remover_check("DISPLAY A", aux["id"]))
            self.assertEqual(
                ["H1", "BLUE", "FINAL", "USB"],
                [check["name"] for check in repository.listar_checks("DISPLAY A")],
            )

    def test_nomes_de_check_duplicados_sao_rejeitados(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = DisplayProjectRepository(Path(temp_dir) / "display.json")
            repository.adicionar_projeto("DISPLAY A", (640, 480))
            self.assertIsNone(repository.adicionar_check("DISPLAY A", "blue"))
            h1 = repository.listar_checks("DISPLAY A")[0]
            self.assertFalse(repository.renomear_check("DISPLAY A", h1["id"], "USB"))

    def test_alterar_mascaras_preserva_estado_existente_remove_antigo_e_cria_ignore(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = DisplayProjectRepository(Path(temp_dir) / "display.json")
            repository.adicionar_projeto("DISPLAY A", (1920, 1080))
            repository.salvar_mascaras("DISPLAY A", self._masks())
            h1 = repository.listar_checks("DISPLAY A")[0]
            repository.salvar_estados_check(
                "DISPLAY A",
                h1["id"],
                {
                    "MASK_001": DISPLAY_CHECK_STATE_ON,
                    "MASK_002": DISPLAY_CHECK_STATE_OFF,
                },
            )

            novas = [
                self._masks()[0],
                {
                    "id": "MASK_003",
                    "type": "rectangle",
                    "x": 300,
                    "y": 100,
                    "width": 90,
                    "height": 30,
                },
            ]
            repository.salvar_mascaras("DISPLAY A", novas)
            h1_after = repository.carregar_check("DISPLAY A", h1["id"])
            self.assertEqual(
                {
                    "MASK_001": DISPLAY_CHECK_STATE_ON,
                    "MASK_003": DISPLAY_CHECK_STATE_IGNORE,
                },
                h1_after["mask_states"],
            )
            self.assertNotIn("MASK_002", h1_after["mask_states"])

    def test_projeto_legado_fase2_recebe_checks_padrao_sem_mudar_mascaras(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "display.json"
            legacy = {
                "schema_version": 1,
                "active_project": "DISPLAY A",
                "project_order": ["DISPLAY A"],
                "projects": {
                    "DISPLAY A": {
                        "name": "DISPLAY A",
                        "master_resolution": {"width": 1920, "height": 1080},
                        "masks": self._masks(),
                    }
                },
            }
            config_file.write_text(json.dumps(legacy), encoding="utf-8")

            repository = DisplayProjectRepository(config_file)
            project = repository.carregar_projeto("DISPLAY A")
            self.assertEqual(self._masks(), project["masks"])
            self.assertEqual(
                list(DISPLAY_DEFAULT_CHECK_NAMES),
                [check["name"] for check in project["checks"]],
            )
            for check in project["checks"]:
                self.assertEqual(
                    {
                        "MASK_001": DISPLAY_CHECK_STATE_IGNORE,
                        "MASK_002": DISPLAY_CHECK_STATE_IGNORE,
                    },
                    check["mask_states"],
                )

    def test_remover_todos_os_checks_nao_recria_padrao_no_proximo_load(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "display.json"
            repository = DisplayProjectRepository(config_file)
            repository.adicionar_projeto("DISPLAY A", (640, 480))
            for check in list(repository.listar_checks("DISPLAY A")):
                self.assertTrue(repository.remover_check("DISPLAY A", check["id"]))
            self.assertEqual([], repository.listar_checks("DISPLAY A"))
            self.assertEqual([], DisplayProjectRepository(config_file).listar_checks("DISPLAY A"))

    def test_json_f2_nao_e_tocado_pela_gestao_de_checks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            f2_file = base / "odin_pci_config.json"
            f2_file.write_text(
                json.dumps(
                    {
                        "led_projects": {"PCI": {"fixed_leds": [{"id": "LED_001"}]}},
                        "settings": {"active_led_project": "PCI"},
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            before = f2_file.read_bytes()

            repository = DisplayProjectRepository(base / "odin_display_projects.json")
            repository.adicionar_projeto("DISPLAY A", (640, 480))
            repository.salvar_mascaras("DISPLAY A", self._masks())
            h1 = repository.listar_checks("DISPLAY A")[0]
            repository.salvar_estados_check(
                "DISPLAY A",
                h1["id"],
                {"MASK_001": "aceso", "MASK_002": "apagado"},
            )
            repository.mover_check("DISPLAY A", h1["id"], 1)

            self.assertEqual(before, f2_file.read_bytes())
            data = json.loads(
                (base / "odin_display_projects.json").read_text(encoding="utf-8")
            )
            self.assertEqual(DISPLAY_PROJECT_SCHEMA_VERSION, data["schema_version"])
            self.assertIn("checks", data["projects"]["DISPLAY A"])
            self.assertNotIn("led_projects", data)
            self.assertNotIn("fixed_leds", data)


if __name__ == "__main__":
    unittest.main()
