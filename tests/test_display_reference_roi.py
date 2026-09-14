from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

import src.platform.display_check_presence_reference as check_module
import src.platform.display_reference_roi as roi_module
import src.platform.display_visual_reference_status as visual_module
from src.platform.display_reference_roi import (
    descricao_roi_referencia,
    instalar_roi_referencias_display_f3,
    normalizar_roi_referencia,
    recortar_roi_referencia,
)


class DisplayReferenceRoiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        instalar_roi_referencias_display_f3()

    def test_roi_normalizada_e_limitada_a_imagem(self):
        roi = normalizar_roi_referencia(
            {"x": 0.25, "y": 0.20, "width": 0.50, "height": 0.60}
        )
        self.assertEqual(
            {"x": 0.25, "y": 0.20, "width": 0.50, "height": 0.60},
            roi,
        )
        clipped = normalizar_roi_referencia(
            {"x": 0.80, "y": 0.75, "width": 0.50, "height": 0.50}
        )
        self.assertAlmostEqual(0.20, clipped["width"])
        self.assertAlmostEqual(0.25, clipped["height"])

    def test_imagem_inteira_e_representada_sem_roi(self):
        self.assertIsNone(
            normalizar_roi_referencia(
                {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}
            )
        )
        self.assertEqual("IMAGEM TODA", descricao_roi_referencia({}))
        self.assertEqual(
            "RECORTE ATIVO",
            descricao_roi_referencia(
                {"roi": {"x": 0.1, "y": 0.1, "width": 0.4, "height": 0.4}}
            ),
        )

    def test_recorte_usa_as_coordenadas_relativas(self):
        image = np.zeros((100, 200, 3), dtype=np.uint8)
        crop = recortar_roi_referencia(
            image,
            {"x": 0.25, "y": 0.20, "width": 0.50, "height": 0.60},
        )
        self.assertEqual((60, 100, 3), crop.shape)

    def test_seletor_reserva_altura_para_acoes_inferiores(self):
        self.assertGreaterEqual(
            roi_module.DISPLAY_REFERENCE_ROI_VERTICAL_UI_RESERVE,
            300,
        )
        source = inspect.getsource(roi_module.DisplayReferenceRoiDialog.__init__)
        self.assertIn("DISPLAY_REFERENCE_ROI_VERTICAL_UI_RESERVE", source)
        self.assertIn("DISPLAY_REFERENCE_ROI_MIN_DRAW_HEIGHT", source)

    def test_check_store_persiste_roi_por_referencia(self):
        with tempfile.TemporaryDirectory() as tmp:
            repository = SimpleNamespace(
                config_file=Path(tmp) / "odin_display_projects.json"
            )
            store = check_module.DisplayCheckPresenceReferenceStore(repository)
            frame = np.full((120, 160, 3), 70, dtype=np.uint8)
            self.assertIsNotNone(store.capture("Projeto A", "H1", frame, (160, 120)))
            roi = {"x": 0.2, "y": 0.25, "width": 0.4, "height": 0.5}
            self.assertTrue(store.set_roi("Projeto A", "H1", roi))
            loaded = store.get("Projeto A", "H1")
            self.assertEqual(normalizar_roi_referencia(roi), loaded["roi"])

            # Uma nova captura da mesma referência não deve apagar o recorte.
            self.assertIsNotNone(store.capture("Projeto A", "H1", frame, (160, 120)))
            loaded_again = store.get("Projeto A", "H1")
            self.assertEqual(normalizar_roi_referencia(roi), loaded_again["roi"])

            self.assertTrue(store.set_roi("Projeto A", "H1", None))
            self.assertNotIn("roi", store.get("Projeto A", "H1"))

    def test_presenca_projeto_persiste_roi_independente_por_foto(self):
        with tempfile.TemporaryDirectory() as tmp:
            repository = SimpleNamespace(
                config_file=Path(tmp) / "odin_display_projects.json"
            )
            store = visual_module.DisplayProjectPresenceReferenceStore(repository)
            frame = np.full((120, 160, 3), 90, dtype=np.uint8)
            self.assertIsNotNone(
                store.capture(
                    "Projeto A",
                    visual_module.DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                    frame,
                    (160, 120),
                )
            )
            self.assertIsNotNone(
                store.capture(
                    "Projeto A",
                    visual_module.DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
                    frame,
                    (160, 120),
                )
            )
            roi_off = {"x": 0.1, "y": 0.2, "width": 0.35, "height": 0.5}
            roi_empty = {"x": 0.5, "y": 0.1, "width": 0.4, "height": 0.6}
            self.assertTrue(
                store.set_roi(
                    "Projeto A",
                    visual_module.DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                    roi_off,
                )
            )
            self.assertTrue(
                store.set_roi(
                    "Projeto A",
                    visual_module.DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
                    roi_empty,
                )
            )
            self.assertEqual(
                normalizar_roi_referencia(roi_off),
                store.get(
                    "Projeto A", visual_module.DISPLAY_PROJECT_REFERENCE_BOARD_OFF
                )["roi"],
            )
            self.assertEqual(
                normalizar_roi_referencia(roi_empty),
                store.get(
                    "Projeto A", visual_module.DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT
                )["roi"],
            )

    def test_matcher_ignora_alteracao_fora_da_roi(self):
        with tempfile.TemporaryDirectory() as tmp:
            repository = SimpleNamespace(
                config_file=Path(tmp) / "odin_display_projects.json"
            )
            reference = np.zeros((100, 100, 3), dtype=np.uint8)
            path = Path(tmp) / "reference.jpg"
            cv2.imwrite(str(path), reference)
            metadata = {
                "image_path": str(path),
                "threshold": 0.72,
                "roi": {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5},
            }
            matcher = visual_module.DisplayVisualReferenceMatcher(repository)

            outside_changed = np.full((100, 100, 3), 255, dtype=np.uint8)
            outside_changed[25:75, 25:75] = 0
            score_outside = matcher._score(outside_changed, metadata)

            inside_changed = np.zeros((100, 100, 3), dtype=np.uint8)
            inside_changed[25:75, 25:75] = 255
            score_inside = matcher._score(inside_changed, metadata)

            self.assertGreater(score_outside, 0.98)
            self.assertLess(score_inside, 0.50)

    def test_check_analyzer_tambem_respeita_roi(self):
        with tempfile.TemporaryDirectory() as tmp:
            reference = np.zeros((100, 100, 3), dtype=np.uint8)
            path = Path(tmp) / "check.jpg"
            cv2.imwrite(str(path), reference)
            metadata = {
                "image_path": str(path),
                "threshold": 0.72,
                "roi": {"x": 0.2, "y": 0.2, "width": 0.6, "height": 0.6},
            }
            current = np.full((100, 100, 3), 255, dtype=np.uint8)
            current[20:80, 20:80] = 0
            result = check_module.avaliar_referencia_presenca_display(current, metadata)
            self.assertTrue(result["matched"])
            self.assertGreater(result["score"], 0.98)
            self.assertEqual(normalizar_roi_referencia(metadata["roi"]), result["roi"])

    def test_interfaces_expoem_selecao_de_area(self):
        # O botão pode ser inserido por uma extensão posterior do F3; o contrato
        # estável é a ação pública de seleção, não o texto literal dentro do
        # método base que monta o painel.
        self.assertTrue(
            hasattr(
                check_module.DisplayCheckManagerPresenceWindow,
                "select_presence_reference_roi",
            )
        )
        self.assertTrue(
            hasattr(
                visual_module.DisplayProjectConfigPresenceWindow,
                "select_project_presence_reference_roi",
            )
        )


if __name__ == "__main__":
    unittest.main()
