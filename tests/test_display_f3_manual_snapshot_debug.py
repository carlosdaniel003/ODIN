from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

import numpy as np

import src.platform.display_f3_manual_snapshot_debug as snapshot_module
from src.platform.display_f3_fast_expected_gate import (
    instalar_gate_rapido_check_esperado_display_f3,
)


class _FrameApp:
    def __init__(self):
        self.camera_ultimo_frame_id = 41
        self.camera_frame_atual = np.full((4, 6, 3), 25, dtype=np.uint8)


class _FakeButton:
    def __init__(self):
        self.values = {}

    def configure(self, **kwargs):
        self.values.update(kwargs)

    def update_idletasks(self):
        return None

    def after(self, _delay, callback):
        # Não executa o reset no teste; queremos inspecionar o estado imediato.
        self.callback = callback


class _FakeWindow:
    def __init__(self, app):
        self._display_f3_manual_debug_owner = app
        self.f3_manual_analyze_button = _FakeButton()
        self.f3_snapshot_debug_button = _FakeButton()
        self._display_f3_manual_snapshot = None
        self._display_f3_manual_snapshot_report = ""
        self._display_f3_manual_snapshot_serial = 0
        self._display_f3_debug_snapshot_serial = -1
        self._display_f3_manual_analysis_seed = None
        self._display_f3_snapshot_analysis_running = False
        self._display_f3_debug_analysis_running = False
        self._display_f3_manual_screen_capture_image = None
        self._display_f3_manual_screen_capture_meta = {}
        self.closed = 0
        self.opened = 0

    def close_f3_snapshot_debug(self):
        self.closed += 1

    def open_f3_snapshot_debug(self):
        self.opened += 1
        return "OPENED"


