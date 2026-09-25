from __future__ import annotations

"""Proteção de responsividade do Tkinter para o Display F3.

O F3 possui várias autoridades de visão computacional instaladas por wrappers.
Mesmo com captura de câmera em thread, ORB/AKAZE, warp, identidade por contorno
e análise semântica ainda executam no callback do Tk. Esta camada final não muda
nenhuma decisão: apenas garante um intervalo para o event loop depois de ciclos
caros, evitando que callbacks pesados sejam executados em sequência e atrasem
cliques, teclas e repaints.
"""

import time
from types import MethodType


F3_TK_HEAVY_CYCLE_MS = 40.0
F3_TK_VERY_HEAVY_CYCLE_MS = 85.0
F3_TK_EXTREME_CYCLE_MS = 160.0

F3_TK_HEAVY_IDLE_MS = 28
F3_TK_VERY_HEAVY_IDLE_MS = 50
F3_TK_EXTREME_IDLE_MS = 70


def _idle_minimo_para_ciclo(elapsed_ms: float) -> int:
    elapsed = max(0.0, float(elapsed_ms))
    if elapsed >= F3_TK_EXTREME_CYCLE_MS:
        return F3_TK_EXTREME_IDLE_MS
    if elapsed >= F3_TK_VERY_HEAVY_CYCLE_MS:
        return F3_TK_VERY_HEAVY_IDLE_MS
    if elapsed >= F3_TK_HEAVY_CYCLE_MS:
        return F3_TK_HEAVY_IDLE_MS
    return 0


def instalar_responsividade_tk_display_f3(app) -> None:
    """Envolve o callback final do F3 e impede starvation do mainloop."""
    if app is None or bool(
        getattr(app, "_display_f3_tk_responsiveness_installed", False)
    ):
        return

    previous_preview = getattr(app, "_atualizar_preview_display_f3", None)
    if not callable(previous_preview):
        return

    def responsive_preview(self):
        started = time.perf_counter()
        try:
            return previous_preview()
        finally:
            elapsed_ms = max(
                0.0,
                (time.perf_counter() - started) * 1000.0,
            )
            self._display_f3_tk_last_cycle_ms = round(elapsed_ms, 2)

            if not bool(getattr(self, "display_f3_ativo", False)):
                return

            required_idle = _idle_minimo_para_ciclo(elapsed_ms)
            if required_idle <= 0:
                return

            # A camada adaptativa anterior pode já ter escolhido um intervalo
            # maior. Nunca o reduzimos; apenas elevamos o mínimo quando o callback
            # completo (inclusive wrappers finais) foi pesado.
            try:
                adaptive_idle = int(
                    getattr(self, "_display_f3_last_idle_slice_ms", 0) or 0
                )
            except (TypeError, ValueError):
                adaptive_idle = 0
            wait_ms = max(required_idle, adaptive_idle)
            self._display_f3_tk_forced_idle_ms = int(wait_ms)

            scheduled = getattr(self, "display_f3_after_id", None)
            if scheduled is not None:
                try:
                    self.root.after_cancel(scheduled)
                except Exception:
                    pass
                self.display_f3_after_id = None

            try:
                self._agendar_preview_display_f3(wait_ms)
            except Exception:
                pass

    app._atualizar_preview_display_f3 = MethodType(
        responsive_preview,
        app,
    )
    app._display_f3_tk_responsiveness_installed = True
