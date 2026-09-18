from __future__ import annotations

import inspect
from pathlib import Path
import tempfile
import unittest

import numpy as np

import src.platform.display_auto_check_analyzer as analyzer
import src.platform.display_check_editor as check_editor
import src.platform.display_f3_tracking_orientation_ui as tracking_ui
import src.platform.display_f3_workspace_ui as workspace
import src.platform.display_visual_rotation as visual_rotation
import src.platform.display_reference_roi_runtime_fix as reference_runtime_fix
import src.platform.display_f3_exact_check_template as exact_template
import src.platform.display_f3_same_mask_reference_fix as same_mask
import src.platform.display_f3_preview_clarity_fix as preview_clarity
import src.platform.display_live_roi_overlay as live_overlay
import src.platform.display_check_presence_reference as check_presence
import src.platform.display_f3_reference_geometry_editor as reference_geometry_editor
import src.platform.display_f3_mask_editor_reference as mask_editor_reference
import src.platform.display_project_config as project_config
import src.platform.display_visual_reference_status as visual_reference_status
from src.platform.display_project_repository import DisplayProjectRepository
from src.platform.display_visual_reference_status import (
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
    DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
    DisplayProjectPresenceReferenceStore,
)


class DisplayF3GeometryAdjustmentTests(unittest.TestCase):
    def _repository(self, directory: str) -> DisplayProjectRepository:
        return DisplayProjectRepository(
            Path(directory) / "odin_display_projects.json"
        )

    def _project(self, repository: DisplayProjectRepository) -> tuple[str, str]:
        name = "DISPLAY TESTE"
        self.assertTrue(repository.adicionar_projeto(name, (640, 480)))
        masks = [
            {
                "id": "MASK_001",
                "type": "circle",
                "cx": 200,
                "cy": 180,
                "radius": 14,
            },
            {
                "id": "MASK_002",
                "type": "polygon",
                "points": [[300, 200], [340, 200], [340, 230], [300, 230]],
            },
            {
                "id": "MASK_003",
                "type": "segment",
                "cx": 430,
                "cy": 260,
                "width": 72,
                "height": 16,
                "angle": 18.0,
            },
        ]
        self.assertTrue(
            repository.salvar_configuracao_projeto(
                name,
                (640, 480),
                masks,
            )
        )
        existing = repository.listar_checks(name)
        check_id = (
            str(existing[0].get("id") or "")
            if existing
            else str(repository.adicionar_check(name, "H1") or "")
        )
        self.assertTrue(check_id)
        return name, check_id

    def test_check_geometry_roundtrip_is_local_to_check(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(directory)
            project_name, check_id = self._project(repository)
            board = [[50, 60], [590, 60], [590, 420], [50, 420]]
            overrides = {
                "MASK_001": {
                    "id": "MASK_001",
                    "type": "circle",
                    "cx": 206,
                    "cy": 184,
                    "radius": 16,
                },
                "MASK_003": {
                    "id": "MASK_003",
                    "type": "segment",
                    "cx": 438,
                    "cy": 266,
                    "width": 76,
                    "height": 18,
                    "angle": 19.0,
                },
            }
            self.assertTrue(
                repository.salvar_geometria_check(
                    project_name,
                    check_id,
                    board,
                    overrides,
                )
            )

            reopened = DisplayProjectRepository(repository.config_file)
            check = reopened.carregar_check(project_name, check_id)
            project = reopened.carregar_projeto(project_name)
            self.assertEqual(board, check["board_points_reference"])
            self.assertEqual(
                206,
                check["mask_overrides_reference"]["MASK_001"]["cx"],
            )
            self.assertEqual(
                "segment",
                check["mask_overrides_reference"]["MASK_003"]["type"],
            )
            self.assertEqual(
                19.0,
                check["mask_overrides_reference"]["MASK_003"]["angle"],
            )
            # A geometria canônica do Projeto Display permanece independente.
            self.assertEqual(200, project["masks"][0]["cx"])

    def test_board_off_accepts_geometry_but_empty_support_does_not(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(directory)
            project_name, _ = self._project(repository)
            store = DisplayProjectPresenceReferenceStore(repository)
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            self.assertIsNotNone(
                store.capture(
                    project_name,
                    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                    frame,
                    (640, 480),
                )
            )
            self.assertIsNotNone(
                store.capture(
                    project_name,
                    DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
                    frame,
                    (640, 480),
                )
            )
            board = [[40, 40], [600, 40], [600, 440], [40, 440]]
            masks = [
                {
                    "id": "MASK_001",
                    "type": "circle",
                    "cx": 205,
                    "cy": 181,
                    "radius": 15,
                }
            ]
            self.assertTrue(
                store.save_geometry(
                    project_name,
                    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                    board,
                    masks,
                )
            )
            self.assertFalse(
                store.save_geometry(
                    project_name,
                    DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
                    board,
                    masks,
                )
            )
            saved = store.get(
                project_name,
                DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
            )
            self.assertEqual(board, saved["board_points_reference"])
            self.assertEqual(
                205,
                saved["mask_overrides_reference"]["MASK_001"]["cx"],
            )

    def test_check_analyzer_applies_local_mask_overrides(self):
        source = inspect.getsource(analyzer.DisplayAutomaticCheckAnalyzer.analyze)
        self.assertIn("mascaras_geometria_check_display(project, check)", source)

    def test_final_f3_analysis_and_previews_use_effective_check_geometry(self):
        self.assertIn(
            "mascaras_geometria_check_display",
            inspect.getsource(exact_template),
        )
        self.assertIn(
            "mascaras_geometria_check_display",
            inspect.getsource(same_mask),
        )
        self.assertIn(
            "mascaras_geometria_check_display",
            inspect.getsource(preview_clarity),
        )
        self.assertIn(
            "mascaras_geometria_check_display",
            inspect.getsource(live_overlay),
        )

    def test_check_editor_exposes_board_and_mask_adjustment(self):
        source = Path(check_editor.__file__).read_text(encoding="utf-8")
        self.assertIn("AJUSTAR GEOMETRIA", source)
        self.assertIn("board_points", source)
        self.assertIn("mask_overrides", source)
        self.assertIn("on_save_geometry", source)
        self.assertIn("undo_geometry", source)
        self.assertIn("_geometry_wheel", source)
        self.assertIn("REDESENHAR PLACA", source)
        self.assertIn("geometry_draw_board_points", source)
        self.assertIn("_finish_redraw_board_geometry", source)

    def test_board_off_uses_geometry_only_rotation_style_editor(self):
        source = inspect.getsource(
            visual_reference_status.DisplayProjectConfigPresenceWindow.edit_board_off_geometry
        )
        self.assertIn("F3ReferenceGeometryEditor", source)
        self.assertNotIn("DisplayCheckMaskEditorWindow", source)
        self.assertNotIn("mask_states", source)

        editor_source = inspect.getsource(
            reference_geometry_editor.F3ReferenceGeometryEditor
        )
        self.assertIn("F3OrientationGeometryEditor", editor_source)
        self.assertIn("REDESENHAR PLACA", editor_source)
        self.assertNotIn("ACESO", editor_source)
        self.assertNotIn("APAGADO", editor_source)
        self.assertNotIn("IGNORAR", editor_source)

    def test_check_manager_has_internal_scroll_for_lower_actions(self):
        source = Path(check_editor.__file__).read_text(encoding="utf-8")
        self.assertIn("_check_detail_canvas", source)
        self.assertIn("detail_scrollbar", source)
        self.assertIn("scrollregion", source)

        presence_source = inspect.getsource(
            check_presence.DisplayCheckManagerPresenceWindow._install_presence_panel
        )
        self.assertIn("CAPTURAR FOTO DA CÂMERA", presence_source)

    def test_check_editor_keeps_save_action_in_fixed_footer(self):
        source = Path(check_editor.__file__).read_text(encoding="utf-8")
        self.assertIn("footer.pack(side=tk.BOTTOM", source)
        self.assertIn('text="SALVAR GEOMETRIA" if self.geometry_only else "SALVAR CHECK"', source)
        self.assertIn("footer_actions", source)

    def test_mask_editor_persists_static_reference_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(directory)
            project_name, _ = self._project(repository)
            store = mask_editor_reference.DisplayMaskEditorReferenceStore(repository)
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            frame[100:140, 120:180] = 255
            saved = store.save_frame(
                project_name,
                frame,
                (640, 480),
            )
            self.assertIsNotNone(saved)
            loaded = store.load_frame(project_name)
            self.assertIsNotNone(loaded)
            self.assertEqual((480, 640), loaded.shape[:2])
            self.assertGreater(int(loaded[120, 150].mean()), 200)

    def test_mask_settings_show_preview_capture_remove_and_shared_draw_editor(self):
        config_source = Path(project_config.__file__).read_text(encoding="utf-8")
        self.assertIn("mask_reference_preview", config_source)
        self.assertIn("Tirar foto com a câmera", config_source)
        self.assertIn("Remover foto", config_source)
        self.assertIn("Desenhar placa e máscaras", config_source)
        self.assertIn("capture_masks_reference_photo", config_source)
        self.assertIn("remove_masks_reference_photo", config_source)
        self.assertIn("draw_masks_geometry", config_source)
        self.assertIn("F3ReferenceGeometryEditor", config_source)
        self.assertIn("allow_mask_creation=True", config_source)
        self.assertIn("canonical_board_points", config_source)

        shared_editor = inspect.getsource(
            reference_geometry_editor.F3ReferenceGeometryEditor
        )
        self.assertIn("+ SEGMENTO", shared_editor)
        self.assertIn("+ CÍRCULO", shared_editor)
        self.assertIn("+ POR PONTOS", shared_editor)
        self.assertIn("REDESENHAR PLACA", shared_editor)

        rotation_source = inspect.getsource(
            visual_rotation.instalar_rotacao_visual_editor_mascaras_display
        )
        self.assertIn("self.draw_masks_geometry()", rotation_source)
        self.assertNotIn("DisplayMaskEditorWindow(", rotation_source)

    def test_orientation_preview_draws_after_thumbnail_resize(self):
        source = inspect.getsource(tracking_ui._build_tracking_config_class)
        resize_index = source.find("thumbnail = cv2.resize")
        draw_index = source.find("thumbnail = draw_reference_geometry")
        self.assertGreaterEqual(resize_index, 0)
        self.assertGreater(draw_index, resize_index)

    def test_check_editor_prefers_saved_check_photo_without_affecting_mask_editor(self):
        masks_source = inspect.getsource(
            visual_rotation.instalar_rotacao_visual_editor_mascaras_display
        )
        checks_source = inspect.getsource(
            visual_rotation.instalar_rotacao_visual_editor_check_display
        )
        self.assertNotIn("_presence_store", masks_source)
        self.assertNotIn("check_id", masks_source)
        self.assertIn("_presence_store", checks_source)
        self.assertIn('metadata.get("image_path")', checks_source)
        self.assertIn("self.frame_provider()", checks_source)

    def test_runtime_reference_recapture_preserves_board_off_geometry(self):
        source = inspect.getsource(reference_runtime_fix._project_store_capture)
        self.assertIn('"board_points_reference"', source)
        self.assertIn('"mask_overrides_reference"', source)
        self.assertIn("previous", source)

    def test_main_reasserts_final_reference_geometry_preview(self):
        main_path = Path(check_editor.__file__).parents[2] / "main_rpi.py"
        source = main_path.read_text(encoding="utf-8")
        self.assertIn(
            "instalar_rotacao_preview_referencias_display_f3()",
            source,
        )

    def test_workspace_does_not_use_real_fullscreen_or_native_zoom(self):
        source = inspect.getsource(workspace.maximizar_janela_workspace_f3)
        self.assertIn("fit_f3_toplevel", source)
        self.assertNotIn('state("zoomed")', source)
        self.assertNotIn('attributes("-zoomed"', source)
        self.assertNotIn('attributes("-fullscreen"', source)


if __name__ == "__main__":
    unittest.main()
