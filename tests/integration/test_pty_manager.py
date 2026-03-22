from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import time
import unittest

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.domain.events.runtime_events import (
    PTYStarted,
    PTYStartupFailed,
    ProcessOutputReceived,
    TerminalExited,
)
from cockpit.infrastructure.shell.base import ShellLaunchConfig
from cockpit.infrastructure.shell.local_shell_adapter import LocalShellAdapter
from cockpit.runtime.pty_manager import PTYManager
from cockpit.runtime.stream_router import StreamRouter
from cockpit.runtime.task_supervisor import TaskSupervisor
from cockpit.shared.enums import SessionTargetKind


class PTYManagerTests(unittest.TestCase):
    def test_starts_streams_and_stops_local_session(self) -> None:
        with TemporaryDirectory() as temp_dir:
            manager, bus, router = self._build_manager()
            started = Event()
            output_seen = Event()
            exited = Event()

            bus.subscribe(
                PTYStarted,
                lambda event: started.set() if event.panel_id == "work-panel" else None,
            )
            bus.subscribe(
                ProcessOutputReceived,
                lambda event: (
                    output_seen.set()
                    if event.panel_id == "work-panel" and "ready" in event.chunk
                    else None
                ),
            )
            bus.subscribe(
                TerminalExited,
                lambda event: exited.set() if event.panel_id == "work-panel" else None,
            )

            session = manager.start_session(
                "work-panel",
                temp_dir,
                command=["/bin/sh", "-lc", "printf 'ready\\n'; sleep 30"],
            )

            self.assertIsNotNone(session)
            self.assertTrue(started.wait(1.0))
            self.assertTrue(output_seen.wait(2.0))
            self.assertIn("ready", router.get_buffer("work-panel"))

            manager.stop_session("work-panel")

            self.assertTrue(exited.wait(2.0))
            manager.shutdown()

    def test_send_input_reaches_running_process(self) -> None:
        with TemporaryDirectory() as temp_dir:
            manager, bus, router = self._build_manager()
            output_seen = Event()

            def on_output(event: ProcessOutputReceived) -> None:
                if event.panel_id != "work-panel":
                    return
                if "hello from cockpit" in event.chunk:
                    output_seen.set()

            bus.subscribe(ProcessOutputReceived, on_output)

            session = manager.start_session(
                "work-panel",
                temp_dir,
                command=["/bin/cat"],
            )

            self.assertIsNotNone(session)
            manager.send_input("work-panel", "hello from cockpit\n")

            self.assertTrue(output_seen.wait(2.0))
            self.assertIn("hello from cockpit", router.get_buffer("work-panel"))
            manager.stop_session("work-panel")
            manager.shutdown()

    def test_emits_explicit_startup_failure_event(self) -> None:
        with TemporaryDirectory() as temp_dir:
            manager, bus, _router = self._build_manager()
            failed = Event()
            captured: list[PTYStartupFailed] = []

            def on_failure(event: PTYStartupFailed) -> None:
                if event.panel_id != "work-panel":
                    return
                captured.append(event)
                failed.set()

            bus.subscribe(PTYStartupFailed, on_failure)

            session = manager.start_session(
                "work-panel",
                temp_dir,
                command=["/definitely/missing-shell"],
            )

            self.assertIsNone(session)
            self.assertTrue(failed.wait(1.0))
            self.assertTrue(captured)
            self.assertIn("missing-shell", captured[0].reason)
            manager.shutdown()

    def test_resize_session_reaches_running_process(self) -> None:
        with TemporaryDirectory() as temp_dir:
            manager, bus, router = self._build_manager()
            first_output = Event()
            resized_output = Event()

            def on_output(event: ProcessOutputReceived) -> None:
                if event.panel_id != "work-panel":
                    return
                buffer = router.get_buffer("work-panel")
                if "\n" in buffer:
                    first_output.set()
                if "33 120" in buffer:
                    resized_output.set()

            bus.subscribe(ProcessOutputReceived, on_output)

            session = manager.start_session(
                "work-panel",
                temp_dir,
                command=["/bin/sh", "-lc", "stty size; sleep 2; stty size; sleep 30"],
            )

            self.assertIsNotNone(session)
            self.assertTrue(first_output.wait(2.0))
            manager.resize_session("work-panel", rows=33, cols=120)

            self.assertTrue(resized_output.wait(3.0))
            self.assertEqual(manager.get_session("work-panel").rows, 33)
            self.assertEqual(manager.get_session("work-panel").cols, 120)
            manager.stop_session("work-panel")
            manager.shutdown()

    def test_exited_session_is_removed_from_registry(self) -> None:
        with TemporaryDirectory() as temp_dir:
            manager, bus, _router = self._build_manager()
            exited = Event()

            def on_exit(event: TerminalExited) -> None:
                if event.panel_id == "work-panel":
                    exited.set()

            bus.subscribe(TerminalExited, on_exit)

            session = manager.start_session(
                "work-panel",
                temp_dir,
                command=["/bin/sh", "-lc", "printf 'bye\\n'"],
            )

            self.assertIsNotNone(session)
            self.assertTrue(exited.wait(2.0))
            self.assertTrue(self._wait_for(lambda: manager.get_session("work-panel") is None))
            manager.shutdown()

    def test_starts_remote_session_and_preserves_target_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            bus = EventBus()
            router = StreamRouter()
            manager = PTYManager(
                event_bus=bus,
                shell_adapter=FakeRemoteShellAdapter(),
                stream_router=router,
                task_supervisor=TaskSupervisor(),
            )
            started = Event()
            seen: list[PTYStarted] = []

            def on_started(event: PTYStarted) -> None:
                if event.panel_id == "work-panel":
                    seen.append(event)
                    started.set()

            bus.subscribe(PTYStarted, on_started)

            session = manager.start_session(
                "work-panel",
                temp_dir,
                target_kind=SessionTargetKind.SSH,
                target_ref="dev@example.com",
            )

            self.assertIsNotNone(session)
            assert session is not None
            self.assertTrue(started.wait(1.0))
            self.assertEqual(session.target_kind, SessionTargetKind.SSH)
            self.assertEqual(session.target_ref, "dev@example.com")
            self.assertTrue(seen)
            self.assertEqual(seen[0].target_kind, SessionTargetKind.SSH)
            self.assertEqual(seen[0].target_ref, "dev@example.com")
            manager.stop_session("work-panel")
            manager.shutdown()

    def _build_manager(self) -> tuple[PTYManager, EventBus, StreamRouter]:
        bus = EventBus()
        router = StreamRouter()
        manager = PTYManager(
            event_bus=bus,
            shell_adapter=LocalShellAdapter(shell="/bin/sh"),
            stream_router=router,
            task_supervisor=TaskSupervisor(),
        )
        return manager, bus, router

    def _wait_for(self, predicate: object, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return bool(predicate())

class FakeRemoteShellAdapter:
    def build_launch_config(
        self,
        cwd: str,
        *,
        command: list[str] | tuple[str, ...] | None = None,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
    ) -> ShellLaunchConfig:
        del cwd, command, target_kind, target_ref
        return ShellLaunchConfig(
            command=("/bin/sh", "-lc", "printf 'remote ready\\n'; sleep 30"),
            cwd=str(Path.cwd()),
            env={},
        )


if __name__ == "__main__":
    unittest.main()
