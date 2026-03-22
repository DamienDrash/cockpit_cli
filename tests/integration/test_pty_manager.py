from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.domain.events.runtime_events import (
    PTYStarted,
    PTYStartupFailed,
    ProcessOutputReceived,
    TerminalExited,
)
from cockpit.infrastructure.shell.local_shell_adapter import LocalShellAdapter
from cockpit.runtime.pty_manager import PTYManager
from cockpit.runtime.stream_router import StreamRouter
from cockpit.runtime.task_supervisor import TaskSupervisor


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


if __name__ == "__main__":
    unittest.main()
