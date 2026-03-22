"""Database panel implementation."""

from __future__ import annotations

from pathlib import Path

from textual import events
from textual.widgets import Static

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.domain.events.runtime_events import PanelMounted, PanelStateChanged
from cockpit.domain.models.panel_state import PanelState
from cockpit.infrastructure.db.database_adapter import (
    DatabaseAdapter,
    DatabaseCatalogSnapshot,
    DatabaseQueryResult,
)
from cockpit.shared.enums import SessionTargetKind


class DBPanel(Static):
    """SQLite-oriented database panel."""

    PANEL_ID = "db-panel"
    PANEL_TYPE = "db"
    can_focus = True

    def __init__(self, *, event_bus: EventBus, database_adapter: DatabaseAdapter) -> None:
        super().__init__("", id=self.PANEL_ID, markup=False)
        self._event_bus = event_bus
        self._database_adapter = database_adapter
        self._workspace_name = "No workspace"
        self._workspace_root = ""
        self._workspace_id: str | None = None
        self._session_id: str | None = None
        self._target_kind = SessionTargetKind.LOCAL
        self._target_ref: str | None = None
        self._databases: list[str] = []
        self._selected_database_path: str | None = None
        self._message = "No database state loaded."
        self._last_result: dict[str, object] | None = None

    def on_mount(self) -> None:
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
        self._target_kind = self._target_kind_from_context(context.get("target_kind"))
        self._target_ref = self._optional_str(context.get("target_ref"))
        selected_database_path = context.get("selected_database_path")
        if isinstance(selected_database_path, str) and selected_database_path:
            self._selected_database_path = selected_database_path
        self.refresh_catalog()

    def restore_state(self, snapshot: dict[str, object]) -> None:
        selected_database_path = snapshot.get("selected_database_path")
        if isinstance(selected_database_path, str) and selected_database_path:
            self._selected_database_path = selected_database_path
        last_result = snapshot.get("last_result")
        if isinstance(last_result, dict):
            self._last_result = dict(last_result)
        if self.is_mounted:
            self._render_state()

    def snapshot_state(self) -> PanelState:
        return PanelState(
            panel_id=self.PANEL_ID,
            panel_type=self.PANEL_TYPE,
            snapshot={
                "selected_database_path": self._selected_database_path,
                "last_result": dict(self._last_result) if self._last_result else None,
            },
        )

    def resume(self) -> None:
        self.refresh_catalog()

    def suspend(self) -> None:
        """No runtime resources need suspension."""

    def dispose(self) -> None:
        """No runtime resources need disposal."""

    def command_context(self) -> dict[str, object]:
        return {
            "panel_id": self.PANEL_ID,
            "workspace_id": self._workspace_id,
            "session_id": self._session_id,
            "workspace_name": self._workspace_name,
            "workspace_root": self._workspace_root,
            "target_kind": self._target_kind.value,
            "target_ref": self._target_ref,
            "selected_database_path": self._selected_database_path,
        }

    def apply_command_result(self, payload: dict[str, object]) -> None:
        database_path = payload.get("database_path")
        if isinstance(database_path, str) and database_path:
            self._selected_database_path = database_path
        result = payload.get("query_result")
        if isinstance(result, dict):
            self._last_result = dict(result)
        self._render_state()
        self._publish_panel_state()

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
            self.refresh_catalog()
            event.stop()

    def refresh_catalog(self) -> None:
        snapshot = self._database_adapter.list_databases(
            self._workspace_root,
            target_kind=self._target_kind,
            target_ref=self._target_ref,
        )
        self._apply_catalog(snapshot)
        self._publish_panel_state()

    def _apply_catalog(self, snapshot: DatabaseCatalogSnapshot) -> None:
        self._databases = snapshot.databases
        self._message = snapshot.message or ""
        self._sync_selected_database()
        self._render_state()

    def _sync_selected_database(self) -> None:
        if self._selected_database_path in set(self._databases):
            return
        self._selected_database_path = self._databases[0] if self._databases else None

    def _move_selection(self, delta: int) -> None:
        if not self._databases:
            return
        current_index = 0
        for index, entry in enumerate(self._databases):
            if entry == self._selected_database_path:
                current_index = index
                break
        next_index = max(0, min(len(self._databases) - 1, current_index + delta))
        self._selected_database_path = self._databases[next_index]
        self._render_state()
        self._publish_panel_state()

    def _render_state(self) -> None:
        self.update(self._render_text())

    def _render_text(self) -> str:
        lines = [
            f"Workspace: {self._workspace_name}",
            f"Root: {self._workspace_root or '(none)'}",
            f"Databases: {len(self._databases)}",
            "",
            "Catalog:",
        ]
        if not self._databases:
            lines.append(self._message or "No SQLite databases found.")
        else:
            for path_text in self._databases[:12]:
                marker = ">" if path_text == self._selected_database_path else " "
                lines.append(f"{marker} {Path(path_text).name}")
        lines.extend(["", "Last query result:"])
        lines.extend(self._render_result_lines())
        lines.extend(
            [
                "",
                'Use Up/Down to choose a DB, r to refresh, and run /db run_query "SELECT ..." to execute.',
            ]
        )
        return "\n".join(lines)

    def _render_result_lines(self) -> list[str]:
        result = self._last_result
        if not isinstance(result, dict):
            return [self._message or "No query executed yet."]
        query = result.get("query")
        columns = result.get("columns")
        rows = result.get("rows")
        message = result.get("message")
        affected_rows = result.get("affected_rows")
        lines: list[str] = []
        if isinstance(query, str) and query:
            lines.append(f"query={query}")
        if isinstance(columns, list) and columns:
            lines.append("columns=" + ", ".join(str(column) for column in columns))
        if isinstance(rows, list) and rows:
            for row in rows[:6]:
                if isinstance(row, list):
                    lines.append(" | ".join(str(cell) for cell in row))
        if isinstance(affected_rows, int):
            lines.append(f"affected_rows={affected_rows}")
        if isinstance(message, str) and message:
            lines.append(message)
        return lines or ["No query executed yet."]

    def _publish_panel_state(self) -> None:
        self._event_bus.publish(
            PanelStateChanged(
                panel_id=self.PANEL_ID,
                snapshot=dict(self.snapshot_state().snapshot),
            )
        )

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return value if isinstance(value, str) else None

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
