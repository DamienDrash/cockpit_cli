"""Reference LogsPanel implementation."""

from __future__ import annotations

from threading import get_ident

from textual import events
from textual.widgets import Static

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


class LogsPanel(Static):
    """Read-only activity log panel backed by persisted command and audit records."""

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
        super().__init__("", id=self.PANEL_ID, markup=False)
        self._event_bus = event_bus
        self._activity_log_service = activity_log_service
        self._main_thread_id = get_ident()
        self._subscriptions_registered = False
        self._workspace_name = "No workspace"
        self._workspace_root = ""
        self._workspace_id: str | None = None
        self._session_id: str | None = None
        self._entries: list[ActivityLogRecord] = []
        self._selected_entry_id: str | None = None

    def on_mount(self) -> None:
        self._main_thread_id = get_ident()
        if not self._subscriptions_registered:
            for event_type in self._REFRESH_EVENTS:
                self._event_bus.subscribe(event_type, self._on_activity_event)
            self._subscriptions_registered = True
        self._event_bus.publish(
            PanelMounted(
                panel_id=self.PANEL_ID,
                panel_type=self.PANEL_TYPE,
            )
        )
        self._render_state()

    def initialize(self, context: dict[str, object]) -> None:
        self._workspace_name = str(context.get("workspace_name", "Workspace"))
        self._workspace_root = str(context.get("workspace_root", ""))
        self._workspace_id = self._optional_str(context.get("workspace_id"))
        self._session_id = self._optional_str(context.get("session_id"))
        selected_entry_id = context.get("selected_entry_id")
        if isinstance(selected_entry_id, str) and selected_entry_id:
            self._selected_entry_id = selected_entry_id
        self.refresh_entries()

    def restore_state(self, snapshot: dict[str, object]) -> None:
        selected_entry_id = snapshot.get("selected_entry_id")
        if isinstance(selected_entry_id, str) and selected_entry_id:
            self._selected_entry_id = selected_entry_id

    def snapshot_state(self) -> PanelState:
        return PanelState(
            panel_id=self.PANEL_ID,
            panel_type=self.PANEL_TYPE,
            snapshot={"selected_entry_id": self._selected_entry_id},
        )

    def suspend(self) -> None:
        """No runtime resources need suspension yet."""

    def resume(self) -> None:
        self.refresh_entries()

    def dispose(self) -> None:
        """No runtime resources need disposal yet."""

    def command_context(self) -> dict[str, object]:
        return {
            "panel_id": self.PANEL_ID,
            "workspace_id": self._workspace_id,
            "session_id": self._session_id,
            "workspace_root": self._workspace_root,
            "selected_log_entry_id": self._selected_entry_id,
        }

    def on_key(self, event: events.Key) -> None:
        if event.key == "up":
            self._move_selection(-1)
            event.stop()
            return
        if event.key == "down":
            self._move_selection(1)
            event.stop()
            return
        if event.key == "r":
            self.refresh_entries()
            event.stop()

    def refresh_entries(self) -> None:
        self._entries = self._activity_log_service.recent_entries(
            limit=24,
            workspace_id=self._workspace_id,
            session_id=self._session_id,
            workspace_root=self._workspace_root,
        )
        self._sync_selected_entry()
        self._render_state()
        self._publish_panel_state()

    def _sync_selected_entry(self) -> None:
        available_ids = {entry.entry_id for entry in self._entries}
        if self._selected_entry_id in available_ids:
            return
        self._selected_entry_id = self._entries[0].entry_id if self._entries else None

    def _move_selection(self, delta: int) -> None:
        if not self._entries:
            return
        current_index = 0
        for index, entry in enumerate(self._entries):
            if entry.entry_id == self._selected_entry_id:
                current_index = index
                break
        next_index = max(0, min(len(self._entries) - 1, current_index + delta))
        self._selected_entry_id = self._entries[next_index].entry_id
        self._render_state()
        self._publish_panel_state()

    def _render_state(self) -> None:
        self.update(self._render_text())

    def _render_text(self) -> str:
        lines = [
            f"Workspace: {self._workspace_name}",
            f"Root: {self._workspace_root or '(none)'}",
            f"Entries: {len(self._entries)}",
            "",
            "Recent activity:",
        ]
        if not self._entries:
            lines.append("No activity recorded yet.")
        else:
            for entry in self._entries[:12]:
                marker = ">" if entry.entry_id == self._selected_entry_id else " "
                timestamp = entry.recorded_at.strftime("%H:%M:%S")
                status = f" {entry.status}" if entry.status else ""
                lines.append(
                    f"{marker} {timestamp} [{entry.category}] {entry.title}{status}"
                )
        lines.extend(["", "Selected detail:"])
        selected = self._selected_entry()
        if selected is None:
            lines.append("No entry selected.")
        else:
            lines.append(selected.detail)
        lines.extend(["", "Use Up/Down to inspect entries. Press r to refresh."])
        return "\n".join(lines)

    def _selected_entry(self) -> ActivityLogRecord | None:
        for entry in self._entries:
            if entry.entry_id == self._selected_entry_id:
                return entry
        return self._entries[0] if self._entries else None

    def _publish_panel_state(self) -> None:
        self._event_bus.publish(
            PanelStateChanged(
                panel_id=self.PANEL_ID,
                snapshot=dict(self.snapshot_state().snapshot),
            )
        )

    def _on_activity_event(self, _event: BaseEvent) -> None:
        if not self.is_attached or not self.is_mounted:
            return
        if get_ident() != self._main_thread_id:
            self.app.call_from_thread(self.refresh_entries)
            return
        self.refresh_entries()

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return value if isinstance(value, str) else None
