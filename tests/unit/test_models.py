import unittest
from datetime import UTC, datetime

from cockpit.domain.commands.command import Command, CommandAuditEntry, CommandHistoryEntry
from cockpit.domain.models.layout import Layout, PanelRef, SplitNode, TabLayout
from cockpit.domain.models.panel_state import PanelState
from cockpit.domain.models.session import Session
from cockpit.domain.models.workspace import SessionTarget, Workspace
from cockpit.shared.enums import (
    CommandSource,
    PanelPersistPolicy,
    SessionStatus,
    SessionTargetKind,
)


class ModelSerializationTests(unittest.TestCase):
    def test_workspace_serializes_with_target_kind(self) -> None:
        workspace = Workspace(
            id="ws_local",
            name="Local",
            root_path="/tmp/project",
            target=SessionTarget(kind=SessionTargetKind.LOCAL),
        )

        payload = workspace.to_dict()

        self.assertEqual(payload["target"]["kind"], "local")
        self.assertEqual(payload["root_path"], "/tmp/project")
        self.assertEqual(payload["schema_version"], 1)

    def test_session_serializes_datetimes_to_isoformat(self) -> None:
        now = datetime(2026, 3, 22, tzinfo=UTC)
        session = Session(
            id="sess_1",
            workspace_id="ws_local",
            name="Main",
            status=SessionStatus.ACTIVE,
            active_tab_id="work",
            focused_panel_id="work-panel",
            snapshot_ref="snap_1",
            created_at=now,
            updated_at=now,
        )

        payload = session.to_dict()

        self.assertEqual(payload["status"], "active")
        self.assertEqual(payload["created_at"], now.isoformat())
        self.assertEqual(payload["schema_version"], 1)

    def test_layout_serializes_nested_split_tree(self) -> None:
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

        payload = layout.to_dict()

        self.assertEqual(
            payload["tabs"][0]["root_split"]["children"][0]["panel_id"], "work-panel"
        )
        self.assertEqual(payload["schema_version"], 1)

    def test_panel_state_serializes_persist_policy(self) -> None:
        state = PanelState(
            panel_id="work-panel",
            panel_type="work",
            persist_policy=PanelPersistPolicy.RUNTIME_RECREATED,
            snapshot={"cwd": "/tmp/project"},
        )

        payload = state.to_dict()

        self.assertEqual(payload["persist_policy"], "runtime_recreated")
        self.assertEqual(payload["snapshot"]["cwd"], "/tmp/project")
        self.assertEqual(payload["schema_version"], 1)

    def test_command_serializes_source(self) -> None:
        command = Command(
            id="cmd_1",
            source=CommandSource.SLASH,
            name="workspace.open",
            args={"argv": ["."]},
        )

        payload = command.to_dict()

        self.assertEqual(payload["source"], "slash")
        self.assertEqual(payload["name"], "workspace.open")
        self.assertEqual(payload["schema_version"], 1)

    def test_command_history_entry_serializes_result_metadata(self) -> None:
        entry = CommandHistoryEntry(
            command_id="cmd_1",
            name="workspace.open",
            source=CommandSource.SLASH,
            args={"argv": ["."]},
            success=True,
            message="workspace ready",
        )

        payload = entry.to_dict()

        self.assertTrue(payload["success"])
        self.assertEqual(payload["message"], "workspace ready")
        self.assertEqual(payload["schema_version"], 1)

    def test_command_audit_entry_serializes_metadata(self) -> None:
        entry = CommandAuditEntry(
            command_id="cmd_1",
            action="workspace.open",
            workspace_id="ws_local",
            metadata={"root_path": "/tmp/project"},
        )

        payload = entry.to_dict()

        self.assertEqual(payload["action"], "workspace.open")
        self.assertEqual(payload["metadata"]["root_path"], "/tmp/project")
        self.assertEqual(payload["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
