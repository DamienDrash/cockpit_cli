"""Professional Database Panel with Hierarchical Schema Browser."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Static,
    Label,
    Input,
    DataTable,
    Tree,
    Button,
    ContentSwitcher,
    Select,
)

from cockpit.core.dispatch.event_bus import EventBus
from cockpit.datasources.services.datasource_service import DataSourceService
from cockpit.core.events.runtime import PanelMounted
from cockpit.core.panel_state import PanelState
from cockpit.datasources.adapters.database_adapter import (
    DatabaseAdapter,
    DatabaseCatalogSnapshot,
)
from cockpit.core.enums import SessionTargetKind
from cockpit.ui.panels.base_panel import BasePanel


class DBPanel(BasePanel):
    """Professional Database TUI with deep hierarchical schema browser."""

    PANEL_ID = "db-panel"
    PANEL_TYPE = "db"
    can_focus = True

    def __init__(
        self,
        *,
        event_bus: EventBus,
        database_adapter: DatabaseAdapter,
        datasource_service: DataSourceService,
        dispatch: Callable[..., object] | None = None,
    ) -> None:
        super().__init__(id=self.PANEL_ID)
        self._event_bus = event_bus
        self._database_adapter = database_adapter
        self._datasource_service = datasource_service
        self._dispatch = dispatch
        self._workspace_root = ""
        self._target_kind = SessionTargetKind.LOCAL
        self._selected_profile_id: str | None = None
        self._selected_database_path: str | None = None
        self._last_result: dict[str, object] | None = None
        self._config_mode = False

    def compose(self) -> ComposeResult:
        with Horizontal():
            # Sidebar: Deep Catalog Browser
            with Vertical(id="db-sidebar", classes="sidebar"):
                yield Label(" [ CATALOG ] ", classes="section-title")
                yield Button(
                    "＋ NEW CONNECTION", id="db-btn-new", classes="action-button"
                )
                yield Tree("DATABASES", id="db-catalog-tree")
                yield Label(" [ ACTIONS ] ", classes="section-title")
                yield Static(
                    " Enter: Select/Preview\n r: Refresh\n e: Query Editor",
                    id="db-legend",
                )

            # Main: IDE or Config
            with Vertical(id="db-main"):
                with ContentSwitcher(initial="ide", id="db-main-switcher"):
                    with Vertical(id="ide"):
                        with Vertical(id="db-editor-pane"):
                            yield Label("SQL QUERY EDITOR", classes="pane-title")
                            yield Input(
                                placeholder="SELECT * FROM ...", id="db-query-input"
                            )

                        with Vertical(id="db-results-pane"):
                            yield Label("QUERY RESULTS", classes="pane-title")
                            yield DataTable(id="db-results-grid")
                            yield Static("No query executed yet.", id="db-status-msg")

                    with Vertical(id="config"):
                        yield Label("CONFIGURE NEW DATASOURCE", classes="pane-title")
                        with Vertical(id="db-config-form"):
                            yield Label("Name:")
                            yield Input(placeholder="my-db", id="db-cfg-name")
                            yield Label("Backend:")
                            yield Select(
                                [("SQLite", "sqlite"), ("PostgreSQL", "postgres")],
                                value="sqlite",
                                id="db-cfg-backend",
                            )
                            yield Label("URL:")
                            yield Input(
                                placeholder="sqlite:///db.sqlite", id="db-cfg-url"
                            )
                            with Horizontal(id="db-cfg-actions"):
                                yield Button(
                                    "SAVE", id="db-cfg-save", variant="primary"
                                )
                                yield Button("CANCEL", id="db-cfg-cancel")

    def on_mount(self) -> None:
        self._event_bus.publish(
            PanelMounted(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE)
        )
        self.refresh_catalog()

    def initialize(self, context: dict[str, object]) -> None:
        self._workspace_root = str(context.get("workspace_root", ""))
        self.refresh_catalog()
        self.focus()

    def refresh_catalog(self) -> None:
        try:
            profiles = self._datasource_service.list_profiles()
            snapshot = self._database_adapter.list_databases(self._workspace_root)
            self._update_catalog_tree(snapshot, profiles)
        except Exception:
            pass

    def _update_catalog_tree(
        self, snapshot: DatabaseCatalogSnapshot, profiles: list[object]
    ) -> None:
        tree = self.query_one("#db-catalog-tree", Tree)
        tree.clear()
        tree.root.expand()

        # 1. Datasources (Profiles)
        for profile in profiles:
            pid = getattr(profile, "id", "unknown")
            name = getattr(profile, "name", "unknown")
            node = tree.root.add(
                f"  {name}", data={"kind": "profile", "id": pid}, expand=False
            )
            # Add a dummy node to allow expansion
            node.add("loading...", data={"kind": "loading"})

        # 2. Local SQLite Files
        for path in snapshot.databases:
            node = tree.root.add(
                f"  {Path(path).name}",
                data={"kind": "sqlite_file", "path": path},
                expand=False,
            )
            node.add("loading...", data={"kind": "loading"})

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        node = event.node
        data = node.data
        if not data:
            return

        if data["kind"] == "profile":
            self._load_profile_tables(node, data["id"])
        elif data["kind"] == "sqlite_file":
            self._load_sqlite_tables(node, data["path"])

    def _load_profile_tables(self, node: Tree.Node, profile_id: str) -> None:
        node.remove_children()
        try:
            inspect = self._datasource_service.inspect_profile(profile_id)
            if inspect.success:
                tables = inspect.details.get("tables", [])
                for t in tables:
                    node.add_leaf(
                        f"  {t}", data={"kind": "table", "name": t, "pid": profile_id}
                    )
                if not tables:
                    node.add_leaf("(no tables)", data={})
        except Exception as exc:
            node.add_leaf(f"Error: {exc}", data={})

    def _load_sqlite_tables(self, node: Tree.Node, path: str) -> None:
        node.remove_children()
        try:
            # We use the database adapter to run a quick query for table names

            # Simple SQLite table query
            import sqlite3

            conn = sqlite3.connect(path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cursor.fetchall()]
            conn.close()

            for t in tables:
                node.add_leaf(
                    f"  {t}", data={"kind": "sqlite_table", "name": t, "path": path}
                )
            if not tables:
                node.add_leaf("(no tables)", data={})
        except Exception as exc:
            node.add_leaf(f"Error: {exc}", data={})

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        data = event.node.data
        if not data:
            return

        if data["kind"] == "table":
            self._selected_profile_id = data["pid"]
            self._selected_database_path = None
            query = f"SELECT * FROM {data['name']} LIMIT 50;"
            self.query_one("#db-query-input", Input).value = query
            self._execute_query(query)
        elif data["kind"] == "sqlite_table":
            self._selected_database_path = data["path"]
            self._selected_profile_id = None
            query = f"SELECT * FROM {data['name']} LIMIT 50;"
            self.query_one("#db-query-input", Input).value = query
            self._execute_query(query)

    @on(Input.Submitted, "#db-query-input")
    def on_query_submitted(self, event: Input.Submitted) -> None:
        self._execute_query(event.value)

    def _execute_query(self, sql: str) -> None:
        if not sql.strip():
            return
        if self._dispatch is None:
            return
        from cockpit.core.command import Command
        from cockpit.core.enums import CommandSource
        from cockpit.core.utils import make_id

        args: dict[str, object] = {"query": sql}
        if self._selected_profile_id:
            args["profile_id"] = self._selected_profile_id
        elif self._selected_database_path:
            args["database_path"] = self._selected_database_path
        else:
            self.app.notify(
                "Please select a database or table from the tree first.",
                severity="warning",
            )
            return
        self._dispatch(
            Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="db.run_query",
                args=args,
                context=self.command_context(),
            )
        )

    def apply_command_result(self, payload: dict[str, object]) -> None:
        res = payload.get("query_result")
        if isinstance(res, dict):
            self._last_result = res
            self._render_results()

    def _render_results(self) -> None:
        grid = self.query_one("#db-results-grid", DataTable)
        grid.clear(columns=True)
        cols = self._last_result.get("columns", [])
        rows = self._last_result.get("rows", [])
        if cols:
            grid.add_columns(*[str(c) for c in cols])
            for r in rows:
                if isinstance(r, list):
                    grid.add_row(*[str(cell) for cell in r])
            self.query_one("#db-status-msg", Static).update(f"Rows: {len(rows)}")

    def resume(self) -> None:
        self.refresh_catalog()
        self.focus()

    def command_context(self) -> dict[str, object]:
        return {"panel_id": self.PANEL_ID, "workspace_root": self._workspace_root}

    def snapshot_state(self) -> PanelState:
        return PanelState(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE)
