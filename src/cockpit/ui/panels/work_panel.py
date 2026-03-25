"""Reference WorkPanel implementation."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from threading import get_ident

from textual import events
from textual.app import ComposeResult
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
    """Workspace-first reference panel with an embedded local terminal."""

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
        self._remote_listing_message: str | None = None
        self._restored = False
        self._recovery_message: str | None = None

    def compose(self) -> ComposeResult:
        yield FileContext()
        yield FileExplorer()
        yield Static("Terminal not started.", id="work-panel-note")
        yield EmbeddedTerminal()

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
        target_label = self._target_label() or "local"
        self.query_one("#work-panel-note", Static).update(
            "Terminal target: "
            f"{target_label} {self._cwd or self._workspace_root or '(unset)'}"
        )
        if not self._cwd:
            return
        self._pty_manager.start_session(
            self.PANEL_ID,
            self._cwd,
            target_kind=self._target_kind,
            target_ref=self._target_ref,
        )

    def focus_terminal(self) -> None:
        self.query_one(EmbeddedTerminal).focus()

    def on_resize(self, _event: events.Resize) -> None:
        self._sync_terminal_size()

    def on_key(self, event: events.Key) -> None:
        terminal = self.query_one(EmbeddedTerminal)
        if not terminal.has_focus:
            if self.query_one(FileExplorer).has_focus:
                if self._target_kind is SessionTargetKind.SSH:
                    self._handle_remote_explorer_key(event)
                    return
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
        if event.key == "end":
            terminal.scroll_to_end()
            event.stop()
            return
        if event.key == "ctrl+space":
            enabled = terminal.toggle_selection()
            note = "Terminal selection started." if enabled else "Terminal selection cleared."
            self.query_one("#work-panel-note", Static).update(note)
            event.stop()
            return
        if event.key == "shift+up":
            if terminal.expand_selection(-1):
                self.query_one("#work-panel-note", Static).update("Terminal selection expanded upward.")
            event.stop()
            return
        if event.key == "shift+down":
            if terminal.expand_selection(1):
                self.query_one("#work-panel-note", Static).update("Terminal selection expanded downward.")
            event.stop()
            return
        if event.key == "escape" and terminal.has_selection():
            terminal.clear_selection()
            self.query_one("#work-panel-note", Static).update("Terminal selection cleared.")
            event.stop()
            return
        if event.key == "ctrl+shift+v":
            try:
                clipboard_text, backend = self._clipboard_service.read_text()
            except ClipboardError as exc:
                self.query_one("#work-panel-note", Static).update(str(exc))
                event.stop()
                return
            if not clipboard_text:
                self.query_one("#work-panel-note", Static).update("Clipboard is empty.")
                event.stop()
                return
            try:
                self._pty_manager.send_input(self.PANEL_ID, clipboard_text)
            except LookupError:
                self.query_one("#work-panel-note", Static).update(
                    "No active terminal session is available for paste."
                )
                event.stop()
                return
            self.query_one("#work-panel-note", Static).update(f"Pasted clipboard via {backend}.")
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
            "target_kind": self._target_kind.value,
            "target_ref": self._target_ref,
            "workspace_root": self._workspace_root,
            "cwd": self._cwd or self._workspace_root,
            "browser_path": self._browser_path or self._workspace_root,
            "selected_path": self._selected_path or self._workspace_root,
        }

    def resume(self) -> None:
        self._render_context()
        self._restore_terminal_buffer()
        try:
            self.query_one(FileExplorer).focus()
        except NoMatches:
            return

    def dispose(self) -> None:
        self._pty_manager.stop_session(self.PANEL_ID)

    def apply_command_result(self, payload: dict[str, object]) -> None:
        terminal_action = payload.get("terminal_action")
        if not isinstance(terminal_action, str):
            return
        terminal = self.query_one(EmbeddedTerminal)
        note = self.query_one("#work-panel-note", Static)
        if terminal_action == "search":
            query = payload.get("query")
            if not isinstance(query, str) or not query:
                note.update("Terminal search requires a non-empty query.")
                return
            if terminal.search(query):
                note.update(f"Terminal search active for '{query}'.")
            else:
                note.update(f"No terminal matches for '{query}'.")
            return
        if terminal_action == "search_next":
            if terminal.search_next():
                note.update("Moved to next terminal match.")
            else:
                note.update("No active terminal search results.")
            return
        if terminal_action == "search_previous":
            if terminal.search_previous():
                note.update("Moved to previous terminal match.")
            else:
                note.update("No active terminal search results.")
            return
        if terminal_action == "export":
            destination = payload.get("path")
            if not isinstance(destination, str) or not destination:
                note.update("Terminal export requires a destination path.")
                return
            exported_path = self._resolve_export_path(destination)
            terminal.export_text(exported_path)
            note.update(f"Terminal buffer exported to {exported_path}.")
            return
        if terminal_action == "copy_buffer":
            try:
                backend = self._clipboard_service.copy_text(terminal.current_output())
            except ClipboardError as exc:
                note.update(str(exc))
                return
            note.update(f"Terminal buffer copied via {backend}.")
            return
        if terminal_action == "copy_selection":
            selection = terminal.selected_text()
            if not selection:
                note.update("No terminal selection is active.")
                return
            try:
                backend = self._clipboard_service.copy_text(selection)
            except ClipboardError as exc:
                note.update(str(exc))
                return
            note.update(f"Terminal selection copied via {backend}.")
            return

    def _render_context(self) -> None:
        self.query_one(FileContext).update_context(
            workspace_name=self._workspace_name,
            workspace_root=self._workspace_root or "(none)",
            cwd=self._cwd or "(none)",
            selected_path=self._selected_path or self._workspace_root or "(none)",
            restored=self._restored,
            target_label=self._target_label(),
            risk_label=self._risk_label(),
            recovery_message=self._recovery_message,
        )

    def _on_runtime_event(self, event: object) -> None:
        panel_id = getattr(event, "panel_id", None)
        if panel_id != self.PANEL_ID:
            return
        if not self.is_attached or not self.is_mounted:
            return
        if get_ident() != self._main_thread_id:
            self.app.call_from_thread(self._apply_runtime_event, event)
            return
        self._apply_runtime_event(event)

    def _apply_runtime_event(self, event: object) -> None:
        widgets = self._runtime_widgets()
        if widgets is None:
            return
        terminal, note = widgets
        if isinstance(event, PTYStarted):
            target_label = (
                f"{event.target_kind.value}:{event.target_ref}"
                if event.target_kind is SessionTargetKind.SSH and event.target_ref
                else event.target_kind.value
            )
            terminal.clear(f"Terminal running in {event.cwd}")
            note.update(
                f"Terminal active on {target_label}. Focus the terminal region to type."
            )
            self._sync_terminal_size()
            buffered = self._stream_router.get_buffer(self.PANEL_ID)
            if buffered:
                terminal.append_output(buffered)
        elif isinstance(event, PTYStartupFailed):
            target_label = (
                f"{event.target_kind.value}:{event.target_ref}"
                if event.target_kind is SessionTargetKind.SSH and event.target_ref
                else event.target_kind.value
            )
            note.update(
                "Terminal startup failed "
                f"for {target_label}. Restart after fixing the environment."
            )
            terminal.set_status(f"Terminal failed to start: {event.reason}")
        elif isinstance(event, ProcessOutputReceived):
            terminal.append_output(event.chunk)
        elif isinstance(event, TerminalExited):
            note.update(f"Terminal exited with code {event.exit_code}. Press Ctrl+R to restart.")
            terminal.set_status(f"\n[terminal exited with {event.exit_code}]")

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return value if isinstance(value, str) else None

    def _sync_explorer(self) -> None:
        if self._target_kind is SessionTargetKind.SSH:
            self._load_remote_directory(
                self._browser_path or self._workspace_root,
                desired_selected=self._selected_path or self._cwd or self._workspace_root,
            )
            return

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

    def _handle_local_explorer_key(self, event: events.Key) -> None:
        if event.key == "up":
            self._apply_explorer_selection(self.query_one(FileExplorer).move_selection(-1))
            event.stop()
        elif event.key == "down":
            self._apply_explorer_selection(self.query_one(FileExplorer).move_selection(1))
            event.stop()
        elif event.key == "enter":
            self._apply_explorer_selection(self.query_one(FileExplorer).open_selection())
            event.stop()
        elif event.key == "backspace":
            self._apply_explorer_selection(self.query_one(FileExplorer).go_parent())
            event.stop()

    def _handle_remote_explorer_key(self, event: events.Key) -> None:
        if event.key == "up":
            self._move_remote_selection(-1)
            event.stop()
        elif event.key == "down":
            self._move_remote_selection(1)
            event.stop()
        elif event.key == "enter":
            self._open_remote_selection()
            event.stop()
        elif event.key == "backspace":
            self._go_remote_parent()
            event.stop()

    def _load_remote_directory(
        self,
        browser_path: str,
        *,
        desired_selected: str | None = None,
    ) -> None:
        snapshot = self._remote_filesystem_adapter.list_directory(
            target_ref=self._target_ref,
            root_path=self._workspace_root or browser_path or ".",
            browser_path=browser_path or self._workspace_root,
        )
        self._browser_path = snapshot.browser_path or browser_path or self._workspace_root
        self._remote_entries = snapshot.entries
        self._remote_listing_message = snapshot.message
        self._sync_remote_selected_path(desired_selected)
        self._render_remote_explorer()
        note = self.query_one("#work-panel-note", Static)
        if snapshot.message:
            note.update(snapshot.message)
        else:
            note.update(
                "Remote explorer active. Use arrows to move, Enter to open, Backspace to go up."
            )

    def _sync_remote_selected_path(self, desired_selected: str | None) -> None:
        if not self._remote_entries:
            self._remote_selected_index = 0
            self._selected_path = self._browser_path or desired_selected or self._workspace_root
            return
        entry_paths = [entry.path for entry in self._remote_entries]
        if desired_selected in entry_paths:
            self._remote_selected_index = entry_paths.index(str(desired_selected))
        else:
            self._remote_selected_index = 0
        self._selected_path = self._remote_entries[self._remote_selected_index].path

    def _render_remote_explorer(self) -> None:
        explorer = self.query_one(FileExplorer)
        lines = [
            f"Explorer: remote {self._target_ref or '(ssh)'}:{self._browser_path or self._workspace_root}",
        ]
        if not self._remote_entries:
            lines.append(f"  {self._remote_listing_message or '(empty)'}")
        else:
            for is_selected, entry in self._windowed_remote_entries():
                marker = ">" if is_selected else " "
                label = f"{entry.name}/" if entry.is_dir else entry.name
                lines.append(f"{marker} {label}")
        if self._remote_listing_message and self._remote_entries:
            lines.extend(["", self._remote_listing_message])
        explorer.update("\n".join(lines))
        self._render_context()

    def _windowed_remote_entries(self) -> list[tuple[bool, RemotePathEntry]]:
        if not self._remote_entries:
            return []
        window = 10
        start = max(0, self._remote_selected_index - window // 2)
        end = min(len(self._remote_entries), start + window)
        start = max(0, end - window)
        return [
            (index == self._remote_selected_index, self._remote_entries[index])
            for index in range(start, end)
        ]

    def _move_remote_selection(self, delta: int) -> None:
        if not self._remote_entries:
            return
        self._remote_selected_index = max(
            0,
            min(len(self._remote_entries) - 1, self._remote_selected_index + delta),
        )
        self._selected_path = self._remote_entries[self._remote_selected_index].path
        self._render_remote_explorer()
        self._publish_panel_state()

    def _open_remote_selection(self) -> None:
        entry = self._selected_remote_entry()
        if entry is None:
            return
        if entry.is_dir:
            self._load_remote_directory(entry.path, desired_selected=entry.path)
        else:
            self._selected_path = entry.path
            self._render_remote_explorer()
        self._publish_panel_state()

    def _go_remote_parent(self) -> None:
        current = self._browser_path or self._workspace_root
        if not current:
            return
        current_path = PurePosixPath(current)
        workspace_root = PurePosixPath(self._workspace_root or current)
        if current_path == workspace_root:
            self._render_remote_explorer()
            return
        parent = str(current_path.parent)
        if not self._remote_within_workspace(parent):
            parent = self._workspace_root or current
        self._load_remote_directory(parent, desired_selected=parent)
        self._publish_panel_state()

    def _selected_remote_entry(self) -> RemotePathEntry | None:
        if not self._remote_entries:
            return None
        if self._remote_selected_index >= len(self._remote_entries):
            self._remote_selected_index = 0
        return self._remote_entries[self._remote_selected_index]

    def _remote_within_workspace(self, path_text: str) -> bool:
        if not self._workspace_root or self._workspace_root == ".":
            return True
        candidate = PurePosixPath(path_text)
        workspace_root = PurePosixPath(self._workspace_root)
        return candidate == workspace_root or workspace_root in candidate.parents

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
        self._publish_panel_state()

    def _publish_panel_state(self) -> None:
        state = self.snapshot_state()
        self._event_bus.publish(
            PanelStateChanged(
                panel_id=self.PANEL_ID,
                panel_type=self.PANEL_TYPE,
                snapshot=state.snapshot,
                config=state.config,
            )
        )

    def _merge_recovery_message(self, message: str) -> str:
        if not self._recovery_message:
            return message
        if message in self._recovery_message:
            return self._recovery_message
        return f"{self._recovery_message} {message}"

    def _runtime_widgets(self) -> tuple[EmbeddedTerminal, Static] | None:
        if not self.is_attached or not self.is_mounted:
            return None
        try:
            return (
                self.query_one(EmbeddedTerminal),
                self.query_one("#work-panel-note", Static),
            )
        except NoMatches:
            return None

    def _restore_terminal_buffer(self) -> None:
        widgets = self._runtime_widgets()
        if widgets is None:
            return
        terminal, _note = widgets
        buffered = self._stream_router.get_buffer(self.PANEL_ID)
        if buffered and not terminal.current_output():
            terminal.append_output(buffered)

    def _sync_terminal_size(self) -> None:
        widgets = self._runtime_widgets()
        if widgets is None:
            return
        terminal, _note = widgets
        session = self._pty_manager.get_session(self.PANEL_ID)
        if session is None:
            return
        content_size = getattr(terminal, "content_size", None)
        cols = getattr(content_size, "width", 0) if content_size is not None else 0
        rows = getattr(content_size, "height", 0) if content_size is not None else 0
        if rows <= 0 or cols <= 0:
            size = getattr(terminal, "size", None)
            cols = getattr(size, "width", 0) if size is not None else cols
            rows = getattr(size, "height", 0) if size is not None else rows
        if rows <= 0 or cols <= 0:
            return
        try:
            self._pty_manager.resize_session(
                self.PANEL_ID,
                rows=max(1, int(rows)),
                cols=max(1, int(cols)),
            )
        except (LookupError, OSError, ValueError):
            return

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

    @staticmethod
    def _target_kind_from_context(value: object) -> SessionTargetKind:
        if isinstance(value, SessionTargetKind):
            return value
        if isinstance(value, str):
            try:
                return SessionTargetKind(value)
            except ValueError:
                return SessionTargetKind.LOCAL
        return SessionTargetKind.LOCAL

    def _target_label(self) -> str | None:
        if self._target_kind is SessionTargetKind.LOCAL:
            return "local"
        if self._target_ref:
            return f"{self._target_kind.value}:{self._target_ref}"
        return self._target_kind.value

    def _resolve_export_path(self, raw_path: str) -> Path:
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return path
        base = Path(self._workspace_root or self._cwd or ".")
        return (base / path).resolve()

    def _risk_label(self) -> str:
        level = classify_target_risk(
            target_kind=self._target_kind,
            target_ref=self._target_ref,
            workspace_name=self._workspace_name,
            workspace_root=self._workspace_root,
        )
        return risk_presentation(level).label
