"""Reference WorkPanel implementation with safe Keyboard mapping."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
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
from cockpit.infrastructure.system.clipboard import ClipboardError, ClipboardService
from cockpit.runtime.pty_manager import PTYManager
from cockpit.runtime.stream_router import StreamRouter
from cockpit.shared.enums import SessionTargetKind
from cockpit.shared.risk import classify_target_risk, risk_presentation
from cockpit.ui.panels.base_panel import BasePanel
from cockpit.ui.widgets.embedded_terminal import EmbeddedTerminal
from cockpit.ui.widgets.file_context import FileContext
from cockpit.ui.widgets.file_explorer import FileExplorer


class WorkPanel(BasePanel):
    """Workspace-first reference panel with safe keyboard mapping."""

    PANEL_ID = "work-panel"
    PANEL_TYPE = "work"

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
        self._main_thread_id = get_ident()
        self._subscriptions_registered = False
        self._workspace_name = "No workspace"
        self._workspace_root = ""
        self._workspace_id: str | None = None
        self._session_id: str | None = None
        self._target_kind = SessionTargetKind.LOCAL
        self._target_ref: str | None = None
        self._cwd = ""
        self._browser_path = ""
        self._selected_path = ""
        self._remote_entries: list[RemotePathEntry] = []
        self._remote_selected_index = 0
        self._restored = False
        self._recovery_message: str | None = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="work-sidebar"):
                yield FileContext()
                yield FileExplorer()
            with Vertical(id="work-main"):
                yield Static("Terminal initializing...", id="work-panel-note")
                yield EmbeddedTerminal(on_input=lambda data: self._pty_manager.send_input(self.PANEL_ID, data))

    def on_mount(self) -> None:
        self._main_thread_id = get_ident()
        if not self._subscriptions_registered:
            self._event_bus.subscribe(PTYStarted, self._on_runtime_event)
            self._event_bus.subscribe(PTYStartupFailed, self._on_runtime_event)
            self._event_bus.subscribe(ProcessOutputReceived, self._on_runtime_event)
            self._event_bus.subscribe(TerminalExited, self._on_runtime_event)
            self._subscriptions_registered = True
        self._event_bus.publish(
            PanelMounted(
                panel_id=self.PANEL_ID,
                panel_type=self.PANEL_TYPE,
            )
        )
        if self._workspace_root or self._cwd:
            self._sync_explorer()
        self._render_context()
        self._refresh_terminal_status()

    def initialize(self, context: dict[str, object]) -> None:
        self._workspace_name = str(context.get("workspace_name", "Workspace"))
        self._workspace_root = str(context.get("workspace_root", ""))
        self._workspace_id = self._optional_str(context.get("workspace_id"))
        self._session_id = self._optional_str(context.get("session_id"))
        self._target_kind = self._target_kind_from_context(context.get("target_kind"))
        self._target_ref = self._optional_str(context.get("target_ref"))
        self._cwd = str(context.get("cwd", self._workspace_root))
        self._browser_path = str(
            context.get("browser_path", context.get("selected_path", self._workspace_root))
        )
        self._selected_path = str(context.get("selected_path", self._workspace_root))
        self._restored = bool(context.get("restored", False))
        
        self._sync_explorer()
        self._render_context()
        self.query_one(FileExplorer).focus()
        self.attach_terminal()

    def restore_state(self, snapshot: dict[str, object]) -> None:
        cwd = snapshot.get("cwd")
        if isinstance(cwd, str) and cwd:
            self._cwd = cwd
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
        existing = self._pty_manager.get_session(self.PANEL_ID)
        if existing is not None:
            self._refresh_terminal_status()
            self._restore_terminal_buffer()
            self._sync_terminal_size()
            return

        if not self._cwd:
            return
        
        try:
            self._pty_manager.start_session(
                self.PANEL_ID,
                self._cwd,
                target_kind=self._target_kind,
                target_ref=self._target_ref,
            )
            self._refresh_terminal_status()
        except Exception as exc:
            self._update_note(f"Terminal failed: {exc}")

    def _refresh_terminal_status(self) -> None:
        session = self._pty_manager.get_session(self.PANEL_ID)
        if session:
            self._update_note(f"Terminal active on {self._target_label()}.")
        else:
            self._update_note(f"Terminal ready on {self._target_label()}.")

    def _update_note(self, message: str) -> None:
        try:
            self.query_one("#work-panel-note", Static).update(message)
        except NoMatches:
            pass

    def focus_terminal(self) -> None:
        self.query_one(EmbeddedTerminal).focus()

    def on_resize(self, _event: events.Resize) -> None:
        self._sync_terminal_size()

    def on_key(self, event: events.Key) -> None:
        terminal = self.query_one(EmbeddedTerminal)
        if not terminal.has_focus:
            if self.query_one(FileExplorer).has_focus:
                self._handle_local_explorer_key(event)
            return
            
        if event.key == "pageup":
            terminal.page_up()
            event.stop()
            return
        if event.key == "pagedown":
            terminal.page_down()
            event.stop()
            return
            
        payload = self._map_key_to_ansi(event)
        if payload:
            try:
                self._pty_manager.send_input(self.PANEL_ID, payload)
            except LookupError:
                pass
            event.stop()

    def _map_key_to_ansi(self, event: events.Key) -> str | None:
        if event.key and event.key.startswith("ctrl+"):
            part = event.key.split("+")[1].upper()
            # ONLY map letters A-Z to control characters
            if len(part) == 1 and "A" <= part <= "Z":
                return chr(ord(part) - 64)
            # Numbers (ctrl+1, etc.) should be handled by Textual, not sent to PTY
            return None
        
        mapping = {
            "enter": "\r",
            "tab": "\t",
            "backspace": "\x7f",
            "delete": "\x1b[3~",
            "up": "\x1b[A",
            "down": "\x1b[B",
            "left": "\x1b[D",
            "right": "\x1b[C",
            "escape": "\x1b",
            "home": "\x1b[H",
            "end": "\x1b[F",
            "f1": "\x1bOP", "f2": "\x1bOQ", "f3": "\x1bOR", "f4": "\x1bOS",
            "f5": "\x1b[15~", "f6": "\x1b[17~", "f7": "\x1b[18~", "f8": "\x1b[19~",
            "f9": "\x1b[20~", "f10": "\x1b[21~", "f11": "\x1b[23~", "f12": "\x1b[24~",
        }
        if event.key in mapping:
            return mapping[event.key]
        if event.character and event.character.isprintable():
            return event.character
        return None

    def _handle_local_explorer_key(self, event: events.Key) -> None:
        explorer = self.query_one(FileExplorer)
        if event.key == "up":
            self._apply_explorer_selection(explorer.move_selection(-1))
            event.stop()
        elif event.key == "down":
            self._apply_explorer_selection(explorer.move_selection(1))
            event.stop()
        elif event.key == "enter":
            self._apply_explorer_selection(explorer.open_selection())
            event.stop()
        elif event.key == "e":
            selected = self._selected_path
            if selected and Path(selected).is_file():
                # Clean line and run nano
                cmd = f"\x03\x0c nano {shlex.quote(selected)}\r"
                self._pty_manager.send_input(self.PANEL_ID, cmd)
                self.focus_terminal()
            event.stop()
        elif event.key == "backspace":
            self._apply_explorer_selection(explorer.go_parent())
            event.stop()

    def command_context(self) -> dict[str, object]:
        return {
            "panel_id": self.PANEL_ID,
            "workspace_id": self._workspace_id,
            "session_id": self._session_id,
            "target_kind": self._target_kind.value,
            "target_ref": self._target_ref,
            "workspace_root": self._workspace_root,
            "cwd": self._cwd or self._workspace_root,
            "browser_path": self._browser_path or self._workspace_root,
            "selected_path": self._selected_path or self._workspace_root,
        }

    def _render_context(self) -> None:
        self.query_one(FileContext).update_context(
            workspace_name=self._workspace_name,
            workspace_root=self._workspace_root or "(none)",
            cwd=self._cwd or "(none)",
            selected_path=self._selected_path or self._workspace_root or "(none)",
            restored=self._restored,
            target_label=self._target_label(),
            risk_label=self._risk_label(),
        )

    def _on_runtime_event(self, event: object) -> None:
        panel_id = getattr(event, "panel_id", None)
        if panel_id != self.PANEL_ID: return
        if not self.is_attached: return
        if get_ident() != self._main_thread_id:
            self.app.call_from_thread(self._apply_runtime_event, event)
            return
        self._apply_runtime_event(event)

    def _apply_runtime_event(self, event: object) -> None:
        widgets = self._runtime_widgets()
        if widgets is None: return
        terminal, note = widgets
        if isinstance(event, PTYStarted):
            terminal.clear(f"Terminal active in {event.cwd}")
            self._refresh_terminal_status()
            self._sync_terminal_size()
            buffered = self._stream_router.get_buffer(self.PANEL_ID)
            if buffered: terminal.append_output(buffered)
        elif isinstance(event, ProcessOutputReceived):
            terminal.append_output(event.chunk)
        elif isinstance(event, TerminalExited):
            self._update_note(f"Terminal exited ({event.exit_code}).")

    def _sync_explorer(self) -> None:
        explorer = self.query_one(FileExplorer)
        selection = explorer.load(
            root_path=self._workspace_root or self._cwd,
            browser_path=self._browser_path or self._workspace_root,
            selected_path=self._selected_path or self._workspace_root,
        )
        self._browser_path = selection.browser_path
        self._selected_path = selection.selected_path

    def _apply_explorer_selection(self, selection: object) -> None:
        self._browser_path = getattr(selection, "browser_path", self._browser_path)
        self._selected_path = getattr(selection, "selected_path", self._selected_path)
        self._render_context()
        self._publish_panel_state()

    def _publish_panel_state(self) -> None:
        state = self.snapshot_state()
        self._event_bus.publish(PanelStateChanged(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE, snapshot=state.snapshot, config=state.config))

    def _runtime_widgets(self) -> tuple[EmbeddedTerminal, Static] | None:
        try: return self.query_one(EmbeddedTerminal), self.query_one("#work-panel-note", Static)
        except NoMatches: return None

    def _restore_terminal_buffer(self) -> None:
        widgets = self._runtime_widgets()
        if widgets:
            terminal, _ = widgets
            buffered = self._stream_router.get_buffer(self.PANEL_ID)
            if buffered and not terminal.current_output(): terminal.append_output(buffered)

    def _sync_terminal_size(self) -> None:
        widgets = self._runtime_widgets()
        if not widgets: return
        terminal, _ = widgets
        size = getattr(terminal, "size", None)
        if size and size.width > 0:
            try: self._pty_manager.resize_session(self.PANEL_ID, rows=max(1, size.height-2), cols=max(1, size.width-2))
            except Exception: pass

    def _target_label(self) -> str:
        if self._target_kind is SessionTargetKind.LOCAL: return "local"
        return f"{self._target_kind.value}:{self._target_ref or '?'}"

    def _risk_label(self) -> str:
        level = classify_target_risk(target_kind=self._target_kind, target_ref=self._target_ref, workspace_name=self._workspace_name, workspace_root=self._workspace_root)
        return risk_presentation(level).label

    @staticmethod
    def _optional_str(value: object) -> str | None: return value if isinstance(value, str) else None

    @staticmethod
    def _target_kind_from_context(value: object) -> SessionTargetKind:
        if isinstance(value, SessionTargetKind): return value
        try: return SessionTargetKind(str(value))
        except Exception: return SessionTargetKind.LOCAL
