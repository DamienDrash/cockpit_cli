"""Professional LogsPanel implementation with Activity Dashboard."""

from __future__ import annotations

from threading import get_ident
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Label, DataTable

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.services.activity_log_service import ActivityLogRecord, ActivityLogService
from cockpit.domain.events.base import BaseEvent
from cockpit.domain.events.domain_events import (
    CommandExecuted,
    LayoutApplied,
    SessionCreated,
    SessionRestored,
    SnapshotSaved,
    WorkspaceOpened,
)
from cockpit.domain.events.runtime_events import (
    PTYStarted,
    PTYStartupFailed,
    PanelMounted,
    PanelStateChanged,
    TerminalExited,
)
from cockpit.domain.models.panel_state import PanelState
from cockpit.ui.panels.base_panel import BasePanel
from cockpit.ui.branding import C_PRIMARY, C_SECONDARY


class LogsPanel(BasePanel):
    """Professional Activity Log TUI with detailed event tracking."""

    PANEL_ID = "logs-panel"
    PANEL_TYPE = "logs"
    can_focus = True

    _REFRESH_EVENTS = (
        CommandExecuted,
        WorkspaceOpened,
        SessionCreated,
        SessionRestored,
        LayoutApplied,
        SnapshotSaved,
        PTYStarted,
        PTYStartupFailed,
        TerminalExited,
    )

    def __init__(
        self,
        *,
        event_bus: EventBus,
        activity_log_service: ActivityLogService,
    ) -> None:
        super().__init__(id=self.PANEL_ID)
        self._event_bus = event_bus
        self._activity_log_service = activity_log_service
        self._main_thread_id = get_ident()
        self._subscriptions_registered = False
        self._workspace_root = ""
        self._workspace_id: str | None = None
        self._session_id: str | None = None
        self._entries: list[ActivityLogRecord] = []
        self._selected_entry_id: str | None = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            # Sidebar: Categories/Filters
            with Vertical(id="logs-sidebar", classes="sidebar"):
                yield Label(" [ FILTERS ] ", classes="section-title")
                yield Static(" All Events\n Errors\n Commands\n System", id="logs-filter-list")
                yield Label(" [ ACTIONS ] ", classes="section-title")
                yield Static(
                    " Enter: Details\n"
                    " r: Refresh\n"
                    " c: Clear Log",
                    id="logs-legend"
                )
            
            # Main: Activity Grid
            with Vertical(id="logs-main"):
                yield Label("ACTIVITY LOG DASHBOARD", classes="pane-title")
                yield DataTable(id="logs-grid")
                
                yield Label("EVENT DETAILS", classes="pane-title")
                yield Static("Select an event to see raw payload.", id="logs-detail-view", classes="detail-view")

    def on_mount(self) -> None:
        self._main_thread_id = get_ident()
        if not self._subscriptions_registered:
            for event_type in self._REFRESH_EVENTS:
                self._event_bus.subscribe(event_type, self._on_activity_event)
            self._subscriptions_registered = True
        
        grid = self.query_one("#logs-grid", DataTable)
        grid.add_columns("Time", "Category", "Title", "Status")
        grid.cursor_type = "row"
        
        self._event_bus.publish(PanelMounted(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE))
        self.refresh_entries()

    def initialize(self, context: dict[str, object]) -> None:
        self._workspace_root = str(context.get("workspace_root", ""))
        self._workspace_id = str(context.get("workspace_id", ""))
        self._session_id = str(context.get("session_id", ""))
        self.refresh_entries()
        self.focus()

    def on_key(self, event: events.Key) -> None:
        if event.key == "r":
            self.refresh_entries()
            event.stop()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_index = event.cursor_row
        if 0 <= row_index < len(self._entries):
            entry = self._entries[row_index]
            self._selected_entry_id = entry.entry_id
            self._update_detail(entry)

    def refresh_entries(self) -> None:
        try:
            self._entries = self._activity_log_service.recent_entries(
                limit=50,
                workspace_id=self._workspace_id,
                session_id=self._session_id,
                workspace_root=self._workspace_root,
            )
            self._render_grid()
        except Exception:
            pass

    def _render_grid(self) -> None:
        try:
            grid = self.query_one("#logs-grid", DataTable)
            grid.clear()
            for entry in self._entries:
                time_str = entry.recorded_at.strftime("%H:%M:%S")
                category = entry.category.upper()
                status = entry.status or "-"
                
                status_style = "green" if entry.success else "red"
                if not entry.success and not entry.status: status_style = "yellow"
                
                grid.add_row(
                    time_str,
                    Text(category, style="cyan"),
                    entry.title,
                    Text(status, style=status_style)
                )
        except Exception:
            pass

    def _update_detail(self, entry: ActivityLogRecord) -> None:
        detail_view = self.query_one("#logs-detail-view", Static)
        detail_text = Text()
        detail_text.append(f"Event ID: {entry.entry_id}\n", style="dim")
        detail_text.append(f"Recorded: {entry.recorded_at.isoformat()}\n\n", style="cyan")
        detail_text.append(entry.detail)
        detail_view.update(detail_text)

    def resume(self) -> None:
        self.refresh_entries()
        self.focus()

    def command_context(self) -> dict[str, object]:
        return {
            "panel_id": self.PANEL_ID,
            "workspace_id": self._workspace_id,
            "session_id": self._session_id,
            "selected_log_entry_id": self._selected_entry_id,
        }

    def snapshot_state(self) -> PanelState:
        return PanelState(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE)

    def _on_activity_event(self, _event: BaseEvent) -> None:
        if not self.is_attached or not self.is_mounted: return
        if get_ident() != self._main_thread_id:
            self.app.call_from_thread(self.refresh_entries)
        else:
            self.refresh_entries()
