from __future__ import annotations

import unittest

import numpy as np

import src.platform.display_f3_live_runtime_fix as live_module
import src.platform.display_f3_operational_status as operational_module
from src.platform.display_f3_cycle_rearm_release_fix import (
    F3_NEW_BOARD_STABLE_FRAMES,
    F3_REARM_EMPTY_STABLE_FRAMES,
    aplicar_rearme_fisico_dedicado_f3,
    instalar_rearme_fisico_final_display_f3,
)


class _Store:
    def __init__(self, values):
        self.values = values

    def get_all(self, project_name):
        return dict(self.values.get(project_name, {}))

    def get(self, project_name, key):
        return self.values.get(project_name, {}).get(key)


class _Repository:
    @staticmethod
    def listar_checks(_project_name):
        return []


class _Matcher:
    def __init__(self, board_refs):
        self.repository = _Repository()
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


class _SequenceRuntime:
    def __init__(self):
        self.restart_calls = 0

    def reiniciar_placa(self):
        self.restart_calls += 1


class _App:
    def __init__(self):
        self.display_check_runtime = _SequenceRuntime()
        self.reset_calls = 0
        self.clear_gate_calls = 0
        self._display_f3_physical_status_memory_project = "DISPLAY_TESTE"
        self._display_f3_physical_status_memory_check_id = "CHECK_AUX"
        self._display_f3_physical_status_memory_check_name = "AUX"
        self._display_f3_physical_status_memory_reason = "check_aprovado"

    def _display_auto_clear_manual_entry_gate(self):
        self.clear_gate_calls += 1

    def _reset_display_auto_stability(self, transition=True):
        self.reset_calls += 1


