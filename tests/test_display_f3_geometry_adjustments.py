from __future__ import annotations

import inspect
from pathlib import Path
import tempfile
import unittest

import numpy as np

import src.platform.display_auto_check_analyzer as analyzer
import src.platform.display_check_editor as check_editor
import src.platform.display_f3_tracking_orientation_ui as tracking_ui
import src.platform.display_f3_object_tracking as tracking
import src.platform.display_f3_workspace_ui as workspace
import src.platform.display_visual_rotation as visual_rotation
import src.platform.display_reference_roi_runtime_fix as reference_runtime_fix
import src.platform.display_f3_exact_check_template as exact_template
import src.platform.display_f3_same_mask_reference_fix as same_mask
import src.platform.display_f3_preview_clarity_fix as preview_clarity
import src.platform.display_live_roi_overlay as live_overlay
from src.platform.display_mask_geometry import (
    mapear_slots_sete_segmentos_display,
    numero_mascara_display,
    sincronizar_formato_mascara_display,
)
import src.platform.display_check_presence_reference as check_presence
import src.platform.display_f3_reference_geometry_editor as reference_geometry_editor
import src.platform.display_f3_reference_preview_rotation as reference_preview_rotation
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

    def test_numero_visual_sempre_vem_do_mask_id_canonico(self):
        self.assertEqual("6", numero_mascara_display("MASK_006", 99))
        self.assertEqual("27", numero_mascara_display({"id": "MASK_027"}, 1))
        self.assertEqual("4", numero_mascara_display("SEM_NUMERO", 4))

    def test_layout_88_88_descobre_slots_pela_geometria_e_nao_pelo_numero(self):
        def rect(mask_id, cx, cy, w=18, h=8):
            return {
                "id": mask_id,
                "type": "polygon",
                "points": [
                    [cx - w / 2, cy - h / 2],
                    [cx + w / 2, cy - h / 2],
                    [cx + w / 2, cy + h / 2],
                    [cx - w / 2, cy + h / 2],
                ],
            }

        ids_per_digit = [
            ["MASK_001", "MASK_002", "MASK_003", "MASK_006", "MASK_004", "MASK_005", "MASK_007"],
            ["MASK_008", "MASK_009", "MASK_011", "MASK_010", "MASK_012", "MASK_013", "MASK_014"],
            ["MASK_015", "MASK_016", "MASK_017", "MASK_020", "MASK_018", "MASK_019", "MASK_021"],
            ["MASK_022", "MASK_023", "MASK_024", "MASK_027", "MASK_025", "MASK_026", "MASK_028"],
        ]
        slot_xy = {
            "a": (0, 0),
            "b": (24, 20),
            "c": (24, 60),
            "d": (0, 80),
            "e": (-24, 60),
            "f": (-24, 20),
            "g": (0, 40),
        }
        masks = []
        for digit_index, ids in enumerate(ids_per_digit):
            cx = 100 + digit_index * 110
            for segment_name, mask_id in zip(
                ("a", "b", "c", "d", "e", "f", "g"),
                ids,
            ):
                dx, dy = slot_xy[segment_name]
                if segment_name in {"b", "c", "e", "f"}:
                    masks.append(rect(mask_id, cx + dx, 100 + dy, w=8, h=22))
                else:
                    masks.append(rect(mask_id, cx + dx, 100 + dy, w=22, h=8))

        slots = mapear_slots_sete_segmentos_display(
            list(reversed(masks)),
            digit_count=4,
        )
        self.assertEqual(28, len(slots))
        self.assertEqual(
            ["MASK_006", "MASK_010", "MASK_020", "MASK_027"],
            [slots[3], slots[10], slots[17], slots[24]],
        )
        self.assertEqual(ids_per_digit[0], slots[0:7])
        self.assertEqual(ids_per_digit[1], slots[7:14])
        self.assertEqual(ids_per_digit[2], slots[14:21])
        self.assertEqual(ids_per_digit[3], slots[21:28])

    def test_check_e_referencias_usam_mask_id_canonico(self):
        check_source = Path(check_editor.__file__).read_text(encoding="utf-8")
        self.assertIn("nome_segmento_display(mask_id, index + 1)", check_source)
        self.assertNotIn("nome_segmento_display(index)", check_source)

        interaction_source = inspect.getsource(
            tracking_ui.F3GeometryEditorInteractionBase
        )
        self.assertIn("numero_mascara_display(mask, index)", interaction_source)
        self.assertIn("self._draw_mask_numbers()", interaction_source)

        reference_source = inspect.getsource(
            reference_geometry_editor.F3ReferenceGeometryEditor
        )
        self.assertIn(
            "numero_mascara_display",
            inspect.getsource(reference_geometry_editor._mask_display_number),
        )
        self.assertIn("F3GeometryEditorInteractionBase", reference_source)
        self.assertNotIn("F3OrientationGeometryEditor", reference_source)

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
                    "id": "MASK_002",
                    "type": "polygon",
                    "points": [[300, 200], [342, 200], [342, 232], [300, 232]],
                },
                {
                    "id": "MASK_004",
                    "type": "circle",
                    "cx": 205,
                    "cy": 181,
                    "radius": 15,
                },
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
                ["MASK_002", "MASK_004"],
                [mask["id"] for mask in saved["masks_reference"]],
            )
            self.assertNotIn(
                "MASK_001",
                {mask["id"] for mask in saved["masks_reference"]},
            )
            self.assertEqual(
                205,
                saved["mask_overrides_reference"]["MASK_004"]["cx"],
            )

    def test_tracking_store_exposes_only_canonical_board_geometry(self):
        source = inspect.getsource(tracking.F3TrackingConfigStore)
        self.assertIn("save_board_points", source)
        self.assertIn("_migrate_legacy_rotation_state", source)
        self.assertNotIn("def save_orientation(", source)
        self.assertNotIn("def orientations(", source)
        self.assertNotIn("F3_ORIENTATION_", source)

    def test_formato_canonico_triangular_substitui_override_circular_sem_perder_posicao(self):
        base = {
            "id": "MASK_001",
            "type": "polygon",
            "points": [[10, 10], [50, 10], [30, 45]],
        }
        local = {
            "id": "MASK_001",
            "type": "circle",
            "cx": 220,
            "cy": 180,
            "radius": 30,
        }
        synced = sincronizar_formato_mascara_display(base, local)
        self.assertEqual("polygon", synced["type"])
        self.assertEqual(3, len(synced["points"]))
        center_x = sum(point[0] for point in synced["points"]) / 3.0
        center_y = sum(point[1] for point in synced["points"]) / 3.0
        self.assertAlmostEqual(220.0, center_x, places=3)
        self.assertAlmostEqual(180.0, center_y, places=3)

    def test_segmento_desenhado_na_base_nao_vira_circulo_no_check(self):
        segment = reference_geometry_editor._segment_polygon_from_drag(
            100,
            100,
            190,
            100,
            "MASK_009",
        )
        local_circle = {
            "id": "MASK_009",
            "type": "circle",
            "cx": 310,
            "cy": 220,
            "radius": 35,
        }
        synced = sincronizar_formato_mascara_display(segment, local_circle)
        self.assertEqual("polygon", synced["type"])
        self.assertEqual(4, len(synced["points"]))

    def test_check_mantem_geometria_local_quando_formato_continua_triangular(self):
        base = {
            "id": "MASK_001",
            "type": "polygon",
            "points": [[10, 10], [50, 10], [30, 45]],
        }
        local = {
            "id": "MASK_001",
            "type": "polygon",
            "points": [[200, 180], [270, 190], [225, 250]],
        }
        synced = sincronizar_formato_mascara_display(base, local)
        self.assertEqual(local, synced)

    def test_check_effective_geometry_uses_project_shape_and_local_pose(self):
        from src.platform.display_project_repository import (
            mascaras_geometria_check_display,
        )
        project = {
            "masks": [
                {
                    "id": "MASK_001",
                    "type": "polygon",
                    "points": [[10, 10], [70, 10], [40, 50]],
                }
            ]
        }
        check = {
            "mask_overrides_reference": {
                "MASK_001": {
                    "id": "MASK_001",
                    "type": "circle",
                    "cx": 300,
                    "cy": 200,
                    "radius": 25,
                }
            }
        }
        effective = mascaras_geometria_check_display(project, check)
        self.assertEqual(1, len(effective))
        self.assertEqual("polygon", effective[0]["type"])
        self.assertEqual(3, len(effective[0]["points"]))

    def test_check_editor_and_live_overlay_share_canonical_shape_authority(self):
        editor_source = inspect.getsource(
            check_editor.DisplayCheckMaskEditorWindow.__init__
        )
        self.assertIn("sincronizar_formato_mascara_display", editor_source)
        overlay_source = inspect.getsource(live_overlay._overlay_context)
        self.assertIn("mascaras_geometria_check_display", overlay_source)

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

    def test_board_off_uses_geometry_only_canonical_editor(self):
        source = inspect.getsource(
            visual_reference_status.DisplayProjectConfigPresenceWindow.edit_board_off_geometry
        )
        self.assertIn("F3ReferenceGeometryEditor", source)
        self.assertIn("allow_mask_creation=True", source)
        self.assertNotIn("DisplayCheckMaskEditorWindow", source)
        self.assertNotIn("mask_states", source)

        editor_source = inspect.getsource(
            reference_geometry_editor.F3ReferenceGeometryEditor
        )
        self.assertIn("F3GeometryEditorInteractionBase", editor_source)
        self.assertNotIn("F3OrientationGeometryEditor", editor_source)
        self.assertIn("REDESENHAR PLACA", editor_source)
        self.assertNotIn("ACESO", editor_source)
        self.assertNotIn("APAGADO", editor_source)
        self.assertNotIn("IGNORAR", editor_source)

    def test_tracking_config_does_not_mount_rotation_geometry_slots(self):
        source = inspect.getsource(tracking_ui._build_tracking_config_class)
        self.assertIn("CONTORNO + SEGMENTOS LUMINOSOS", source)
        for removed in (
            "F3ReferenceGeometryEditor",
            "F3OrientationGeometryEditor",
            "masks_reference",
            "mask_overrides_reference",
            "orientation_90",
            "orientation_180",
            "orientation_270",
        ):
            self.assertNotIn(removed, source)

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

    def test_mask_preview_uses_same_visual_rotation_as_geometry_editor(self):
        config_source = Path(project_config.__file__).read_text(encoding="utf-8")
        self.assertIn(
            "obter_rotacao_visual_do_frame_provider",
            config_source,
        )
        self.assertIn(
            "preparar_check_visual_display(",
            config_source,
        )
        self.assertIn(
            "preparar_pontos_visuais_display(",
            config_source,
        )
        self.assertIn(
            'f"VISUAL {visual_rotation}°"',
            config_source,
        )

    def test_mask_settings_show_preview_capture_remove_and_shared_draw_editor(self):
        config_source = Path(project_config.__file__).read_text(encoding="utf-8")
        self.assertIn("mask_reference_preview", config_source)
        self.assertIn("Tirar foto com a câmera", config_source)
        self.assertIn("Remover foto", config_source)
        self.assertIn("Desenhar placa e máscaras", config_source)
        self.assertIn("capture_masks_reference_photo", config_source)
        self.assertIn("F3MaskReferenceCaptureWindow", config_source)
        self.assertIn("mask_capture_window", config_source)
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

    def test_static_mask_preview_uses_canonical_transformer_for_segments(self):
        config_source = Path(project_config.__file__).read_text(encoding="utf-8")
        self.assertIn("transform_mask", config_source)
        self.assertNotIn(
            "from src.platform.display_f3_object_tracking import (\n"
            "                F3TrackingConfigStore,\n"
            "                _transform_reference_mask,",
            config_source,
        )

        segment = {
            "id": "MASK_SEG",
            "type": "segment",
            "cx": 120,
            "cy": 90,
            "width": 60,
            "height": 14,
            "angle": 20.0,
        }
        transformed = tracking.transform_mask(
            segment,
            [[0.5, 0.0, 0.0], [0.0, 0.5, 0.0]],
        )
        self.assertIsNotNone(transformed)
        self.assertEqual("polygon", transformed["type"])
        self.assertGreaterEqual(len(transformed.get("points", [])), 3)

    def test_mask_photo_button_opens_visible_live_capture(self):
        capture_source = inspect.getsource(
            mask_editor_reference.F3MaskReferenceCaptureWindow
        )
        self.assertIn("AGUARDANDO FRAME DA CÂMERA", capture_source)
        self.assertIn("CÂMERA SEM FRAME", capture_source)
        self.assertIn('text="CAPTURAR"', capture_source)
        self.assertIn("self.frame_provider()", capture_source)
        self.assertIn("self.store.save_frame", capture_source)
        self.assertIn("self._render_latest()", capture_source)

    def test_tracking_config_has_no_rotation_slot_preview_style(self):
        source = inspect.getsource(tracking_ui._build_tracking_config_class)
        self.assertNotIn("F3_ORIENTATION_PREVIEW_STYLE_VERSION", source)
        self.assertNotIn("thumbnail = cv2.resize", source)
        self.assertNotIn("thumbnail = draw_reference_geometry", source)
        self.assertNotIn("_render_f3_tracking_slot", source)

    def test_board_presence_previews_share_mask_preview_geometry_style(self):
        source = inspect.getsource(
            reference_preview_rotation.preparar_preview_referencia_com_mascaras_f3
        )
        self.assertIn("draw_reference_geometry", source)
        self.assertIn("alpha=0.74", source)
        self.assertIn("board_thickness=2", source)
        self.assertIn("mask_thickness=1", source)

        metadata_source = inspect.getsource(
            reference_preview_rotation._metadata_com_mascaras_do_projeto
        )
        self.assertIn("canonical_board_points", metadata_source)
        self.assertIn("mask_overrides_reference", metadata_source)
        self.assertIn("masks_reference", metadata_source)

    def test_tracking_config_does_not_schedule_angular_thumbnail_pipeline(self):
        source = inspect.getsource(tracking_ui._build_tracking_config_class)
        self.assertNotIn("_schedule_f3_tracking_previews", source)
        self.assertNotIn("_render_f3_tracking_slot", source)
        self.assertNotIn("orientation_90", source)
        self.assertNotIn("orientation_180", source)
        self.assertNotIn("orientation_270", source)

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
        self.assertIn('"masks_reference"', source)
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
