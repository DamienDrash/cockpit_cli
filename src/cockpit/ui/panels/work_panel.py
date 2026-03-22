"""Reference WorkPanel implementation."""

from __future__ import annotations

from threading import get_ident

from textual import events
from textual.app import ComposeResult
from textual.widgets import Static

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.domain.events.runtime_events import (
    PTYStarted,
    PTYStartupFailed,
    PanelMounted,
    ProcessOutputReceived,
    TerminalExited,
)
from cockpit.domain.models.panel_state import PanelState
from cockpit.runtime.pty_manager import PTYManager
from cockpit.runtime.stream_router import StreamRouter
from cockpit.ui.panels.base_panel import BasePanel
from cockpit.ui.widgets.embedded_terminal import EmbeddedTerminal
from cockpit.ui.widgets.file_context import FileContext
from cockpit.ui.widgets.file_explorer import FileExplorer


class WorkPanel(BasePanel):
    """Workspace-first reference panel with an embedded local terminal."""

    PANEL_ID = "work-panel"
    PANEL_TYPE = "work"

    def __init__(
        self,
        *,
        event_bus: EventBus,
        pty_manager: PTYManager,
        stream_router: StreamRouter,
    ) -> None:
        super().__init__(id=self.PANEL_ID)
        self._event_bus = event_bus
        self._pty_manager = pty_manager
        self._stream_router = stream_router
        self._main_thread_id = get_ident()
        self._workspace_name = "No workspace"
        self._workspace_root = ""
        self._workspace_id: str | None = None
        self._session_id: str | None = None
        self._cwd = ""
        self._browser_path = ""
        self._selected_path = ""
        self._restored = False
        self._recovery_message: str | None = None

    def compose(self) -> ComposeResult:
        yield FileContext()
        yield FileExplorer()
        yield Static("Terminal not started.", id="work-panel-note")
        yield EmbeddedTerminal()

    def on_mount(self) -> None:
        self._main_thread_id = get_ident()
        self._event_bus.subscribe(PTYStarted, self._on_runtime_event)
        self._event_bus.subscribe(PTYStartupFailed, self._on_runtime_event)
        self._event_bus.subscribe(ProcessOutputReceived, self._on_runtime_event)
        self._event_bus.subscribe(TerminalExited, self._on_runtime_event)
        self._event_bus.publish(
            PanelMounted(
                panel_id=self.PANEL_ID,
                panel_type=self.PANEL_TYPE,
            )
        )
        self._render_context()

    def initialize(self, context: dict[str, object]) -> None:
        self._workspace_name = str(context.get("workspace_name", "Workspace"))
        self._workspace_root = str(context.get("workspace_root", ""))
        self._workspace_id = self._optional_str(context.get("workspace_id"))
        self._session_id = self._optional_str(context.get("session_id"))
        self._cwd = str(context.get("cwd", self._workspace_root))
        self._browser_path = str(
            context.get("browser_path", context.get("selected_path", self._workspace_root))
        )
        self._selected_path = str(context.get("selected_path", self._workspace_root))
        self._restored = bool(context.get("restored", False))
        self._recovery_message = self._optional_str(context.get("recovery_message"))
        self._sync_explorer()
        self._render_context()
        self.query_one(FileExplorer).focus()
        self.attach_terminal()

    def restore_state(self, snapshot: dict[str, object]) -> None:
        cwd = snapshot.get("cwd")
        browser_path = snapshot.get("browser_path")
        selected_path = snapshot.get("selected_path")
        if isinstance(cwd, str) and cwd:
            self._cwd = cwd
        if isinstance(browser_path, str) and browser_path:
            self._browser_path = browser_path
        if isinstance(selected_path, str) and selected_path:
            self._selected_path = selected_path
        if self.is_mounted:
            self._sync_explorer()
        self._render_context()

    def snapshot_state(self) -> PanelState:
        return PanelState(
            panel_id=self.PANEL_ID,
            panel_type=self.PANEL_TYPE,
            snapshot={
                "cwd": self._cwd,
                "browser_path": self._browser_path,
                "selected_path": self._selected_path,
            },
        )

    def attach_terminal(self) -> None:
        terminal = self.query_one(EmbeddedTerminal)
        terminal.clear("Launching terminal...")
        self.query_one("#work-panel-note", Static).update(
            f"Terminal target cwd: {self._cwd or self._workspace_root or '(unset)'}"
        )
        if not self._cwd:
            return
        self._pty_manager.start_session(self.PANEL_ID, self._cwd)

    def focus_terminal(self) -> None:
        self.query_one(EmbeddedTerminal).focus()

    def on_key(self, event: events.Key) -> None:
        terminal = self.query_one(EmbeddedTerminal)
        if not terminal.has_focus:
            if self.query_one(FileExplorer).has_focus:
                if event.key == "up":
                    self._apply_explorer_selection(
                        self.query_one(FileExplorer).move_selection(-1)
                    )
                    event.stop()
                elif event.key == "down":
                    self._apply_explorer_selection(
                        self.query_one(FileExplorer).move_selection(1)
                    )
                    event.stop()
                elif event.key == "enter":
                    self._apply_explorer_selection(
                        self.query_one(FileExplorer).open_selection()
                    )
                    event.stop()
                elif event.key == "backspace":
                    self._apply_explorer_selection(
                        self.query_one(FileExplorer).go_parent()
                    )
                    event.stop()
            return
        payload = self._terminal_payload_for_key(event)
        if payload is None:
            return
        try:
            self._pty_manager.send_input(self.PANEL_ID, payload)
        except LookupError:
            self.query_one("#work-panel-note", Static).update(
                "No active terminal session is available for input."
            )
        event.stop()

    def command_context(self) -> dict[str, object]:
        return {
            "panel_id": self.PANEL_ID,
            "workspace_id": self._workspace_id,
            "session_id": self._session_id,
            "workspace_root": self._workspace_root,
            "cwd": self._cwd or self._workspace_root,
            "browser_path": self._browser_path or self._workspace_root,
            "selected_path": self._selected_path or self._workspace_root,
        }

    def dispose(self) -> None:
        self._pty_manager.stop_session(self.PANEL_ID)

    def on_unmount(self) -> None:
        self.dispose()

    def _render_context(self) -> None:
        self.query_one(FileContext).update_context(
            workspace_name=self._workspace_name,
            workspace_root=self._workspace_root or "(none)",
            cwd=self._cwd or "(none)",
            selected_path=self._selected_path or self._workspace_root or "(none)",
            restored=self._restored,
            recovery_message=self._recovery_message,
        )

    def _on_runtime_event(self, event: object) -> None:
        panel_id = getattr(event, "panel_id", None)
        if panel_id != self.PANEL_ID:
            return
        if get_ident() != self._main_thread_id:
            self.app.call_from_thread(self._apply_runtime_event, event)
            return
        self._apply_runtime_event(event)

    def _apply_runtime_event(self, event: object) -> None:
        terminal = self.query_one(EmbeddedTerminal)
        if isinstance(event, PTYStarted):
            terminal.clear(f"Terminal running in {event.cwd}")
            self.query_one("#work-panel-note", Static).update(
                "Terminal active. Focus the terminal region to type."
            )
            buffered = self._stream_router.get_buffer(self.PANEL_ID)
            if buffered:
                terminal.append_output(buffered)
        elif isinstance(event, PTYStartupFailed):
            self.query_one("#work-panel-note", Static).update(
                "Terminal startup failed. Restart after fixing the environment."
            )
            terminal.set_status(f"Terminal failed to start: {event.reason}")
        elif isinstance(event, ProcessOutputReceived):
            terminal.append_output(event.chunk)
        elif isinstance(event, TerminalExited):
            self.query_one("#work-panel-note", Static).update(
                f"Terminal exited with code {event.exit_code}. Press Ctrl+R to restart."
            )
            terminal.set_status(f"\n[terminal exited with {event.exit_code}]")

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return value if isinstance(value, str) else None

    def _sync_explorer(self) -> None:
        explorer = self.query_one(FileExplorer)
        selection = explorer.load(
            root_path=self._workspace_root or self._cwd,
            browser_path=self._browser_path or self._selected_path or self._workspace_root,
            selected_path=self._selected_path or self._workspace_root,
        )
        self._browser_path = selection.browser_path
        self._selected_path = selection.selected_path
        if selection.recovery_message:
            self._recovery_message = self._merge_recovery_message(selection.recovery_message)
            self.query_one("#work-panel-note", Static).update(selection.recovery_message)

    def _apply_explorer_selection(self, selection: object) -> None:
        if not hasattr(selection, "browser_path") or not hasattr(selection, "selected_path"):
            return
        browser_path = getattr(selection, "browser_path", "")
        selected_path = getattr(selection, "selected_path", "")
        recovery_message = getattr(selection, "recovery_message", None)
        if isinstance(browser_path, str):
            self._browser_path = browser_path
        if isinstance(selected_path, str):
            self._selected_path = selected_path
        if isinstance(recovery_message, str) and recovery_message:
            self._recovery_message = self._merge_recovery_message(recovery_message)
            self.query_one("#work-panel-note", Static).update(recovery_message)
        else:
            self.query_one("#work-panel-note", Static).update(
                "Explorer active. Use arrows to move, Enter to open, Backspace to go up."
            )
        self._render_context()

    def _merge_recovery_message(self, message: str) -> str:
        if not self._recovery_message:
            return message
        if message in self._recovery_message:
            return self._recovery_message
        return f"{self._recovery_message} {message}"

    @staticmethod
    def _terminal_payload_for_key(event: events.Key) -> str | None:
        special_keys = {
            "enter": "\n",
            "tab": "\t",
            "backspace": "\x7f",
            "delete": "\x1b[3~",
            "up": "\x1b[A",
            "down": "\x1b[B",
            "left": "\x1b[D",
            "right": "\x1b[C",
            "ctrl+c": "\x03",
            "ctrl+d": "\x04",
            "ctrl+l": "\x0c",
        }
        if event.key in special_keys:
            return special_keys[event.key]
        if event.character and event.character.isprintable():
            return event.character
        return None
