"""Database panel implementation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from textual import events
from textual.widgets import Static

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.services.datasource_service import DataSourceService
from cockpit.domain.events.runtime_events import PanelMounted, PanelStateChanged
from cockpit.domain.models.panel_state import PanelState
from cockpit.infrastructure.db.database_adapter import (
    DatabaseAdapter,
    DatabaseCatalogSnapshot,
)
from cockpit.shared.enums import SessionTargetKind


@dataclass(slots=True, frozen=True)
class _CatalogEntry:
    kind: str
    entry_id: str
    label: str
    detail: str


class DBPanel(Static):
    """Database panel spanning configured datasources and workspace SQLite files."""

    PANEL_ID = "db-panel"
    PANEL_TYPE = "db"
    can_focus = True

    def __init__(
        self,
        *,
        event_bus: EventBus,
        database_adapter: DatabaseAdapter,
        datasource_service: DataSourceService,
    ) -> None:
        super().__init__("", id=self.PANEL_ID, markup=False)
        self._event_bus = event_bus
        self._database_adapter = database_adapter
        self._datasource_service = datasource_service
        self._workspace_name = "No workspace"
        self._workspace_root = ""
        self._workspace_id: str | None = None
        self._session_id: str | None = None
        self._target_kind = SessionTargetKind.LOCAL
        self._target_ref: str | None = None
        self._catalog_entries: list[_CatalogEntry] = []
        self._selected_catalog_id: str | None = None
        self._selected_profile_id: str | None = None
        self._selected_database_path: str | None = None
        self._message = "No database state loaded."
        self._last_inspection: dict[str, object] | None = None
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
        selected_profile_id = context.get("selected_profile_id")
        if isinstance(selected_profile_id, str) and selected_profile_id:
            self._selected_profile_id = selected_profile_id
        self.refresh_catalog()

    def restore_state(self, snapshot: dict[str, object]) -> None:
        selected_database_path = snapshot.get("selected_database_path")
        if isinstance(selected_database_path, str) and selected_database_path:
            self._selected_database_path = selected_database_path
        selected_profile_id = snapshot.get("selected_profile_id")
        if isinstance(selected_profile_id, str) and selected_profile_id:
            self._selected_profile_id = selected_profile_id
        last_inspection = snapshot.get("last_inspection")
        if isinstance(last_inspection, dict):
            self._last_inspection = dict(last_inspection)
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
                "selected_profile_id": self._selected_profile_id,
                "selected_database_path": self._selected_database_path,
                "last_inspection": (
                    dict(self._last_inspection) if self._last_inspection else None
                ),
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
            "selected_profile_id": self._selected_profile_id,
            "selected_database_path": self._selected_database_path,
        }

    def apply_command_result(self, payload: dict[str, object]) -> None:
        profile_id = payload.get("selected_profile_id")
        if isinstance(profile_id, str) and profile_id:
            self._selected_profile_id = profile_id
            self._selected_catalog_id = f"datasource:{profile_id}"
        database_path = payload.get("database_path")
        if isinstance(database_path, str) and database_path:
            self._selected_database_path = database_path
            self._selected_catalog_id = f"sqlite:{database_path}"
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
        profiles = self._datasource_service.list_profiles()
        snapshot = self._database_adapter.list_databases(
            self._workspace_root,
            target_kind=self._target_kind,
            target_ref=self._target_ref,
        )
        self._apply_catalog(snapshot, profiles=profiles)
        self._publish_panel_state()

    def _apply_catalog(
        self,
        snapshot: DatabaseCatalogSnapshot,
        *,
        profiles: list[object],
    ) -> None:
        entries: list[_CatalogEntry] = []
        for profile in profiles:
            profile_id = getattr(profile, "id", None)
            name = getattr(profile, "name", None)
            backend = getattr(profile, "backend", None)
            enabled = getattr(profile, "enabled", True)
            if not isinstance(profile_id, str) or not isinstance(name, str) or not enabled:
                continue
            entries.append(
                _CatalogEntry(
                    kind="datasource",
                    entry_id=profile_id,
                    label=name,
                    detail=str(backend or "datasource"),
                )
            )
        for database_path in snapshot.databases:
            entries.append(
                _CatalogEntry(
                    kind="sqlite",
                    entry_id=database_path,
                    label=Path(database_path).name,
                    detail=database_path,
                )
            )
        self._catalog_entries = entries
        self._message = snapshot.message or ""
        self._sync_selected_entry()
        self._refresh_inspection()
        self._render_state()

    def _sync_selected_entry(self) -> None:
        entry_ids = {f"{entry.kind}:{entry.entry_id}" for entry in self._catalog_entries}
        preferred = None
        if isinstance(self._selected_profile_id, str) and self._selected_profile_id:
            preferred = f"datasource:{self._selected_profile_id}"
        elif isinstance(self._selected_database_path, str) and self._selected_database_path:
            preferred = f"sqlite:{self._selected_database_path}"
        if isinstance(preferred, str) and preferred in entry_ids:
            self._selected_catalog_id = preferred
            self._apply_selection_payload(preferred)
            return
        if self._catalog_entries:
            first = self._catalog_entries[0]
            self._selected_catalog_id = f"{first.kind}:{first.entry_id}"
            self._apply_selection_payload(self._selected_catalog_id)
            return
        self._selected_catalog_id = None
        self._selected_profile_id = None
        self._selected_database_path = None

    def _move_selection(self, delta: int) -> None:
        if not self._catalog_entries:
            return
        current_index = 0
        for index, entry in enumerate(self._catalog_entries):
            if f"{entry.kind}:{entry.entry_id}" == self._selected_catalog_id:
                current_index = index
                break
        next_index = max(0, min(len(self._catalog_entries) - 1, current_index + delta))
        next_entry = self._catalog_entries[next_index]
        self._selected_catalog_id = f"{next_entry.kind}:{next_entry.entry_id}"
        self._apply_selection_payload(self._selected_catalog_id)
        self._refresh_inspection()
        self._render_state()
        self._publish_panel_state()

    def _apply_selection_payload(self, selected_catalog_id: str | None) -> None:
        if not isinstance(selected_catalog_id, str):
            self._selected_profile_id = None
            self._selected_database_path = None
            return
        if selected_catalog_id.startswith("datasource:"):
            self._selected_profile_id = selected_catalog_id.split(":", 1)[1]
            self._selected_database_path = None
            return
        if selected_catalog_id.startswith("sqlite:"):
            self._selected_database_path = selected_catalog_id.split(":", 1)[1]
            self._selected_profile_id = None

    def _render_state(self) -> None:
        self.update(self._render_text())

    def _render_text(self) -> str:
        lines = [
            f"Workspace: {self._workspace_name}",
            f"Root: {self._workspace_root or '(none)'}",
            f"Targets: {len(self._catalog_entries)}",
            "",
            "Catalog:",
        ]
        if not self._catalog_entries:
            lines.append(self._message or "No datasources or SQLite databases found.")
        else:
            for entry in self._catalog_entries[:16]:
                marker = ">" if f"{entry.kind}:{entry.entry_id}" == self._selected_catalog_id else " "
                lines.append(f"{marker} {entry.label} [{entry.kind}:{entry.detail}]")
        lines.extend(["", "Last query result:"])
        lines.extend(self._render_result_lines())
        lines.extend(["", "Examples:"])
        lines.extend(self._render_example_lines())
        lines.extend(
            [
                "",
                'Use Up/Down to choose a datasource or DB, r to refresh, and run /db run_query "SELECT ..." to execute.',
            ]
        )
        return "\n".join(lines)

    def _refresh_inspection(self) -> None:
        if not isinstance(self._selected_profile_id, str) or not self._selected_profile_id:
            self._last_inspection = None
            return
        result = self._datasource_service.inspect_profile(self._selected_profile_id)
        self._last_inspection = result.to_dict()

    def _render_result_lines(self) -> list[str]:
        result = self._last_result
        if not isinstance(result, dict):
            if isinstance(self._last_inspection, dict):
                return self._render_inspection_lines()
            return [self._message or "No query executed yet."]
        query = result.get("query")
        backend = result.get("backend")
        operation = result.get("operation")
        columns = result.get("columns")
        rows = result.get("rows")
        message = result.get("message")
        affected_rows = result.get("affected_rows")
        metadata = result.get("metadata")
        lines: list[str] = []
        if isinstance(backend, str) and backend:
            lines.append(f"backend={backend}")
        if isinstance(operation, str) and operation:
            lines.append(f"operation={operation}")
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
        if isinstance(metadata, dict) and metadata:
            for key in ("schemas", "tables", "dialect", "driver"):
                value = metadata.get(key)
                if isinstance(value, list) and value:
                    lines.append(f"{key}=" + ", ".join(str(item) for item in value[:8]))
                elif isinstance(value, str) and value:
                    lines.append(f"{key}={value}")
        return lines or ["No query executed yet."]

    def _render_inspection_lines(self) -> list[str]:
        result = self._last_inspection
        if not isinstance(result, dict):
            return [self._message or "No inspection available."]
        backend = result.get("backend")
        message = result.get("message")
        metadata = result.get("metadata")
        lines: list[str] = []
        if isinstance(backend, str) and backend:
            lines.append(f"backend={backend}")
        if isinstance(message, str) and message:
            lines.append(message)
        if isinstance(metadata, dict):
            for key, value in metadata.items():
                if isinstance(value, list) and value:
                    lines.append(f"{key}=" + ", ".join(str(item) for item in value[:8]))
                elif isinstance(value, str) and value:
                    lines.append(f"{key}={value}")
        return lines or ["No inspection available."]

    def _render_example_lines(self) -> list[str]:
        backend = self._selected_backend()
        if backend in {
            "postgres",
            "postgresql",
            "mysql",
            "mariadb",
            "mssql",
            "duckdb",
            "bigquery",
            "snowflake",
            "sqlite",
        }:
            return [
                "SELECT 1;",
                "SELECT name FROM sqlite_master ORDER BY name LIMIT 10;",
            ]
        if backend == "mongodb":
            return [
                '{"database":"app","collection":"users","operation":"find","filter":{"active":true}}',
                '{"database":"app","collection":"users","operation":"update_many","filter":{"active":false},"update":{"$set":{"archived":true}}}',
            ]
        if backend == "redis":
            return [
                "GET session:123",
                "SCAN 0 MATCH app:* COUNT 20",
            ]
        if backend == "chromadb":
            return [
                '{"collection":"docs","operation":"query","query_texts":["search term"]}',
                '{"collection":"docs","operation":"add","ids":["doc-1"],"documents":["hello world"]}',
            ]
        return [self._message or "Select a datasource to see backend-specific examples."]

    def _selected_backend(self) -> str | None:
        if isinstance(self._selected_profile_id, str) and self._selected_profile_id:
            profile = self._datasource_service.get_profile(self._selected_profile_id)
            if profile is not None:
                return profile.backend.lower()
        if isinstance(self._selected_database_path, str) and self._selected_database_path:
            return "sqlite"
        return None

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
