import unittest

from cockpit.application.handlers.base import ConfirmationRequiredError
from cockpit.application.handlers.db_handlers import RunDatabaseQueryHandler
from cockpit.domain.commands.command import Command
from cockpit.domain.models.datasource import DataSourceOperationResult, DataSourceProfile
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


class FakeDataSourceService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self._profiles = {
            "analytics": DataSourceProfile(
                id="analytics",
                name="Analytics",
                backend="postgres",
                connection_url="postgresql://localhost/app",
                risk_level="stage",
                capabilities=["can_query", "can_mutate"],
            )
        }

    def get_profile(self, profile_id: str) -> DataSourceProfile | None:
        return self._profiles.get(profile_id)

    def run_statement(
        self,
        profile_id: str,
        statement: str,
        *,
        operation: str = "query",
        row_limit: int = 50,
    ) -> DataSourceOperationResult:
        del row_limit
        self.calls.append((profile_id, statement, operation))
        return DataSourceOperationResult(
            success=True,
            profile_id=profile_id,
            backend="postgres",
            operation=operation,
            columns=["value"],
            rows=[["1"]],
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

    def test_runs_query_for_selected_datasource_profile(self) -> None:
        adapter = FakeDatabaseAdapter()
        datasource_service = FakeDataSourceService()
        handler = RunDatabaseQueryHandler(adapter, datasource_service)
        command = Command(
            id="cmd_3",
            source=CommandSource.SLASH,
            name="db.run_query",
            args={"argv": ["SELECT 1"]},
            context={
                "selected_profile_id": "analytics",
                "target_kind": SessionTargetKind.LOCAL.value,
            },
        )

        result = handler(command)

        self.assertTrue(result.success)
        self.assertEqual(adapter.calls, [])
        self.assertEqual(
            datasource_service.calls,
            [("analytics", "SELECT 1", "query")],
        )
        self.assertEqual(
            result.data["result_payload"]["selected_profile_id"],
            "analytics",
        )

    def test_requires_confirmation_for_mutating_datasource_queries(self) -> None:
        adapter = FakeDatabaseAdapter()
        datasource_service = FakeDataSourceService()
        handler = RunDatabaseQueryHandler(adapter, datasource_service)
        command = Command(
            id="cmd_4",
            source=CommandSource.SLASH,
            name="db.run_query",
            args={"argv": ["UPDATE users SET active = 0"]},
            context={
                "selected_profile_id": "analytics",
                "workspace_name": "analytics-stage",
                "workspace_root": "/srv/analytics",
                "target_kind": SessionTargetKind.LOCAL.value,
            },
        )

        with self.assertRaises(ConfirmationRequiredError):
            handler(command)

        self.assertEqual(datasource_service.calls, [])


if __name__ == "__main__":
    unittest.main()
