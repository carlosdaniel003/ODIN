from __future__ import annotations

"""Coordenador canônico do runtime periódico do Display F3.

Responsabilidades desta etapa:
- possuir o único scheduler periódico do F3;
- coalescer frames repetidos (latest-frame-wins);
- separar repaint leve de ciclo operacional completo;
- pausar o pipeline pesado durante configuração;
- aplicar backpressure temporal depois de ciclos caros;
- publicar métricas de scheduling.

O coordenador orquestra o pipeline existente. Ele não implementa tracking,
presença, energia, regra de CHECK ou state machine; essas autoridades serão
consolidadas separadamente na Etapa 5.
"""

import time


F3_COORDINATOR_CONFIG_INTERVAL_MS = 280
F3_COORDINATOR_HEAVY_CYCLE_MS = 40.0
F3_COORDINATOR_VERY_HEAVY_CYCLE_MS = 85.0
F3_COORDINATOR_EXTREME_CYCLE_MS = 160.0
F3_COORDINATOR_HEAVY_IDLE_MS = 28
F3_COORDINATOR_VERY_HEAVY_IDLE_MS = 50
F3_COORDINATOR_EXTREME_IDLE_MS = 70


class F3RuntimeCoordinator:
    """Single Owner do timer periódico do Display F3."""

    def __init__(self, app) -> None:
        if app is None:
            raise ValueError("F3RuntimeCoordinator requer app.")
        self.app = app
        self.root = app.root
        self._full_cycle = app._atualizar_preview_display_f3
        self._render_once = app._render_preview_display_f3_once
        self._after_id = None
        self._running = False
        self._shutdown = False
        self._in_tick = False
        self._requested_delay_ms = None
        self._last_frame_token = None
        self._last_full_cycle_frame_token = None
        self._tick_count = 0
        self._full_cycle_count = 0
        self._render_only_count = 0
        self._repeated_frame_count = 0
        self._last_cycle_ms = 0.0
        self._last_idle_ms = 0
        self._last_path = "idle"
        self._last_reason = "created"

    @property
    def is_shutdown(self) -> bool:
        return bool(self._shutdown)

    @property
    def scheduled_after_id(self):
        return self._after_id

    def start(self, delay_ms: int = 0) -> None:
        if self._shutdown:
            return
        self._running = True
        self.schedule(delay_ms)

    def stop(self) -> None:
        self._running = False
        self._requested_delay_ms = None
        token = self._after_id
        self._after_id = None
        self.app.display_f3_after_id = None
        if token is not None:
            try:
                self.root.after_cancel(token)
            except Exception:
                pass

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self.stop()
        self._shutdown = True

    def schedule(self, delay_ms: int | None = None) -> None:
        """Agenda no máximo um callback.

        Chamadas históricas a _agendar_preview_display_f3 durante um ciclo viram
        apenas pedidos de cadência; somente este objeto toca root.after().
        """
        if self._shutdown:
            return
        if not bool(getattr(self.app, "display_f3_ativo", False)):
            return
        self._running = True
        delay = self._base_interval_ms() if delay_ms is None else max(
            0,
            int(delay_ms),
        )

        if self._in_tick:
            current = self._requested_delay_ms
            self._requested_delay_ms = (
                delay if current is None else min(int(current), delay)
            )
            return

        if self._after_id is not None:
            return
        try:
            token = self.root.after(delay, self._tick)
        except Exception:
            token = None
        self._after_id = token
        self.app.display_f3_after_id = token

    def stats(self) -> dict:
        return {
            "single_scheduler": True,
            "running": bool(self._running),
            "shutdown": bool(self._shutdown),
            "scheduled": self._after_id is not None,
            "tick_count": int(self._tick_count),
            "full_cycle_count": int(self._full_cycle_count),
            "render_only_count": int(self._render_only_count),
            "repeated_frame_count": int(self._repeated_frame_count),
            "last_cycle_ms": round(float(self._last_cycle_ms), 2),
            "last_idle_ms": int(self._last_idle_ms),
            "last_path": str(self._last_path),
            "last_reason": str(self._last_reason),
            "last_frame_token": self._last_frame_token,
            "last_full_cycle_frame_token": self._last_full_cycle_frame_token,
        }

    def _base_interval_ms(self) -> int:
        try:
            return max(
                1,
                int(
                    getattr(
                        self.app,
                        "DISPLAY_F3_PREVIEW_INTERVAL_MS",
                        16,
                    )
                    or 16
                ),
            )
        except (TypeError, ValueError):
            return 16

    def _configuration_open(self) -> bool:
        if bool(
            getattr(
                self.app,
                "_display_f3_configuration_opening",
                False,
            )
        ):
            return True
        window = getattr(
            self.app,
            "_display_project_config_window",
            None,
        )
        if window is None:
            return False
        try:
            return bool(window.visible)
        except Exception:
            return False

    def _frame_token(self):
        frame = getattr(self.app, "camera_frame_atual", None)
        if frame is None or getattr(frame, "size", 0) == 0:
            return None
        token_fn = getattr(self.app, "_display_auto_frame_token", None)
        if callable(token_fn):
            try:
                return token_fn(frame)
            except Exception:
                pass
        camera_id = getattr(self.app, "camera_ultimo_frame_id", None)
        if isinstance(camera_id, int) and camera_id >= 0:
            return ("camera", int(camera_id))
        return ("object", id(frame))

    def _analysis_due(self) -> bool:
        due_fn = getattr(
            self.app,
            "_display_auto_analysis_due_now",
            None,
        )
        if not callable(due_fn):
            return True
        try:
            return bool(due_fn())
        except Exception:
            return True

    def _tracking_needs_initial_lock(self) -> bool:
        enabled = bool(
            getattr(
                self.app,
                "_display_f3_object_tracking_enabled",
                False,
            )
        )
        if not enabled:
            return False
        if bool(
            getattr(
                self.app,
                "_display_f3_tracking_config_open",
                False,
            )
        ):
            return False
        return getattr(self.app, "_display_f3_tracking_result", None) is None

    def _rearm_pending(self) -> bool:
        return bool(
            getattr(self.app, "_display_f3_waiting_empty_rearm", False)
            or getattr(
                self.app,
                "_display_f3_waiting_new_board_after_empty",
                False,
            )
        )

    @staticmethod
    def _idle_after_cycle(elapsed_ms: float) -> int:
        elapsed = max(0.0, float(elapsed_ms))
        if elapsed >= F3_COORDINATOR_EXTREME_CYCLE_MS:
            return F3_COORDINATOR_EXTREME_IDLE_MS
        if elapsed >= F3_COORDINATOR_VERY_HEAVY_CYCLE_MS:
            return F3_COORDINATOR_VERY_HEAVY_IDLE_MS
        if elapsed >= F3_COORDINATOR_HEAVY_CYCLE_MS:
            return F3_COORDINATOR_HEAVY_IDLE_MS
        return 0

    def _choose_path(self, frame_token) -> tuple[str, str]:
        if self._configuration_open():
            return "render_only", "configuration_open"
        if frame_token is None:
            return "render_only", "no_frame"

        if bool(
            getattr(
                self.app,
                "_display_f3_tracking_analysis_pending",
                False,
            )
        ):
            return "full_cycle", "tracking_analysis_pending"

        new_frame = frame_token != self._last_frame_token
        if not new_frame:
            self._repeated_frame_count += 1
            return "render_only", "repeated_frame"

        if self._rearm_pending():
            return "full_cycle", "rearm_new_frame"
        if self._tracking_needs_initial_lock():
            return "full_cycle", "tracking_initial_lock"
        if self._analysis_due():
            return "full_cycle", "analysis_due_new_frame"
        return "render_only", "analysis_not_due"

    def _tick(self) -> None:
        self._after_id = None
        self.app.display_f3_after_id = None
        if (
            self._shutdown
            or not self._running
            or not bool(getattr(self.app, "display_f3_ativo", False))
        ):
            self._running = False
            return

        self._tick_count += 1
        self._requested_delay_ms = None
        frame_token = self._frame_token()
        path, reason = self._choose_path(frame_token)
        started = time.perf_counter()
        self._in_tick = True
        try:
            if path == "full_cycle":
                self._full_cycle_count += 1
                self._last_full_cycle_frame_token = frame_token
                self._full_cycle()
            else:
                self._render_only_count += 1
                self._render_once()
        finally:
            elapsed_ms = max(
                0.0,
                (time.perf_counter() - started) * 1000.0,
            )
            self._in_tick = False
            self._last_cycle_ms = elapsed_ms
            self._last_frame_token = frame_token
            self._last_path = path
            self._last_reason = reason
            self.app._display_f3_coordinator_last_cycle_ms = round(
                elapsed_ms,
                2,
            )
            self.app._display_f3_runtime_coordinator_stats = self.stats()

        if (
            self._shutdown
            or not bool(getattr(self.app, "display_f3_ativo", False))
        ):
            self._running = False
            return

        if self._configuration_open():
            wait_ms = F3_COORDINATOR_CONFIG_INTERVAL_MS
        else:
            wait_ms = self._base_interval_ms()
            requested = self._requested_delay_ms
            if requested is not None:
                # Pedidos internos não criam timers. Eles podem apenas tornar o
                # próximo tick mais cedo que a cadência padrão.
                wait_ms = min(wait_ms, max(0, int(requested)))
            idle = self._idle_after_cycle(self._last_cycle_ms)
            if idle > 0:
                wait_ms = max(wait_ms, idle)

        self._last_idle_ms = int(wait_ms)
        self.app._display_f3_coordinator_idle_ms = int(wait_ms)
        self.schedule(wait_ms)


def instalar_coordenador_runtime_display_f3(app) -> F3RuntimeCoordinator | None:
    """Instala o coordenador depois de todos os wrappers/autoridades finais."""
    if app is None:
        return None
    existing = getattr(app, "_display_f3_runtime_coordinator", None)
    if isinstance(existing, F3RuntimeCoordinator) and not existing.is_shutdown:
        return existing

    coordinator = F3RuntimeCoordinator(app)
    app._display_f3_runtime_coordinator = coordinator
    app._display_f3_runtime_coordinator_installed = True
    if bool(getattr(app, "display_f3_ativo", False)):
        coordinator.start(0)
    return coordinator