class DisplayF3CycleRearmReleaseFixTests(unittest.TestCase):
    @staticmethod
    def _images():
        empty = np.zeros((80, 120, 3), dtype=np.uint8)
        board = empty.copy()
        board[10:70, 10:110] = 90
        return empty, board

    @classmethod
    def _matcher(cls):
        empty, board = cls._images()
        return _Matcher(
            {
                "empty_support": {
                    "image": empty,
                    "score": 0.96,
                    "threshold": 0.72,
                },
                "board_off": {
                    "image": board,
                    "score": 0.94,
                    "threshold": 0.72,
                },
            }
        )

    @staticmethod
    def _false_check_state():
        # Reproduz o defeito real: o classificador geral ainda pode chamar a
        # cena vazia de H1 por causa das referências de CHECK. O gate terminal
        # não pode depender desse vencedor geral para enxergar a retirada.
        return {
            "kind": "check",
            "text": "DISPLAY EM H1",
            "check_id": "CHECK_H1",
            "check_name": "H1",
            "allow_auto": True,
            "board_references_complete": True,
        }

    def test_empty_rearma_mesmo_se_classificador_geral_disser_h1(self):
        app = _App()
        matcher = self._matcher()
        empty, board = self._images()
        live_module.armar_rearme_por_suporte_vazio_f3(app)

        first = aplicar_rearme_fisico_dedicado_f3(
            app,
            matcher,
            empty,
            "DISPLAY_TESTE",
            self._false_check_state(),
        )
        # Um único frame de EMPTY ainda não representa retirada confirmada.
        self.assertEqual("CHECK_AUX", app._display_f3_physical_status_memory_check_id)

        second = aplicar_rearme_fisico_dedicado_f3(
            app,
            matcher,
            empty,
            "DISPLAY_TESTE",
            self._false_check_state(),
        )

        self.assertEqual(2, F3_REARM_EMPTY_STABLE_FRAMES)
        self.assertEqual("unknown", first["kind"])
        self.assertFalse(first["allow_auto"])
        self.assertEqual("empty", second["kind"])
        self.assertTrue(second["cycle_rearmed"])
        self.assertFalse(app._display_f3_waiting_empty_rearm)
        self.assertTrue(app._display_f3_waiting_new_board_after_empty)
        self.assertEqual(1, app.display_check_runtime.restart_calls)
        self.assertEqual("", app._display_f3_physical_status_memory_check_id)
        self.assertEqual("", app._display_f3_physical_status_memory_check_name)
        self.assertEqual(
            "suporte_vazio_confirmado",
            app._display_f3_physical_status_memory_reason,
        )

        still_empty = aplicar_rearme_fisico_dedicado_f3(
            app,
            matcher,
            empty,
            "DISPLAY_TESTE",
            self._false_check_state(),
        )
        self.assertEqual("empty", still_empty["kind"])
        self.assertFalse(still_empty["allow_auto"])
        self.assertTrue(still_empty["cycle_rearmed_waiting_new_board"])

        new_board_first = aplicar_rearme_fisico_dedicado_f3(
            app,
            matcher,
            board,
            "DISPLAY_TESTE",
            self._false_check_state(),
        )
        new_board_second = aplicar_rearme_fisico_dedicado_f3(
            app,
            matcher,
            board,
            "DISPLAY_TESTE",
            self._false_check_state(),
        )

        self.assertEqual(2, F3_NEW_BOARD_STABLE_FRAMES)
        self.assertEqual("unknown", new_board_first["kind"])
        self.assertFalse(new_board_first["allow_auto"])
        self.assertEqual("check", new_board_second["kind"])
        self.assertTrue(new_board_second["allow_auto"])
        self.assertTrue(new_board_second["cycle_new_board_confirmed"])
        self.assertFalse(app._display_f3_waiting_new_board_after_empty)

    def test_mesma_placa_sem_empty_continua_bloqueada_e_memoria_permanece(self):
        app = _App()
        matcher = self._matcher()
        _empty, board = self._images()
        live_module.armar_rearme_por_suporte_vazio_f3(app)

        first = aplicar_rearme_fisico_dedicado_f3(
            app,
            matcher,
            board,
            "DISPLAY_TESTE",
            self._false_check_state(),
        )
        second = aplicar_rearme_fisico_dedicado_f3(
            app,
            matcher,
            board,
            "DISPLAY_TESTE",
            self._false_check_state(),
        )

        self.assertTrue(app._display_f3_waiting_empty_rearm)
        self.assertFalse(first["allow_auto"])
        self.assertFalse(second["allow_auto"])
        self.assertEqual(0, app.display_check_runtime.restart_calls)
        self.assertEqual("CHECK_AUX", app._display_f3_physical_status_memory_check_id)
        self.assertEqual("AUX", app._display_f3_physical_status_memory_check_name)

    def test_instalador_final_reaplica_rearme_se_builder_for_substituido(self):
        original_builder = operational_module._build_operational_state
        original_flag = getattr(
            operational_module,
            "_display_f3_dedicated_cycle_rearm_release_installed",
            False,
        )

        def builder_substituto(self, frame, project_name, context):
            return {
                "kind": "check",
                "check_id": "CHECK_H1",
                "check_name": "H1",
                "allow_auto": True,
            }

        try:
            # Reproduz a ordem real que causou a regressão: uma camada posterior
            # troca o builder, mas o booleano antigo continua marcado como instalado.
            operational_module._build_operational_state = builder_substituto
            operational_module._display_f3_dedicated_cycle_rearm_release_installed = True

            instalar_rearme_fisico_final_display_f3()
            installed = operational_module._build_operational_state

            self.assertIsNot(installed, builder_substituto)
            self.assertTrue(
                getattr(installed, "_odin_f3_dedicated_cycle_rearm_release", False)
            )
            self.assertIs(
                builder_substituto,
                getattr(installed, "_odin_f3_dedicated_cycle_rearm_base", None),
            )
        finally:
            operational_module._build_operational_state = original_builder
            operational_module._display_f3_dedicated_cycle_rearm_release_installed = (
                original_flag
            )


if __name__ == "__main__":
    unittest.main()
