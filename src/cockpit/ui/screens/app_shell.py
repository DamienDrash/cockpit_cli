"""Minimal Textual app shell."""

from __future__ import annotations

import shlex
from threading import get_ident

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widgets import Footer, Input, Static

from cockpit.application.dispatch.command_dispatcher import UnknownCommandError
from cockpit.application.dispatch.command_parser import CommandParseError
from cockpit.bootstrap import ApplicationContainer, build_container
from cockpit.domain.commands.command import Command
from cockpit.domain.events.base import BaseEvent
from cockpit.domain.events.domain_events import CommandExecuted
from cockpit.domain.events.runtime_events import (
    PanelStateChanged,
    PTYStarted,
    PTYStartupFailed,
    PanelFocused,
    StatusMessagePublished,
    TerminalExited,
)
from cockpit.shared.config import themes_dir
from cockpit.shared.enums import CommandSource, SessionTargetKind, StatusLevel
from cockpit.shared.risk import classify_target_risk
from cockpit.shared.utils import make_id
from cockpit.ui.panels.panel_host import PanelHost
from cockpit.ui.widgets.confirmation_bar import ConfirmationBar
from cockpit.ui.widgets.command_palette import CommandPalette, PaletteItem
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
        ("ctrl+k", "toggle_palette", "Command Palette"),
        ("ctrl+1", "focus_work_tab", "Focus Work"),
        ("ctrl+2", "focus_git_tab", "Focus Git"),
        ("ctrl+3", "focus_logs_tab", "Focus Logs"),
        ("ctrl+4", "focus_docker_tab", "Focus Docker"),
        ("ctrl+5", "focus_cron_tab", "Focus Cron"),
        ("ctrl+t", "focus_terminal", "Focus Terminal"),
        ("ctrl+r", "restart_terminal", "Restart Terminal"),
        ("f8", "restart_selected_docker", "Restart Container"),
    ]

    def __init__(
        self,
        container: ApplicationContainer | None = None,
        *,
        startup_command_text: str | None = None,
    ) -> None:
        super().__init__()
        self.container = container or build_container()
        self._main_thread_id = get_ident()
        self._startup_command_text = startup_command_text
        self._pending_confirmation: dict[str, object] | None = None

    def compose(self) -> ComposeResult:
        yield CockpitHeader(show_clock=False)
        with Vertical(id="app-body"):
            yield TabBar()
            yield ConfirmationBar()
            yield PanelHost(container=self.container)
            yield CommandPalette()
            yield SlashInput()
        yield StatusBar()
        yield Footer()

    def on_mount(self) -> None:
        self._main_thread_id = get_ident()
        self.container.event_bus.subscribe(StatusMessagePublished, self._on_event)
        self.container.event_bus.subscribe(CommandExecuted, self._on_event)
        self.container.event_bus.subscribe(PanelFocused, self._on_event)
        self.container.event_bus.subscribe(PanelStateChanged, self._on_event)
        self.container.event_bus.subscribe(PTYStarted, self._on_event)
        self.container.event_bus.subscribe(PTYStartupFailed, self._on_event)
        self.container.event_bus.subscribe(TerminalExited, self._on_event)
        self._run_startup_flow()

    def on_key(self, event: events.Key) -> None:
        confirmation_bar = self.query_one(ConfirmationBar)
        if confirmation_bar.is_open:
            if event.key in {"enter", "y"}:
                self._confirm_pending_action()
                event.stop()
                return
            if event.key in {"escape", "n"}:
                self._cancel_pending_action()
                event.stop()
                return
        palette = self.query_one(CommandPalette)
        if not palette.is_open:
            return
        if event.key == "escape":
            palette.close()
            self.query_one(SlashInput).focus()
            event.stop()
            return
        if event.key == "up":
            palette.move_selection(-1)
            event.stop()
            return
        if event.key == "down":
            palette.move_selection(1)
            event.stop()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "command-palette-input":
            return
        self.query_one(CommandPalette).filter(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "command-palette-input":
            self._dispatch_palette_selection()
            return
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
        try:
            self.query_one(PanelHost).shutdown()
        except NoMatches:
            pass
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

    def action_focus_work_tab(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="tab.focus",
                args={"argv": ["work"]},
                context=self._command_context(),
            )
        )

    def action_focus_git_tab(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="tab.focus",
                args={"argv": ["git"]},
                context=self._command_context(),
            )
        )

    def action_focus_logs_tab(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="tab.focus",
                args={"argv": ["logs"]},
                context=self._command_context(),
            )
        )

    def action_focus_docker_tab(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="tab.focus",
                args={"argv": ["docker"]},
                context=self._command_context(),
            )
        )

    def action_focus_cron_tab(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="tab.focus",
                args={"argv": ["cron"]},
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

    def action_restart_selected_docker(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="docker.restart",
                context=self._command_context(),
            )
        )

    def action_toggle_palette(self) -> None:
        palette = self.query_one(CommandPalette)
        if palette.is_open:
            palette.close()
            self.query_one(SlashInput).focus()
            return
        palette.open(self._palette_items())

    def _dispatch_command(self, command: Command) -> None:
        try:
            result = self.container.command_dispatcher.dispatch(command)
        except UnknownCommandError as exc:
            self._set_status(str(exc), StatusLevel.ERROR)
            return

        self._apply_command_result(command.name, result.data)
        if result.data.get("confirmation_required") is not True:
            self._clear_confirmation()
        if result.success and command.name in {
            "workspace.open",
            "workspace.reopen_last",
            "session.restore",
            "tab.focus",
            "layout.apply_default",
            "terminal.focus",
            "terminal.restart",
            "docker.restart",
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
            try:
                self.query_one(PanelHost).focus_terminal()
            except NoMatches:
                return
        elif isinstance(event, PanelStateChanged):
            self._persist_current_snapshot()
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
        try:
            status_bar = self.query_one(StatusBar)
        except NoMatches:
            return
        status_bar.set_message(message, level)

    def _apply_command_result(self, command_name: str, data: dict[str, object]) -> None:
        if data.get("confirmation_required") is True:
            self._set_pending_confirmation(data)
            return
        refresh_panel_id = data.get("refresh_panel_id")
        if isinstance(refresh_panel_id, str):
            self.query_one(PanelHost).refresh_panel(refresh_panel_id)
            return
        if command_name not in {
            "workspace.open",
            "workspace.reopen_last",
            "session.restore",
            "tab.focus",
            "layout.apply_default",
        }:
            return
        if command_name in {"tab.focus", "layout.apply_default"}:
            active_tab_id = data.get("active_tab_id")
            if isinstance(active_tab_id, str):
                panel_host = self.query_one(PanelHost)
                active_tab = panel_host.set_active_tab(active_tab_id)
                self.query_one(TabBar).set_active_tab(active_tab)
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
                "target_kind": data.get("target_kind"),
                "target_ref": data.get("target_ref"),
                "session_id": data.get("session_id"),
                "tabs": data.get("tabs"),
                "cwd": str(data.get("cwd", workspace_root)),
                "browser_path": str(data.get("browser_path", workspace_root)),
                "selected_path": str(data.get("selected_path", workspace_root)),
                "active_tab_id": str(data.get("active_tab_id", "work")),
                "snapshot": data.get("snapshot"),
                "restored": bool(data.get("restored", False)),
                "recovery_message": data.get("recovery_message"),
            }
        )
        self.query_one(TabBar).set_tabs(panel_host.available_tabs())
        self.query_one(TabBar).set_workspace(
            str(data.get("workspace_name", "Workspace")),
            active_tab_id=str(data.get("active_tab_id", "work")),
            restored=bool(data.get("restored", False)),
            target_label=self._target_label_from_data(data),
            risk_level=self._risk_level_from_data(data),
        )
        self.query_one(StatusBar).set_context(
            target_label=self._target_label_from_data(data),
            risk_level=self._risk_level_from_data(data),
        )

    def _command_context(self) -> dict[str, object]:
        return self.query_one(PanelHost).command_context()

    def _persist_current_snapshot(self) -> None:
        try:
            panel_host = self.query_one(PanelHost)
        except NoMatches:
            return
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
            active_tab_id=panel_host.active_tab_id(),
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

    def _run_startup_flow(self) -> None:
        if self._startup_command_text:
            self._dispatch_startup_command(self._startup_command_text)
            return
        self._restore_last_session_if_available()

    def _dispatch_startup_command(self, command_text: str) -> None:
        try:
            command = self.container.command_parser.parse(
                command_text,
                source=CommandSource.PANEL_ACTION,
                context=self._command_context(),
            )
        except CommandParseError as exc:
            self._set_status(str(exc), StatusLevel.ERROR)
            return
        self._dispatch_command(command)

    def _dispatch_palette_selection(self) -> None:
        palette = self.query_one(CommandPalette)
        item = palette.selected_item()
        if item is None:
            self._set_status("No palette command is available to execute.", StatusLevel.WARNING)
            return
        try:
            command = self.container.command_parser.parse(
                item.command_text,
                source=CommandSource.PALETTE,
                context=self._command_context(),
            )
        except CommandParseError as exc:
            self._set_status(str(exc), StatusLevel.ERROR)
            return
        palette.close()
        self._dispatch_command(command)
        self.query_one(SlashInput).focus()

    def _palette_items(self) -> list[PaletteItem]:
        context = self._command_context()
        workspace_root = context.get("workspace_root")
        open_path = (
            workspace_root
            if isinstance(workspace_root, str) and workspace_root
            else str(self.container.project_root)
        )
        quoted_open_path = shlex.quote(open_path)
        labels: dict[str, tuple[str, str]] = {
            "workspace.open": (
                "Open Workspace Root",
                f"workspace open {quoted_open_path}",
            ),
            "workspace.reopen_last": (
                "Reopen Last Workspace",
                "workspace reopen_last",
            ),
            "session.restore": (
                "Restore Session",
                "session restore",
            ),
            "layout.apply_default": (
                "Apply Default Layout",
                "layout apply_default",
            ),
            "terminal.focus": (
                "Focus Terminal",
                "terminal focus",
            ),
            "terminal.restart": (
                "Restart Terminal",
                "terminal restart",
            ),
        }
        items: list[PaletteItem] = []
        for command_name in self.container.command_catalog:
            if command_name == "tab.focus":
                for tab_id, tab_name in self.query_one(PanelHost).available_tabs():
                    items.append(
                        PaletteItem(
                            label=f"Focus {tab_name} Tab",
                            command_text=f"tab focus {tab_id}",
                            description=command_name,
                        )
                    )
                continue
            if command_name == "docker.restart":
                selected_container_id = context.get("selected_container_id")
                selected_container_name = context.get("selected_container_name")
                if not isinstance(selected_container_id, str) or not selected_container_id:
                    continue
                label = "Restart Selected Container"
                if isinstance(selected_container_name, str) and selected_container_name:
                    label = f"Restart {selected_container_name}"
                items.append(
                    PaletteItem(
                        label=label,
                        command_text=f"docker restart {shlex.quote(selected_container_id)}",
                        description=command_name,
                    )
                )
                continue
            label_command = labels.get(command_name)
            if label_command is None:
                continue
            label, command_text = label_command
            items.append(
                PaletteItem(
                    label=label,
                    command_text=command_text,
                    description=command_name,
                )
            )
        return items

    def _set_pending_confirmation(self, data: dict[str, object]) -> None:
        self._pending_confirmation = {
            "command_name": data.get("pending_command_name"),
            "args": data.get("pending_args"),
            "context": data.get("pending_context"),
        }
        message = data.get("confirmation_message")
        if not isinstance(message, str) or not message:
            message = "Confirm pending action. Press Enter/Y to continue or Esc/N to cancel."
        self.query_one(ConfirmationBar).open(message)

    def _clear_confirmation(self) -> None:
        self._pending_confirmation = None
        self.query_one(ConfirmationBar).close()

    def _confirm_pending_action(self) -> None:
        pending = self._pending_confirmation
        if not isinstance(pending, dict):
            return
        command_name = pending.get("command_name")
        args = pending.get("args")
        context = pending.get("context")
        if not isinstance(command_name, str) or not command_name:
            self._cancel_pending_action()
            return
        next_args = dict(args) if isinstance(args, dict) else {}
        next_args["confirmed"] = True
        next_context = dict(context) if isinstance(context, dict) else self._command_context()
        self._clear_confirmation()
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name=command_name,
                args=next_args,
                context=next_context,
            )
        )

    def _cancel_pending_action(self) -> None:
        self._clear_confirmation()
        self._set_status("Cancelled pending action.", StatusLevel.WARNING)

    def _target_label_from_data(self, data: dict[str, object]) -> str:
        target_kind = self._target_kind_from_data(data.get("target_kind"))
        target_ref = data.get("target_ref")
        if target_kind is SessionTargetKind.LOCAL:
            return "local"
        if isinstance(target_ref, str) and target_ref:
            return f"{target_kind.value}:{target_ref}"
        return target_kind.value

    def _risk_level_from_data(self, data: dict[str, object]):
        return classify_target_risk(
            target_kind=self._target_kind_from_data(data.get("target_kind")),
            target_ref=data.get("target_ref") if isinstance(data.get("target_ref"), str) else None,
            workspace_name=str(data.get("workspace_name", "Workspace")),
            workspace_root=str(data.get("workspace_root", "")),
        )

    @staticmethod
    def _target_kind_from_data(value: object) -> SessionTargetKind:
        if isinstance(value, SessionTargetKind):
            return value
        if isinstance(value, str):
            try:
                return SessionTargetKind(value)
            except ValueError:
                return SessionTargetKind.LOCAL
        return SessionTargetKind.LOCAL
