from threading import Event
import time
import unittest

from cockpit.runtime.task_supervisor import TaskSupervisor


class TaskSupervisorStage1Tests(unittest.TestCase):
    def test_supervised_task_emits_heartbeats_and_is_not_stale(self) -> None:
        supervisor = TaskSupervisor()
        finished = Event()

        def worker(context) -> None:
            for _ in range(3):
                context.heartbeat("tick")
                time.sleep(0.05)
            finished.set()

        supervisor.spawn_supervised(
            "heartbeat-worker",
            worker,
            heartbeat_timeout_seconds=1.0,
        )
        self.assertTrue(finished.wait(1.0))
        snapshot = supervisor.get_snapshot("heartbeat-worker")
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertFalse(snapshot.stale)
        supervisor.stop_all()

    def test_detects_stale_task(self) -> None:
        supervisor = TaskSupervisor()
        ready = Event()

        def worker(context) -> None:
            context.heartbeat("started")
            ready.set()
            while not context.stop_event.is_set():
                time.sleep(0.02)

        supervisor.spawn_supervised(
            "stale-worker",
            worker,
            heartbeat_timeout_seconds=1.0,
        )
        self.assertTrue(ready.wait(0.2))
        deadline = time.monotonic() + 1.5
        stale = []
        while time.monotonic() < deadline:
            stale = supervisor.list_stale()
            if stale:
                break
            time.sleep(0.02)
        self.assertEqual([item.name for item in stale], ["stale-worker"])
        supervisor.stop_all()

    def test_restarts_restartable_task(self) -> None:
        supervisor = TaskSupervisor()
        runs: list[int] = []

        def worker(context) -> None:
            runs.append(1)
            context.heartbeat("running")
            while not context.stop_event.is_set():
                time.sleep(0.02)

        supervisor.spawn_supervised(
            "restartable-worker",
            worker,
            heartbeat_timeout_seconds=1.0,
            restartable=True,
        )
        supervisor.restart("restartable-worker")
        snapshot = supervisor.get_snapshot("restartable-worker")
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.restart_count, 1)
        self.assertGreaterEqual(len(runs), 2)
        supervisor.stop_all()


if __name__ == "__main__":
    unittest.main()
