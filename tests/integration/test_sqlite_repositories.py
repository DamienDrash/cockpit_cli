from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.domain.commands.command import CommandAuditEntry, CommandHistoryEntry
from cockpit.domain.models.layout import Layout, PanelRef, SplitNode, TabLayout
from cockpit.domain.models.session import Session
from cockpit.domain.models.workspace import SessionTarget, Workspace
from cockpit.infrastructure.persistence.repositories import (
    AuditLogRepository,
    CommandHistoryRepository,
    LayoutRepository,
    SessionRepository,
    SnapshotRepository,
    WorkspaceRepository,
)
from cockpit.infrastructure.persistence.sqlite_store import SQLiteStore
from cockpit.shared.enums import (
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
                            children=[PanelRef(panel_id="work-panel", panel_type="work")],
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


if __name__ == "__main__":
    unittest.main()