class DisplayF3ManualSnapshotDebugTests(unittest.TestCase):
    def test_ng_congelado_usa_frame_e_contexto_da_evidencia_e_ignora_live(self):
        app = _FrameApp()
        app.camera_frame_atual[:] = 220
        app.camera_ultimo_frame_id = 99
        app._display_f3_ng_evidence_frozen = True
        app._display_f3_ng_evidence_frame = np.full(
            (4, 6, 3),
            37,
            dtype=np.uint8,
        )
        app._display_f3_ng_evidence_snapshot = {
            "frame_id": 77,
            "rotation": 180,
            "context": {
                "project_name": "DISPLAY",
                "check_id": "CHECK_BLUE",
                "check_name": "BLUE",
                "intermittent": True,
                "current_index": 1,
            },
        }

        frozen, capture = snapshot_module._freeze_current_frame(app)

        self.assertTrue(np.all(frozen == 37))
        self.assertEqual(77, capture["frame_id"])
        self.assertEqual("ng_evidence_frozen", capture["source"])
        self.assertTrue(capture["live_camera_ignored"])
        self.assertEqual("CHECK_BLUE", snapshot_module._current_context(app)["check_id"])
        self.assertEqual(180, snapshot_module._rotation(app))
        self.assertTrue(np.all(app.camera_frame_atual == 220))

    def test_ng_congelado_sem_copia_nao_cai_para_camera_ao_vivo(self):
        app = _FrameApp()
        app._display_f3_ng_evidence_frozen = True
        app._display_f3_ng_evidence_frame = None
        app._display_f3_ng_evidence_snapshot = {
            "frame_id": 77,
            "context": {"check_id": "CHECK_BLUE"},
        }

        frozen, capture = snapshot_module._freeze_current_frame(app)

        self.assertIsNone(frozen)
        self.assertEqual("ng_evidence_frame_missing", capture["reason"])
        self.assertEqual("ng_evidence_frozen", capture["source"])
        self.assertTrue(capture["live_camera_ignored"])

    def test_frame_e_copiado_no_instante_do_analisar(self):
        app = _FrameApp()
        frozen, capture = snapshot_module._freeze_current_frame(app)

        self.assertTrue(capture["stable_frame_id"])
        self.assertEqual(41, capture["frame_id"])
        self.assertTrue(np.all(frozen == 25))

        app.camera_frame_atual[:] = 200
        self.assertTrue(np.all(frozen == 25))
        self.assertTrue(np.all(app.camera_frame_atual == 200))

    def test_runtime_do_debug_ng_usa_telemetria_congelada(self):
        source = inspect.getsource(
            snapshot_module.capturar_snapshot_debug_display_f3
        )
        self.assertIn('evidence.get("runtime_debug")', source)
        self.assertIn('diagnostic_source = "ng_evidence_frozen"', source)
        self.assertIn('"live_camera_ignored": evidence is not None', source)
        self.assertIn("runtime_value(", source)

    def test_estado_visual_e_runtime_sao_capturados_antes_da_analise_pesada(self):
        source = inspect.getsource(
            snapshot_module.capturar_snapshot_debug_display_f3
        )
        visual_pos = source.index('snapshot["visual_state"] = _coherent_visual_state_from_runtime(')
        runtime_pos = source.index('snapshot["runtime_at_click"] = _runtime_state_at_frame(app)')
        analyses_pos = source.index('snapshot["check_analyses"] = _run_check_analyses(')
        self.assertLess(visual_pos, analyses_pos)
        self.assertLess(runtime_pos, analyses_pos)

    def test_debug_completo_usa_projeto_capturado_no_analisar(self):
        source = inspect.getsource(
            snapshot_module.capturar_snapshot_debug_display_f3
        )
        self.assertIn("captured_project_name", source)
        captured_pos = source.index("if captured_project_name:")
        active_pos = source.index("repository.obter_projeto_ativo()")
        self.assertLess(captured_pos, active_pos)

    def test_snapshot_inclui_contexto_overlay_e_configuracao_camera(self):
        source = inspect.getsource(
            snapshot_module.capturar_snapshot_debug_display_f3
        )
        self.assertIn("montar_contexto_overlay_snapshot_display_f3", source)
        self.assertIn('snapshot["overlay_context"]', source)
        self.assertIn('snapshot["camera_settings_at_frame"]', source)

    def test_debug_d025_usa_foto_h1_real_e_frame_congelado_sem_autoridade_produtiva(self):
        source = inspect.getsource(
            snapshot_module._run_d025_h1_registration_diagnostic
        )
        self.assertIn("DisplayCheckPresenceReferenceStore(repository).get", source)
        self.assertIn("cv2.imread(image_path", source)
        self.assertIn("_check_reference_geometry", source)
        self.assertIn("experiment_h1_filter_registration", source)
        self.assertIn("frame,", source)
        self.assertIn('"production_authority": False', source)
        self.assertNotIn("camera_frame_atual", source)
        self.assertNotIn("registrar_resultado_check_display_f3", source)

    def test_relatorio_inclui_metricas_d025_sem_serializar_imagem(self):
        snapshot = {
            "source": snapshot_module.F3_MANUAL_SNAPSHOT_SOURCE,
            "capture": {},
            "frame": {},
            "logical_context": {},
            "project": {},
            "d025_h1_registration": {
                "available": True,
                "quality_ok": True,
                "check_name": "H1",
                "reference_image_path": "h1.jpg",
                "filter_candidate_count": 2,
                "rectified_size": [320, 120],
                "ecc_score": 0.97,
                "rotation_deg": 1.2,
                "center_shift_px": 8.5,
                "reason": "h1_filter_registration_ready",
                "metrics_before": {
                    "dice": 0.40,
                    "correlation": 0.50,
                    "mean_error_px": 8.0,
                    "p95_error_px": 14.0,
                },
                "metrics_after": {
                    "dice": 0.92,
                    "correlation": 0.95,
                    "mean_error_px": 1.2,
                    "p95_error_px": 2.4,
                },
                "mask_overlap_before": {
                    "emission_inside_fraction": 0.35,
                },
                "mask_overlap_after": {
                    "emission_inside_fraction": 0.88,
                },
            },
            "reference_analysis": [],
            "physical_analysis": {},
            "check_configuration": [],
            "mask_configuration": [],
            "check_analyses": [],
            "runtime_at_click": {},
            "errors": [],
        }
        report = snapshot_module.montar_relatorio_snapshot_display_f3(snapshot)
        self.assertIn(
            "[D-025 / HOMOGRAFIA DO FILTRO + REGISTRO VISUAL H1]",
            report,
        )
        self.assertIn("check=H1", report)
        self.assertIn("ecc=0.9700", report)
        self.assertIn("dice=0.4000->0.9200", report)
        self.assertIn("emission_in_masks=0.3500->0.8800", report)
        self.assertIn("NÃO participa de energia, OK/NG", report)

    def test_debug_captura_telemetria_do_refinamento_luminoso(self):
        source = inspect.getsource(snapshot_module._runtime_state_at_frame)
        self.assertIn('"luminous_tracking"', source)
        self.assertIn("_display_f3_luminous_tracking_debug", source)

    def test_estado_visual_do_debug_herda_energia_e_analise_do_runtime(self):
        visual = {
            "readout_context": {
                "classifications": {"MASK_001": "off"},
                "power_confirmed": False,
                "power_off_confirmed": True,
                "energy_state": "off",
            },
            "overlay_context": {
                "classifications": {"MASK_001": "off"},
            },
        }
        runtime = {
            "last_auto_analysis": {
                "project_name": "DISPLAY",
                "check_id": "CHECK_001",
                "mask_results": [
                    {
                        "mask_id": "MASK_001",
                        "expected": "on",
                        "classified": "on",
                        "matched": True,
                    },
                    {
                        "mask_id": "MASK_002",
                        "expected": "off",
                        "classified": "off",
                        "matched": True,
                    },
                ],
            },
            "power_authority_status": {
                "board_present": True,
                "decision_allowed": True,
                "energy": {
                    "energy_state": "powered",
                    "powered_confirmed": True,
                    "off_confirmed": False,
                },
            },
        }

        result = snapshot_module._coherent_visual_state_from_runtime(
            visual,
            runtime,
        )

        readout = result["readout_context"]
        self.assertTrue(readout["power_confirmed"])
        self.assertFalse(readout["power_off_confirmed"])
        self.assertEqual("powered", readout["energy_state"])
        self.assertEqual(
            {"MASK_001": "on", "MASK_002": "off"},
            readout["classifications"],
        )
        self.assertEqual(
            {"MASK_001": "on", "MASK_002": "off"},
            result["overlay_context"]["classifications"],
        )
        self.assertTrue(result["debug_visual_runtime_coherent"])

    def test_contexto_visual_do_frame_congelado_inclui_28_mascaras(self):
        snapshot = {
            "frame": {"sha256_24": "abc123"},
            "logical_context": {"intermittent": True},
            "runtime_at_click": {
                "power_authority_status": {
                    "energy": {"minimum_discriminative_on_count": 7}
                }
            },
        }
        analysis = {
            "mask_results": [
                {
                    "mask_id": f"MASK_{index:03d}",
                    "expected": "on" if index <= 18 else "off",
                    "classified": "on" if index <= 13 else "off",
                    "matched": index <= 13 or index > 18,
                    "confidence": 0.9,
                }
                for index in range(1, 29)
            ]
        }
        context = snapshot_module._frozen_frame_visual_context(
            snapshot,
            analysis,
        )
        self.assertEqual(28, len(context["mask_ids"]))
        self.assertEqual("on", context["intermittent_phase"])
        self.assertTrue(context["power_confirmed"])
        self.assertEqual("abc123", context["debug_frame_sha256_24"])

    def test_relatorio_identifica_frame_por_hash_e_declara_snapshot_estatico(self):
        frame = np.arange(60, dtype=np.uint8).reshape(4, 5, 3)
        stats = snapshot_module._frame_statistics(frame)
        snapshot = {
            "source": snapshot_module.F3_MANUAL_SNAPSHOT_SOURCE,
            "captured_at": "2026-09-04T12:00:00.000-04:00",
            "capture": {"frame_id": 88, "stable_frame_id": True},
            "frame": stats,
            "rotation": 180,
            "project_name": "TESTE",
            "config_file": "data/config/odin_display_projects.json",
            "logical_context": {"check_id": "H1", "check_name": "H1"},
            "project": {"mask_count": 30, "check_count": 4},
            "reference_analysis": [],
            "physical_analysis": {},
            "check_configuration": [],
            "mask_configuration": [],
            "check_analyses": [],
            "runtime_at_click": {
                "luminous_tracking": {
                    "check_id": "CHECK_001",
                    "check_name": "H1",
                    "frame_id": 88,
                    "fit_space": "check:CHECK_001",
                    "expected_on_count": 7,
                    "luminous_component_count": 5,
                    "local_luminous_landmark_count": 7,
                    "fit_landmark_source": "expected_on_local_emission",
                    "coarse_matched_count": 5,
                    "matched_count": 3,
                    "required_match_count": 4,
                    "fit_failure_stage": "final_matches_insufficient",
                    "fit_diagnostics": {
                        "hypothesis_count": 5,
                        "best_coarse_match_count": 5,
                        "best_final_match_count": 3,
                        "required_match_count": 4,
                        "failure_stage": "final_matches_insufficient",
                        "best_hypothesis": {
                            "hypothesis_index": 2,
                            "median_nearest_distance_px": 11.25,
                        },
                    },
                    "attempts": [
                        {
                            "local_luminous_landmark_count": 3,
                            "local_luminous_details": [
                                {
                                    "mask_id": "MASK_001",
                                    "median_prediction_error_px": 4.0,
                                },
                                {
                                    "mask_id": "MASK_008",
                                    "median_prediction_error_px": 7.5,
                                },
                                {
                                    "mask_id": "MASK_013",
                                    "median_prediction_error_px": 12.0,
                                },
                            ],
                        }
                    ],
                    "luminous_emission_detected": True,
                    "alignment_required": True,
                    "alignment_ready": False,
                    "reason": "luminous_grid_not_fitted",
                }
            },
            "errors": [],
        }

        text = snapshot_module.montar_relatorio_snapshot_display_f3(snapshot)

        self.assertIn("ODIN DISPLAY F3 - ANÁLISE MANUAL DE FRAME", text)
        self.assertIn("frame_id=88", text)
        self.assertIn(stats["sha256_24"], text)
        self.assertIn("MESMA cópia congelada", text)
        self.assertIn("auditoria completa em segundo plano", text)
        self.assertIn("[ANÁLISE DA IMAGEM / FRAME CONGELADO]", text)
        self.assertIn("[REFERÊNCIAS VISUAIS / PRESENÇA / SCORE - MESMO FRAME]", text)
        self.assertIn("[ANÁLISE FÍSICA - SEM DEBOUNCE / MESMO FRAME]", text)
        self.assertIn("[COMPARAÇÃO DO MESMO FRAME CONTRA TODOS OS CHECKS]", text)
        self.assertIn("[RUNTIME PRODUTIVO OBSERVADO NO MESMO CLIQUE]", text)
        self.assertIn("[REFINAMENTO LUMINOSO DO CHECK]", text)
        self.assertIn("fit_space=check:CHECK_001", text)
        self.assertIn("emission_detected=SIM", text)
        self.assertIn("alignment_ready=NÃO", text)
        self.assertIn("components=5", text)
        self.assertIn("local_landmarks=7", text)
        self.assertIn("fit_source=expected_on_local_emission", text)
        self.assertIn("coarse_matched=5", text)
        self.assertIn("matched=3", text)
        self.assertIn("required=4", text)
        self.assertIn("fit_failure=final_matches_insufficient", text)
        self.assertIn("fit_debug=hypotheses=5", text)
        self.assertIn("best_final=3", text)
        self.assertIn("median_nearest_px=11.25", text)
        self.assertIn("landmark_alignment=count=3", text)
        self.assertIn("median_error_px=7.500", text)
        self.assertIn("max_error_px=12.000", text)
        self.assertIn("MASK_001:4.00px", text)
        self.assertIn("MASK_008:7.50px", text)
        self.assertIn("MASK_013:12.00px", text)
        self.assertIn(
            "DISPLAY COM EMISSÃO; AGUARDANDO GEOMETRIA FINA ANTES DE OK/NG",
            text,
        )
        self.assertIn("luminous_tracking=emission=SIM", text)


    def test_analisar_captura_tela_e_inicia_check_e_relatorio_no_mesmo_clique(self):
        source = inspect.getsource(snapshot_module._capture_from_window)
        screen_pos = source.index("_capture_f3_production_screen(window)")
        button_pos = source.index('button.configure(text="ANALISANDO..."')
        self.assertLess(screen_pos, button_pos)
        self.assertIn("DisplayF3CurrentCheckAnalysisService", source)
        self.assertIn('name="manual-current-check"', source)
        self.assertIn("F3HeavyWorkPriority.NORMAL", source)
        self.assertIn("_prepare_debug_seed_from_analysis(app, seed)", source)
        self.assertIn("capturar_snapshot_debug_display_f3(app)", source)
        self.assertIn("montar_relatorio_snapshot_display_f3", source)
        self.assertIn('name="technical-report-at-analyze"', source)
        self.assertIn("F3HeavyWorkPriority.LOW", source)


    def test_novo_analisar_invalida_relatorio_anterior_no_inicio_do_clique(self):
        source = inspect.getsource(snapshot_module._capture_from_window)
        screen_pos = source.index("_capture_f3_production_screen(window)")
        report_reset = source.index('window._display_f3_manual_snapshot_report = ""')
        serial_reset = source.index("window._display_f3_debug_snapshot_serial = -1")
        self.assertLess(screen_pos, report_reset)
        self.assertLess(report_reset, serial_reset)
        self.assertIn("window.close_f3_snapshot_debug()", source)


    def test_handler_analisar_enfileira_auditoria_completa_sem_nova_thread(self):
        source = inspect.getsource(snapshot_module._capture_from_window)
        self.assertIn("executor = _heavy_executor_for_app(app)", source)
        self.assertEqual(2, source.count("executor.submit("))
        self.assertIn('name="manual-current-check"', source)
        self.assertIn('name="technical-report-at-analyze"', source)
        self.assertNotIn("threading.Thread", source)
        self.assertNotIn("while True", source)

    def test_seed_do_analisar_e_minimo(self):
        source = inspect.getsource(
            snapshot_module._prepare_async_snapshot_seed
        )
        self.assertIn("_freeze_current_frame(app)", source)
        self.assertIn("_current_context(app)", source)
        self.assertIn("_tracking_geometry_snapshot(app)", source)
        self.assertNotIn("_runtime_state_at_frame(app)", source)
        self.assertNotIn("_window_visual_state(app)", source)
        self.assertNotIn("_camera_settings_at_frame(app)", source)


    def test_debug_tecnico_apenas_abre_material_ja_capturado(self):
        source = inspect.getsource(snapshot_module._generate_debug_from_window)
        self.assertIn("open_f3_snapshot_debug", source)
        self.assertNotIn("_prepare_debug_seed_from_analysis", source)
        self.assertNotIn("capturar_snapshot_debug_display_f3", source)
        self.assertNotIn("montar_relatorio_snapshot_display_f3", source)
        self.assertNotIn("executor.submit", source)

    def test_print_da_tela_e_evidencia_visual_e_nao_fonte_da_visao(self):
        source = inspect.getsource(snapshot_module._capture_f3_production_screen)
        self.assertIn("_capture_windows_f3_client(target)", source)
        self.assertIn("ImageGrab.grab", source)
        self.assertIn("winfo_rootx", source)
        self.assertIn("winfo_rooty", source)
        analyze = inspect.getsource(snapshot_module._capture_from_window)
        self.assertIn("_prepare_async_snapshot_seed(app)", analyze)
        self.assertIn("_capture_f3_production_screen(window)", analyze)
        audit = inspect.getsource(snapshot_module.capturar_snapshot_debug_display_f3)
        self.assertNotIn("_display_f3_manual_screen_capture_image", audit)

    def test_print_windows_captura_area_cliente_sem_bbox_logico(self):
        source = inspect.getsource(snapshot_module._capture_windows_f3_client)
        self.assertIn("GetClientRect", source)
        self.assertIn("PrintWindow", source)
        self.assertIn("PW_CLIENTONLY", source)
        self.assertIn("PW_RENDERFULLCONTENT", source)
        self.assertIn("GetDIBits", source)
        self.assertIn('biHeight = -height', source)
        self.assertNotIn("winfo_rootx", source)
        self.assertNotIn("winfo_rooty", source)

    def test_captura_windows_tem_prioridade_sobre_fallback_imagegrab(self):
        source = inspect.getsource(snapshot_module._capture_f3_production_screen)
        native_pos = source.index("_capture_windows_f3_client(target)")
        fallback_pos = source.index("ImageGrab.grab")
        self.assertLess(native_pos, fallback_pos)
        self.assertIn('"windows_printwindow_client"', source)
        self.assertIn('"imagegrab_bbox_fallback"', source)

    def test_interface_remove_debug_antigo_e_toggle_off(self):
        source = inspect.getsource(snapshot_module._install_window_controls)
        self.assertIn('_destroy_widget(self, "technical_debug_button")', source)
        self.assertIn('_destroy_widget(self, "technical_debug_toggle")', source)
        self.assertIn('text="ANALISAR"', source)
        self.assertIn('text="DEBUG TÉCNICO"', source)
        self.assertIn("generate_f3_snapshot_debug", source)
        self.assertIn('state=tk.DISABLED', source)

    def test_analise_manual_e_instalada_depois_do_contrato_runtime(self):
        source = inspect.getsource(instalar_gate_rapido_check_esperado_display_f3)
        contract = source.index("instalar_contrato_runtime_display_f3()")
        manual = source.index("instalar_analise_manual_snapshot_display_f3()")
        self.assertLess(contract, manual)

    def test_modulo_manual_nao_depende_de_f2_nem_registra_resultado(self):
        source = inspect.getsource(snapshot_module)
        for forbidden in (
            "src.platform.f2_",
            "F2Automatic",
            "registrar_resultado_check_display_f3(",
            "concluir_check_display_f3(",
            "descartar_placa_display_f3(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
