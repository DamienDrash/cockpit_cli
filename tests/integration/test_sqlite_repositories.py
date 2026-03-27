from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.core.command import CommandAuditEntry, CommandHistoryEntry
from cockpit.datasources.models.datasource import DataSourceProfile
from cockpit.workspace.models.layout import Layout, PanelRef, SplitNode, TabLayout
from cockpit.plugins.models import InstalledPlugin
from cockpit.workspace.models.session import Session
from cockpit.workspace.models.workspace import SessionTarget, Workspace
from cockpit.workspace.repositories import (
    AuditLogRepository,
    CommandHistoryRepository,
    DataSourceProfileRepository,
    InstalledPluginRepository,
    LayoutRepository,
    SessionRepository,
    SnapshotRepository,
    WebAdminStateRepository,
    WorkspaceRepository,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.core.enums import (
    CommandSource,
    SessionStatus,
    SessionTargetKind,
    SnapshotKind,
)


class SQLiteRepositoryTests(unittest.TestCase):
    def test_sessions_layouts_and_workspaces_round_trip(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            workspace_repo = WorkspaceRepository(store)
            layout_repo = LayoutRepository(store)
            session_repo = SessionRepository(store)

            workspace = Workspace(
                id="ws_local",
                name="Local",
                root_path="/tmp/project",
                target=SessionTarget(kind=SessionTargetKind.LOCAL),
                default_layout_id="default",
            )
            layout = Layout(
                id="default",
                name="Default",
                tabs=[
                    TabLayout(
                        id="work",
                        name="Work",
                        root_split=SplitNode(
                            orientation="vertical",
                            ratio=0.7,
                            children=[
                                PanelRef(panel_id="work-panel", panel_type="work")
                            ],
                        ),
                    )
                ],
                focus_path=["work", "work-panel"],
            )
            now = datetime(2026, 3, 22, tzinfo=UTC)
            session = Session(
                id="sess_1",
                workspace_id="ws_local",
                name="Main",
                status=SessionStatus.ACTIVE,
                active_tab_id="work",
                focused_panel_id="work-panel",
                snapshot_ref=None,
                created_at=now,
                updated_at=now,
                last_opened_at=now,
            )

            workspace_repo.save(workspace)
            layout_repo.save(layout)
            session_repo.save(session)

            loaded_workspace = workspace_repo.get("ws_local")
            loaded_layout = layout_repo.get("default")
            loaded_session = session_repo.get("sess_1")

            self.assertIsNotNone(loaded_workspace)
            self.assertIsNotNone(loaded_layout)
            self.assertIsNotNone(loaded_session)
            assert loaded_workspace is not None
            assert loaded_layout is not None
            assert loaded_session is not None
            self.assertEqual(loaded_workspace.root_path, "/tmp/project")
            self.assertEqual(loaded_layout.focus_path, ["work", "work-panel"])
            self.assertEqual(loaded_session.status, SessionStatus.ACTIVE)

            updated = Session(
                id="sess_1",
                workspace_id="ws_local",
                name="Main",
                status=SessionStatus.ACTIVE,
                active_tab_id="work",
                focused_panel_id="work-panel",
                snapshot_ref="snap_1",
                created_at=now,
                updated_at=datetime(2026, 3, 22, 12, 0, tzinfo=UTC),
                last_opened_at=now,
            )
            session_repo.save(updated)

            latest_session = session_repo.get_latest_for_workspace("ws_local")
            self.assertIsNotNone(latest_session)
            assert latest_session is not None
            self.assertEqual(latest_session.snapshot_ref, "snap_1")
            store.close()

    def test_snapshot_repository_handles_round_trip_and_corruption(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            store.execute(
                """
                INSERT INTO workspaces (
                    id, name, root_path, target_kind, target_ref,
                    default_layout_id, tags_json, metadata_json, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "ws_local",
                    "Local",
                    "/tmp/project",
                    "local",
                    None,
                    None,
                    "[]",
                    "{}",
                    '{"id":"ws_local","name":"Local","root_path":"/tmp/project","target":{"kind":"local"},"tags":[],"metadata":{},"schema_version":1}',
                ),
            )
            store.execute(
                """
                INSERT INTO sessions (
                    id, workspace_id, name, status, active_tab_id, focused_panel_id,
                    snapshot_ref, payload_json, created_at, updated_at, last_opened_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "sess_1",
                    "ws_local",
                    "Main",
                    "active",
                    "work",
                    "work-panel",
                    None,
                    '{"id":"sess_1","workspace_id":"ws_local","name":"Main","status":"active","active_tab_id":"work","focused_panel_id":"work-panel","snapshot_ref":null,"created_at":"2026-03-22T00:00:00+00:00","updated_at":"2026-03-22T00:00:00+00:00","last_opened_at":null,"schema_version":1}',
                    "2026-03-22T00:00:00+00:00",
                    "2026-03-22T00:00:00+00:00",
                    None,
                ),
            )
            snapshot_repo = SnapshotRepository(store)

            snapshot_ref = snapshot_repo.save(
                session_id="sess_1",
                snapshot_kind=SnapshotKind.RESUME,
                payload={"cwd": "/tmp/project"},
            )
            decoded = snapshot_repo.load(snapshot_ref)

            self.assertTrue(decoded.success)
            self.assertIsNotNone(decoded.envelope)
            assert decoded.envelope is not None
            self.assertEqual(decoded.envelope.payload["cwd"], "/tmp/project")

            store.execute(
                """
                INSERT INTO snapshots (
                    ref, session_id, snapshot_kind, schema_version, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "snap_bad",
                    "sess_1",
                    "resume",
                    1,
                    "{bad-json",
                    "2026-03-22T00:00:00+00:00",
                ),
            )

            corrupted = snapshot_repo.load("snap_bad")
            self.assertFalse(corrupted.success)
            self.assertEqual(corrupted.error, "Snapshot payload is not valid JSON.")
            store.close()

    def test_command_and_audit_repositories_store_records(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            history_repo = CommandHistoryRepository(store)
            audit_repo = AuditLogRepository(store)

            history_repo.record(
                CommandHistoryEntry(
                    command_id="cmd_1",
                    name="workspace.open",
                    source=CommandSource.SLASH,
                    success=True,
                    message="opened",
                )
            )
            audit_repo.record(
                CommandAuditEntry(
                    command_id="cmd_1",
                    action="workspace.open",
                    workspace_id="ws_local",
                    metadata={"root_path": "/tmp/project"},
                )
            )

            history = history_repo.list_recent()
            audit = audit_repo.list_recent()

            self.assertEqual(history[0]["name"], "workspace.open")
            self.assertTrue(history[0]["success"])
            self.assertEqual(audit[0]["action"], "workspace.open")
            self.assertEqual(audit[0]["metadata"]["root_path"], "/tmp/project")
            store.close()

    def test_datasource_plugin_and_web_admin_state_round_trip(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            datasource_repo = DataSourceProfileRepository(store)
            plugin_repo = InstalledPluginRepository(store)
            web_admin_repo = WebAdminStateRepository(store)

            datasource_repo.save(
                DataSourceProfile(
                    id="pg-main",
                    name="Main Postgres",
                    backend="postgres",
                    connection_url="postgresql://localhost/app",
                    capabilities=["can_query", "can_mutate"],
                )
            )
            plugin_repo.save(
                InstalledPlugin(
                    id="plug_1",
                    name="Notes Plugin",
                    module="cockpit.plugins.notes_plugin",
                    requirement="notes-plugin",
                    version_pin="1.0.0",
                    enabled=True,
                    manifest={"summary": "notes"},
                )
            )
            web_admin_repo.save("web_admin:last_page", {"page": "/plugins"})

            datasource = datasource_repo.get("pg-main")
            plugins = plugin_repo.list_all()
            state = web_admin_repo.get("web_admin:last_page")
            web_admin_repo.save(
                "secret:analytics-pass",
                {
                    "name": "analytics-pass",
                    "provider": "env",
                    "reference": {"provider": "env", "name": "ANALYTICS_DB_PASS"},
                },
            )
            prefixed = web_admin_repo.list_prefix("secret:")
            web_admin_repo.delete("secret:analytics-pass")
            removed = web_admin_repo.get("secret:analytics-pass")

            self.assertIsNotNone(datasource)
            assert datasource is not None
            self.assertEqual(datasource.backend, "postgres")
            self.assertEqual(plugins[0].version_pin, "1.0.0")
            self.assertEqual(state, {"page": "/plugins"})
            self.assertEqual(prefixed[0][0], "secret:analytics-pass")
            self.assertIsNone(removed)
            store.close()


if __name__ == "__main__":
    unittest.main()
