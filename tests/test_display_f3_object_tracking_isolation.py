from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

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

    def test_nominal_cardinal_orientations_keep_display_inside_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            project = {
                "name": "DISPLAY TESTE",
                "master_resolution": {"width": 640, "height": 480},
                "masks": [
                    {
                        "id": "MASK_001",
                        "type": "circle",
                        "cx": 230,
                        "cy": 210,
                        "radius": 18,
                    },
                    {
                        "id": "MASK_002",
                        "type": "circle",
                        "cx": 410,
                        "cy": 270,
                        "radius": 18,
                    },
                ],
                "checks": [],
            }
            board = tracking.canonical_board_points(project, store)
            self.assertGreaterEqual(len(board), 3)

            for slot in tracking.F3_ORIENTATION_SLOTS:
                matrix = tracking.nominal_orientation_matrix(project, store, slot)
                self.assertIsNotNone(matrix)
                rotated = np.asarray(
                    tracking.transform_points(board, matrix),
                    dtype=np.float32,
                )
                self.assertTrue(np.all(rotated[:, 0] >= 0.0))
                self.assertTrue(np.all(rotated[:, 0] < 640.0))
                self.assertTrue(np.all(rotated[:, 1] >= 0.0))
                self.assertTrue(np.all(rotated[:, 1] < 480.0))

    def test_orientation_mask_override_returns_to_canonical_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            project = {
                "name": "DISPLAY TESTE",
                "master_resolution": {"width": 640, "height": 480},
                "masks": [
                    {
                        "id": "MASK_001",
                        "type": "circle",
                        "cx": 100,
                        "cy": 100,
                        "radius": 10,
                    }
                ],
                "checks": [],
            }
            self.assertTrue(
                store.save_orientation(
                    "DISPLAY TESTE",
                    tracking.F3_ORIENTATION_90,
                    {
                        "image_path": str(Path(directory) / "orientation_90.png"),
                        "width": 640,
                        "height": 480,
                        "canonical_to_reference": [
                            [1.0, 0.0, 50.0],
                            [0.0, 1.0, 20.0],
                        ],
                        "calibrated": True,
                        "mask_overrides_reference": {
                            "MASK_001": {
                                "id": "MASK_001",
                                "type": "circle",
                                "cx": 155.0,
                                "cy": 125.0,
                                "radius": 12.0,
                            }
                        },
                    },
                )
            )
            runtime = SimpleNamespace(store=store)
            corrected = tracking._canonical_masks_for_orientation(
                runtime,
                project,
                tracking.F3_ORIENTATION_90,
            )

            self.assertIsNotNone(corrected)
            self.assertEqual(1, len(corrected))
            self.assertEqual("MASK_001", corrected[0]["id"])
            self.assertAlmostEqual(105.0, float(corrected[0]["cx"]), places=3)
            self.assertAlmostEqual(105.0, float(corrected[0]["cy"]), places=3)
            self.assertAlmostEqual(12.0, float(corrected[0]["radius"]), places=3)

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

    def test_orientation_project_view_keeps_base_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            project = {
                "name": "DISPLAY TESTE",
                "master_resolution": {"width": 640, "height": 480},
                "masks": [
                    {
                        "id": "MASK_001",
                        "type": "polygon",
                        "points": [[20, 20], [80, 20], [50, 60]],
                    }
                ],
                "checks": [],
            }
            self.assertTrue(
                store.save_orientation(
                    "DISPLAY TESTE",
                    tracking.F3_ORIENTATION_90,
                    {
                        "image_path": str(Path(directory) / "orientation_90.png"),
                        "width": 640,
                        "height": 480,
                        "canonical_to_reference": [[1, 0, 50], [0, 1, 20]],
                        "calibrated": True,
                        "masks_reference": [
                            {
                                "id": "MASK_001",
                                "type": "circle",
                                "cx": 170,
                                "cy": 140,
                                "radius": 30,
                            }
                        ],
                    },
                )
            )
            runtime = SimpleNamespace(store=store)
            corrected = tracking._canonical_masks_for_orientation(
                runtime,
                project,
                tracking.F3_ORIENTATION_90,
            )
            self.assertEqual(1, len(corrected))
            self.assertEqual("polygon", corrected[0]["type"])
            self.assertEqual(3, len(corrected[0]["points"]))

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
                real_orientation=False,
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

    def test_final_instance_authority_bypasses_historical_f3_wrappers(self):
        source = inspect.getsource(
            tracking.instalar_autoridade_final_instancia_rastreamento_f3
        )
        self.assertIn("app._atualizar_preview_display_f3 = MethodType", source)
        self.assertIn("window.update_camera_preview = MethodType", source)
        self.assertIn("sequence.registrar_resultado_check = MethodType", source)
        self.assertIn("_tracking_h1_power_gate(app)", source)
        self.assertIn("_display_f3_tracking_raw_authority_frame", source)
        self.assertIn("self.camera_frame_atual = analysis_frame", source)
        self.assertIn("_display_f3_tracking_instance_frame_prepared", source)

        main_source = Path("main_rpi.py").read_text(encoding="utf-8")
        self.assertIn("app = RaspberryPi3ProductionApp(root)", main_source)
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


if __name__ == "__main__":
    unittest.main()
