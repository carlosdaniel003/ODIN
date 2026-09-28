from __future__ import annotations

import ast
import json
import inspect
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import src.platform.display_f3_object_tracking as tracking
import src.platform.display_f3_tracking_orientation_ui as tracking_ui
import src.platform.display_f3_preview_clarity_fix as preview_clarity
import src.platform.display_auto_check_runtime as auto_runtime
import src.platform.display_auto_check_policy as auto_policy


class F3ObjectTrackingIsolationTests(unittest.TestCase):
    def _store(self, directory: str):
        repository = SimpleNamespace(
            config_file=Path(directory) / "odin_display_projects.json"
        )
        return tracking.F3TrackingConfigStore(repository)

    def test_setting_uses_dedicated_f3_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            self.assertFalse(store.enabled())
            store.set_enabled(True)

            self.assertTrue(store.enabled())
            self.assertEqual(
                "odin_display_tracking.json",
                store.config_file.name,
            )
            self.assertTrue(store.config_file.is_file())
            self.assertNotEqual(
                tracking.F3_TRACKING_SETTING_KEY,
                "f2_object_tracking_enabled",
            )

    def test_tracking_sidecar_reuses_normalized_cache_until_file_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            store.set_enabled(True)
            first = store._load_shared()
            second = store._load_shared()
            self.assertIs(first, second)
            self.assertTrue(second[tracking.F3_TRACKING_SETTING_KEY])

            store.set_enabled(False)
            third = store._load_shared()
            self.assertIsNot(second, third)
            self.assertFalse(third[tracking.F3_TRACKING_SETTING_KEY])

    def test_f3_tracking_modules_do_not_import_f2_runtime(self):
        for module in (tracking, tracking_ui):
            tree = ast.parse(inspect.getsource(module))
            imported = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imported.append(str(node.module or ""))
            self.assertFalse(
                any(name.startswith("src.platform.f2") for name in imported),
                imported,
            )

    def test_tracking_sidecar_ignores_and_purges_legacy_rotation_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / tracking.F3_TRACKING_CONFIG_FILENAME
            legacy_image_dir = (
                Path(directory)
                / "display_tracking_orientations"
                / "display_teste"
            )
            legacy_image_dir.mkdir(parents=True)
            (legacy_image_dir / "orientation_90.png").write_bytes(b"legacy")
            config_file.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        tracking.F3_TRACKING_SETTING_KEY: True,
                        "projects": {
                            "DISPLAY TESTE": {
                                "board_points": [[10, 10], [300, 10], [300, 200], [10, 200]],
                                "orientations": {
                                    "orientation_90": {
                                        "image_path": str(
                                            legacy_image_dir / "orientation_90.png"
                                        ),
                                        "board_points_reference": [
                                            [10, 10],
                                            [200, 10],
                                            [200, 150],
                                            [10, 150],
                                        ],
                                        "masks_reference": [{"id": "MASK_001"}],
                                    }
                                },
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            store = self._store(directory)
            loaded = store._load_shared()
            project = loaded["projects"]["DISPLAY TESTE"]
            self.assertNotIn("orientations", project)
            self.assertEqual(4, len(project["board_points"]))
            self.assertFalse(
                (Path(directory) / "display_tracking_orientations").exists()
            )

            persisted = json.loads(config_file.read_text(encoding="utf-8"))
            self.assertEqual(2, persisted["schema_version"])
            self.assertTrue(persisted[tracking.F3_TRACKING_SETTING_KEY])
            self.assertNotIn("orientations", persisted["projects"]["DISPLAY TESTE"])

    def test_canonical_board_contour_persists_without_rotation_slots(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            contour = [[90, 70], [550, 70], [550, 410], [90, 410]]
            self.assertTrue(store.save_board_points("DISPLAY TESTE", contour))
            self.assertEqual(contour, store.board_points("DISPLAY TESTE"))
            self.assertNotIn("orientations", store.project("DISPLAY TESTE"))

    def test_check_reference_geometry_keeps_project_polygon_shape(self):
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
                    "cx": 200,
                    "cy": 180,
                    "radius": 25,
                }
            }
        }
        _board, masks = tracking._check_reference_geometry(project, check)
        self.assertEqual(1, len(masks))
        self.assertEqual("polygon", masks[0]["type"])
        self.assertEqual(3, len(masks[0]["points"]))

    def test_reference_pose_is_recovered_from_drawn_board_and_masks(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            project = {
                "name": "DISPLAY TESTE",
                "master_resolution": {"width": 640, "height": 480},
                "masks": [
                    {
                        "id": "MASK_001",
                        "type": "circle",
                        "cx": 190,
                        "cy": 170,
                        "radius": 12,
                    },
                    {
                        "id": "MASK_002",
                        "type": "circle",
                        "cx": 420,
                        "cy": 270,
                        "radius": 14,
                    },
                    {
                        "id": "MASK_003",
                        "type": "polygon",
                        "points": [[280, 120], [330, 120], [330, 145], [280, 145]],
                    },
                ],
                "checks": [],
            }
            canonical_board = [
                [90, 70],
                [550, 70],
                [550, 410],
                [90, 410],
            ]
            self.assertTrue(
                store.save_board_points("DISPLAY TESTE", canonical_board)
            )

            canonical_to_reference = cv2.getRotationMatrix2D(
                (320.0, 240.0),
                17.0,
                1.08,
            ).astype(np.float32)
            canonical_to_reference[0, 2] += 34.0
            canonical_to_reference[1, 2] -= 21.0

            reference_board = tracking.transform_points(
                canonical_board,
                canonical_to_reference,
            )
            reference_masks = [
                tracking.transform_mask(mask, canonical_to_reference)
                for mask in project["masks"]
            ]
            reference_masks = [
                mask for mask in reference_masks if mask is not None
            ]

            estimated = tracking.estimate_reference_to_canonical(
                project,
                store,
                reference_board,
                reference_masks,
            )
            self.assertIsNotNone(estimated)

            expected = cv2.invertAffineTransform(canonical_to_reference)
            probe = np.asarray(
                [[[140.0, 120.0]], [[510.0, 360.0]], [[320.0, 240.0]]],
                dtype=np.float32,
            )
            got_points = cv2.transform(probe, estimated)
            expected_points = cv2.transform(probe, expected)
            self.assertTrue(
                np.allclose(got_points, expected_points, atol=2.0),
                (got_points, expected_points),
            )

    def test_preview_live_e_reduzido_antes_do_overlay_sem_mudar_aspecto(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

        class _Window:
            @staticmethod
            def _get_canvas_size():
                return (640, 480)

        preview = tracking._fit_live_preview_before_overlay(
            frame,
            _Window(),
        )
        self.assertEqual((360, 640, 3), preview.shape)

    def test_preview_e_analise_tem_cadencias_separadas(self):
        self.assertLess(
            auto_runtime.DisplayAutomaticCheckF3Mixin.DISPLAY_F3_PREVIEW_INTERVAL_MS,
            auto_runtime.DisplayAutomaticCheckF3Mixin.DISPLAY_F3_ANALYSIS_INTERVAL_MS,
        )
        self.assertEqual(
            50,
            auto_runtime.DisplayAutomaticCheckF3Mixin.DISPLAY_F3_PREVIEW_INTERVAL_MS,
        )
        self.assertGreaterEqual(
            auto_runtime.DisplayAutomaticCheckF3Mixin.DISPLAY_F3_ANALYSIS_INTERVAL_MS,
            70,
        )

    def test_instancia_final_pula_orb_nos_frames_exclusivos_de_preview(self):
        source = inspect.getsource(
            tracking.instalar_autoridade_final_instancia_rastreamento_f3
        )
        self.assertIn("_display_auto_analysis_due_now", source)
        self.assertIn("_display_f3_skip_auto_analysis_this_preview", source)
        self.assertIn("if heavy_due:", source)

    def test_live_preview_never_prefers_worker_raw_frame(self):
        source = inspect.getsource(
            tracking.instalar_autoridade_final_instancia_rastreamento_f3
        )
        self.assertIn("source = frame", source)
        self.assertNotIn(
            "source = authority_frame if _valid_frame(authority_frame) else frame",
            source,
        )
        self.assertIn(
            "_display_f3_tracking_raw_authority_frame = raw_latest",
            source,
        )

    def test_tracking_result_age_blocks_multi_second_operational_decision(self):
        fresh = {
            "age_ms": 250.0,
            "frame_token": ("camera", 100),
        }
        stale_time = {
            "age_ms": 15000.0,
            "frame_token": ("camera", 100),
        }
        stale_gap = {
            "age_ms": 300.0,
            "frame_token": ("camera", 10),
        }
        self.assertTrue(
            tracking._tracking_result_operationally_fresh(
                fresh,
                ("camera", 104),
            )
        )
        self.assertFalse(
            tracking._tracking_result_operationally_fresh(
                stale_time,
                ("camera", 101),
            )
        )
        self.assertFalse(
            tracking._tracking_result_operationally_fresh(
                stale_gap,
                ("camera", 100),
            )
        )

    def test_cached_lock_never_promotes_held_pose_to_current_evidence(self):
        source = inspect.getsource(tracking.F3DisplayObjectTracker.align)
        self.assertIn(
            "evidence_current=bool(self.last_result.evidence_current)",
            source,
        )
        self.assertIn('reason="lock_held"', inspect.getsource(
            tracking.F3DisplayObjectTracker._held_lock_result
        ))

    def test_tracker_has_temporal_continuity_and_lock_hysteresis(self):
        source = inspect.getsource(tracking.F3DisplayObjectTracker)
        self.assertIn("_temporal_candidate", source)
        self.assertIn("cv2.calcOpticalFlowPyrLK", source)
        self.assertIn("_held_lock_result", source)
        self.assertIn("F3_TRACKING_LOCK_GRACE_FRAMES", source)
        self.assertIn("evidence_current=False", source)
        self.assertIn("locked_temporal", source)

    def test_multiview_bank_uses_structural_f3_sources_without_rotation_slots(self):
        source = inspect.getsource(
            tracking.F3DisplayObjectTracker._calibrated_reference_specs
        )
        self.assertIn('"mask_reference"', source)
        self.assertIn('"board_off"', source)
        self.assertIn('f"check:{check_id}"', source)

        configure_source = inspect.getsource(
            tracking.F3DisplayObjectTracker.configure
        )
        self.assertNotIn("F3_ORIENTATION_SLOTS", configure_source)
        self.assertNotIn("reference_geometry(project, self.store, slot, entry)", configure_source)
        self.assertNotIn('source_type="orientation"', configure_source)

    def test_held_lock_is_visual_only_and_blocks_automatic_decision(self):
        runtime_source = inspect.getsource(
            tracking.instalar_runtime_rastreamento_objetos_display_f3
        )
        self.assertIn('status.get("evidence_current"', runtime_source)
        self.assertIn("LOCK MANTIDO", runtime_source)
        gate_source = inspect.getsource(tracking._tracking_h1_power_gate)
        self.assertIn("evidence_current", gate_source)

    def test_runtime_uses_all_calibrated_f3_sources_and_live_geometry(self):
        source = inspect.getsource(tracking.F3DisplayObjectTracker._calibrated_reference_specs)
        self.assertIn('"mask_reference"', source)
        self.assertIn('"board_off"', source)
        self.assertIn('f"check:{check_id}"', source)

        runtime_source = inspect.getsource(
            tracking.instalar_runtime_rastreamento_objetos_display_f3
        )
        self.assertIn("_update_tracking_live_geometry(self, raw, result)", runtime_source)
        self.assertIn("_analysis_alignment_for_current_check", runtime_source)
        self.assertIn("analysis_aligned", runtime_source)

        preview_source = inspect.getsource(preview_clarity._project_preview_context)
        self.assertIn("_display_f3_tracking_live_geometry", preview_source)
        self.assertIn('"tracking_locked": True', preview_source)
        renderer_source = inspect.getsource(
            preview_clarity.renderizar_preview_claro_display_f3
        )
        self.assertIn('context.get("board_points")', renderer_source)
        self.assertIn("cv2.polylines", renderer_source)

    def test_live_preview_propagates_tracking_board_and_hides_fixed_fallback(self):
        context_source = inspect.getsource(preview_clarity._contexto_preview_claro)
        self.assertIn('result["board_points"]', context_source)
        self.assertIn('result["tracking_active"]', context_source)
        self.assertIn('result["tracking_locked"]', context_source)

        project_source = inspect.getsource(preview_clarity._project_preview_context)
        self.assertIn("tracking_runtime_enabled(app)", project_source)
        self.assertIn("Rastreamento ligado mas ainda sem LOCK", project_source)
        self.assertIn('"masks": ()', project_source)

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        rendered = preview_clarity.renderizar_preview_claro_display_f3(
            frame,
            {
                "resolution": (320, 240),
                "tracking_active": True,
                "tracking_locked": True,
                "board_points": (
                    (40, 40),
                    (280, 40),
                    (280, 200),
                    (40, 200),
                ),
                "masks": (
                    {
                        "id": "MASK_001",
                        "type": "circle",
                        "cx": 120,
                        "cy": 110,
                        "radius": 20,
                    },
                    {
                        "id": "MASK_002",
                        "type": "polygon",
                        "points": [[180, 90], [230, 90], [230, 120], [180, 120]],
                    },
                ),
                "expected_states": {},
                "classifications": {},
            },
        )
        self.assertGreater(int(np.count_nonzero(rendered)), 0)

    def test_display_readout_uses_same_semantic_context_as_live_rois(self):
        window_source = inspect.getsource(
            tracking.DisplayProductionF3Window
        ) if hasattr(tracking, "DisplayProductionF3Window") else ""
        clarity_source = inspect.getsource(
            preview_clarity._contexto_preview_claro
        )
        self.assertIn("set_display_readout_context", clarity_source)

        tracking_source = inspect.getsource(
            tracking.instalar_autoridade_final_instancia_rastreamento_f3
        )
        self.assertIn("set_display_readout_context", tracking_source)

    def test_display_readout_ng_covers_low_light_and_on_off_mismatch(self):
        from src.platform.display_production_f3_window import (
            DisplayProductionF3Window,
        )
        state = DisplayProductionF3Window._display_readout_semantic_state
        self.assertEqual("neutral", state("off", "on", False, ready=False))
        self.assertEqual("neutral", state("on", "off", True, ready=False))
        self.assertEqual("neutral", state("low_light", "on", True, ready=False))
        self.assertEqual("ng", state("low_light", "on", False, ready=True))
        self.assertEqual("ng", state("off", "on", False, ready=True))
        self.assertEqual("ng", state("on", "off", False, ready=True))
        self.assertEqual("ng", state("on", "on", True, ready=True))
        self.assertEqual("on", state("on", "on", False, ready=True))
        self.assertEqual("off", state("off", "off", False, ready=True))
        self.assertEqual("neutral", state("on", "ignore", False, ready=True))

    def test_display_readout_prefere_ordem_geometrica_canonica(self):
        from src.platform.display_production_f3_window import (
            DisplayProductionF3Window,
        )
        setter = inspect.getsource(
            DisplayProductionF3Window.set_display_readout_context
        )
        draw = inspect.getsource(
            DisplayProductionF3Window._draw_live_display_readout
        )
        self.assertIn('context.get("readout_slot_mask_ids")', setter)
        self.assertIn('context.get("mask_slots")', draw)

        context_source = inspect.getsource(preview_clarity._project_preview_context)
        self.assertIn("mapear_slots_sete_segmentos_display", context_source)
        self.assertIn("canonical_visual_masks", context_source)
        self.assertIn('"readout_slot_mask_ids"', context_source)

    def test_display_readout_is_fixed_28_segment_88_88_canvas(self):
        from src.platform.display_production_f3_window import (
            DisplayProductionF3Window,
        )
        slots = DisplayProductionF3Window._display_readout_mask_slots(
            [f"MASK_{index:03d}" for index in range(28, 0, -1)]
        )
        self.assertEqual("MASK_001", slots[0])
        self.assertEqual("MASK_007", slots[6])
        self.assertEqual("MASK_008", slots[7])
        self.assertEqual("MASK_014", slots[13])
        self.assertEqual("MASK_015", slots[14])
        self.assertEqual("MASK_021", slots[20])
        self.assertEqual("MASK_022", slots[21])
        self.assertEqual("MASK_028", slots[27])

        source = inspect.getsource(
            DisplayProductionF3Window._draw_live_display_readout
        )
        self.assertIn("slots[0:7]", source)
        self.assertIn("slots[7:14]", source)
        self.assertIn("slots[14:21]", source)
        self.assertIn("slots[21:28]", source)
        self.assertNotIn("bbox_mascara_display", source)
        self.assertNotIn("pontos_mascara_display", source)

    def test_display_readout_numbers_are_outside_fixed_segments_without_badge(self):
        from src.platform.display_production_f3_window import (
            DisplayProductionF3Window,
        )
        number_source = inspect.getsource(
            DisplayProductionF3Window._draw_fixed_segment_number
        )
        self.assertIn("create_text", number_source)
        self.assertNotIn("create_rectangle", number_source)
        self.assertIn('"a":', number_source)
        self.assertIn('"b":', number_source)
        self.assertIn('"g":', number_source)

    def test_display_readout_board_off_has_absolute_gray_priority(self):
        from src.platform.display_production_f3_window import (
            DisplayProductionF3Window,
        )
        source = inspect.getsource(
            DisplayProductionF3Window._draw_live_display_readout
        )
        self.assertIn('context.get("power_confirmed")', source)
        self.assertIn('context.get("power_off_confirmed")', source)
        self.assertIn('energy_state != "off"', source)
        self.assertNotIn('or context.get("has_any_on")', source)

        semantic = inspect.getsource(
            DisplayProductionF3Window._display_readout_semantic_state
        )
        self.assertLess(
            semantic.index("if not bool(ready)"),
            semantic.index('if current == "low_light"'),
        )

    def test_display_readout_reserves_space_between_numbered_digits(self):
        from src.platform.display_production_f3_window import (
            DisplayProductionF3Window,
        )
        source = inspect.getsource(
            DisplayProductionF3Window._draw_live_display_readout
        )
        self.assertIn("digit_gap = 44.0", source)
        self.assertIn("group_gap = 34.0", source)

        labels = inspect.getsource(
            DisplayProductionF3Window._draw_fixed_segment_number
        )
        self.assertIn("side_gutter = 8.0", labels)
        self.assertIn("vertical_gutter = 5.0", labels)

    def test_display_readout_palette_is_green_dark_green_gray_and_red(self):
        from src.platform.display_production_f3_window import (
            DisplayProductionF3Window,
        )
        self.assertEqual("#22C55E", DisplayProductionF3Window.DISPLAY_READOUT_ACTIVE)
        self.assertEqual("#1E293B", DisplayProductionF3Window.DISPLAY_READOUT_OFF)
        self.assertEqual("#64748B", DisplayProductionF3Window.DISPLAY_READOUT_INACTIVE)
        self.assertEqual("#EF4444", DisplayProductionF3Window.DISPLAY_READOUT_NG)

        clarity_source = inspect.getsource(preview_clarity._contexto_preview_claro)
        self.assertIn('result["power_confirmed"]', clarity_source)
        self.assertIn('result["power_off_confirmed"]', clarity_source)
        self.assertIn('result["energy_state"]', clarity_source)
        self.assertIn('result["readout_mask_ids"]', clarity_source)

    def test_tracking_preview_uses_classic_luminous_mask_presentation(self):
        source = inspect.getsource(
            tracking.instalar_autoridade_final_instancia_rastreamento_f3
        )
        self.assertIn("renderizar_preview_claro_display_f3", source)
        self.assertIn("_project_preview_context", source)
        self.assertIn("_mask_snapshot_for_current_check", source)
        self.assertIn('semantic_context["classifications"]', source)
        self.assertIn("MÁSCARA CLÁSSICA", source)
        self.assertIn("VERDE = LUZ IDENTIFICADA", source)

        context_source = inspect.getsource(
            preview_clarity._project_preview_context
        )
        self.assertIn('"live_luminous_only": True', context_source)
        self.assertIn('"luminous_mask_ids"', context_source)

    def test_live_semantic_renderer_draws_mask_numbers_without_solid_badge(self):
        renderer_source = inspect.getsource(
            preview_clarity.renderizar_preview_claro_display_f3
        )
        helper_source = inspect.getsource(
            preview_clarity._draw_live_mask_number
        )
        self.assertIn("_draw_live_mask_number", renderer_source)
        self.assertIn("cv2.putText", helper_source)
        self.assertNotIn("cv2.rectangle", helper_source)
        self.assertLessEqual(preview_clarity.F3_PREVIEW_CLEAR_ALPHA, 0.08)
        self.assertLessEqual(preview_clarity.F3_PREVIEW_ALERT_ALPHA, 0.20)
        self.assertIn("_draw_failure_badge", renderer_source)
        self.assertIn("_draw_display_zoom_inset", renderer_source)

    def test_h1_reference_gate_requires_real_on_evidence(self):
        helper = auto_runtime.DisplayAutomaticCheckF3Mixin._display_auto_has_reference_power_evidence

        off_analysis = {
            "ready": True,
            "approved": True,
            "mask_results": [
                {
                    "mask_id": "MASK_001",
                    "expected": "on",
                    "classified": "off",
                    "matched": True,
                    "confidence": 0.99,
                },
                {
                    "mask_id": "MASK_002",
                    "expected": "off",
                    "classified": "off",
                    "matched": True,
                    "confidence": 0.99,
                },
            ],
        }
        self.assertFalse(helper(off_analysis))

        powered_analysis = {
            "ready": True,
            "approved": True,
            "mask_results": [
                {
                    "mask_id": "MASK_001",
                    "expected": "on",
                    "classified": "on",
                    "matched": True,
                    "confidence": 0.99,
                },
                {
                    "mask_id": "MASK_002",
                    "expected": "off",
                    "classified": "off",
                    "matched": True,
                    "confidence": 0.99,
                },
            ],
        }
        self.assertTrue(helper(powered_analysis))

        decision = auto_policy.decidir_analise_display_f3(
            off_analysis,
            reference_gate=True,
        )
        self.assertEqual(
            auto_policy.DISPLAY_AUTO_DECISION_SEARCHING,
            decision["decision"],
        )
        self.assertFalse(decision["board_powered"])

    def test_final_tracking_power_gate_rejects_stale_or_unpowered_h1(self):
        context = {
            "project_name": "DISPLAY A",
            "check_id": "CHECK_001",
            "check_name": "H1",
            "current_index": 0,
        }
        analysis = {
            "ready": True,
            "project_name": "DISPLAY A",
            "check_id": "CHECK_001",
            "mask_results": [
                {
                    "mask_id": "MASK_001",
                    "expected": "on",
                    "classified": "on",
                    "matched": True,
                    "confidence": 0.99,
                }
            ],
        }
        app = SimpleNamespace(
            _display_f3_object_tracking_last_status={"locked": True},
            _display_auto_last_analysis=analysis,
            _display_auto_current_context=lambda: context,
            _display_f3_power_authority_status={
                "board_present": True,
                "decision_allowed": True,
                "energy": {
                    "powered_confirmed": True,
                    "raw_analysis_ready": True,
                    "powered_votes": 1,
                    "project_name": "DISPLAY A",
                    "check_id": "CHECK_OLD",
                },
            },
        )
        allowed, reason = tracking._tracking_h1_power_gate(app)
        self.assertFalse(allowed)
        self.assertEqual("energia_fisica_nao_confirmada", reason)

        app._display_f3_power_authority_status["energy"]["check_id"] = "CHECK_001"
        allowed, reason = tracking._tracking_h1_power_gate(app)
        self.assertTrue(allowed)
        self.assertEqual("h1_ligado_confirmado", reason)

        app._display_auto_last_analysis["mask_results"][0]["classified"] = "off"
        allowed, reason = tracking._tracking_h1_power_gate(app)
        self.assertFalse(allowed)
        self.assertEqual("h1_sem_segmento_aceso", reason)

    def test_tracking_installs_final_h1_cycle_fail_safe(self):
        source = inspect.getsource(
            tracking.instalar_runtime_rastreamento_objetos_display_f3
        )
        self.assertIn("_display_f3_auto_decision_in_progress", source)
        self.assertIn("_display_f3_tracking_h1_confirmed_cycle", source)
        self.assertIn("_display_f3_power_authority_status", source)
        self.assertIn("tracking_h1_power_guard", source)
        self.assertIn("tracking_h1_cycle_guard", source)

    def test_edge_template_fallback_recovers_board_translation(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = SimpleNamespace(
                config_file=Path(directory) / "odin_display_projects.json"
            )
            tracker = tracking.F3DisplayObjectTracker(repository)
            reference = np.zeros((240, 320, 3), dtype=np.uint8)
            cv2.rectangle(reference, (70, 55), (250, 185), (210, 210, 210), 3)
            cv2.circle(reference, (120, 110), 18, (255, 255, 255), 3)
            cv2.line(reference, (155, 75), (220, 160), (180, 180, 180), 4)
            cv2.putText(
                reference,
                "PCB",
                (135, 145),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            board = [[70, 55], [250, 55], [250, 185], [70, 185]]
            tracking_mask = tracking.build_tracking_mask(
                320,
                240,
                board,
                [],
            )
            refs = {}
            tracker._add_reference(
                refs,
                key="ref",
                image=reference,
                tracking_mask=tracking_mask,
                reference_to_canonical=np.asarray(
                    [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                    dtype=np.float32,
                ),
                angle=0.0,
                source_type="mask_reference",
                board_points=board,
            )
            self.assertIn("ref", refs)
            tracker.references = refs

            dx, dy = 28, -17
            current = cv2.warpAffine(
                reference,
                np.asarray(
                    [[1.0, 0.0, dx], [0.0, 1.0, dy]],
                    dtype=np.float32,
                ),
                (320, 240),
            )
            gray = tracker._gray(current)
            candidate = tracker._template_candidate(
                cv2.Canny(gray, 45, 135),
                "ref",
            )
            self.assertIsNotNone(candidate)
            self.assertEqual("edge_template", candidate.get("fallback"))
            matrix = np.asarray(candidate["matrix"], dtype=np.float32)
            self.assertAlmostEqual(-dx, float(matrix[0, 2]), delta=3.0)
            self.assertAlmostEqual(-dy, float(matrix[1, 2]), delta=3.0)

    def test_template_tracking_ignores_changed_display_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = SimpleNamespace(
                config_file=Path(directory) / "odin_display_projects.json"
            )
            tracker = tracking.F3DisplayObjectTracker(repository)
            reference = np.zeros((240, 320, 3), dtype=np.uint8)

            # Estrutura fixa da placa.
            cv2.rectangle(reference, (50, 45), (270, 195), (220, 220, 220), 3)
            cv2.line(reference, (65, 65), (65, 175), (180, 180, 180), 3)
            cv2.line(reference, (250, 65), (250, 175), (180, 180, 180), 3)

            # Segmento luminoso propositalmente excluído do tracking.
            segment = {
                "id": "MASK_024",
                "type": "polygon",
                "points": [[200, 150], [240, 150], [240, 162], [200, 162]],
            }
            cv2.rectangle(reference, (200, 150), (240, 162), (255, 255, 255), -1)
            board = [[50, 45], [270, 45], [270, 195], [50, 195]]
            tracking_mask = tracking.build_tracking_mask(
                320,
                240,
                board,
                [segment],
            )
            refs = {}
            tracker._add_reference(
                refs,
                key="check:BLUE",
                image=reference,
                tracking_mask=tracking_mask,
                reference_to_canonical=np.asarray(
                    [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                    dtype=np.float32,
                ),
                angle=0.0,
                source_type="check",
                board_points=board,
            )
            self.assertIn("check:BLUE", refs)
            self.assertIsNotNone(
                refs["check:BLUE"].get("template_support_mask")
            )
            tracker.references = refs

            # Frame atual: mesma placa transladada, mas MASK_024 apagada.
            current = reference.copy()
            cv2.rectangle(current, (195, 145), (245, 167), (0, 0, 0), -1)
            dx, dy = 18, -11
            current = cv2.warpAffine(
                current,
                np.asarray(
                    [[1.0, 0.0, dx], [0.0, 1.0, dy]],
                    dtype=np.float32,
                ),
                (320, 240),
            )

            gray = tracker._gray(current)
            candidate = tracker._template_candidate(
                cv2.Canny(gray, 45, 135),
                "check:BLUE",
                min_score=tracking.F3_TRACKING_CURRENT_CHECK_TEMPLATE_MIN_SCORE,
            )
            self.assertIsNotNone(candidate)
            self.assertTrue(candidate.get("template_masked_for_segments"))
            matrix = np.asarray(candidate["matrix"], dtype=np.float32)
            self.assertAlmostEqual(-dx, float(matrix[0, 2]), delta=4.0)
            self.assertAlmostEqual(-dy, float(matrix[1, 2]), delta=4.0)

    def test_board_off_recupera_lock_quando_check_atual_nao_localiza(self):
        class _Runtime:
            def __init__(self):
                self.ready = True
                self.references = {
                    "check:CHECK_001": {},
                    "board_off": {},
                }
                self.width = 320
                self.height = 240
                self.last_matrix = None
                self._last_reference = ""
                self.last_compute_s = 0.0
                self.last_frame_id = None
                self.last_gray = None
                self.last_verified_s = 0.0
                self.consecutive_misses = 0
                self.last_result = None
                self.calls = []

            def candidate_for_reference(
                self,
                frame,
                key,
                current_tracking_mask=None,
                *,
                template_min_score=None,
            ):
                self.calls.append((key, template_min_score))
                if key == "check:CHECK_001":
                    return None
                return {
                    "reference": "board_off",
                    "matrix": np.asarray(
                        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                        dtype=np.float32,
                    ),
                    "matches": 0,
                    "inliers": 0,
                    "ratio": 0.61,
                    "rotation_deg": 0.0,
                    "scale": 1.0,
                    "score": 6.88,
                    "source_type": "board_off",
                    "fallback": "edge_template",
                    "template_masked_for_segments": True,
                }

            @staticmethod
            def _candidate_rank(candidate):
                return float(candidate.get("score", 0.0) or 0.0)

            @staticmethod
            def _gray(image):
                return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        runtime = _Runtime()
        app = SimpleNamespace(
            camera_ultimo_frame_id=77,
            display_check_runtime=SimpleNamespace(
                snapshot=lambda: {
                    "current_check": {
                        "id": "CHECK_001",
                        "name": "H1",
                    }
                }
            ),
        )
        frame = np.zeros((240, 320, 3), dtype=np.uint8)

        result = tracking._rescue_current_check_tracking_lock(
            app,
            frame,
            runtime,
        )

        self.assertIsNotNone(result)
        self.assertTrue(result.locked)
        self.assertEqual("board_off", result.reference)
        self.assertEqual(
            "locked_board_off_template_rescue",
            result.reason,
        )
        self.assertEqual(
            ["check:CHECK_001", "board_off"],
            [item[0] for item in runtime.calls],
        )
        self.assertTrue(app._display_f3_tracking_rescue_debug["available"])
        self.assertEqual(
            "board_off",
            app._display_f3_tracking_rescue_debug["selected_reference"],
        )
        # A referência BOARD_OFF recupera apenas a pose. O resultado do tracker
        # não contém qualquer campo de energia/OK/NG.
        self.assertFalse(hasattr(result, "powered_confirmed"))
        self.assertFalse(hasattr(result, "off_confirmed"))

    @staticmethod
    def _rich_tracking_reference():
        image = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.rectangle(image, (65, 50), (255, 190), (210, 210, 210), 3)
        cv2.line(image, (80, 70), (235, 165), (180, 180, 180), 4)
        cv2.line(image, (82, 170), (230, 72), (150, 150, 150), 3)
        cv2.circle(image, (120, 105), 24, (255, 255, 255), 3)
        cv2.circle(image, (205, 135), 17, (190, 190, 190), 3)
        cv2.putText(
            image,
            "CM500",
            (105, 155),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (245, 245, 245),
            2,
            cv2.LINE_AA,
        )
        board = [[65, 50], [255, 50], [255, 190], [65, 190]]
        return image, board

    def test_reference_bank_adds_akaze_for_absolute_reacquisition(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = SimpleNamespace(
                config_file=Path(directory) / "odin_display_projects.json"
            )
            tracker = tracking.F3DisplayObjectTracker(repository)
            tracker.width = 320
            tracker.height = 240
            reference, board = self._rich_tracking_reference()
            mask = tracking.build_tracking_mask(320, 240, board, [])
            refs = {}
            tracker._add_reference(
                refs,
                key="ref",
                image=reference,
                tracking_mask=mask,
                reference_to_canonical=np.asarray(
                    [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                    dtype=np.float32,
                ),
                angle=0.0,
                source_type="board_off",
                board_points=board,
            )

            self.assertIn("ref", refs)
            self.assertIn("akaze_descriptors", refs["ref"])
            self.assertIn("akaze_canonical_points", refs["ref"])
            self.assertIsNotNone(refs["ref"]["akaze_descriptors"])
            self.assertGreaterEqual(
                len(refs["ref"]["akaze_canonical_points"]),
                tracking.F3_TRACKING_AKAZE_MIN_MATCHES,
            )

    def test_adaptive_template_reacquires_rotated_scaled_board(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = SimpleNamespace(
                config_file=Path(directory) / "odin_display_projects.json"
            )
            tracker = tracking.F3DisplayObjectTracker(repository)
            tracker.width = 320
            tracker.height = 240
            reference, board = self._rich_tracking_reference()
            mask = tracking.build_tracking_mask(320, 240, board, [])
            refs = {}
            tracker._add_reference(
                refs,
                key="board_off",
                image=reference,
                tracking_mask=mask,
                reference_to_canonical=np.asarray(
                    [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                    dtype=np.float32,
                ),
                angle=0.0,
                source_type="board_off",
                board_points=board,
            )
            tracker.references = refs

            known = cv2.getRotationMatrix2D(
                (160.0, 120.0),
                12.0,
                1.10,
            ).astype(np.float32)
            known[0, 2] += 18.0
            known[1, 2] -= 8.0
            current = cv2.warpAffine(
                reference,
                known,
                (320, 240),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_CONSTANT,
            )
            gray = tracker._gray(current)
            current_edges = cv2.Canny(gray, 45, 135)

            candidate = tracker._adaptive_template_candidate(
                current_edges,
                "board_off",
                min_score=0.24,
            )

            self.assertIsNotNone(candidate)
            self.assertEqual(
                "adaptive_edge_template",
                candidate.get("fallback"),
            )
            canonical_center = np.asarray(
                [[[160.0, 120.0]]],
                dtype=np.float32,
            )
            current_center = cv2.transform(
                canonical_center,
                known,
            )
            recovered = cv2.transform(
                current_center,
                np.asarray(
                    candidate["matrix"],
                    dtype=np.float32,
                ).reshape(2, 3),
            )
            error = float(
                np.linalg.norm(
                    recovered.reshape(2)
                    - canonical_center.reshape(2)
                )
            )
            self.assertLess(error, 12.0)

    def test_tracking_loss_invalidates_stale_mask_and_power_authority(self):
        app = SimpleNamespace(
            _display_auto_last_analysis={"approved": True},
            _display_f3_tracking_analysis_frame=object(),
            _display_f3_power_authority_status={
                "board_present": True,
                "presence": {"presence_confirmed": True},
                "energy": {
                    "energy_state": "powered",
                    "powered_confirmed": True,
                },
                "decision_allowed": True,
            },
            _display_f3_operational_state={
                "kind": "powered",
                "text": "PLACA NO SUPORTE • LIGADA",
                "allow_auto": True,
            },
        )

        tracking._invalidate_spatial_authority_after_tracking_loss(
            app,
            "object_not_locked",
        )

        self.assertIsNone(app._display_auto_last_analysis)
        self.assertIsNone(app._display_f3_tracking_analysis_frame)
        status = app._display_f3_power_authority_status
        self.assertFalse(status["decision_allowed"])
        self.assertFalse(status["energy"]["powered_confirmed"])
        self.assertFalse(status["energy"]["off_confirmed"])
        self.assertEqual("unconfirmed", status["energy"]["energy_state"])
        self.assertEqual("object_not_locked", status["reason"])
        self.assertEqual(
            "unknown",
            app._display_f3_operational_state["kind"],
        )
        self.assertFalse(
            app._display_f3_operational_state["allow_auto"]
        )

    def test_final_instance_authority_bypasses_historical_f3_wrappers(self):
        source = inspect.getsource(
            tracking.instalar_autoridade_final_instancia_rastreamento_f3
        )
        self.assertIn("app._atualizar_preview_display_f3 = MethodType", source)
        self.assertIn("window.update_camera_preview = MethodType", source)
        self.assertIn("sequence.registrar_resultado_check = MethodType", source)
        self.assertIn("_tracking_h1_power_gate(app)", source)
        self.assertIn("_display_f3_tracking_raw_authority_frame", source)
        self.assertNotIn("self.camera_frame_atual = pending_frame", source)
        self.assertIn("_display_auto_analysis_frame_override", source)
        self.assertIn("_display_f3_tracking_instance_frame_prepared", source)

        main_source = Path("main_desktop.py").read_text(encoding="utf-8")
        self.assertIn("app = DesktopProductionApp(root)", main_source)
        self.assertIn(
            "instalar_autoridade_final_instancia_rastreamento_f3(app)",
            main_source,
        )

    def test_tracking_renderer_draws_moving_board_and_all_masks(self):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        geometry = {
            "locked": True,
            "resolution": (320, 240),
            "board_points": [[50, 45], [270, 45], [270, 195], [50, 195]],
            "masks": [
                {
                    "id": "A",
                    "type": "circle",
                    "cx": 110,
                    "cy": 110,
                    "radius": 14,
                },
                {
                    "id": "B",
                    "type": "polygon",
                    "points": [[180, 90], [225, 90], [225, 120], [180, 120]],
                },
            ],
        }
        rendered = tracking._draw_tracking_geometry_visual(frame, geometry, 0)
        self.assertGreater(int(np.count_nonzero(rendered)), 0)
        # Move a geometria: o desenho precisa mudar junto, não permanecer fixo.
        moved = dict(geometry)
        moved["board_points"] = [
            [p[0] + 20, p[1] + 10] for p in geometry["board_points"]
        ]
        moved["masks"] = [
            tracking.transform_mask(
                mask,
                np.asarray(
                    [[1.0, 0.0, 20.0], [0.0, 1.0, 10.0]],
                    dtype=np.float32,
                ),
            )
            for mask in geometry["masks"]
        ]
        rendered_moved = tracking._draw_tracking_geometry_visual(
            frame,
            moved,
            0,
        )
        self.assertFalse(np.array_equal(rendered, rendered_moved))

    def test_tracking_mask_excludes_display_segments(self):
        board = [[80, 80], [560, 80], [560, 400], [80, 400]]
        masks = [
            {
                "id": "MASK_001",
                "type": "circle",
                "cx": 320,
                "cy": 240,
                "radius": 24,
            }
        ]
        result = tracking.build_tracking_mask(640, 480, board, masks)
        self.assertIsNotNone(result)
        self.assertEqual(0, int(result[240, 320]))
        self.assertGreater(int(result[140, 140]), 0)
        self.assertEqual(0, int(result[20, 20]))

    def test_tracking_keeps_operator_preview_on_raw_camera(self):
        source = inspect.getsource(
            tracking.instalar_runtime_rastreamento_objetos_display_f3
        )
        self.assertIn("_display_f3_tracking_raw_preview_frame", source)
        self.assertIn("base_preview_with_raw_camera", source)
        self.assertIn(
            "DisplayProductionF3Mixin._atualizar_preview_display_f3",
            source,
        )

    def test_disabled_runtime_has_literal_legacy_bypass(self):
        source = inspect.getsource(
            tracking.instalar_runtime_rastreamento_objetos_display_f3
        )
        self.assertIn("if not tracking_enabled(self)", source)
        self.assertIn("return preview_previous(self)", source)
        self.assertIn(
            "DisplayAutomaticCheckF3Mixin._atualizar_preview_display_f3",
            source,
        )


    def test_live_tracking_heavy_compute_runs_through_high_priority_executor(self):
        installer = inspect.getsource(
            tracking.instalar_autoridade_final_instancia_rastreamento_f3
        )
        submitter = inspect.getsource(tracking._submit_live_tracking_job)
        worker = inspect.getsource(tracking._run_live_tracking_heavy_job)

        self.assertIn("_submit_live_tracking_job(self, raw_latest)", installer)
        self.assertNotIn("align_frame_for_f3(self, raw_latest)", installer)
        self.assertIn("F3HeavyWorkPriority.HIGH", submitter)
        self.assertIn("replace_pending=True", submitter)
        self.assertIn("align_frame_for_f3(app, raw_frame)", worker)
        self.assertIn("_analysis_alignment_for_current_check", worker)

    def test_semantic_worker_preserva_raw_e_geometria_do_mesmo_tracking_snapshot(self):
        raw = np.zeros((40, 60, 3), dtype=np.uint8)
        aligned = np.ones((40, 60, 3), dtype=np.uint8)
        geometry = {
            "locked": True,
            "resolution": (60, 40),
            "geometry_space": "check:CHECK_001",
            "reference": "check:CHECK_001",
            "masks": [{"id": "MASK_001"}],
        }

        class _Analyzer:
            def __init__(self):
                self.snapshot_kwargs = None

            def analyze_tracking_snapshot(self, **kwargs):
                self.snapshot_kwargs = kwargs
                return {
                    "ready": True,
                    "approved": True,
                    "live_geometry_override": True,
                    "analysis_frame_source": (
                        "tracking_raw_with_live_geometry"
                    ),
                }

            def analyze(self, **_kwargs):
                raise AssertionError(
                    "worker nao pode voltar ao estado mutavel do app"
                )

        analyzer = _Analyzer()
        payload = tracking._run_live_semantic_job(
            analyzer,
            aligned,
            raw,
            geometry,
            {
                "project_name": "DISPLAY A",
                "check_id": "CHECK_001",
            },
            180,
            7,
            ("camera", 123),
            0.0,
            0.0,
        )

        self.assertIs(raw, analyzer.snapshot_kwargs["raw_frame"])
        self.assertIs(aligned, analyzer.snapshot_kwargs["analysis_frame"])
        self.assertEqual(
            geometry,
            analyzer.snapshot_kwargs["tracking_geometry"],
        )
        self.assertTrue(payload["analysis"]["live_geometry_override"])
        self.assertEqual(
            "tracking_raw_with_live_geometry",
            payload["analysis"]["analysis_frame_source"],
        )

    def test_semantic_check_analysis_also_runs_in_heavy_executor(self):
        installer = inspect.getsource(
            tracking.instalar_autoridade_final_instancia_rastreamento_f3
        )
        submitter = inspect.getsource(tracking._submit_live_semantic_job)
        worker = inspect.getsource(tracking._run_live_semantic_job)
        process = inspect.getsource(auto_runtime.DisplayAutomaticCheckF3Mixin._process_display_auto_check)

        self.assertIn("_submit_live_semantic_job(", installer)
        self.assertIn("F3HeavyWorkPriority.HIGH", submitter)
        self.assertIn('name="f3-live-semantic"', submitter)
        self.assertIn("analyzer.analyze(", worker)
        self.assertIn("_display_auto_precomputed_payload", process)
        self.assertIn("_display_auto_analysis_frame_override", process)

    def test_semantic_apply_never_replaces_visible_camera_with_old_frame(self):
        source = inspect.getsource(
            tracking.instalar_autoridade_final_instancia_rastreamento_f3
        )
        self.assertNotIn("self.camera_frame_atual = pending_frame", source)
        self.assertIn(
            "Preview usa camera_frame_atual (latest)",
            source,
        )

    def test_config_open_invalidates_live_tracking_before_build(self):
        from src.platform.display_production_f3 import DisplayProductionF3Mixin

        source = inspect.getsource(
            DisplayProductionF3Mixin.abrir_configuracao_projeto_display
        )
        self.assertIn("reset_tracking_runtime(self)", source)
        self.assertLess(
            source.index("reset_tracking_runtime(self)"),
            source.index("self.root.after(1, build)"),
        )

    def test_tracking_reset_cancels_pending_executor_work(self):
        source = inspect.getsource(tracking.reset_tracking_runtime)
        self.assertIn("cancel_owner(F3_TRACKING_EXECUTOR_OWNER)", source)
        self.assertIn("_display_f3_tracking_job_generation", source)
        self.assertIn("_display_f3_tracking_future = None", source)

    def test_live_geometry_uses_canonical_shape_without_check_local_warp(self):
        source = inspect.getsource(tracking._update_tracking_live_geometry)
        self.assertIn("canonical_board_points", source)
        self.assertIn("project.get(\"masks\"", source)
        self.assertIn("sincronizar_formato_mascara_display", source)
        self.assertNotIn("_check_reference_geometry", source)
        self.assertNotIn("_analysis_transform_for_current_check", source)
        self.assertNotIn("_analysis_alignment_for_current_check", source)

    def test_luminous_tracking_uses_canonical_mask_geometry(self):
        source = inspect.getsource(
            tracking._canonical_check_masks_for_luminous_tracking
        )
        self.assertIn("canonical_masks", source)
        self.assertIn('project.get("masks"', source)
        self.assertNotIn("mask_overrides_reference", source)
        self.assertNotIn("reference_to_canonical", source)

        rescue = inspect.getsource(
            tracking._rescue_luminous_segment_tracking_lock
        )
        self.assertIn('fit_space = "canonical"', rescue)
        self.assertNotIn("canonical_to_fit", rescue)
        self.assertNotIn("fit_to_canonical", rescue)

    def test_rotation_anchor_rejects_90_degree_pose_flip(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = SimpleNamespace(
                config_file=Path(directory) / "odin_display_projects.json"
            )
            tracker = tracking.F3DisplayObjectTracker(repository)
            tracker.last_verified_rotation_deg = 0.0

            stable = {
                "reference": "check:CHECK_001",
                "matrix": cv2.getRotationMatrix2D(
                    (320.0, 240.0),
                    8.0,
                    1.0,
                ).astype(np.float32),
                "rotation_deg": -8.0,
            }
            wrong_90 = {
                "reference": "board_off",
                "matrix": cv2.getRotationMatrix2D(
                    (320.0, 240.0),
                    90.0,
                    1.0,
                ).astype(np.float32),
                "rotation_deg": -90.0,
            }

            accepted = tracker._filter_abrupt_rotation_candidates(
                [wrong_90, stable],
                source="test",
            )

            self.assertEqual(1, len(accepted))
            self.assertIs(stable, accepted[0])
            self.assertEqual(
                "abrupt_rotation_jump_rejected",
                tracker._last_rotation_jump_rejections[-1]["reason"],
            )
            self.assertGreater(
                tracker._last_rotation_jump_rejections[-1][
                    "rotation_delta_deg"
                ],
                80.0,
            )

    def test_rotation_anchor_survives_temporary_lock_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = SimpleNamespace(
                config_file=Path(directory) / "odin_display_projects.json"
            )
            tracker = tracking.F3DisplayObjectTracker(repository)
            tracker.last_verified_rotation_deg = 3.0
            tracker.last_matrix = None

            vertical = cv2.getRotationMatrix2D(
                (320.0, 240.0),
                90.0,
                1.0,
            ).astype(np.float32)
            compatible, delta = tracker._rotation_anchor_compatible(
                vertical
            )

            self.assertFalse(compatible)
            self.assertGreater(delta, 80.0)

            tracker.reset()
            compatible, _delta = tracker._rotation_anchor_compatible(
                vertical
            )
            self.assertTrue(compatible)

    def test_structural_and_luminous_rescues_use_rotation_anchor(self):
        structural = inspect.getsource(
            tracking._rescue_current_check_tracking_lock
        )
        luminous = inspect.getsource(
            tracking._rescue_luminous_segment_tracking_lock
        )
        self.assertIn(
            "_filter_abrupt_rotation_candidates",
            structural,
        )
        self.assertIn(
            "_rotation_anchor_compatible",
            luminous,
        )
        self.assertIn(
            "luminous_pose_rotation_jump_rejected",
            luminous,
        )

    def test_luminous_refinement_guard_rejects_large_twist(self):
        board = [[100, 100], [500, 100], [500, 300], [100, 300]]
        coarse = np.asarray(
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            dtype=np.float32,
        )
        allowed = coarse.copy()
        allowed[0, 2] = 18.0
        allowed[1, 2] = -10.0
        ok, details = tracking._luminous_refinement_within_coarse_guard(
            allowed,
            coarse,
            board,
        )
        self.assertTrue(ok, details)

        center = (300.0, 200.0)
        twisted = cv2.getRotationMatrix2D(center, 28.0, 1.0).astype(
            np.float32
        )
        ok, details = tracking._luminous_refinement_within_coarse_guard(
            twisted,
            coarse,
            board,
        )
        self.assertFalse(ok)
        self.assertEqual(
            "refinement_outside_structural_guard",
            details["reason"],
        )


    def test_tracking_search_preview_skips_semantic_project_render_until_lock(self):
        source = inspect.getsource(
            tracking.instalar_autoridade_final_instancia_rastreamento_f3
        )
        self.assertIn("if not locked:", source)
        self.assertIn(
            "não recarregue projeto",
            source,
        )
        no_lock = source.split("if not locked:", 1)[1].split("else:", 1)[0]
        self.assertNotIn("_project_preview_context", no_lock)
        self.assertNotIn("renderizar_preview_claro_display_f3", no_lock)



    @staticmethod
    def _luminous_tracking_scene(*, missing_index: int | None = None):
        width, height = 640, 480
        canonical_board = [
            [120.0, 150.0],
            [520.0, 150.0],
            [520.0, 310.0],
            [120.0, 310.0],
        ]
        expected_centers = [
            [185.0, 190.0],
            [225.0, 245.0],
            [275.0, 190.0],
            [330.0, 245.0],
            [380.0, 190.0],
            [430.0, 245.0],
            [475.0, 190.0],
        ]
        rows = [
            {
                "mask_id": f"MASK_{index + 1:03d}",
                "center": center,
            }
            for index, center in enumerate(expected_centers)
        ]

        frame = np.full((height, width, 3), 175, dtype=np.uint8)
        filter_to_current = cv2.getRotationMatrix2D(
            (320.0, 230.0),
            -7.0,
            0.96,
        ).astype(np.float32)
        filter_to_current[0, 2] += 18.0
        filter_to_current[1, 2] += 24.0
        filter_points = tracking.transform_points(
            canonical_board,
            filter_to_current,
        )
        cv2.fillConvexPoly(
            frame,
            np.rint(np.asarray(filter_points)).astype(np.int32),
            (18, 18, 18),
            lineType=cv2.LINE_AA,
        )

        # O display se move alguns pixels em relação ao próprio filtro. A pose
        # final precisa vir dos segmentos luminosos, não do offset do retângulo.
        display_to_current = filter_to_current.copy()
        display_to_current[0, 2] += 26.0
        display_to_current[1, 2] -= 11.0

        canonical = np.asarray(expected_centers, dtype=np.float32).reshape(-1, 1, 2)
        observed = cv2.transform(
            canonical,
            display_to_current,
        ).reshape(-1, 2)
        for index, point in enumerate(observed):
            if missing_index is not None and index == int(missing_index):
                continue
            cx, cy = int(round(float(point[0]))), int(round(float(point[1])))
            cv2.rectangle(
                frame,
                (cx - 12, cy - 4),
                (cx + 12, cy + 4),
                (250, 250, 250),
                -1,
            )

        # Emissão extra simula segmento indevido/reflexo: ela não pode impedir
        # o encaixe do padrão esperado.
        extra = cv2.transform(
            np.asarray([[[455.0, 275.0]]], dtype=np.float32),
            display_to_current,
        ).reshape(2)
        ex, ey = int(round(float(extra[0]))), int(round(float(extra[1])))
        cv2.rectangle(
            frame,
            (ex - 12, ey - 4),
            (ex + 12, ey + 4),
            (245, 245, 245),
            -1,
        )
        return (
            frame,
            canonical_board,
            rows,
            filter_to_current,
            display_to_current,
            observed,
        )

    def test_luminous_segments_refine_pose_inside_moving_filter(self):
        (
            frame,
            canonical_board,
            rows,
            filter_to_current,
            display_to_current,
            observed,
        ) = self._luminous_tracking_scene()

        coarse_current_to_canonical = cv2.invertAffineTransform(
            filter_to_current
        )
        result = tracking._find_luminous_segment_pose(
            frame,
            canonical_board,
            rows,
            (640, 480),
            base_matrix=coarse_current_to_canonical,
        )

        self.assertTrue(result["available"], result)
        self.assertGreaterEqual(result["matched_count"], 6)
        self.assertEqual("tracked_filter", result["filter_source"])

        estimated = np.asarray(result["matrix"], dtype=np.float32).reshape(2, 3)
        recovered = cv2.transform(
            observed.reshape(-1, 1, 2),
            estimated,
        ).reshape(-1, 2)
        canonical = np.asarray(
            [row["center"] for row in rows],
            dtype=np.float32,
        )
        error = np.linalg.norm(recovered - canonical, axis=1)
        self.assertLess(float(np.median(error)), 6.0)

        # A transformação final deve acompanhar o display, que foi deslocado
        # em relação ao filtro, e não permanecer na pose grosseira do contorno.
        coarse_recovered = cv2.transform(
            observed.reshape(-1, 1, 2),
            coarse_current_to_canonical,
        ).reshape(-1, 2)
        coarse_error = np.linalg.norm(coarse_recovered - canonical, axis=1)
        self.assertLess(
            float(np.median(error)),
            float(np.median(coarse_error)),
        )

    def test_luminous_grid_survives_missing_expected_on_and_extra_light(self):
        (
            frame,
            canonical_board,
            rows,
            _filter_to_current,
            _display_to_current,
            _observed,
        ) = self._luminous_tracking_scene(missing_index=3)

        result = tracking._find_luminous_segment_pose(
            frame,
            canonical_board,
            rows,
            (640, 480),
        )

        self.assertTrue(result["available"], result)
        self.assertGreaterEqual(result["matched_count"], 5)
        self.assertIn(
            "MASK_004",
            result["missing_expected_on_mask_ids"],
        )
        self.assertGreaterEqual(
            result["luminous_component_count"],
            result["matched_count"],
        )

    def test_luminous_blooming_recovers_expected_on_landmarks_with_structural_lock(self):
        board = [
            [100.0, 120.0],
            [540.0, 120.0],
            [540.0, 330.0],
            [100.0, 330.0],
        ]
        centers = [
            [180.0, 175.0],
            [230.0, 250.0],
            [285.0, 175.0],
            [340.0, 250.0],
            [390.0, 175.0],
            [445.0, 250.0],
            [490.0, 175.0],
        ]
        rows = [
            {
                "mask_id": f"MASK_{index + 1:03d}",
                "center": center,
            }
            for index, center in enumerate(centers)
        ]
        frame = np.full((480, 640, 3), 170, dtype=np.uint8)
        cv2.fillConvexPoly(
            frame,
            np.rint(np.asarray(board)).astype(np.int32),
            (18, 18, 18),
            lineType=cv2.LINE_AA,
        )
        for cx, cy in centers:
            cv2.rectangle(
                frame,
                (int(cx) - 10, int(cy) - 4),
                (int(cx) + 10, int(cy) + 4),
                (250, 250, 250),
                -1,
            )

        # Reproduz a condição observada no equipamento: blooming/morfologia
        # devolvem só 4 componentes globais e apenas 3 encaixam; o quorum H1
        # continua sendo 4, então somente dividir a emissão local pode recuperar
        # a geometria sem afrouxar a regra.
        global_components = [
            centers[0],
            centers[1],
            centers[2],
            [115.0, 315.0],
        ]
        identity = np.asarray(
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            dtype=np.float32,
        )
        with patch.object(
            tracking,
            "_detect_luminous_segment_centers",
            return_value={
                "available": True,
                "reason": "luminous_segments_detected",
                "centers": global_components,
                "threshold_v": 120.0,
                "dynamic_range": 220.0,
            },
        ):
            result = tracking._find_luminous_segment_pose(
                frame,
                board,
                rows,
                (640, 480),
                base_matrix=identity,
            )

        self.assertTrue(result["available"], result)
        self.assertEqual(4, result["luminous_component_count"])
        self.assertGreaterEqual(
            result["local_luminous_landmark_count"],
            4,
        )
        self.assertGreaterEqual(result["matched_count"], 4)
        self.assertEqual(
            "expected_on_local_emission",
            result["fit_landmark_source"],
        )
        self.assertEqual("", result["fit_diagnostics"]["failure_stage"])

    def test_luminous_fit_diagnostics_explain_coarse_failure(self):
        board = [
            [0.0, 0.0],
            [100.0, 0.0],
            [100.0, 100.0],
            [0.0, 100.0],
        ]
        rows = [
            {"mask_id": "MASK_001", "center": [20.0, 20.0]},
            {"mask_id": "MASK_002", "center": [50.0, 20.0]},
            {"mask_id": "MASK_003", "center": [80.0, 20.0]},
        ]
        observed = [
            [300.0, 300.0],
            [330.0, 300.0],
            [360.0, 300.0],
        ]
        diagnostics = {}
        result = tracking._fit_luminous_pose(
            board,
            rows,
            observed,
            [
                np.asarray(
                    [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                    dtype=np.float32,
                )
            ],
            diagnostics=diagnostics,
        )

        self.assertIsNone(result)
        self.assertEqual(3, diagnostics["expected_on_count"])
        self.assertEqual(3, diagnostics["observed_component_count"])
        self.assertEqual(1, diagnostics["hypothesis_count"])
        self.assertEqual(0, diagnostics["best_coarse_match_count"])
        self.assertEqual(
            "coarse_matches_insufficient",
            diagnostics["failure_stage"],
        )
        self.assertEqual(3, len(diagnostics["expected_centers"]))
        self.assertEqual(3, len(diagnostics["observed_centers"]))

    def test_luminous_grid_failure_preserves_observed_components_in_telemetry(self):
        frame = np.full((120, 160, 3), 20, dtype=np.uint8)
        board = [
            [20.0, 30.0],
            [140.0, 30.0],
            [140.0, 90.0],
            [20.0, 90.0],
        ]
        rows = [
            {
                "mask_id": f"MASK_{index:03d}",
                "center": [35.0 + index * 12.0, 55.0],
            }
            for index in range(1, 8)
        ]
        centers = [
            [30.0 + index * 9.0, 58.0 + (index % 2) * 4.0]
            for index in range(10)
        ]

        def failed_fit(
            _board,
            _rows,
            _centers,
            _matrices,
            diagnostics=None,
        ):
            diagnostics.update(
                {
                    "expected_on_count": 7,
                    "observed_component_count": 10,
                    "required_match_count": 4,
                    "hypothesis_count": 5,
                    "best_coarse_match_count": 5,
                    "best_final_match_count": 3,
                    "failure_stage": "final_matches_insufficient",
                    "stage_counts": {"final_matches_insufficient": 5},
                    "best_hypothesis": {
                        "hypothesis_index": 2,
                        "coarse_match_count": 5,
                        "final_match_count": 3,
                        "required_match_count": 4,
                        "median_nearest_distance_px": 11.25,
                    },
                }
            )
            return None

        with (
            patch.object(
                tracking,
                "_detect_luminous_segment_centers",
                return_value={
                    "available": True,
                    "reason": "luminous_segments_detected",
                    "centers": centers,
                    "threshold_v": 156.04,
                    "dynamic_range": 158.0,
                },
            ),
            patch.object(
                tracking,
                "_fit_luminous_pose",
                side_effect=failed_fit,
            ),
        ):
            result = tracking._find_luminous_segment_pose(
                frame,
                board,
                rows,
                (160, 120),
                base_matrix=np.asarray(
                    [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                    dtype=np.float32,
                ),
            )

        self.assertFalse(result["available"])
        self.assertEqual("luminous_grid_not_fitted", result["reason"])
        self.assertEqual(10, result["luminous_component_count"])
        self.assertEqual(5, result["coarse_matched_count"])
        self.assertEqual(3, result["matched_count"])
        self.assertEqual(4, result["required_match_count"])
        self.assertEqual(
            "final_matches_insufficient",
            result["fit_failure_stage"],
        )
        self.assertEqual(
            10,
            result["fit_diagnostics"]["observed_component_count"],
        )

    def test_dark_filter_without_emission_does_not_search_off_segments(self):
        width, height = 640, 480
        canonical_board = [
            [120.0, 150.0],
            [520.0, 150.0],
            [520.0, 310.0],
            [120.0, 310.0],
        ]
        rows = [
            {"mask_id": "MASK_001", "center": [190.0, 190.0]},
            {"mask_id": "MASK_002", "center": [260.0, 240.0]},
            {"mask_id": "MASK_003", "center": [390.0, 190.0]},
        ]
        frame = np.full((height, width, 3), 180, dtype=np.uint8)
        cv2.fillConvexPoly(
            frame,
            np.asarray(canonical_board, dtype=np.int32),
            (20, 20, 20),
        )

        result = tracking._find_luminous_segment_pose(
            frame,
            canonical_board,
            rows,
            (width, height),
        )

        self.assertFalse(result["available"])
        self.assertEqual(
            "filter_found_without_luminous_segments",
            result["reason"],
        )

    def test_luminous_rescue_permanece_no_espaco_canonico(self):
        frame = np.full((480, 640, 3), 20, dtype=np.uint8)
        canonical_board = [
            [120.0, 150.0],
            [520.0, 150.0],
            [520.0, 310.0],
            [120.0, 310.0],
        ]
        canonical_masks = [
            {
                "id": f"MASK_{index:03d}",
                "type": "circle",
                "cx": float(180 + index * 45),
                "cy": float(220 + (index % 2) * 25),
                "radius": 8.0,
            }
            for index in range(1, 5)
        ]
        check = {
            "id": "CHECK_001",
            "name": "H1",
            "mask_states": {
                str(mask["id"]): "on"
                for mask in canonical_masks
            },
        }
        project = {
            "name": "DISPLAY",
            "master_resolution": {"width": 640, "height": 480},
            "masks": canonical_masks,
        }
        current_to_canonical = np.asarray(
            [[1.0, 0.0, 10.0], [0.0, 1.0, 15.0]],
            dtype=np.float32,
        )

        repository = SimpleNamespace(
            obter_projeto_ativo=lambda: "DISPLAY",
            carregar_projeto=lambda _name: project,
            carregar_check=lambda _name, _check_id: check,
        )
        app = SimpleNamespace(
            display_project_repository=repository,
            display_check_runtime=SimpleNamespace(
                snapshot=lambda: {"current_check": check}
            ),
            camera_ultimo_frame_id=88,
        )
        runtime = SimpleNamespace(
            references={
                # A referência pode existir, mas não tem autoridade sobre a
                # geometria usada pelo encaixe luminoso.
                "check:CHECK_001": {
                    "reference_to_canonical": np.asarray(
                        [[1.0, 0.0, 40.0], [0.0, 1.0, 20.0]],
                        dtype=np.float32,
                    ),
                }
            },
            canonical_board=canonical_board,
            canonical_masks=canonical_masks,
            store=object(),
            width=640,
            height=480,
            _gray=lambda image: cv2.cvtColor(image, cv2.COLOR_BGR2GRAY),
            last_matrix=None,
            _last_reference="",
            last_compute_s=0.0,
            last_frame_id=None,
            last_gray=None,
            last_verified_s=0.0,
            consecutive_misses=0,
            ready=True,
            reason="ready",
            last_result=None,
        )
        pose = {
            "available": True,
            "reason": "luminous_segment_grid_fitted",
            "matrix": current_to_canonical,
            "matched_count": 4,
            "expected_on_count": 4,
            "match_ratio": 1.0,
            "luminous_component_count": 4,
            "matched_mask_ids": [
                str(mask["id"]) for mask in canonical_masks
            ],
            "attempts": [
                {
                    "luminous_reason": "luminous_segments_detected",
                    "luminous_component_count": 4,
                    "fit": True,
                }
            ],
        }

        with patch.object(
            tracking,
            "_find_luminous_segment_pose",
            return_value=pose,
        ) as finder:
            result = tracking._rescue_luminous_segment_tracking_lock(
                app,
                frame,
                runtime,
                base_result=None,
            )

        self.assertIsNotNone(result)
        self.assertTrue(result.locked)
        self.assertEqual("luminous_segment_grid", result.source_type)
        self.assertEqual("luminous:CHECK_001", result.reference)
        np.testing.assert_allclose(
            result.current_to_canonical,
            current_to_canonical,
            atol=1e-5,
        )
        fit_args = finder.call_args.args
        self.assertEqual(canonical_board, fit_args[1])
        self.assertEqual(4, len(fit_args[2]))
        telemetry = app._display_f3_luminous_tracking_debug
        self.assertEqual("canonical", telemetry["fit_space"])
        self.assertFalse(telemetry["fit_composed_to_canonical"])
        self.assertEqual(
            [str(mask["id"]) for mask in canonical_masks],
            telemetry["matched_mask_ids"],
        )
        self.assertTrue(telemetry["luminous_emission_detected"])
        self.assertTrue(telemetry["alignment_ready"])
        self.assertEqual(88, telemetry["frame_id"])

    def test_tracking_worker_preserva_token_do_snapshot_mesmo_se_camera_avanca(self):
        source = inspect.getsource(tracking._run_live_tracking_heavy_job)
        self.assertIn("frame_token=frame_token", source)

        align_source = inspect.getsource(tracking.align_frame_for_f3)
        self.assertIn("analysis_frame_id", align_source)
        self.assertIn('"frame_token": deepcopy(frame_token)', align_source)
        self.assertNotIn(
            '"frame_id": getattr(app, "camera_ultimo_frame_id", None)',
            align_source,
        )

    def test_live_tracking_calls_luminous_refinement_after_structural_attempt(self):
        source = inspect.getsource(tracking.align_frame_for_f3)
        self.assertIn(
            "_rescue_luminous_segment_tracking_lock",
            source,
        )
        self.assertIn(
            "base_result=result if bool(result.locked) else None",
            source,
        )


if __name__ == "__main__":
    unittest.main()
