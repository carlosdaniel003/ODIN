from __future__ import annotations

import inspect
import unittest

import numpy as np

from src.platform.display_f3_live_runtime_fix import (
    F3_EMPTY_STABLE_FRAMES,
    F3_TRANSIENT_HOLD_FRAMES,
    aplicar_gate_rearme_ciclo_f3,
    armar_rearme_por_suporte_vazio_f3,
    atualizar_classificacao_overlay_f3,
    estabilizar_estado_fisico_rapido_f3,
    promover_suporte_vazio_rapido_f3,
)
from src.platform.desktop_production_app import DesktopProductionApp


class _PhysicalApp:
    pass


class _PhysicalAppWithRelease:
    def __init__(self):
        self.release_calls = 0

    def _liberar_evidencia_ng_display_f3(self):
        self.release_calls += 1


class _AnalyzerFake:
    def __init__(self, repository, result):
        self.repository = repository
        self.result = dict(result)
        self.calls = 0

    def analyze(self, **_kwargs):
        self.calls += 1
        return dict(self.result)


class _OverlayApp:
    def __init__(self, analyzer, repository):
        self.display_f3_ativo = True
        self.camera_frame_atual = np.zeros((40, 60, 3), dtype=np.uint8)
        self.display_project_repository = repository
        self._display_auto_analyzer = analyzer
        self._display_auto_last_analysis = None
        self._display_auto_last_decision = True
        self._display_auto_stable_frames = 7
        self._frame_id = 11

    @staticmethod
    def _display_auto_configuration_open():
        return False

    @staticmethod
    def _display_auto_current_context():
        return {
            "project_name": "DISPLAY_TESTE",
            "check_id": "CHECK_H1",
            "check_name": "H1",
            "current_index": 0,
        }

    def _display_auto_frame_token(self, _frame):
        return ("camera", self._frame_id)

    @staticmethod
    def _obter_rotacao_visual_display_f3():
        return 0

    def registrar_resultado_check_display_f3(self, _approved):
        raise AssertionError("classificação de overlay não pode registrar CHECK")


class _Store:
    def __init__(self, values):
        self.values = values

    def get_all(self, project_name):
        return dict(self.values.get(project_name, {}))

    def get(self, project_name, key):
        return self.values.get(project_name, {}).get(key)


class _ReferenceRepository:
    @staticmethod
    def listar_checks(_project_name):
        return []


class _Matcher:
    def __init__(self, board_refs):
        self.repository = _ReferenceRepository()
        self.project_store = _Store({"DISPLAY_TESTE": board_refs})
        self.check_store = _Store({"DISPLAY_TESTE": {}})

    @staticmethod
    def _reference_image(metadata):
        return metadata.get("image")

    @staticmethod
    def _score(_current, metadata):
        return float(metadata.get("score", 0.0))

    @staticmethod
    def _threshold(metadata):
        return float(metadata.get("threshold", 0.72))


