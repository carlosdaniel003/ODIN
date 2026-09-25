from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import numpy as np

import src.platform.display_check_presence_reference as check_module
import src.platform.display_reference_roi_runtime_fix as fix
import src.platform.display_visual_reference_status as visual_module
import src.platform.desktop_production_app as desktop_production_module


class _Repository:
    def __init__(self, root: Path) -> None:
        self.config_file = root / "odin_display_projects.json"
        self.config_file.write_text("{}", encoding="utf-8")
        self.project = {
            "name": "PROJETO A",
            "master_resolution": {"width": 120, "height": 80},
            "masks": [
                {
                    "id": "MASK_001",
                    "type": "circle",
                    "cx": 35,
                    "cy": 40,
                    "radius": 8,
                },
                {
                    "id": "MASK_002",
                    "type": "segment",
                    "cx": 80,
                    "cy": 40,
                    "width": 24,
                    "height": 8,
                    "angle": 0.0,
                },
            ],
        }

    def carregar_projeto(self, _name):
        return deepcopy(self.project)


class DisplayReferenceRoiRuntimeFixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repository = _Repository(self.root)
        fix.roi_module._PROJECT_MASK_CACHE.clear()
        fix.roi_module._UNION_CACHE.clear()
        fix._repair_store_bindings()
        self.frame = np.full((80, 120, 3), 90, dtype=np.uint8)

    def tearDown(self):
        self.temp.cleanup()

    def test_hook_aponta_para_composicao_desktop_canonica(self):
        self.assertIs(fix.production_app_module, desktop_production_module)
        self.assertTrue(
            callable(
                getattr(
                    fix.production_app_module,
                    "instalar_roi_referencias_display_f3",
                    None,
                )
            )
        )

    def test_check_capture_salva_e_reabre_com_mascaras(self):
        store = check_module.DisplayCheckPresenceReferenceStore(self.repository)
        metadata = store.capture(
            "PROJETO A",
            "CHECK_USB",
            self.frame,
            (120, 80),
        )
        self.assertIsInstance(metadata, dict)
        self.assertEqual(2, metadata["mask_region_count"])
        self.assertEqual("project_mask_union", metadata["comparison_mode"])
        self.assertTrue(Path(metadata["image_path"]).is_file())

        reopened = store.get("PROJETO A", "CHECK_USB")
        self.assertIsInstance(reopened, dict)
        self.assertEqual(2, reopened["mask_region_count"])

    def test_referencia_projeto_salva_e_reabre_com_mascaras(self):
        store = visual_module.DisplayProjectPresenceReferenceStore(self.repository)
        metadata = store.capture(
            "PROJETO A",
            visual_module.DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
            self.frame,
            (120, 80),
        )
        self.assertIsInstance(metadata, dict)
        self.assertEqual(2, metadata["mask_region_count"])
        self.assertTrue(Path(metadata["image_path"]).is_file())

        reopened = store.get(
            "PROJETO A",
            visual_module.DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
        )
        self.assertIsInstance(reopened, dict)
        self.assertEqual(2, reopened["mask_region_count"])

    def test_check_e_projeto_usam_persistencias_independentes(self):
        check_store = check_module.DisplayCheckPresenceReferenceStore(self.repository)
        project_store = visual_module.DisplayProjectPresenceReferenceStore(self.repository)

        check_store.capture("PROJETO A", "CHECK_USB", self.frame, (120, 80))
        project_store.capture(
            "PROJETO A",
            visual_module.DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
            self.frame,
            (120, 80),
        )

        self.assertIsNotNone(check_store.get("PROJETO A", "CHECK_USB"))
        self.assertIsNotNone(
            project_store.get(
                "PROJETO A",
                visual_module.DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
            )
        )
        self.assertIsNone(project_store.get("PROJETO A", "CHECK_USB"))


if __name__ == "__main__":
    unittest.main()
