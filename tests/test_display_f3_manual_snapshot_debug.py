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
            "runtime_at_click": {},
            "errors": [],
        }

        text = snapshot_module.montar_relatorio_snapshot_display_f3(snapshot)

        self.assertIn("ODIN DISPLAY F3 - ANÁLISE MANUAL DE FRAME", text)
        self.assertIn("frame_id=88", text)
        self.assertIn(stats["sha256_24"], text)
        self.assertIn("MESMA cópia congelada", text)
        self.assertIn("auditoria completa sob demanda", text)
        self.assertIn("[ANÁLISE DA IMAGEM / FRAME CONGELADO]", text)
        self.assertIn("[REFERÊNCIAS VISUAIS / PRESENÇA / SCORE - MESMO FRAME]", text)
        self.assertIn("[ANÁLISE FÍSICA - SEM DEBOUNCE / MESMO FRAME]", text)
        self.assertIn("[COMPARAÇÃO DO MESMO FRAME CONTRA TODOS OS CHECKS]", text)
        self.assertIn("[RUNTIME PRODUTIVO OBSERVADO NO MESMO CLIQUE]", text)

    def test_analisar_processa_somente_check_atual_e_libera_debug(self):
        app = _FrameApp()
        app.display_project_repository = object()
        app._display_f3_ng_evidence_frozen = False
        window = _FakeWindow(app)
        seed = {
            "captured_at": "agora",
            "frame": np.zeros((4, 6, 3), dtype=np.uint8),
            "capture": {"frame_id": 123, "stable_frame_id": True},
            "rotation": 0,
            "logical_context": {
                "project_name": "DISPLAY",
                "check_id": "CHECK_001",
                "check_name": "H1",
            },
        }
        snapshot = {
            "source": "f3_manual_current_check_analysis",
            "analysis_ready": True,
            "capture": {"frame_id": 123},
            "frame": {"available": True, "shape": [4, 6, 3]},
            "logical_context": seed["logical_context"],
            "frozen_frame_analysis": {
                "ready": True,
                "approved": True,
                "mask_results": [],
            },
        }

        with patch.object(
            snapshot_module,
            "_prepare_async_snapshot_seed",
            return_value=seed,
        ), patch(
            "src.platform.display_f3_manual_snapshot_debug."
            "DisplayF3CurrentCheckAnalysisService"
        ) as service_cls:
            service_cls.return_value.analyze.return_value = snapshot
            result = snapshot_module._capture_from_window(window)

        self.assertIs(result, snapshot)
        self.assertEqual(1, window._display_f3_manual_snapshot_serial)
        self.assertEqual("", window._display_f3_manual_snapshot_report)
        self.assertIs(seed, window._display_f3_manual_analysis_seed)
        self.assertEqual(
            "normal",
            window.f3_snapshot_debug_button.values.get("state"),
        )
        service_cls.return_value.analyze.assert_called_once_with(seed)

    def test_novo_analisar_invalida_debug_completo_anterior(self):
        app = _FrameApp()
        window = _FakeWindow(app)
        window._display_f3_manual_snapshot_report = "DEBUG ANTIGO"
        window._display_f3_debug_snapshot_serial = 3
        window._display_f3_manual_snapshot_serial = 3
        seed = {
            "frame": np.zeros((4, 6, 3), dtype=np.uint8),
            "capture": {"frame_id": 11},
        }
        snapshot = {
            "frame": {"available": True},
            "frozen_frame_analysis": {"ready": True, "mask_results": []},
        }

        snapshot_module._apply_current_analysis_result_to_window(
            window,
            snapshot,
            seed,
        )

        self.assertEqual("", window._display_f3_manual_snapshot_report)
        self.assertEqual(-1, window._display_f3_debug_snapshot_serial)
        self.assertEqual(4, window._display_f3_manual_snapshot_serial)
        self.assertEqual(1, window.closed)

    def test_handler_analisar_nao_gera_auditoria_completa(self):
        source = inspect.getsource(snapshot_module._capture_from_window)
        self.assertIn("DisplayF3CurrentCheckAnalysisService", source)
        self.assertIn('name="ODIN-F3-CurrentCheckAnalysis"', source)
        self.assertNotIn("capturar_snapshot_debug_display_f3", source)
        self.assertNotIn("montar_relatorio_snapshot_display_f3", source)
        self.assertNotIn("_run_check_analyses", source)

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

    def test_debug_completo_e_gerado_sob_demanda_do_mesmo_seed(self):
        source = inspect.getsource(
            snapshot_module._generate_debug_from_window
        )
        self.assertIn("_display_f3_manual_analysis_seed", source)
        self.assertIn("_prepare_debug_seed_from_analysis", source)
        self.assertIn("capturar_snapshot_debug_display_f3", source)
        self.assertIn("montar_relatorio_snapshot_display_f3", source)
        self.assertIn('name="ODIN-F3-DebugSnapshot"', source)

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
