"""Professional CronPanel implementation with Dashboard Layout."""

from __future__ import annotations

from pathlib import Path
from rich.text import Text
from rich.panel import Panel as RichPanel
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Label, Button

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.domain.events.runtime_events import PanelMounted, PanelStateChanged
from cockpit.domain.models.panel_state import PanelState
from cockpit.infrastructure.cron.cron_adapter import CronAdapter, CronJob
from cockpit.shared.enums import SessionTargetKind, StatusLevel
from cockpit.ui.panels.base_panel import BasePanel
from cockpit.ui.branding import C_PRIMARY, C_SECONDARY


class CronPanel(BasePanel):
    """Professional Cron TUI with job management and dashboard."""

    PANEL_ID = "cron-panel"
    PANEL_TYPE = "cron"
    can_focus = True

    def __init__(self, *, event_bus: EventBus, cron_adapter: CronAdapter) -> None:
        super().__init__(id=self.PANEL_ID)
        self._event_bus = event_bus
        self._cron_adapter = cron_adapter
        self._workspace_root = ""
        self._target_kind = SessionTargetKind.LOCAL
        self._target_ref: str | None = None
        self._jobs: list[CronJob] = []
        self._selected_index = 0
        self._session_id: str | None = None
        self._workspace_id: str | None = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            # Sidebar: Job List
            with Vertical(id="cron-sidebar", classes="sidebar"):
                yield Label(" [ CRONTAB ] ", classes="section-title")
                yield Static("loading...", id="cron-job-list", classes="list-view")
                yield Label(" [ ACTIONS ] ", classes="section-title")
                yield Static(
                    " space: Toggle On/Off\n"
                    " r: Refresh\n"
                    " Enter: Run Now",
                    id="cron-legend"
                )
            
            # Main: Dashboard
            with Vertical(id="cron-main"):
                yield Label("JOB DASHBOARD", classes="pane-title")
                with Vertical(id="cron-details-container"):
                    yield Static("Select a job to see details", id="cron-details-view")
                
                yield Label("RECENT OUTPUT / LOGS", classes="pane-title")
                yield Static("No logs captured for this session.", id="cron-logs-view")

    def on_mount(self) -> None:
        self._event_bus.publish(PanelMounted(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE))
        self.refresh_jobs()

    def initialize(self, context: dict[str, object]) -> None:
        self._workspace_root = str(context.get("workspace_root", ""))
        self._target_kind = SessionTargetKind(str(context.get("target_kind", "local")))
        self._target_ref = context.get("target_ref")
        self.refresh_jobs()
        self.focus()

    def on_key(self, event: events.Key) -> None:
        if event.key == "up":
            self._move_selection(-1)
            event.stop()
        elif event.key == "down":
            self._move_selection(1)
            event.stop()
        elif event.key == "space":
            self._toggle_selected()
            event.stop()
        elif event.key == "r":
            self.refresh_jobs()
            event.stop()

    def refresh_jobs(self) -> None:
        try:
            snapshot = self._cron_adapter.list_jobs(
                target_kind=self._target_kind,
                target_ref=self._target_ref,
            )
            self._jobs = snapshot.jobs
            self._render_all()
        except Exception:
            pass

    def _render_all(self) -> None:
        # 1. Job List
        list_text = Text()
        if not self._jobs:
            list_text.append("  No cron jobs found.", style="dim")
        else:
            for i, job in enumerate(self._jobs):
                is_selected = i == self._selected_index
                marker = "▶ " if is_selected else "  "
                style = f"{C_SECONDARY} bold" if is_selected else ""
                
                state_color = "green" if job.enabled else "dim red"
                list_text.append(marker, style=C_PRIMARY if is_selected else "dim")
                list_text.append("[ON] " if job.enabled else "[OFF]", style=state_color)
                list_text.append(f" {job.schedule.ljust(12)} ", style="cyan" if is_selected else "dim cyan")
                list_text.append(f"{job.command[:20]}...\n", style=style)
        
        self.query_one("#cron-job-list", Static).update(list_text)
        
        # 2. Details
        self._update_details()

    def _update_details(self) -> None:
        if not self._jobs: return
        job = self._jobs[self._selected_index]
        
        details = Text()
        details.append("Status: ", style="bold")
        details.append("ACTIVE\n" if job.enabled else "DISABLED\n", style="green" if job.enabled else "red")
        details.append(f"Schedule: {job.schedule}\n", style="cyan")
        details.append(f"Command:  {job.command}\n", style="white")
        if job.comment:
            details.append(f"Comment:  {job.comment}\n", style="dim italic")
            
        self.query_one("#cron-details-view", Static).update(details)

    def _move_selection(self, delta: int) -> None:
        if not self._jobs: return
        self._selected_index = max(0, min(len(self._jobs) - 1, self._selected_index + delta))
        self._render_all()

    def _toggle_selected(self) -> None:
        if not self._jobs: return
        job = self._jobs[self._selected_index]
        
        from cockpit.domain.commands.command import Command
        from cockpit.shared.enums import CommandSource
        from cockpit.shared.utils import make_id
        
        cmd_name = "cron.disable" if job.enabled else "cron.enable"
        cmd = Command(
            id=make_id("cmd"),
            source=CommandSource.KEYBINDING,
            name=cmd_name,
            args={"command": job.command},
            context=self.command_context()
        )
        self.app._dispatch_command(cmd)
        # Refresh will happen via command result normally, but let's trigger it
        self.refresh_jobs()

    def resume(self) -> None:
        self.refresh_jobs()
        self.focus()

    def command_context(self) -> dict[str, object]:
        job = self._jobs[self._selected_index] if self._jobs else None
        return {
            "panel_id": self.PANEL_ID,
            "target_kind": self._target_kind.value,
            "target_ref": self._target_ref,
            "selected_cron_command": job.command if job else None,
        }

    def snapshot_state(self) -> PanelState:
        return PanelState(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE)
