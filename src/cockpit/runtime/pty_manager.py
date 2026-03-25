"""Local PTY runtime manager."""

from __future__ import annotations

from dataclasses import dataclass
import errno
import fcntl
import os
import pty
import select
import signal
import subprocess
import struct
import termios
from threading import Lock

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.domain.events.runtime_events import (
    PTYStarted,
    PTYStartupFailed,
    ProcessOutputReceived,
    StatusMessagePublished,
    TerminalExited,
)
from cockpit.infrastructure.shell.base import ShellAdapter
from cockpit.runtime.stream_router import StreamRouter
from cockpit.runtime.task_supervisor import BackgroundTask, SupervisedTaskContext, TaskSupervisor
from cockpit.shared.enums import SessionTargetKind, StatusLevel


@dataclass(slots=True)
class TerminalSession:
    panel_id: str
    cwd: str
    process: subprocess.Popen[bytes]
    master_fd: int
    task: BackgroundTask
    target_kind: SessionTargetKind = SessionTargetKind.LOCAL
    target_ref: str | None = None
    launch_command: tuple[str, ...] = ()
    rows: int | None = None
    cols: int | None = None


class PTYManager:
    """Starts, stops, and monitors local PTY sessions."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        shell_adapter: ShellAdapter,
        stream_router: StreamRouter,
        task_supervisor: TaskSupervisor,
    ) -> None:
        self._event_bus = event_bus
        self._shell_adapter = shell_adapter
        self._stream_router = stream_router
        self._task_supervisor = task_supervisor
        self._sessions: dict[str, TerminalSession] = {}
        self._expected_exits: set[str] = set()
        self._lock = Lock()

    def start_session(
        self,
        panel_id: str,
        cwd: str,
        *,
        command: list[str] | tuple[str, ...] | None = None,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
    ) -> TerminalSession | None:
        self.stop_session(panel_id)
        master_fd = -1
        slave_fd = -1
        try:
            launch = self._shell_adapter.build_launch_config(
                cwd,
                command=command,
                target_kind=target_kind,
                target_ref=target_ref,
            )
            master_fd, slave_fd = pty.openpty()

            def preexec() -> None:
                os.setsid()
                # Set the slave FD as the controlling terminal
                fcntl.ioctl(0, termios.TIOCSCTTY, 0)

            process = subprocess.Popen(
                launch.command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=launch.cwd,
                env=launch.env,
                close_fds=True,
                preexec_fn=preexec,
            )
            os.close(slave_fd)
            slave_fd = -1
        except Exception as exc:
            try:
                if master_fd != -1:
                    os.close(master_fd)
            except Exception:
                pass
            try:
                if slave_fd != -1:
                    os.close(slave_fd)
            except Exception:
                pass
            reason = str(exc)
            self._event_bus.publish(
                PTYStartupFailed(
                    panel_id=panel_id,
                    cwd=cwd,
                    reason=reason,
                    command=tuple(command or ()),
                    target_kind=target_kind,
                    target_ref=target_ref,
                )
            )
            self._event_bus.publish(
                StatusMessagePublished(
                    message=f"Terminal start failed: {reason}",
                    level=StatusLevel.ERROR,
                )
            )
            return None

        self._stream_router.clear(panel_id)
        task_name = f"pty-reader-{panel_id}"
        task = self._task_supervisor.spawn_supervised(
            task_name,
            lambda context: self._reader_loop(
                panel_id=panel_id,
                process=process,
                master_fd=master_fd,
                context=context,
            ),
            heartbeat_timeout_seconds=5.0,
            restartable=False,
            metadata={
                "component_kind": "pty_reader",
                "panel_id": panel_id,
                "cwd": launch.cwd,
            },
        )
        session = TerminalSession(
            panel_id=panel_id,
            cwd=launch.cwd,
            process=process,
            master_fd=master_fd,
            task=task,
            target_kind=target_kind,
            target_ref=target_ref,
            launch_command=launch.command,
        )
        with self._lock:
            self._sessions[panel_id] = session
        self._event_bus.publish(
            PTYStarted(
                panel_id=panel_id,
                cwd=launch.cwd,
                pid=process.pid,
                command=launch.command,
                target_kind=target_kind,
                target_ref=target_ref,
            )
        )
        return session

    def stop_session(self, panel_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(panel_id, None)
        if session is None:
            return

        self._expected_exits.add(panel_id)
        if session.process.poll() is None:
            session.process.terminate()
            try:
                session.process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                session.process.kill()
                session.process.wait(timeout=1.0)

        self._task_supervisor.stop(session.task.name, timeout=2.5)

    def restart_session(
        self,
        panel_id: str,
        cwd: str,
        *,
        command: list[str] | tuple[str, ...] | None = None,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
    ) -> TerminalSession | None:
        return self.start_session(
            panel_id,
            cwd,
            command=command,
            target_kind=target_kind,
            target_ref=target_ref,
        )

    def send_input(self, panel_id: str, data: str) -> None:
        session = self.get_session(panel_id)
        if session is None:
            raise LookupError(f"No PTY session exists for panel '{panel_id}'.")
        os.write(session.master_fd, data.encode("utf-8"))

    def resize_session(self, panel_id: str, *, rows: int, cols: int) -> None:
        session = self.get_session(panel_id)
        if session is None:
            raise LookupError(f"No PTY session exists for panel '{panel_id}'.")

        normalized_rows = max(1, int(rows))
        normalized_cols = max(1, int(cols))
        winsize = struct.pack("HHHH", normalized_rows, normalized_cols, 0, 0)
        fcntl.ioctl(session.master_fd, termios.TIOCSWINSZ, winsize)
        session.rows = normalized_rows
        session.cols = normalized_cols
        if session.process.poll() is None:
            session.process.send_signal(signal.SIGWINCH)

    def get_session(self, panel_id: str) -> TerminalSession | None:
        with self._lock:
            return self._sessions.get(panel_id)

    def shutdown(self) -> None:
        with self._lock:
            panel_ids = list(self._sessions.keys())
        for panel_id in panel_ids:
            self.stop_session(panel_id)
        self._task_supervisor.stop_all(timeout=1.0)

    def _reader_loop(
        self,
        *,
        panel_id: str,
        process: subprocess.Popen[bytes],
        master_fd: int,
        context: SupervisedTaskContext,
    ) -> None:
        while True:
            context.heartbeat("pty-reader-loop")
            if context.stop_event.is_set() and process.poll() is not None:
                break

            try:
                readable, _, _ = select.select([master_fd], [], [], 0.1)
            except (OSError, ValueError):
                break

            if readable:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        break
                    break
                if chunk:
                    decoded = chunk.decode("utf-8", errors="replace")
                    self._stream_router.route_output(panel_id, decoded)
                    self._event_bus.publish(
                        ProcessOutputReceived(
                            panel_id=panel_id,
                            chunk=decoded,
                        )
                    )
                    context.heartbeat("output")

            if process.poll() is not None and not readable:
                break

        exit_code = process.poll()
        with self._lock:
            expected = panel_id in self._expected_exits
            if expected:
                self._expected_exits.discard(panel_id)
            current = self._sessions.get(panel_id)
            cwd = current.cwd if current is not None else ""
            command = current.launch_command if current is not None else ()
            target_kind = current.target_kind if current is not None else SessionTargetKind.LOCAL
            target_ref = current.target_ref if current is not None else None
        self._event_bus.publish(
            TerminalExited(
                panel_id=panel_id,
                exit_code=exit_code if exit_code is not None else -1,
                cwd=cwd,
                command=command,
                expected=expected,
                target_kind=target_kind,
                target_ref=target_ref,
            )
        )
        with self._lock:
            current = self._sessions.get(panel_id)
            if current is not None and current.master_fd == master_fd:
                self._sessions.pop(panel_id, None)
        try:
            os.close(master_fd)
        except OSError:
            pass
