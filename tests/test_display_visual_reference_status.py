from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

import src.platform.display_visual_reference_status as status_module
from src.platform.display_check_presence_reference import (
    DisplayCheckPresenceReferenceStore,
)
from src.platform.display_project_repository import DisplayProjectRepository
from src.platform.display_visual_reference_status import (
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
    DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
    DisplayProjectConfigPresenceWindow,
    DisplayProjectPresenceReferenceStore,
    DisplayVisualReferenceMatcher,
    display_check_cards_structure_key,
)
from src.platform.desktop_production_app import DesktopProductionApp


class DisplayVisualReferenceStatusTests(unittest.TestCase):
    @staticmethod
    def _empty_support_frame():
        frame = np.full((240, 320, 3), 28, dtype=np.uint8)
        cv2.rectangle(frame, (18, 18), (302, 222), (72, 72, 72), 4)
        cv2.line(frame, (24, 120), (296, 120), (58, 58, 58), 3)
        return frame

    @staticmethod
    def _board_off_frame():
        frame = DisplayVisualReferenceStatusTests._empty_support_frame()
        cv2.rectangle(frame, (46, 42), (274, 202), (95, 95, 95), -1)
        cv2.rectangle(frame, (58, 54), (262, 190), (142, 142, 142), 3)
        cv2.circle(frame, (90, 112), 18, (56, 56, 56), -1)
        cv2.circle(frame, (160, 112), 18, (56, 56, 56), -1)
        cv2.circle(frame, (230, 112), 18, (56, 56, 56), -1)
        return frame

    @staticmethod
    def _h1_frame():
        frame = DisplayVisualReferenceStatusTests._board_off_frame()
        cv2.circle(frame, (90, 112), 16, (250, 250, 250), -1)
        cv2.circle(frame, (160, 112), 16, (210, 210, 210), -1)
        return frame

    @staticmethod
    def _bluetooth_frame():
        frame = DisplayVisualReferenceStatusTests._board_off_frame()
        cv2.rectangle(frame, (188, 78), (252, 146), (245, 245, 245), -1)
        cv2.line(frame, (200, 88), (240, 136), (30, 30, 30), 6)
        cv2.line(frame, (240, 88), (200, 136), (30, 30, 30), 6)
        return frame

    def test_projeto_salva_duas_referencias_de_presenca_separadas(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = DisplayProjectRepository(Path(temp_dir) / "display.json")
            repository.adicionar_projeto("DISPLAY A", (320, 240))
            store = DisplayProjectPresenceReferenceStore(repository)

            board = store.capture(
                "DISPLAY A",
                DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                self._board_off_frame(),
                (320, 240),
            )
            empty = store.capture(
                "DISPLAY A",
                DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
                self._empty_support_frame(),
                (320, 240),
            )

            self.assertIsNotNone(board)
            self.assertIsNotNone(empty)
            self.assertTrue(Path(board["image_path"]).is_file())
            self.assertTrue(Path(empty["image_path"]).is_file())
            reopened = DisplayProjectPresenceReferenceStore(repository).get_all("DISPLAY A")
            self.assertEqual(
                {
                    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                    DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
                },
                set(reopened),
            )

    def test_status_distingue_placa_desligada_de_suporte_vazio(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = DisplayProjectRepository(Path(temp_dir) / "display.json")
            repository.adicionar_projeto("DISPLAY A", (320, 240))
            store = DisplayProjectPresenceReferenceStore(repository)
            store.capture(
                "DISPLAY A",
                DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                self._board_off_frame(),
                (320, 240),
            )
            store.capture(
                "DISPLAY A",
                DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
                self._empty_support_frame(),
                (320, 240),
            )
            matcher = DisplayVisualReferenceMatcher(repository)

            board = matcher.identify_board_presence(
                self._board_off_frame(),
                "DISPLAY A",
            )
            empty = matcher.identify_board_presence(
                self._empty_support_frame(),
                "DISPLAY A",
            )

            self.assertTrue(board["matched"])
            self.assertEqual(
                DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                board["best"]["kind"],
            )
            self.assertTrue(empty["matched"])
            self.assertEqual(
                DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
                empty["best"]["kind"],
            )

    def test_status_identifica_h1_e_bluetooth_somente_pelas_fotos_dos_checks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = DisplayProjectRepository(Path(temp_dir) / "display.json")
            repository.adicionar_projeto("DISPLAY A", (320, 240))
            checks = repository.listar_checks("DISPLAY A")
            h1 = checks[0]
            blue = checks[1]
            store = DisplayCheckPresenceReferenceStore(repository)
            store.capture("DISPLAY A", h1["id"], self._h1_frame(), (320, 240))
            store.capture(
                "DISPLAY A",
                blue["id"],
                self._bluetooth_frame(),
                (320, 240),
            )
            matcher = DisplayVisualReferenceMatcher(repository)

            h1_result = matcher.identify_check_state(self._h1_frame(), "DISPLAY A")
            blue_result = matcher.identify_check_state(
                self._bluetooth_frame(),
                "DISPLAY A",
            )

            self.assertTrue(h1_result["matched"])
            self.assertEqual(h1["id"], h1_result["best"]["check_id"])
            self.assertTrue(blue_result["matched"])
            self.assertEqual(blue["id"], blue_result["best"]["check_id"])

    def test_estado_do_check_nao_participa_da_chave_estrutural_dos_cards(self):
        before = {
            "checks": [
                {"id": "CHECK_001", "name": "H1", "state": "current"},
                {"id": "CHECK_002", "name": "BLUE", "state": "pending"},
            ]
        }
        after = {
            "checks": [
                {"id": "CHECK_001", "name": "H1", "state": "completed"},
                {"id": "CHECK_002", "name": "BLUE", "state": "current"},
            ]
        }
        self.assertEqual(
            display_check_cards_structure_key(before),
            display_check_cards_structure_key(after),
        )

    def test_renderer_estavel_so_reconstroi_quando_estrutura_muda(self):
        source = inspect.getsource(status_module._render_check_cards_stable)
        self.assertIn("cached_key != structure_key", source)
        self.assertIn("widgets[\"frame\"].configure", source)
        self.assertNotIn("force_all_completed else str(check.get", source.split("cached_key != structure_key", 1)[0])

    def test_projeto_display_expoe_duas_capturas_com_preview(self):
        source = inspect.getsource(DisplayProjectConfigPresenceWindow)
        self.assertIn("PRESENÇA DA PLACA • REFERÊNCIAS DO PROJETO", source)
        self.assertIn("PLACA DESLIGADA NO SUPORTE", inspect.getsource(status_module))
        self.assertIn("PLACA FORA DO SUPORTE", inspect.getsource(status_module))
        self.assertIn("capture_project_presence_reference", source)
        self.assertIn("_project_presence_canvases", source)

    def test_perfil_final_instala_status_sem_importar_runtime_f2_no_modulo(self):
        app_source = inspect.getsource(DesktopProductionApp.__init__)
        self.assertIn("instalar_status_referencias_visuais_display()", app_source)
        module_source = inspect.getsource(status_module)
        self.assertNotIn("src.platform.f2_", module_source)


if __name__ == "__main__":
    unittest.main()
