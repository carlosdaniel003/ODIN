from __future__ import annotations

"""Executor canônico de trabalho pesado do Display F3.

Um único worker serializa visão computacional e tarefas diagnósticas fora do
thread do Tkinter. A API oferece prioridade, backpressure, substituição de jobs
pendentes e cancelamento por proprietário sem permitir fila ilimitada.
"""

from concurrent.futures import Future
from dataclasses import dataclass
from enum import IntEnum
import threading
import time
from collections.abc import Callable


F3_HEAVY_EXECUTOR_MAX_PENDING = 8


class F3HeavyWorkPriority(IntEnum):
    HIGH = 0
    NORMAL = 10
    LOW = 20


class F3HeavyExecutorShutdownError(RuntimeError):
    pass


class F3HeavyExecutorQueueFullError(RuntimeError):
    pass


@dataclass
class _HeavyJob:
    sequence: int
    priority: int
    name: str
    owner: str
    key: str
    callback: Callable[[], object]
    future: Future
    submitted_at: float


class F3HeavyVisionExecutor:
    """Single Owner dos jobs pesados assíncronos do F3."""

    def __init__(
        self,
        *,
        max_pending: int = F3_HEAVY_EXECUTOR_MAX_PENDING,
    ) -> None:
        self.max_pending = max(1, int(max_pending))
        self._condition = threading.Condition()
        self._pending: list[_HeavyJob] = []
        self._active: _HeavyJob | None = None
        self._shutdown_requested = False
        self._sequence = 0
        self._submitted = 0
        self._completed = 0
        self._failed = 0
        self._cancelled = 0
        self._rejected = 0
        self._peak_active = 0
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="ODIN-F3-HeavyVision",
            daemon=True,
        )
        self._worker.start()

    @property
    def is_shutdown(self) -> bool:
        with self._condition:
            return bool(self._shutdown_requested)

    def submit(
        self,
        callback: Callable[[], object],
        *,
        priority: F3HeavyWorkPriority = F3HeavyWorkPriority.NORMAL,
        name: str,
        owner: str,
        key: str = "",
        replace_pending: bool = False,
    ) -> Future:
        future: Future = Future()
        job_priority = int(priority)
        job_owner = str(owner or "f3")
        job_key = str(key or "")
        job_name = str(name or "f3-heavy-job")

        with self._condition:
            if self._shutdown_requested:
                self._rejected += 1
                future.set_exception(
                    F3HeavyExecutorShutdownError(
                        "Executor pesado do F3 já foi encerrado."
                    )
                )
                return future

            if replace_pending and job_key:
                self._cancel_matching_pending_locked(
                    owner=job_owner,
                    key=job_key,
                )

            if len(self._pending) >= self.max_pending:
                evictable = [
                    item
                    for item in self._pending
                    if int(item.priority) > job_priority
                ]
                if evictable:
                    victim = max(
                        evictable,
                        key=lambda item: (
                            int(item.priority),
                            -int(item.sequence),
                        ),
                    )
                    self._pending.remove(victim)
                    if victim.future.cancel():
                        self._cancelled += 1
                else:
                    self._rejected += 1
                    future.set_exception(
                        F3HeavyExecutorQueueFullError(
                            "Fila limitada do executor pesado do F3 está cheia."
                        )
                    )
                    return future

            self._sequence += 1
            job = _HeavyJob(
                sequence=int(self._sequence),
                priority=job_priority,
                name=job_name,
                owner=job_owner,
                key=job_key,
                callback=callback,
                future=future,
                submitted_at=time.monotonic(),
            )
            self._pending.append(job)
            self._submitted += 1
            self._condition.notify()
        return future

    def cancel_owner(self, owner: str) -> int:
        target = str(owner or "")
        if not target:
            return 0
        with self._condition:
            jobs = [
                item for item in self._pending
                if item.owner == target
            ]
            for item in jobs:
                self._pending.remove(item)
                if item.future.cancel():
                    self._cancelled += 1
            return len(jobs)

    def cancel_pending(self, *, owner: str, key: str) -> int:
        with self._condition:
            return self._cancel_matching_pending_locked(
                owner=str(owner or ""),
                key=str(key or ""),
            )

    def _cancel_matching_pending_locked(
        self,
        *,
        owner: str,
        key: str,
    ) -> int:
        jobs = [
            item
            for item in self._pending
            if item.owner == owner and item.key == key
        ]
        for item in jobs:
            self._pending.remove(item)
            if item.future.cancel():
                self._cancelled += 1
        return len(jobs)

    def stats(self) -> dict:
        with self._condition:
            active = self._active
            return {
                "worker_name": self._worker.name,
                "max_workers": 1,
                "active_jobs": 1 if active is not None else 0,
                "active_name": active.name if active is not None else "",
                "active_owner": active.owner if active is not None else "",
                "pending_jobs": len(self._pending),
                "max_pending": int(self.max_pending),
                "submitted": int(self._submitted),
                "completed": int(self._completed),
                "failed": int(self._failed),
                "cancelled": int(self._cancelled),
                "rejected": int(self._rejected),
                "peak_active": int(self._peak_active),
                "shutdown": bool(self._shutdown_requested),
            }

    def shutdown(
        self,
        *,
        wait: bool = False,
        cancel_pending: bool = True,
        timeout: float | None = None,
    ) -> None:
        with self._condition:
            if not self._shutdown_requested:
                self._shutdown_requested = True
                if cancel_pending:
                    for item in tuple(self._pending):
                        if item.future.cancel():
                            self._cancelled += 1
                    self._pending.clear()
                self._condition.notify_all()
        if (
            wait
            and threading.current_thread() is not self._worker
            and self._worker.is_alive()
        ):
            self._worker.join(timeout=timeout)

    def _next_job_locked(self) -> _HeavyJob:
        job = min(
            self._pending,
            key=lambda item: (
                int(item.priority),
                int(item.sequence),
            ),
        )
        self._pending.remove(job)
        return job

    def _worker_loop(self) -> None:
        while True:
            with self._condition:
                while not self._pending and not self._shutdown_requested:
                    self._condition.wait()
                if self._shutdown_requested and not self._pending:
                    return
                job = self._next_job_locked()
                self._active = job
                self._peak_active = max(self._peak_active, 1)

            if not job.future.set_running_or_notify_cancel():
                with self._condition:
                    self._active = None
                continue

            try:
                result = job.callback()
            except Exception as exc:
                job.future.set_exception(exc)
                with self._condition:
                    self._failed += 1
            else:
                job.future.set_result(result)
                with self._condition:
                    self._completed += 1
            finally:
                with self._condition:
                    self._active = None
                    self._condition.notify_all()