class DisplayF3LiveRuntimeFixTests(unittest.TestCase):
    @staticmethod
    def _check_state(check_id: str, name: str) -> dict:
        return {
            "kind": "check",
            "text": f"DISPLAY EM {name}",
            "check_id": check_id,
            "check_name": name,
            "physical_state_key": f"check:{check_id}",
            "allow_auto": False,
            "board_references_complete": True,
        }

    @staticmethod
    def _empty_state() -> dict:
        return {
            "kind": "empty",
            "text": "PLACA FORA DO SUPORTE",
            "physical_state_key": "empty",
            "allow_auto": False,
            "board_references_complete": True,
        }

    def test_h1_entra_imediatamente_sem_debounce_fisico_de_tres_frames(self):
        app = _PhysicalApp()
        state = estabilizar_estado_fisico_rapido_f3(
            app,
            self._check_state("CHECK_H1", "H1"),
        )

        self.assertEqual("check", state["kind"])
        self.assertEqual("CHECK_H1", state["check_id"])
        self.assertEqual("check:CHECK_H1", app._display_f3_physical_stable_key)
        self.assertEqual(0, app._display_f3_physical_pending_frames)

    def test_blue_mantem_estado_durante_fase_escura_do_pisca(self):
        app = _PhysicalApp()
        blue = self._check_state("CHECK_BLUE", "BLUE")
        estabilizar_estado_fisico_rapido_f3(app, blue)

        off = {
            "kind": "off",
            "text": "PLACA NO SUPORTE • DESLIGADA",
            "physical_state_key": "off",
            "allow_auto": False,
            "board_references_complete": True,
        }
        held = estabilizar_estado_fisico_rapido_f3(app, off)

        self.assertEqual("check", held["kind"])
        self.assertEqual("CHECK_BLUE", held["check_id"])
        self.assertTrue(held["transient_hold"])
        self.assertEqual("off", held["raw_kind_during_hold"])
        self.assertEqual(
            F3_TRANSIENT_HOLD_FRAMES - 1,
            app._display_f3_transient_hold_frames,
        )

    def test_outro_check_substitui_blue_imediatamente(self):
        app = _PhysicalApp()
        estabilizar_estado_fisico_rapido_f3(
            app,
            self._check_state("CHECK_BLUE", "BLUE"),
        )
        usb = estabilizar_estado_fisico_rapido_f3(
            app,
            self._check_state("CHECK_USB", "USB"),
        )

        self.assertEqual("CHECK_USB", usb["check_id"])
        self.assertEqual(0, app._display_f3_transient_hold_frames)
        self.assertIsNone(app._display_f3_transient_hold_state)

    def test_suporte_vazio_cancela_hold_do_blue(self):
        app = _PhysicalApp()
        estabilizar_estado_fisico_rapido_f3(
            app,
            self._check_state("CHECK_BLUE", "BLUE"),
        )
        empty = estabilizar_estado_fisico_rapido_f3(app, self._empty_state())

        self.assertNotEqual("CHECK_BLUE", str(empty.get("check_id") or ""))
        self.assertEqual(0, app._display_f3_transient_hold_frames)
        self.assertIsNone(app._display_f3_transient_hold_state)

    def test_suporte_vazio_confirma_em_dois_frames(self):
        app = _PhysicalApp()
        first = estabilizar_estado_fisico_rapido_f3(app, self._empty_state())
        second = estabilizar_estado_fisico_rapido_f3(app, self._empty_state())

        self.assertEqual(2, F3_EMPTY_STABLE_FRAMES)
        self.assertEqual("unknown", first["kind"])
        self.assertEqual("empty", second["kind"])
        self.assertEqual("empty", app._display_f3_physical_stable_key)

    def test_empty_pode_vencer_off_sem_disputar_com_todos_os_checks(self):
        empty_image = np.zeros((80, 120, 3), dtype=np.uint8)
        off_image = empty_image.copy()
        off_image[10:70, 10:110] = 90
        observed = empty_image.copy()
        matcher = _Matcher(
            {
                "empty_support": {
                    "image": empty_image,
                    "score": 0.95,
                    "threshold": 0.72,
                },
                "board_off": {
                    "image": off_image,
                    "score": 0.80,
                    "threshold": 0.72,
                },
            }
        )
        fallback = {
            "kind": "unknown",
            "text": "IDENTIFICANDO...",
            "allow_auto": False,
        }

        promoted = promover_suporte_vazio_rapido_f3(
            matcher,
            observed,
            "DISPLAY_TESTE",
            fallback,
        )

        self.assertEqual("empty", promoted["kind"])
        self.assertEqual("PLACA FORA DO SUPORTE", promoted["text"])
        self.assertTrue(promoted["fast_empty"])

    def test_ciclo_terminal_fica_bloqueado_ate_passar_por_empty(self):
        app = _PhysicalApp()
        armar_rearme_por_suporte_vazio_f3(app)

        same_board = self._check_state("CHECK_H1", "H1")
        same_board["allow_auto"] = True
        blocked = aplicar_gate_rearme_ciclo_f3(app, same_board)

        self.assertTrue(app._display_f3_waiting_empty_rearm)
        self.assertFalse(blocked["allow_auto"])
        self.assertTrue(blocked["cycle_rearm_waiting"])

        empty = aplicar_gate_rearme_ciclo_f3(app, self._empty_state())
        self.assertEqual("empty", empty["kind"])
        self.assertTrue(empty["cycle_rearmed"])
        self.assertFalse(app._display_f3_waiting_empty_rearm)

        new_board = self._check_state("CHECK_H1", "H1")
        new_board["allow_auto"] = True
        released = aplicar_gate_rearme_ciclo_f3(app, new_board)
        self.assertTrue(released["allow_auto"])

    def test_empty_confirmado_libera_evidencia_ng_uma_unica_vez(self):
        app = _PhysicalAppWithRelease()
        armar_rearme_por_suporte_vazio_f3(app)

        blocked = aplicar_gate_rearme_ciclo_f3(
            app,
            self._check_state("CHECK_H1", "H1"),
        )
        self.assertTrue(blocked["cycle_rearm_waiting"])
        self.assertEqual(0, app.release_calls)

        released = aplicar_gate_rearme_ciclo_f3(app, self._empty_state())
        self.assertTrue(released["cycle_rearmed"])
        self.assertEqual(1, app.release_calls)

        aplicar_gate_rearme_ciclo_f3(app, self._empty_state())
        self.assertEqual(1, app.release_calls)

    def test_classificacao_overlay_roda_sem_registrar_ou_alterar_debounce(self):
        repository = object()
        analyzer = _AnalyzerFake(
            repository,
            {
                "ready": True,
                "approved": True,
                "project_name": "DISPLAY_TESTE",
                "check_id": "CHECK_H1",
                "mask_results": [
                    {"mask_id": "M1", "classified": "on", "matched": True}
                ],
            },
        )
        app = _OverlayApp(analyzer, repository)

        analysis = atualizar_classificacao_overlay_f3(app)

        self.assertEqual(1, analyzer.calls)
        self.assertIs(analysis, app._display_auto_last_analysis)
        self.assertEqual("on", analysis["mask_results"][0]["classified"])
        self.assertTrue(app._display_auto_last_decision)
        self.assertEqual(7, app._display_auto_stable_frames)

    def test_classificacao_overlay_nao_duplica_analise_valida_do_check_atual(self):
        repository = object()
        analyzer = _AnalyzerFake(repository, {})
        app = _OverlayApp(analyzer, repository)
        existing = {
            "ready": True,
            "project_name": "DISPLAY_TESTE",
            "check_id": "CHECK_H1",
            "mask_results": [{"mask_id": "M1", "classified": "off"}],
        }
        app._display_auto_last_analysis = existing

        analysis = atualizar_classificacao_overlay_f3(app)

        self.assertIs(existing, analysis)
        self.assertEqual(0, analyzer.calls)

    def test_cache_restaura_cores_se_gate_limpar_analise_no_mesmo_frame(self):
        repository = object()
        analyzer = _AnalyzerFake(
            repository,
            {
                "ready": True,
                "project_name": "DISPLAY_TESTE",
                "check_id": "CHECK_H1",
                "mask_results": [{"mask_id": "M1", "classified": "off"}],
            },
        )
        app = _OverlayApp(analyzer, repository)
        first = atualizar_classificacao_overlay_f3(app)
        app._display_auto_last_analysis = None
        second = atualizar_classificacao_overlay_f3(app)

        self.assertEqual(1, analyzer.calls)
        self.assertIs(first, second)
        self.assertIs(second, app._display_auto_last_analysis)

    def test_perfil_instala_runtime_rapido_depois_da_correcao_fisica(self):
        source = inspect.getsource(DesktopProductionApp.__init__)
        physical_position = source.index("instalar_correcao_estado_fisico_display_f3()")
        live_position = source.index("instalar_runtime_ao_vivo_display_f3()")
        self.assertLess(physical_position, live_position)


if __name__ == "__main__":
    unittest.main()
