"""Minimal Textual app shell."""

from __future__ import annotations

import shlex
from threading import get_ident

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widgets import Footer, Input

from cockpit.core.dispatch.command_dispatcher import UnknownCommandError
from cockpit.core.dispatch.command_parser import CommandParseError
from cockpit.bootstrap import ApplicationContainer, build_container
from cockpit.core.command import Command
from cockpit.core.events.base import BaseEvent
from cockpit.workspace.events import CommandExecuted
from cockpit.core.events.runtime import (
    PanelStateChanged,
    PTYStarted,
    PTYStartupFailed,
    PanelFocused,
    StatusMessagePublished,
    TerminalExited,
)
from cockpit.core.config import themes_dir
from cockpit.core.enums import CommandSource, SessionTargetKind, StatusLevel
from cockpit.core.risk import classify_target_risk
from cockpit.core.utils import make_id
from cockpit.ui.panels.panel_host import PanelHost
from cockpit.ui.widgets.confirmation_bar import ConfirmationBar
from cockpit.ui.widgets.command_palette import CommandPalette, PaletteItem
from cockpit.ui.widgets.header import CockpitHeader
from cockpit.ui.widgets.slash_input import SlashInput
from cockpit.ui.widgets.action_bar import ActionBar
from cockpit.ui.widgets.scanlines import ScanlineOverlay
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
        ("alt+1", "focus_work_tab", "Focus Work"),
        ("ctrl+2", "focus_git_tab", "Focus Git"),
        ("alt+2", "focus_git_tab", "Focus Git"),
        ("ctrl+3", "focus_logs_tab", "Focus Logs"),
        ("alt+3", "focus_logs_tab", "Focus Logs"),
        ("ctrl+4", "focus_docker_tab", "Focus Docker"),
        ("alt+4", "focus_docker_tab", "Focus Docker"),
        ("ctrl+5", "focus_cron_tab", "Focus Cron"),
        ("alt+5", "focus_cron_tab", "Focus Cron"),
        ("ctrl+6", "focus_db_tab", "Focus DB"),
        ("alt+6", "focus_db_tab", "Focus DB"),
        ("ctrl+7", "focus_curl_tab", "Focus Curl"),
        ("alt+7", "focus_curl_tab", "Focus Curl"),
        ("ctrl+8", "focus_ops_tab", "Focus Ops"),
        ("alt+8", "focus_ops_tab", "Focus Ops"),
        ("ctrl+9", "focus_response_tab", "Focus Response"),
        ("alt+9", "focus_response_tab", "Focus Response"),
        ("ctrl+t", "focus_terminal", "Focus Terminal"),
        ("ctrl+]", "focus_next_panel", "Focus Next Panel"),
        ("ctrl+r", "restart_terminal", "Restart Terminal"),
        ("ctrl+alt+c", "copy_terminal_buffer", "Copy Terminal Buffer"),
        ("ctrl+shift+c", "copy_terminal_selection", "Copy Terminal Selection"),
        ("ctrl+shift+a", "acknowledge_selected_engagement", "Acknowledge Engagement"),
        ("ctrl+shift+p", "repage_selected_engagement", "Re-page Engagement"),
        ("ctrl+shift+e", "execute_selected_response", "Execute Response Step"),
        ("ctrl+shift+u", "retry_selected_response", "Retry Response Step"),
        ("ctrl+shift+x", "abort_selected_response", "Abort Response Run"),
        ("ctrl+shift+z", "compensate_selected_response", "Compensate Response Run"),
        ("ctrl+shift+y", "approve_selected_response", "Approve Response Step"),
        ("ctrl+shift+n", "reject_selected_response", "Reject Response Step"),
        ("f8", "restart_selected_docker", "Restart Container"),
        ("f9", "stop_selected_docker", "Stop Container"),
        ("f10", "remove_selected_docker", "Remove Container"),
        ("ctrl+alt+o", "toggle_layout_orientation", "Toggle Layout Orientation"),
        ("ctrl+alt+=", "grow_layout_split", "Grow Layout Split"),
        ("ctrl+alt+-", "shrink_layout_split", "Shrink Layout Split"),
        ("q", "quit", "Quit"),
        ("ctrl+q", "quit", "Quit"),
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
        yield ScanlineOverlay()
        yield CockpitHeader(show_clock=False)
        with Vertical(id="app-body"):
            yield TabBar()
            yield ConfirmationBar()
            yield PanelHost(container=self.container)
            yield CommandPalette()
            yield SlashInput()
        yield ActionBar()
        yield StatusBar()

    def on_mount(self) -> None:
        self._main_thread_id = get_ident()
        
        # Register semantic highlighter styles in Rich console
        from cockpit.ui.branding import C_PRIMARY, C_SECONDARY, C_ERROR, C_WARNING, C_TERMINAL_GREEN
        self.console.push_styles({
            "slash.command": f"{C_PRIMARY} bold",
            "slash.flag": f"{C_SECONDARY} italic",
            "slash.target": "bold yellow",
            "slash.string": "green",
            "terminal.error": C_ERROR,
            "terminal.warning": C_WARNING,
            "terminal.url": "underline cyan",
            "terminal.path": "cyan italic",
            "terminal.json": C_TERMINAL_GREEN,
        })

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
        try:
            self._persist_current_snapshot()
        except Exception:
            pass
        try:
            panel_host = self.query(PanelHost).first()
            if panel_host:
                panel_host.shutdown()
        except Exception:
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

    def action_focus_next_panel(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="panel.focus_next",
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

    def action_focus_db_tab(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="tab.focus",
                args={"argv": ["db"]},
                context=self._command_context(),
            )
        )

    def action_focus_curl_tab(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="tab.focus",
                args={"argv": ["curl"]},
                context=self._command_context(),
            )
        )

    def action_focus_ops_tab(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="tab.focus",
                args={"argv": ["ops"]},
                context=self._command_context(),
            )
        )

    def action_focus_response_tab(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="tab.focus",
                args={"argv": ["response"]},
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

    def action_copy_terminal_buffer(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="terminal.copy",
                context=self._command_context(),
            )
        )

    def action_copy_terminal_selection(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="terminal.copy_selection",
                context=self._command_context(),
            )
        )

    def action_toggle_layout_orientation(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="layout.toggle_orientation",
                context=self._command_context(),
            )
        )

    def action_grow_layout_split(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="layout.grow",
                context=self._command_context(),
            )
        )

    def action_shrink_layout_split(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="layout.shrink",
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

    def action_stop_selected_docker(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="docker.stop",
                context=self._command_context(),
            )
        )

    def action_remove_selected_docker(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="docker.remove",
                context=self._command_context(),
            )
        )

    def action_acknowledge_selected_engagement(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="engagement.ack",
                context=self._command_context(),
            )
        )

    def action_repage_selected_engagement(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="engagement.repage",
                context=self._command_context(),
            )
        )

    def action_execute_selected_response(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="response.execute",
                context=self._command_context(),
            )
        )

    def action_retry_selected_response(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="response.retry",
                context=self._command_context(),
            )
        )

    def action_abort_selected_response(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="response.abort",
                context=self._command_context(),
            )
        )

    def action_compensate_selected_response(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="response.compensate",
                context=self._command_context(),
            )
        )

    def action_approve_selected_response(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="approval.approve",
                context=self._command_context(),
            )
        )

    def action_reject_selected_response(self) -> None:
        self._dispatch_command(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="approval.reject",
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

        self._apply_command_result(command, result.data)
        if result.data.get("confirmation_required") is not True:
            self._clear_confirmation()
        if result.success and command.name in {
            "workspace.open",
            "workspace.reopen_last",
            "session.restore",
            "tab.focus",
            "layout.apply_default",
            "layout.toggle_orientation",
            "layout.grow",
            "layout.shrink",
            "panel.focus_next",
            "terminal.focus",
            "terminal.restart",
            "terminal.search",
            "terminal.search_next",
            "terminal.search_prev",
            "terminal.export",
            "terminal.copy",
            "terminal.copy_selection",
            "docker.restart",
            "docker.stop",
            "docker.remove",
            "cron.enable",
            "cron.disable",
            "db.run_query",
            "curl.send",
            "engagement.ack",
            "engagement.repage",
            "engagement.handoff",
            "response.start",
            "response.execute",
            "response.retry",
            "response.abort",
            "response.compensate",
            "approval.approve",
            "approval.reject",
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
                self.query_one(ActionBar).set_context(
                    event.panel_id, event.panel_type
                )
                self.query_one(PanelHost).focus_terminal()
            except NoMatches:
                return
        elif isinstance(event, PanelStateChanged):
            self._persist_current_snapshot()
        elif isinstance(event, PTYStarted):
            self._set_status(f"Terminal started in {event.cwd}", StatusLevel.INFO)
        elif isinstance(event, PTYStartupFailed):
            self._set_status(
                f"Terminal start failed: {event.reason}", StatusLevel.ERROR
            )
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

    def _apply_command_result(self, command: Command, data: dict[str, object]) -> None:
        command_name = command.name
        if data.get("confirmation_required") is True:
            self._set_pending_confirmation(data)
            return
        if isinstance(data.get("tabs"), list):
            panel_host = self.query_one(PanelHost)
            active_tab_id = data.get("active_tab_id")
            
            # Force 'work' tab on startup
            if command.is_startup:
                active_tab_id = "work"
                
            panel_host.apply_tabs(
                data["tabs"],
                active_tab_id=active_tab_id
                if isinstance(active_tab_id, str)
                else panel_host.active_tab_id(),
                focus=False,
            )
            self.query_one(TabBar).set_tabs(panel_host.available_tabs())
        focus_panel_id = data.get("focus_panel_id")
        if isinstance(focus_panel_id, str) and focus_panel_id:
            self.query_one(PanelHost).focus_panel(focus_panel_id)
            return
        result_panel_id = data.get("result_panel_id")
        result_payload = data.get("result_payload")
        if isinstance(result_panel_id, str) and isinstance(result_payload, dict):
            self.query_one(PanelHost).deliver_panel_result(
                result_panel_id, result_payload
            )
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
        risk_level = self._risk_level_from_data(data)
        
        active_tab_id = str(data.get("active_tab_id", "work"))
        if command.is_startup:
            active_tab_id = "work"

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
                "active_tab_id": active_tab_id,
                "snapshot": data.get("snapshot"),
                "restored": bool(data.get("restored", False)),
                "recovery_message": data.get("recovery_message"),
            }
        )
        panel_host.apply_risk_level(risk_level)
        
        self.query_one(TabBar).set_tabs(panel_host.available_tabs())
        self.query_one(TabBar).set_workspace(
            str(data.get("workspace_name", "Workspace")),
            active_tab_id=active_tab_id,
            restored=bool(data.get("restored", False)),
            target_label=self._target_label_from_data(data),
            risk_level=risk_level,
        )
        self.query_one(StatusBar).set_context(
            target_label=self._target_label_from_data(data),
            risk_level=risk_level,
        )
        # Final pass to ensure all app-wide contexts (git, etc) are current
        self._update_app_context(data)

    def _update_app_context(self, data: dict[str, object]) -> None:
        """Refresh app-wide status context (Git branch, etc)."""
        try:
            status_bar = self.query_one(StatusBar)
            target_kind = self._target_kind_from_data(data.get("target_kind"))
            risk_level = self._risk_level_from_data(data)
            
            git_branch = None
            git_dirty = False
            
            # App-wide Git tracking for local workspaces
            if target_kind == SessionTargetKind.LOCAL:
                root = str(data.get("workspace_root", ""))
                if root:
                    try:
                        status = self.container.git_adapter.inspect_repository(root)
                        git_branch = status.branch_summary
                        git_dirty = status.is_dirty
                    except Exception:
                        pass
            
            status_bar.set_context(
                target_label=self._target_label_from_data(data),
                risk_level=risk_level,
                git_branch=git_branch,
                git_dirty=git_dirty
            )
        except Exception:
            pass

    def _command_context(self) -> dict[str, object]:
        try:
            return self.query_one(PanelHost).command_context()
        except Exception:
            return {}

    def _persist_current_snapshot(self) -> None:
        try:
            if not self._screen_stack:
                return
            panel_host = self.query(PanelHost).first()
            if not panel_host:
                return
        except Exception:
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
                is_startup=True,
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
            command.is_startup = True
        except CommandParseError as exc:
            self._set_status(str(exc), StatusLevel.ERROR)
            return
        self._dispatch_command(command)

    def _dispatch_palette_selection(self) -> None:
        palette = self.query_one(CommandPalette)
        item = palette.selected_item()
        if item is None:
            self._set_status(
                "No palette command is available to execute.", StatusLevel.WARNING
            )
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
            "layout.toggle_orientation": (
                "Toggle Layout Orientation",
                "layout toggle_orientation",
            ),
            "layout.grow": (
                "Grow Active Split",
                "layout grow",
            ),
            "layout.shrink": (
                "Shrink Active Split",
                "layout shrink",
            ),
            "panel.focus_next": (
                "Focus Next Panel",
                "panel focus_next",
            ),
            "db.run_query": (
                "Run Example DB Query",
                'db run_query "SELECT name FROM sqlite_master ORDER BY name LIMIT 10"',
            ),
            "curl.send": (
                "Send Example GET Request",
                "curl send GET https://example.com",
            ),
            "terminal.focus": (
                "Focus Terminal",
                "terminal focus",
            ),
            "terminal.restart": (
                "Restart Terminal",
                "terminal restart",
            ),
            "terminal.search": (
                "Search Terminal for Error",
                'terminal search "error"',
            ),
            "terminal.search_next": (
                "Next Terminal Search Match",
                "terminal search_next",
            ),
            "terminal.search_prev": (
                "Previous Terminal Search Match",
                "terminal search_prev",
            ),
            "terminal.export": (
                "Export Terminal Buffer",
                "terminal export .cockpit/terminal-buffer.txt",
            ),
            "terminal.copy": (
                "Copy Terminal Buffer",
                "terminal copy",
            ),
            "terminal.copy_selection": (
                "Copy Terminal Selection",
                "terminal copy_selection",
            ),
            "engagement.ack": (
                "Acknowledge Selected Engagement",
                "engagement ack",
            ),
            "engagement.repage": (
                "Re-page Selected Engagement",
                "engagement repage",
            ),
            "response.execute": (
                "Execute Selected Response Step",
                "response execute",
            ),
            "response.retry": (
                "Retry Selected Response Step",
                "response retry",
            ),
            "response.abort": (
                "Abort Selected Response Run",
                "response abort",
            ),
            "response.compensate": (
                "Compensate Selected Response Run",
                "response compensate",
            ),
            "approval.approve": (
                "Approve Selected Response Step",
                "approval approve",
            ),
            "approval.reject": (
                "Reject Selected Approval Request",
                "approval reject",
            ),
        }
        items: list[PaletteItem] = []
        for command_name in self.container.command_catalog:
            if command_name == "tab.focus":
                try:
                    for tab_id, tab_name in self.query_one(PanelHost).available_tabs():
                        items.append(
                            PaletteItem(
                                label=f"Focus {tab_name} Tab",
                                command_text=f"tab focus {tab_id}",
                                description=command_name,
                            )
                        )
                except Exception:
                    pass
                continue
            # ... rest of palette items logic ...
            if command_name in labels:
                label, cmd = labels[command_name]
                items.append(
                    PaletteItem(label=label, command_text=cmd, description=command_name)
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
            message = (
                "Confirm pending action. Press Enter/Y to continue or Esc/N to cancel."
            )
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
        next_context = (
            dict(context) if isinstance(context, dict) else self._command_context()
        )
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
            target_ref=data.get("target_ref")
            if isinstance(data.get("target_ref"), str)
            else None,
            workspace_name=str(data.get("workspace_name", "Workspace")),
            workspace_root=str(data.get("workspace_root", "")),
        )

    def _risk_level_from_context(self, context: dict[str, object]):
        return classify_target_risk(
            target_kind=self._target_kind_from_data(context.get("target_kind")),
            target_ref=(
                context.get("target_ref")
                if isinstance(context.get("target_ref"), str)
                else None
            ),
            workspace_name=str(context.get("workspace_name", "Workspace")),
            workspace_root=str(context.get("workspace_root", "")),
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
