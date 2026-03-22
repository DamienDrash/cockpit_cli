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
from cockpit.infrastructure.shell.local_shell_adapter import LocalShellAdapter
from cockpit.runtime.stream_router import StreamRouter
from cockpit.runtime.task_supervisor import BackgroundTask, TaskSupervisor
from cockpit.shared.enums import StatusLevel


@dataclass(slots=True)
class TerminalSession:
    panel_id: str
    cwd: str
    process: subprocess.Popen[bytes]
    master_fd: int
    task: BackgroundTask
    rows: int | None = None
    cols: int | None = None


class PTYManager:
    """Starts, stops, and monitors local PTY sessions."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        shell_adapter: LocalShellAdapter,
        stream_router: StreamRouter,
        task_supervisor: TaskSupervisor,
    ) -> None:
        self._event_bus = event_bus
        self._shell_adapter = shell_adapter
        self._stream_router = stream_router
        self._task_supervisor = task_supervisor
        self._sessions: dict[str, TerminalSession] = {}
        self._lock = Lock()

    def start_session(
        self,
        panel_id: str,
        cwd: str,
        *,
        command: list[str] | tuple[str, ...] | None = None,
    ) -> TerminalSession | None:
        self.stop_session(panel_id)
        master_fd = -1
        slave_fd = -1
        try:
            launch = self._shell_adapter.build_launch_config(cwd, command=command)
            master_fd, slave_fd = pty.openpty()
            process = subprocess.Popen(
                launch.command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=launch.cwd,
                env=launch.env,
                close_fds=True,
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
        task = self._task_supervisor.spawn(
            task_name,
            lambda stop_event: self._reader_loop(
                panel_id=panel_id,
                process=process,
                master_fd=master_fd,
                stop_event=stop_event,
            ),
        )
        session = TerminalSession(
            panel_id=panel_id,
            cwd=launch.cwd,
            process=process,
            master_fd=master_fd,
            task=task,
        )
        with self._lock:
            self._sessions[panel_id] = session
        self._event_bus.publish(
            PTYStarted(
                panel_id=panel_id,
                cwd=launch.cwd,
                pid=process.pid,
            )
        )
        return session

    def stop_session(self, panel_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(panel_id, None)
        if session is None:
            return

        if session.process.poll() is None:
            session.process.terminate()
            try:
                session.process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                session.process.kill()
                session.process.wait(timeout=1.0)

        self._task_supervisor.stop(session.task.name, timeout=1.0)
        try:
            os.close(session.master_fd)
        except OSError:
            pass

    def restart_session(
        self,
        panel_id: str,
        cwd: str,
        *,
        command: list[str] | tuple[str, ...] | None = None,
    ) -> TerminalSession | None:
        return self.start_session(panel_id, cwd, command=command)

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
        stop_event: object,
    ) -> None:
        while True:
            if getattr(stop_event, "is_set")() and process.poll() is not None:
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

            if process.poll() is not None and not readable:
                break

        exit_code = process.poll()
        self._event_bus.publish(
            TerminalExited(
                panel_id=panel_id,
                exit_code=exit_code if exit_code is not None else -1,
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
