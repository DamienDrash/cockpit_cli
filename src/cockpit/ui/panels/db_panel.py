"""Professional Database Panel with Connection Management."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from rich.text import Text
from rich.syntax import Syntax
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Label, Input, DataTable, Tree, Button, ContentSwitcher, Select

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.services.datasource_service import DataSourceService
from cockpit.domain.events.runtime_events import PanelMounted, PanelStateChanged
from cockpit.domain.models.panel_state import PanelState
from cockpit.infrastructure.db.database_adapter import (
    DatabaseAdapter,
    DatabaseCatalogSnapshot,
)
from cockpit.shared.enums import SessionTargetKind, StatusLevel
from cockpit.ui.panels.base_panel import BasePanel
from cockpit.ui.branding import C_PRIMARY, C_SECONDARY


class DBPanel(BasePanel):
    """Professional Database TUI with connection management and SQL IDE."""

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
        super().__init__(id=self.PANEL_ID)
        self._event_bus = event_bus
        self._database_adapter = database_adapter
        self._datasource_service = datasource_service
        self._workspace_root = ""
        self._target_kind = SessionTargetKind.LOCAL
        self._target_ref: str | None = None
        self._selected_profile_id: str | None = None
        self._selected_database_path: str | None = None
        self._last_result: dict[str, object] | None = None
        self._config_mode = False

    def compose(self) -> ComposeResult:
        with Horizontal():
            # Sidebar: Catalog & Management
            with Vertical(id="db-sidebar", classes="sidebar"):
                yield Label(" [ CATALOG ] ", classes="section-title")
                yield Button("＋ NEW CONNECTION", id="db-btn-new", classes="action-button")
                yield Tree("DATABASES", id="db-catalog-tree")
                yield Label(" [ ACTIONS ] ", classes="section-title")
                yield Static(
                    " Enter: Select\n"
                    " r: Refresh\n"
                    " e: Query Editor\n"
                    " n: New Connection",
                    id="db-legend"
                )
            
            # Main: IDE or Config Form
            with Vertical(id="db-main"):
                with ContentSwitcher(initial="ide", id="db-main-switcher"):
                    # 1. SQL IDE View
                    with Vertical(id="ide"):
                        with Vertical(id="db-editor-pane"):
                            yield Label("SQL QUERY EDITOR", classes="pane-title")
                            yield Input(placeholder="SELECT * FROM ...", id="db-query-input")
                        
                        with Vertical(id="db-results-pane"):
                            yield Label("QUERY RESULTS", classes="pane-title")
                            yield DataTable(id="db-results-grid")
                            yield Static("No query executed yet.", id="db-status-msg")
                    
                    # 2. Connection Config Form
                    with Vertical(id="config"):
                        yield Label("CONFIGURE NEW DATASOURCE", classes="pane-title")
                        with Vertical(id="db-config-form"):
                            yield Label("Name (Alias):")
                            yield Input(placeholder="my-postgres-db", id="db-cfg-name")
                            yield Label("Backend:")
                            yield Select(
                                [("sqlite", "SQLite"), ("postgres", "PostgreSQL"), ("mysql", "MySQL"), ("mongodb", "MongoDB"), ("redis", "Redis")],
                                value="postgres",
                                id="db-cfg-backend"
                            )
                            yield Label("Connection URL:")
                            yield Input(placeholder="postgresql://user:pass@host:5432/db", id="db-cfg-url")
                            yield Label("Target (SSH Alias or 'local'):")
                            yield Input(placeholder="local", id="db-cfg-target")
                            
                            with Horizontal(id="db-cfg-actions"):
                                yield Button("SAVE", id="db-cfg-save", variant="primary")
                                yield Button("CANCEL", id="db-cfg-cancel")

    def on_mount(self) -> None:
        tree = self.query_one("#db-catalog-tree", Tree)
        tree.root.expand()
        self._event_bus.publish(PanelMounted(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE))
        self.refresh_catalog()

    def initialize(self, context: dict[str, object]) -> None:
        self._workspace_root = str(context.get("workspace_root", ""))
        self._target_kind = SessionTargetKind(str(context.get("target_kind", "local")))
        self._target_ref = context.get("target_ref")
        self.refresh_catalog()
        self.focus()

    def on_key(self, event: events.Key) -> None:
        if self._config_mode:
            if event.key == "escape":
                self._toggle_config_mode(False)
                event.stop()
            return

        if event.key == "r":
            self.refresh_catalog()
            event.stop()
        elif event.key == "e":
            self.query_one("#db-query-input").focus()
            event.stop()
        elif event.key == "n":
            self._toggle_config_mode(True)
            event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "db-btn-new":
            self._toggle_config_mode(True)
        elif event.button.id == "db-cfg-cancel":
            self._toggle_config_mode(False)
        elif event.button.id == "db-cfg-save":
            self._handle_save_config()

    def _toggle_config_mode(self, enabled: bool) -> None:
        self._config_mode = enabled
        self.query_one("#db-main-switcher", ContentSwitcher).current = "config" if enabled else "ide"
        if enabled:
            self.query_one("#db-cfg-name").focus()
        else:
            self.focus()

    def _handle_save_config(self) -> None:
        name = self.query_one("#db-cfg-name", Input).value
        backend = str(self.query_one("#db-cfg-backend", Select).value)
        url = self.query_one("#db-cfg-url", Input).value
        target = self.query_one("#db-cfg-target", Input).value
        
        if not name or not url:
            self.app.notify("Name and Connection URL are required!", severity="error")
            return
            
        try:
            self._datasource_service.create_profile(
                name=name,
                backend=backend,
                connection_url=url,
                target_kind=SessionTargetKind.LOCAL if target == "local" else SessionTargetKind.SSH,
                target_ref=None if target == "local" else target
            )
            self.app.notify(f"Datasource '{name}' saved successfully.")
            self._toggle_config_mode(False)
            self.refresh_catalog()
        except Exception as exc:
            self.app.notify(f"Failed to save: {exc}", severity="error")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "db-query-input":
            self._execute_query(event.value)
            event.stop()

    def refresh_catalog(self) -> None:
        try:
            profiles = self._datasource_service.list_profiles()
            snapshot = self._database_adapter.list_databases(
                self._workspace_root,
                target_kind=self._target_kind,
                target_ref=self._target_ref,
            )
            self._update_catalog_tree(snapshot, profiles)
        except Exception:
            pass

    def _update_catalog_tree(self, snapshot: DatabaseCatalogSnapshot, profiles: list[object]) -> None:
        tree = self.query_one("#db-catalog-tree", Tree)
        tree.clear()
        
        ds_root = tree.root.add("Datasources", expand=True)
        for profile in profiles:
            pid = getattr(profile, "id", "unknown")
            name = getattr(profile, "name", "unknown")
            ds_root.add_leaf(f" {name}", data={"kind": "datasource", "id": pid})
            
        sqlite_root = tree.root.add("Local SQLite", expand=True)
        for path in snapshot.databases:
            sqlite_root.add_leaf(f" {Path(path).name}", data={"kind": "sqlite", "path": path})

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        data = event.node.data
        if not data: return
        
        if data["kind"] == "datasource":
            self._selected_profile_id = data["id"]
            self._selected_database_path = None
            self.app.notify(f"Switched to: {data['id']}")
        elif data["kind"] == "sqlite":
            self._selected_database_path = data["path"]
            self._selected_profile_id = None
            self.app.notify(f"Switched to SQLite: {Path(data['path']).name}")

    def _execute_query(self, sql: str) -> None:
        if not sql.strip(): return
        
        from cockpit.domain.commands.command import Command
        from cockpit.shared.enums import CommandSource
        from cockpit.shared.utils import make_id
        
        args = {"query": sql}
        if self._selected_profile_id:
            args["profile_id"] = self._selected_profile_id
        elif self._selected_database_path:
            args["database_path"] = self._selected_database_path
        else:
            self.app.notify("Select a database from the catalog first!", severity="warning")
            return

        cmd = Command(id=make_id("cmd"), source=CommandSource.KEYBINDING, name="db.run_query", args=args, context=self.command_context())
        self.app._dispatch_command(cmd)

    def apply_command_result(self, payload: dict[str, object]) -> None:
        result = payload.get("query_result")
        if isinstance(result, dict):
            self._last_result = result
            self._render_results()

    def _render_results(self) -> None:
        grid = self.query_one("#db-results-grid", DataTable)
        status = self.query_one("#db-status-msg", Static)
        grid.clear(columns=True)
        
        columns = self._last_result.get("columns", [])
        rows = self._last_result.get("rows", [])
        
        if columns:
            grid.add_columns(*[str(c) for c in columns])
            for row in rows:
                if isinstance(row, list):
                    grid.add_row(*[str(cell) for cell in row])
            status.update(f"Rows returned: {len(rows)}")
        else:
            status.update(self._last_result.get("message", "Query executed successfully."))

    def resume(self) -> None:
        self.refresh_catalog()
        self.focus()

    def command_context(self) -> dict[str, object]:
        return {
            "panel_id": self.PANEL_ID,
            "workspace_root": self._workspace_root,
            "target_kind": self._target_kind.value,
            "target_ref": self._target_ref,
            "selected_profile_id": self._selected_profile_id,
            "selected_database_path": self._selected_database_path,
        }

    def snapshot_state(self) -> PanelState:
        return PanelState(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE)
