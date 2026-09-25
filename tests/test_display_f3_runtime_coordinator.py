from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


_MODULE_PATH = Path("src/platform/display_f3_runtime_coordinator.py")
_SPEC = importlib.util.spec_from_file_location(
    "odin_display_f3_runtime_coordinator_test_module",
    _MODULE_PATH,
)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("Nao foi possivel carregar display_f3_runtime_coordinator.py")
coordinator_module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(coordinator_module)

F3RuntimeCoordinator = coordinator_module.F3RuntimeCoordinator
F3_COORDINATOR_CONFIG_INTERVAL_MS = (
    coordinator_module.F3_COORDINATOR_CONFIG_INTERVAL_MS
)
F3_COORDINATOR_VERY_HEAVY_IDLE_MS = (
    coordinator_module.F3_COORDINATOR_VERY_HEAVY_IDLE_MS
)
instalar_coordenador_runtime_display_f3 = (
    coordinator_module.instalar_coordenador_runtime_display_f3
)


class _Frame:
    size = 1


class _Root:
    def __init__(self):
        self.calls = []
        self.cancelled = []
        self._next = 0

    def after(self, delay, callback):
        self._next += 1
        token = f"after-{self._next}"
        self.calls.append(
            {
                "token": token,
                "delay": int(delay),
                "callback": callback,
            }
        )
        return token

    def after_cancel(self, token):
        self.cancelled.append(token)
        self.calls = [
            item for item in self.calls
            if item["token"] != token
        ]

    def run_next(self):
        item = self.calls.pop(0)
        item["callback"]()
        return item


class _Config:
    def __init__(self, visible=False):
        self.visible = visible


class _App:
    DISPLAY_F3_PREVIEW_INTERVAL_MS = 16

    def __init__(self):
        self.root = _Root()
        self.display_f3_ativo = True
        self.display_f3_after_id = None
        self.camera_frame_atual = _Frame()
        self.camera_ultimo_frame_id = 1
        self._display_project_config_window = None
        self._display_f3_configuration_opening = False
        self._display_f3_waiting_empty_rearm = False
        self._display_f3_waiting_new_board_after_empty = False
        self._display_f3_object_tracking_enabled = False
        self._display_f3_tracking_config_open = False
        self._display_f3_tracking_result = object()
        self.analysis_due = True
        self.full_cycles = 0
        self.renders = 0
        self._display_f3_runtime_coordinator = None

    def _display_auto_frame_token(self, _frame):
        return ("camera", self.camera_ultimo_frame_id)

    def _display_auto_analysis_due_now(self):
        return self.analysis_due

    def _render_preview_display_f3_once(self):
        self.renders += 1

    def _agendar_preview_display_f3(self, delay=None):
        coordinator = self._display_f3_runtime_coordinator
        if coordinator is not None:
            coordinator.schedule(delay)

    def _atualizar_preview_display_f3(self):
        self.full_cycles += 1
        self._render_preview_display_f3_once()
        self._agendar_preview_display_f3()


class DisplayF3RuntimeCoordinatorTests(unittest.TestCase):
    def _install(self):
        app = _App()
        coordinator = instalar_coordenador_runtime_display_f3(app)
        self.assertIsInstance(coordinator, F3RuntimeCoordinator)
        return app, coordinator

    def test_installer_creates_exactly_one_scheduled_callback(self):
        app, coordinator = self._install()
        self.assertEqual(1, len(app.root.calls))
        coordinator.schedule(0)
        coordinator.schedule(4)
        self.assertEqual(1, len(app.root.calls))
        self.assertEqual(
            app.root.calls[0]["token"],
            app.display_f3_after_id,
        )

    def test_fresh_due_frame_runs_one_full_cycle_and_one_next_timer(self):
        app, coordinator = self._install()
        app.root.run_next()

        self.assertEqual(1, app.full_cycles)
        self.assertEqual(1, app.renders)
        self.assertEqual(1, len(app.root.calls))
        stats = coordinator.stats()
        self.assertEqual("full_cycle", stats["last_path"])
        self.assertEqual("analysis_due_new_frame", stats["last_reason"])

    def test_repeated_frame_never_runs_full_pipeline_again(self):
        app, coordinator = self._install()
        app.root.run_next()
        app.root.run_next()

        self.assertEqual(1, app.full_cycles)
        self.assertEqual(2, app.renders)
        self.assertEqual(1, coordinator.stats()["repeated_frame_count"])
        self.assertEqual("render_only", coordinator.stats()["last_path"])

    def test_new_frame_not_due_only_repaints(self):
        app, coordinator = self._install()
        app.root.run_next()
        app.camera_ultimo_frame_id = 2
        app.analysis_due = False
        app.root.run_next()

        self.assertEqual(1, app.full_cycles)
        self.assertEqual(2, app.renders)
        self.assertEqual(
            "analysis_not_due",
            coordinator.stats()["last_reason"],
        )

    def test_configuration_open_uses_background_cadence(self):
        app, coordinator = self._install()
        app._display_project_config_window = _Config(visible=True)
        app.root.run_next()

        self.assertEqual(0, app.full_cycles)
        self.assertEqual(1, app.renders)
        self.assertEqual(1, len(app.root.calls))
        self.assertGreaterEqual(
            app.root.calls[0]["delay"],
            F3_COORDINATOR_CONFIG_INTERVAL_MS,
        )

    def test_heavy_cycle_reserves_real_event_loop_idle(self):
        app, coordinator = self._install()
        with patch.object(
            coordinator_module.time,
            "perf_counter",
            side_effect=[10.0, 10.100],
        ):
            app.root.run_next()

        self.assertEqual(1, len(app.root.calls))
        self.assertGreaterEqual(
            app.root.calls[0]["delay"],
            F3_COORDINATOR_VERY_HEAVY_IDLE_MS,
        )
        self.assertGreaterEqual(
            coordinator.stats()["last_idle_ms"],
            F3_COORDINATOR_VERY_HEAVY_IDLE_MS,
        )

    def test_stop_cancels_the_single_owned_timer(self):
        app, coordinator = self._install()
        token = app.display_f3_after_id
        coordinator.stop()

        self.assertIn(token, app.root.cancelled)
        self.assertEqual([], app.root.calls)
        self.assertIsNone(app.display_f3_after_id)
        self.assertFalse(coordinator.stats()["running"])

    def test_rearm_new_frame_forces_full_cycle_even_when_analysis_not_due(self):
        app, coordinator = self._install()
        app.analysis_due = False
        app._display_f3_waiting_empty_rearm = True
        app.root.run_next()

        self.assertEqual(1, app.full_cycles)
        self.assertEqual(
            "rearm_new_frame",
            coordinator.stats()["last_reason"],
        )


if __name__ == "__main__":
    unittest.main()
