"""Minimal Textual app shell."""

from __future__ import annotations

from threading import get_ident

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Input, Static

from cockpit.application.dispatch.command_dispatcher import UnknownCommandError
from cockpit.application.dispatch.command_parser import CommandParseError
from cockpit.bootstrap import ApplicationContainer, build_container
from cockpit.domain.commands.command import Command
from cockpit.domain.events.base import BaseEvent
from cockpit.domain.events.domain_events import CommandExecuted
from cockpit.domain.events.runtime_events import (
    PTYStarted,
    PTYStartupFailed,
    PanelFocused,
    StatusMessagePublished,
    TerminalExited,
)
from cockpit.shared.config import themes_dir
from cockpit.shared.enums import CommandSource, StatusLevel
from cockpit.shared.utils import make_id
from cockpit.ui.panels.panel_host import PanelHost
from cockpit.ui.widgets.header import CockpitHeader
from cockpit.ui.widgets.slash_input import SlashInput
from cockpit.ui.widgets.status_bar import StatusBar
from cockpit.ui.widgets.tab_bar import TabBar


class CockpitApp(App[None]):
    """Bootstrap application shell."""

    TITLE = "Cockpit"
    SUB_TITLE = "Core Platform Spine"
    CSS = (themes_dir() / "default.tcss").read_text(encoding="utf-8")
    BINDINGS = [
        ("ctrl+t", "focus_terminal", "Focus Terminal"),
        ("ctrl+r", "restart_terminal", "Restart Terminal"),
    ]

    def __init__(self, container: ApplicationContainer | None = None) -> None:
        super().__init__()
        self.container = container or build_container()
        self._main_thread_id = get_ident()

    def compose(self) -> ComposeResult:
        yield CockpitHeader(show_clock=False)
        with Vertical(id="app-body"):
            yield TabBar()
            yield PanelHost(container=self.container)
            yield SlashInput()
        yield StatusBar()
        yield Footer()

    def on_mount(self) -> None:
        self._main_thread_id = get_ident()
        self.container.event_bus.subscribe(StatusMessagePublished, self._on_event)
        self.container.event_bus.subscribe(CommandExecuted, self._on_event)
        self.container.event_bus.subscribe(PanelFocused, self._on_event)
        self.container.event_bus.subscribe(PTYStarted, self._on_event)
        self.container.event_bus.subscribe(PTYStartupFailed, self._on_event)
        self.container.event_bus.subscribe(TerminalExited, self._on_event)
        self._restore_last_session_if_available()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "slash-input":
            return

        try:
            command = self.container.command_parser.parse(
                event.value,
                source=CommandSource.SLASH,
                context=self._command_context(),
            )
        except CommandParseError as exc:
            self._set_status(str(exc), StatusLevel.ERROR)
            return
        self._dispatch_command(command)
        event.input.value = ""

    def on_unmount(self) -> None:
        self._persist_current_snapshot()
        self.query_one(PanelHost).shutdown()
        self.container.shutdown()

    def action_focus_terminal(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="terminal.focus",
                context=self._command_context(),
            )
        )

    def action_restart_terminal(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="terminal.restart",
                context=self._command_context(),
            )
        )

    def _dispatch_command(self, command: Command) -> None:
        try:
            result = self.container.command_dispatcher.dispatch(command)
        except UnknownCommandError as exc:
            self._set_status(str(exc), StatusLevel.ERROR)
            return

        self._apply_command_result(command.name, result.data)
        if result.success and command.name in {
            "workspace.open",
            "workspace.reopen_last",
            "session.restore",
            "terminal.focus",
            "terminal.restart",
        }:
            self._persist_current_snapshot()

    def _on_event(self, event: BaseEvent) -> None:
        if get_ident() != self._main_thread_id:
            self.call_from_thread(self._handle_event, event)
            return
        self._handle_event(event)

    def _handle_event(self, event: BaseEvent) -> None:
        if isinstance(event, StatusMessagePublished):
            self._set_status(event.message, event.level)
        elif isinstance(event, CommandExecuted):
            level = StatusLevel.INFO if event.success else StatusLevel.ERROR
            self._set_status(
                event.message or f"Command executed: {event.name}",
                level,
            )
        elif isinstance(event, PanelFocused):
            self.query_one(PanelHost).focus_terminal()
        elif isinstance(event, PTYStarted):
            self._set_status(f"Terminal started in {event.cwd}", StatusLevel.INFO)
        elif isinstance(event, PTYStartupFailed):
            self._set_status(f"Terminal start failed: {event.reason}", StatusLevel.ERROR)
        elif isinstance(event, TerminalExited):
            level = StatusLevel.INFO if event.exit_code == 0 else StatusLevel.WARNING
            self._set_status(
                f"Terminal exited with code {event.exit_code}",
                level,
            )

    def _set_status(self, message: str, level: StatusLevel) -> None:
        status_bar = self.query_one(StatusBar)
        status_bar.set_message(message, level)

    def _apply_command_result(self, command_name: str, data: dict[str, object]) -> None:
        if command_name not in {
            "workspace.open",
            "workspace.reopen_last",
            "session.restore",
        }:
            return
        if "workspace_root" not in data:
            return
        panel_host = self.query_one(PanelHost)
        workspace_root = str(data["workspace_root"])
        panel_host.load_workspace(
            {
                "workspace_name": str(data.get("workspace_name", "Workspace")),
                "workspace_id": data.get("workspace_id"),
                "workspace_root": workspace_root,
                "session_id": data.get("session_id"),
                "cwd": str(data.get("cwd", workspace_root)),
                "browser_path": str(data.get("browser_path", workspace_root)),
                "selected_path": str(data.get("selected_path", workspace_root)),
                "snapshot": data.get("snapshot"),
                "restored": bool(data.get("restored", False)),
                "recovery_message": data.get("recovery_message"),
            }
        )
        self.query_one(TabBar).set_workspace(
            str(data.get("workspace_name", "Workspace")),
            restored=bool(data.get("restored", False)),
        )

    def _command_context(self) -> dict[str, object]:
        return self.query_one(PanelHost).command_context()

    def _persist_current_snapshot(self) -> None:
        panel_host = self.query_one(PanelHost)
        context = panel_host.command_context()
        session_id = context.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return
        snapshot_state = panel_host.snapshot_state()
        snapshot = dict(snapshot_state.snapshot)
        cwd = context.get("cwd")
        workspace_root = context.get("workspace_root")
        browser_path = context.get("browser_path")
        if isinstance(cwd, str):
            snapshot["cwd"] = cwd
        if isinstance(browser_path, str):
            snapshot["browser_path"] = browser_path
        if "selected_path" not in snapshot and isinstance(workspace_root, str):
            snapshot["selected_path"] = workspace_root
        self.container.session_service.save_resume_snapshot(
            session_id=session_id,
            payload=snapshot,
            active_tab_id="work",
            focused_panel_id=snapshot_state.panel_id,
        )

    def _restore_last_session_if_available(self) -> None:
        latest_session = self.container.session_service.latest_session()
        if latest_session is None:
            return
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.PANEL_ACTION,
                name="session.restore",
                context={"workspace_id": latest_session.workspace_id},
            )
        )
