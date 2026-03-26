"""Professional WorkPanel implementation (Gold Standard)."""

from __future__ import annotations

from pathlib import Path
import shlex
from threading import get_ident

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Static

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.domain.events.runtime_events import (
    PanelMounted,
    PanelStateChanged,
    ProcessOutputReceived,
    PTYStarted,
    PTYStartupFailed,
    TerminalExited,
)
from cockpit.domain.models.panel_state import PanelState
from cockpit.infrastructure.filesystem.remote_filesystem_adapter import (
    RemoteFilesystemAdapter,
    RemotePathEntry,
)
from cockpit.infrastructure.system.clipboard import ClipboardService
from cockpit.runtime.pty_manager import PTYManager
from cockpit.runtime.stream_router import StreamRouter
from cockpit.shared.enums import SessionTargetKind
from cockpit.shared.risk import classify_target_risk, risk_presentation
from cockpit.ui.panels.base_panel import BasePanel
from cockpit.ui.widgets.embedded_terminal import EmbeddedTerminal
from cockpit.ui.widgets.file_context import FileContext
from cockpit.ui.widgets.file_explorer import FileExplorer
from cockpit.ui.branding import C_PRIMARY


class WorkPanel(BasePanel):
    """Main terminal workspace with file explorer and context awareness."""

    PANEL_ID = "work-panel"
    PANEL_TYPE = "work"
    can_focus = True

    def __init__(
        self,
        *,
        event_bus: EventBus,
        pty_manager: PTYManager,
        stream_router: StreamRouter,
        remote_filesystem_adapter: RemoteFilesystemAdapter,
        clipboard_service: ClipboardService,
    ) -> None:
        super().__init__(id=self.PANEL_ID)
        self._event_bus = event_bus
        self._pty_manager = pty_manager
        self._stream_router = stream_router
        self._remote_filesystem_adapter = remote_filesystem_adapter
        self._clipboard_service = clipboard_service
        self._workspace_root = ""
        self._target_kind = SessionTargetKind.LOCAL
        self._target_ref: str | None = None
        self._cwd = ""
        self._selected_path = ""
        self._workspace_name = "Workspace"
        self._main_thread_id = get_ident()
        self._subscriptions_registered = False

    def compose(self) -> ComposeResult:
        with Horizontal():
            # Workspace Sidebar
            with Vertical(id="work-sidebar", classes="sidebar"):
                yield FileContext()
                yield FileExplorer()
            
            # Terminal Main
            with Vertical(id="work-main"):
                yield Static("Terminal initializing...", id="work-note", classes="pane-title")
                yield EmbeddedTerminal(
                    on_input=lambda data: self._pty_manager.send_input(self.PANEL_ID, data)
                )

    def on_mount(self) -> None:
        self._main_thread_id = get_ident()
        if not self._subscriptions_registered:
            self._event_bus.subscribe(PTYStarted, self._on_runtime_event)
            self._event_bus.subscribe(PTYStartupFailed, self._on_runtime_event)
            self._event_bus.subscribe(ProcessOutputReceived, self._on_runtime_event)
            self._event_bus.subscribe(TerminalExited, self._on_runtime_event)
            self._subscriptions_registered = True
        
        self._event_bus.publish(PanelMounted(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE))
        self._sync_explorer()
        self._render_context()

    def initialize(self, context: dict[str, object]) -> None:
        self._workspace_name = str(context.get("workspace_name", "Workspace"))
        self._workspace_root = str(context.get("workspace_root", ""))
        self._target_kind = SessionTargetKind(str(context.get("target_kind", "local")))
        self._target_ref = context.get("target_ref")
        self._cwd = str(context.get("cwd", self._workspace_root))
        
        self._sync_explorer()
        self._render_context()
        self.attach_terminal()
        self.focus()

    def attach_terminal(self) -> None:
        existing = self._pty_manager.get_session(self.PANEL_ID)
        if existing is not None:
            self._restore_terminal_buffer()
            return

        if not self._cwd: return
        
        try:
            self._pty_manager.start_session(
                self.PANEL_ID,
                self._cwd,
                target_kind=self._target_kind,
                target_ref=self._target_ref,
            )
        except Exception as exc:
            self._update_note(f"Terminal failed: {exc}")

    def on_key(self, event: events.Key) -> None:
        terminal = self.query_one(EmbeddedTerminal)
        if not terminal.has_focus:
            if self.query_one(FileExplorer).has_focus:
                self._handle_explorer_key(event)
            return
            
        # PTY Input Mapping
        ansi = self._map_key_to_ansi(event)
        if ansi:
            try: self._pty_manager.send_input(self.PANEL_ID, ansi)
            except Exception: pass
            event.stop()

    def _map_key_to_ansi(self, event: events.Key) -> str | None:
        if event.key.startswith("ctrl+"):
            part = event.key.split("+")[1].upper()
            if len(part) == 1 and "A" <= part <= "Z":
                return chr(ord(part) - 64)
            return None
        
        mapping = {
            "enter": "\r", "tab": "\t", "backspace": "\x7f", "delete": "\x1b[3~",
            "up": "\x1b[A", "down": "\x1b[B", "left": "\x1b[D", "right": "\x1b[C",
            "escape": "\x1b", "home": "\x1b[H", "end": "\x1b[F",
        }
        if event.key in mapping: return mapping[event.key]
        if event.character and event.character.isprintable(): return event.character
        return None

    def _handle_explorer_key(self, event: events.Key) -> None:
        explorer = self.query_one(FileExplorer)
        if event.key == "up": explorer.move_selection(-1)
        elif event.key == "down": explorer.move_selection(1)
        elif event.key == "enter": 
            selection = explorer.open_selection()
            self._selected_path = selection.selected_path
            self._render_context()
        elif event.key == "backspace": explorer.go_parent()

    def _update_note(self, message: str) -> None:
        try: self.query_one("#work-note", Static).update(message)
        except NoMatches: pass

    def resume(self) -> None:
        self._sync_explorer()
        self._restore_terminal_buffer()
        self.focus()

    def _sync_explorer(self) -> None:
        try:
            explorer = self.query_one(FileExplorer)
            explorer.load(root_path=self._workspace_root, browser_path=self._workspace_root)
        except NoMatches: pass

    def _render_context(self) -> None:
        try:
            level = classify_target_risk(self._target_kind, self._target_ref, self._workspace_name, self._workspace_root)
            self.query_one(FileContext).update_context(
                workspace_name=self._workspace_name,
                workspace_root=self._workspace_root,
                cwd=self._cwd,
                selected_path=self._selected_path or self._workspace_root,
                target_label=self._target_kind.value,
                risk_label=risk_presentation(level).label
            )
        except NoMatches: pass

    def _on_runtime_event(self, event: object) -> None:
        if getattr(event, "panel_id", None) != self.PANEL_ID: return
        if get_ident() != self._main_thread_id:
            self.app.call_from_thread(self._apply_runtime_event, event)
        else:
            self._apply_runtime_event(event)

    def _apply_runtime_event(self, event: object) -> None:
        try:
            terminal = self.query_one(EmbeddedTerminal)
            if isinstance(event, PTYStarted):
                self._update_note(f"Terminal active: {event.cwd}")
                buffered = self._stream_router.get_buffer(self.PANEL_ID)
                if buffered: terminal.append_output(buffered)
            elif isinstance(event, ProcessOutputReceived):
                terminal.append_output(event.chunk)
            elif isinstance(event, TerminalExited):
                self._update_note(f"Terminal exited ({event.exit_code})")
        except NoMatches: pass

    def _restore_terminal_buffer(self) -> None:
        try:
            terminal = self.query_one(EmbeddedTerminal)
            buffered = self._stream_router.get_buffer(self.PANEL_ID)
            if buffered and not terminal.current_output():
                terminal.append_output(buffered)
        except NoMatches: pass

    def command_context(self) -> dict[str, object]:
        return {
            "panel_id": self.PANEL_ID,
            "workspace_root": self._workspace_root,
            "cwd": self._cwd,
            "selected_path": self._selected_path,
        }

    def snapshot_state(self) -> PanelState:
        return PanelState(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE)
