from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

import src.platform.display_check_presence_reference as presence_module
from src.platform.display_check_presence_reference import (
    DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD,
    DisplayCheckPresenceReferenceStore,
    DisplayCheckManagerPresenceWindow,
    avaliar_referencia_presenca_display,
    calcular_similaridade_presenca_display,
    decidir_analise_display_f3_com_presenca,
)
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_ON,
    DisplayProjectRepository,
)
from src.platform.desktop_production_app import DesktopProductionApp


class DisplayCheckPresenceReferenceTests(unittest.TestCase):
    @staticmethod
    def _reference_frame():
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.rectangle(frame, (42, 38), (278, 202), (70, 70, 70), -1)
        cv2.rectangle(frame, (58, 52), (262, 188), (125, 125, 125), 3)
        cv2.circle(frame, (102, 116), 18, (245, 245, 245), -1)
        cv2.circle(frame, (160, 116), 18, (175, 175, 175), -1)
        cv2.circle(frame, (218, 116), 18, (235, 235, 235), -1)
        cv2.line(frame, (70, 170), (250, 170), (210, 210, 210), 4)
        return frame

    def test_captura_e_reabre_referencia_visual_por_check(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = DisplayProjectRepository(Path(temp_dir) / "display.json")
            repository.adicionar_projeto("DISPLAY A", (320, 240))
            h1 = repository.listar_checks("DISPLAY A")[0]
            store = DisplayCheckPresenceReferenceStore(repository)

            metadata = store.capture(
                "DISPLAY A",
                h1["id"],
                self._reference_frame(),
                (320, 240),
            )

            self.assertIsNotNone(metadata)
            self.assertEqual(
                DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD,
                metadata["threshold"],
            )
            self.assertTrue(Path(metadata["image_path"]).is_file())

            reopened = DisplayCheckPresenceReferenceStore(repository).get(
                "DISPLAY A",
                h1["id"],
            )
            self.assertEqual(metadata["image_path"], reopened["image_path"])
            self.assertEqual(320, reopened["width"])
            self.assertEqual(240, reopened["height"])

    def test_mesma_cena_confirma_presenca_e_cena_diferente_nao(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = DisplayProjectRepository(Path(temp_dir) / "display.json")
            repository.adicionar_projeto("DISPLAY A", (320, 240))
            h1 = repository.listar_checks("DISPLAY A")[0]
            store = DisplayCheckPresenceReferenceStore(repository)
            reference = self._reference_frame()
            metadata = store.capture(
                "DISPLAY A",
                h1["id"],
                reference,
                (320, 240),
            )

            same = avaliar_referencia_presenca_display(reference.copy(), metadata)
            different_frame = np.zeros_like(reference)
            cv2.rectangle(
                different_frame,
                (5, 5),
                (90, 80),
                (255, 255, 255),
                -1,
            )
            different = avaliar_referencia_presenca_display(
                different_frame,
                metadata,
            )

            self.assertTrue(same["configured"])
            self.assertTrue(same["available"])
            self.assertTrue(same["matched"])
            self.assertGreater(same["score"], 0.90)
            self.assertFalse(different["matched"])
            self.assertLess(different["score"], metadata["threshold"])

    def test_similaridade_tolera_pequena_variacao_de_brilho(self):
        reference = self._reference_frame()
        brighter = cv2.convertScaleAbs(reference, alpha=1.02, beta=3)
        score = calcular_similaridade_presenca_display(reference, brighter)
        self.assertGreater(score, DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD)

    def test_referencia_visual_e_parametro_adicional_antes_do_ok(self):
        analysis = {
            "ready": True,
            "approved": True,
            "reason": "check_conforme",
            "mask_results": [
                {
                    "mask_id": "MASK_001",
                    "expected": DISPLAY_CHECK_STATE_ON,
                    "classified": DISPLAY_CHECK_STATE_ON,
                    "matched": True,
                    "confidence": 0.95,
                }
            ],
            "presence_reference": {
                "configured": True,
                "available": True,
                "matched": False,
                "score": 0.41,
                "threshold": 0.72,
            },
        }

        waiting = decidir_analise_display_f3_com_presenca(
            analysis,
            reference_gate=True,
        )
        self.assertEqual("searching", waiting["decision"])
        self.assertEqual(
            "aguardando_referencia_visual_check",
            waiting["reason"],
        )

        analysis["presence_reference"]["matched"] = True
        analysis["presence_reference"]["score"] = 0.91
        approved = decidir_analise_display_f3_com_presenca(
            analysis,
            reference_gate=True,
        )
        self.assertEqual("ok", approved["decision"])

    def test_check_sem_referencia_continua_no_fluxo_legado(self):
        analysis = {
            "ready": True,
            "approved": True,
            "mask_results": [
                {
                    "mask_id": "MASK_001",
                    "expected": DISPLAY_CHECK_STATE_ON,
                    "classified": DISPLAY_CHECK_STATE_ON,
                    "matched": True,
                    "confidence": 0.95,
                }
            ],
            "presence_reference": {
                "configured": False,
                "available": False,
                "matched": True,
                "score": None,
                "threshold": 0.72,
            },
        }
        result = decidir_analise_display_f3_com_presenca(
            analysis,
            reference_gate=True,
        )
        self.assertEqual("ok", result["decision"])

    def test_referencia_acompanha_renomeacao_e_pode_ser_removida(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = DisplayProjectRepository(Path(temp_dir) / "display.json")
            repository.adicionar_projeto("DISPLAY A", (320, 240))
            h1 = repository.listar_checks("DISPLAY A")[0]
            store = DisplayCheckPresenceReferenceStore(repository)
            metadata = store.capture(
                "DISPLAY A",
                h1["id"],
                self._reference_frame(),
                (320, 240),
            )
            image_path = Path(metadata["image_path"])

            store.rename_project("DISPLAY A", "DISPLAY B")
            self.assertIsNone(store.get("DISPLAY A", h1["id"]))
            self.assertIsNotNone(store.get("DISPLAY B", h1["id"]))

            self.assertTrue(store.remove("DISPLAY B", h1["id"]))
            self.assertFalse(image_path.exists())
            self.assertIsNone(store.get("DISPLAY B", h1["id"]))

    def test_interface_expoe_captura_da_camera_dentro_dos_checks(self):
        source = inspect.getsource(DisplayCheckManagerPresenceWindow)
        self.assertIn("REFERÊNCIA VISUAL / PRESENÇA", source)
        self.assertIn("CAPTURAR FOTO DA CÂMERA", source)
        self.assertIn("capture_presence_reference", source)

    def test_perfil_final_instala_extensao_sem_mudar_mro_f2(self):
        source = inspect.getsource(DesktopProductionApp.__init__)
        self.assertIn("instalar_referencia_presenca_check_display()", source)
        module_source = inspect.getsource(presence_module)
        self.assertNotIn("src.platform.f2_", module_source)
        self.assertNotIn("config_repository", module_source)


if __name__ == "__main__":
    unittest.main()
