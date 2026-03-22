from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.application.dispatch.command_dispatcher import CommandDispatcher
from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.handlers.base import DispatchResult
from cockpit.application.services.activity_log_service import ActivityLogService
from cockpit.domain.commands.command import Command
from cockpit.domain.events.domain_events import WorkspaceOpened
from cockpit.domain.events.runtime_events import PTYStartupFailed
from cockpit.infrastructure.persistence.repositories import (
    AuditLogRepository,
    CommandHistoryRepository,
)
from cockpit.infrastructure.persistence.sqlite_store import SQLiteStore
from cockpit.shared.enums import CommandSource, SessionTargetKind


class ActivityLogServiceTests(unittest.TestCase):
    def test_records_command_history_and_audit_entries(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            history_repository = CommandHistoryRepository(store)
            audit_repository = AuditLogRepository(store)
            service = ActivityLogService(
                history_repository=history_repository,
                audit_repository=audit_repository,
            )
            bus = EventBus()
            dispatcher = CommandDispatcher(event_bus=bus)
            dispatcher.observe(service.record_command)
            bus.subscribe(WorkspaceOpened, service.record_event)
            bus.subscribe(PTYStartupFailed, service.record_event)

            def handler(_command: Command) -> DispatchResult:
                return DispatchResult(success=True, message="opened")

            dispatcher.register("workspace.open", handler)
            result = dispatcher.dispatch(
                Command(
                    id="cmd_1",
                    source=CommandSource.SLASH,
                    name="workspace.open",
                    args={"argv": ["."]},
                    context={"workspace_root": "/tmp/project"},
                )
            )
            self.assertTrue(result.success)

            bus.publish(
                WorkspaceOpened(
                    workspace_id="ws_1",
                    name="Project",
                    root_path="/tmp/project",
                    target_kind=SessionTargetKind.LOCAL,
                )
            )
            bus.publish(
                PTYStartupFailed(
                    panel_id="work-panel",
                    cwd="/tmp/project",
                    reason="missing shell",
                )
            )

            history = history_repository.list_recent()
            audit = audit_repository.list_recent()

            self.assertEqual(history[0]["name"], "workspace.open")
            self.assertEqual(history[0]["context"]["workspace_root"], "/tmp/project")
            actions = {entry["action"] for entry in audit}
            self.assertIn("workspace.opened", actions)
            self.assertIn("terminal.start_failed", actions)
            store.close()


if __name__ == "__main__":
    unittest.main()
