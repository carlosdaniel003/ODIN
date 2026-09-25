from __future__ import annotations

import threading
import unittest
from pathlib import Path

from src.platform.display_f3_heavy_executor import (
    F3HeavyExecutorShutdownError,
    F3HeavyVisionExecutor,
    F3HeavyWorkPriority,
)


class DisplayF3HeavyExecutorTests(unittest.TestCase):
    def setUp(self):
        self.executor = F3HeavyVisionExecutor(max_pending=4)

    def tearDown(self):
        self.executor.shutdown(
            wait=True,
            cancel_pending=True,
            timeout=2.0,
        )

    def _occupy_worker(self):
        started = threading.Event()
        release = threading.Event()

        def blocker():
            started.set()
            release.wait(2.0)
            return "blocker"

        future = self.executor.submit(
            blocker,
            priority=F3HeavyWorkPriority.NORMAL,
            name="blocker",
            owner="test",
            key="blocker",
        )
        self.assertTrue(started.wait(1.0))
        return future, release

    def test_only_one_heavy_job_runs_at_a_time(self):
        first, release = self._occupy_worker()
        second = self.executor.submit(
            lambda: "second",
            priority=F3HeavyWorkPriority.NORMAL,
            name="second",
            owner="test",
            key="second",
        )

        stats = self.executor.stats()
        self.assertEqual(1, stats["active_jobs"])
        self.assertEqual(1, stats["pending_jobs"])
        self.assertFalse(second.done())

        release.set()
        self.assertEqual("blocker", first.result(timeout=1.0))
        self.assertEqual("second", second.result(timeout=1.0))
        self.assertEqual(1, self.executor.stats()["peak_active"])

    def test_priority_orders_pending_jobs(self):
        first, release = self._occupy_worker()
        order = []
        low = self.executor.submit(
            lambda: order.append("low") or "low",
            priority=F3HeavyWorkPriority.LOW,
            name="low",
            owner="test",
            key="low",
        )
        high = self.executor.submit(
            lambda: order.append("high") or "high",
            priority=F3HeavyWorkPriority.HIGH,
            name="high",
            owner="test",
            key="high",
        )

        release.set()
        first.result(timeout=1.0)
        self.assertEqual("high", high.result(timeout=1.0))
        self.assertEqual("low", low.result(timeout=1.0))
        self.assertEqual(["high", "low"], order)

    def test_latest_pending_job_replaces_older_same_key(self):
        first, release = self._occupy_worker()
        old = self.executor.submit(
            lambda: "old",
            priority=F3HeavyWorkPriority.LOW,
            name="preview-old",
            owner="preview",
            key="same-preview",
            replace_pending=True,
        )
        new = self.executor.submit(
            lambda: "new",
            priority=F3HeavyWorkPriority.LOW,
            name="preview-new",
            owner="preview",
            key="same-preview",
            replace_pending=True,
        )

        self.assertTrue(old.cancelled())
        release.set()
        first.result(timeout=1.0)
        self.assertEqual("new", new.result(timeout=1.0))

    def test_high_priority_can_evict_low_pending_when_queue_is_full(self):
        executor = F3HeavyVisionExecutor(max_pending=2)
        started = threading.Event()
        release = threading.Event()
        try:
            active = executor.submit(
                lambda: (
                    started.set(),
                    release.wait(2.0),
                    "active",
                )[-1],
                priority=F3HeavyWorkPriority.NORMAL,
                name="active",
                owner="test",
                key="active",
            )
            self.assertTrue(started.wait(1.0))
            low_a = executor.submit(
                lambda: "low-a",
                priority=F3HeavyWorkPriority.LOW,
                name="low-a",
                owner="low",
                key="a",
            )
            low_b = executor.submit(
                lambda: "low-b",
                priority=F3HeavyWorkPriority.LOW,
                name="low-b",
                owner="low",
                key="b",
            )
            high = executor.submit(
                lambda: "high",
                priority=F3HeavyWorkPriority.HIGH,
                name="high",
                owner="high",
                key="high",
            )

            self.assertEqual(
                1,
                sum((low_a.cancelled(), low_b.cancelled())),
            )
            release.set()
            active.result(timeout=1.0)
            self.assertEqual("high", high.result(timeout=1.0))
        finally:
            release.set()
            executor.shutdown(
                wait=True,
                cancel_pending=True,
                timeout=2.0,
            )

    def test_shutdown_rejects_new_jobs(self):
        self.executor.shutdown(
            wait=True,
            cancel_pending=True,
            timeout=2.0,
        )
        future = self.executor.submit(
            lambda: None,
            priority=F3HeavyWorkPriority.NORMAL,
            name="after-shutdown",
            owner="test",
        )
        with self.assertRaises(F3HeavyExecutorShutdownError):
            future.result(timeout=0.2)

    def test_f3_modules_do_not_create_parallel_heavy_threads(self):
        root = Path(__file__).resolve().parents[1] / "src" / "platform"
        offenders = {}
        for path in sorted(root.glob("display_f3*.py")):
            if path.name == "display_f3_heavy_executor.py":
                continue
            source = path.read_text(encoding="utf-8")
            if "threading.Thread(" in source:
                offenders[path.name] = "threading.Thread("
        self.assertEqual({}, offenders)

    def test_migrated_clients_use_bounded_queues_and_executor_priorities(self):
        root = Path(__file__).resolve().parents[1] / "src" / "platform"
        config = (root / "display_f3_config_service.py").read_text(
            encoding="utf-8"
        )
        manual = (root / "display_f3_manual_snapshot_debug.py").read_text(
            encoding="utf-8"
        )
        tracking = (root / "display_f3_tracking_orientation_ui.py").read_text(
            encoding="utf-8"
        )
        production = (root / "display_production_f3.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("F3HeavyWorkPriority.LOW", config)
        self.assertIn("maxsize=F3_CONFIG_PREVIEW_RESULT_LIMIT", config)
        self.assertIn("replace_pending=True", config)

        self.assertIn("F3HeavyWorkPriority.NORMAL", manual)
        self.assertIn("F3HeavyWorkPriority.LOW", manual)
        self.assertIn("queue.Queue(maxsize=1)", manual)

        self.assertIn("F3HeavyWorkPriority.LOW", tracking)
        self.assertIn("queue.Queue(maxsize=2)", tracking)
        self.assertNotIn("threading.Thread(", tracking)

        self.assertIn("_ensure_f3_heavy_executor", production)
        self.assertIn(
            "heavy_executor=owner._ensure_f3_heavy_executor()",
            production,
        )
        self.assertIn("_on_display_f3_root_destroy", production)


if __name__ == "__main__":
    unittest.main()
