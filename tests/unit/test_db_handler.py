import unittest

from cockpit.application.handlers.base import ConfirmationRequiredError
from cockpit.application.handlers.db_handlers import RunDatabaseQueryHandler
from cockpit.domain.commands.command import Command
from cockpit.infrastructure.db.database_adapter import DatabaseQueryResult
from cockpit.shared.enums import CommandSource, SessionTargetKind


class FakeDatabaseAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, SessionTargetKind, str | None]] = []

    def run_query(
        self,
        database_path: str,
        query: str,
        *,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
        row_limit: int = 50,
    ) -> DatabaseQueryResult:
        del row_limit
        self.calls.append((database_path, query, target_kind, target_ref))
        return DatabaseQueryResult(
            success=True,
            database_path=database_path,
            query=query,
            columns=["value"],
            rows=[["1"]],
            row_count=1,
            message="Returned 1 row.",
        )


class RunDatabaseQueryHandlerTests(unittest.TestCase):
    def test_requires_confirmation_for_mutating_queries(self) -> None:
        adapter = FakeDatabaseAdapter()
        handler = RunDatabaseQueryHandler(adapter)
        command = Command(
            id="cmd_1",
            source=CommandSource.SLASH,
            name="db.run_query",
            args={"argv": ["UPDATE users SET active = 0"]},
            context={
                "selected_database_path": "/tmp/app.db",
                "workspace_name": "payments-prod",
                "workspace_root": "/srv/payments",
                "target_kind": SessionTargetKind.LOCAL.value,
            },
        )

        with self.assertRaises(ConfirmationRequiredError):
            handler(command)

        self.assertEqual(adapter.calls, [])

    def test_runs_query_for_selected_database(self) -> None:
        adapter = FakeDatabaseAdapter()
        handler = RunDatabaseQueryHandler(adapter)
        command = Command(
            id="cmd_2",
            source=CommandSource.SLASH,
            name="db.run_query",
            args={"argv": ["SELECT 1"], "confirmed": True},
            context={
                "selected_database_path": "/tmp/app.db",
                "target_kind": SessionTargetKind.SSH.value,
                "target_ref": "dev@example.com",
            },
        )

        result = handler(command)

        self.assertTrue(result.success)
        self.assertEqual(
            adapter.calls,
            [("/tmp/app.db", "SELECT 1", SessionTargetKind.SSH, "dev@example.com")],
        )
        self.assertEqual(result.data["result_panel_id"], "db-panel")


if __name__ == "__main__":
    unittest.main()
