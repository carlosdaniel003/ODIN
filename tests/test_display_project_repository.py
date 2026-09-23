from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.platform.display_project_repository import (
    DISPLAY_PROJECT_SCHEMA_VERSION,
    DisplayProjectRepository,
    normalizar_mascaras_display,
)


class DisplayProjectRepositoryTests(unittest.TestCase):
    def test_round_trip_reabre_projeto_resolucao_e_mascaras_exatamente_iguais(self):
        masks = [
            {
                "id": "MASK_001",
                "type": "rectangle",
                "x": 121,
                "y": 88,
                "width": 507,
                "height": 214,
            },
            {
                "id": "MASK_002",
                "type": "circle",
                "cx": 944,
                "cy": 517,
                "radius": 73,
            },
            {
                "id": "MASK_003",
                "type": "polygon",
                "points": [[1100, 150], [1410, 184], [1375, 620], [1088, 590]],
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "odin_display_projects.json"
            repository = DisplayProjectRepository(config_file)
            self.assertTrue(repository.adicionar_projeto("Display A"))
            self.assertTrue(
                repository.salvar_configuracao_projeto(
                    "Display A",
                    (1920, 1080),
                    masks,
                )
            )

            before_restart = repository.carregar_projeto("DISPLAY A")
            self.assertIsNotNone(before_restart)

            # Simula fechar o ODIN e abrir novamente: nova instância, mesmo arquivo.
            reopened_repository = DisplayProjectRepository(config_file)
            after_restart = reopened_repository.carregar_projeto("DISPLAY A")

            self.assertEqual(before_restart, after_restart)
            self.assertEqual(
                {"width": 1920, "height": 1080},
                after_restart["master_resolution"],
            )
            self.assertEqual(masks, after_restart["masks"])
            self.assertEqual("DISPLAY A", reopened_repository.obter_projeto_ativo())

    def test_arquivo_display_e_totalmente_separado_do_json_f2(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            f2_file = base / "odin_pci_config.json"
            display_file = base / "odin_display_projects.json"
            f2_content = {
                "project": "ODIN",
                "led_projects": {"PCI LED": {"fixed_leds": [{"id": "LED_001"}]}},
                "fixed_leds": [{"id": "LED_001"}],
                "settings": {"active_led_project": "PCI LED"},
            }
            f2_file.write_text(
                json.dumps(f2_content, sort_keys=True),
                encoding="utf-8",
            )
            before = f2_file.read_bytes()

            repository = DisplayProjectRepository(display_file)
            repository.adicionar_projeto("Painel frontal", (1280, 720))
            repository.salvar_mascaras(
                "Painel frontal",
                [{
                    "id": "MASK_001",
                    "type": "rectangle",
                    "x": 20,
                    "y": 30,
                    "width": 200,
                    "height": 80,
                }],
            )

            self.assertEqual(before, f2_file.read_bytes())
            self.assertTrue(display_file.exists())
            display_data = json.loads(display_file.read_text(encoding="utf-8"))
            self.assertEqual(DISPLAY_PROJECT_SCHEMA_VERSION, display_data["schema_version"])
            self.assertIn("projects", display_data)
            self.assertNotIn("led_projects", display_data)
            self.assertNotIn("fixed_leds", display_data)
            self.assertNotIn("active_led_project", display_data)

    def test_projetos_display_tem_resolucao_e_mascaras_independentes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = DisplayProjectRepository(Path(temp_dir) / "display.json")
            self.assertTrue(repository.adicionar_projeto("DISPLAY A", (1920, 1080)))
            self.assertTrue(repository.adicionar_projeto("DISPLAY B", (800, 480)))

            masks_a = [{
                "id": "MASK_001",
                "type": "circle",
                "cx": 100,
                "cy": 100,
                "radius": 35,
            }]
            masks_b = [{
                "id": "MASK_001",
                "type": "polygon",
                "points": [[10, 10], [300, 10], [300, 200], [10, 200]],
            }]
            self.assertTrue(repository.salvar_mascaras("DISPLAY A", masks_a))
            self.assertTrue(repository.salvar_mascaras("DISPLAY B", masks_b))

            project_a = repository.carregar_projeto("DISPLAY A")
            project_b = repository.carregar_projeto("DISPLAY B")
            self.assertEqual({"width": 1920, "height": 1080}, project_a["master_resolution"])
            self.assertEqual({"width": 800, "height": 480}, project_b["master_resolution"])
            self.assertEqual(masks_a, project_a["masks"])
            self.assertEqual(masks_b, project_b["masks"])

    def test_normalizacao_preserva_ordem_e_geometria_das_mascaras_validas(self):
        masks = [
            {"id": "A", "type": "rectangle", "x": 1, "y": 2, "width": 3, "height": 4},
            {"id": "B", "type": "circle", "cx": 5, "cy": 6, "radius": 7},
            {"id": "C", "type": "polygon", "points": [[1, 1], [9, 1], [5, 8]]},
        ]
        self.assertEqual(masks, normalizar_mascaras_display(masks))

    def test_trocar_mascara_de_circulo_para_pontos_migra_geometria_do_check(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = DisplayProjectRepository(Path(temp_dir) / "display.json")
            repository.adicionar_projeto("DISPLAY A", (800, 480))
            repository.salvar_mascaras(
                "DISPLAY A",
                [{
                    "id": "MASK_027",
                    "type": "circle",
                    "cx": 100,
                    "cy": 100,
                    "radius": 20,
                }],
            )
            check_id = repository.listar_checks("DISPLAY A")[0]["id"]
            repository.salvar_geometria_check(
                "DISPLAY A",
                check_id,
                [[0, 0], [799, 0], [799, 479], [0, 479]],
                {
                    "MASK_027": {
                        "id": "MASK_027",
                        "type": "circle",
                        "cx": 310,
                        "cy": 210,
                        "radius": 30,
                    }
                },
            )

            repository.salvar_mascaras(
                "DISPLAY A",
                [{
                    "id": "MASK_027",
                    "type": "polygon",
                    "points": [
                        [80, 90],
                        [120, 90],
                        [130, 100],
                        [120, 110],
                        [80, 110],
                        [70, 100],
                    ],
                }],
            )

            check = repository.carregar_check("DISPLAY A", check_id)
            migrated = check["mask_overrides_reference"]["MASK_027"]
            self.assertEqual("polygon", migrated["type"])
            self.assertEqual(6, len(migrated["points"]))
            cx = sum(point[0] for point in migrated["points"]) / 6.0
            cy = sum(point[1] for point in migrated["points"]) / 6.0
            self.assertAlmostEqual(310.0, cx, delta=1.0)
            self.assertAlmostEqual(210.0, cy, delta=1.0)

    def test_renomear_e_remover_nao_mistura_conteudo_de_outros_projetos(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = DisplayProjectRepository(Path(temp_dir) / "display.json")
            repository.adicionar_projeto("A", (640, 480))
            repository.adicionar_projeto("B", (1280, 720))
            repository.salvar_mascaras(
                "A",
                [{"id": "MASK_001", "type": "rectangle", "x": 1, "y": 2, "width": 3, "height": 4}],
            )
            project_b_before = repository.carregar_projeto("B")

            self.assertTrue(repository.renomear_projeto("A", "A NOVO"))
            self.assertEqual(project_b_before, repository.carregar_projeto("B"))
            self.assertTrue(repository.remover_projeto("A NOVO"))
            self.assertEqual(project_b_before, repository.carregar_projeto("B"))


if __name__ == "__main__":
    unittest.main()
