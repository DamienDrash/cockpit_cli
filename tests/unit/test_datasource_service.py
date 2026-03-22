from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.application.services.datasource_service import DataSourceService
from cockpit.domain.models.datasource import DataSourceOperationResult, DataSourceProfile
from cockpit.infrastructure.config.config_loader import ConfigLoader
from cockpit.infrastructure.datasources.base import DataSourceInspection
from cockpit.infrastructure.persistence.repositories import DataSourceProfileRepository
from cockpit.infrastructure.persistence.sqlite_store import SQLiteStore


class FakeDatasourceAdapter:
    def __init__(self, backend: str) -> None:
        self.backend = backend
        self.inspect_calls: list[str] = []
        self.run_calls: list[tuple[str, str, str]] = []

    def inspect(self, profile: DataSourceProfile) -> DataSourceInspection:
        self.inspect_calls.append(profile.id)
        return DataSourceInspection(
            success=True,
            profile_id=profile.id,
            backend=self.backend,
            summary=f"Connected to {profile.name}.",
            details={"backend": self.backend},
        )

    def run(
        self,
        profile: DataSourceProfile,
        statement: str,
        *,
        operation: str = "query",
        row_limit: int = 50,
    ) -> DataSourceOperationResult:
        del row_limit
        self.run_calls.append((profile.id, statement, operation))
        return DataSourceOperationResult(
            success=True,
            profile_id=profile.id,
            backend=self.backend,
            operation=operation,
            columns=["value"],
            rows=[["1"]],
            message="ok",
        )


class DataSourceServiceTests(unittest.TestCase):
    def test_routes_sql_and_non_sql_profiles_and_seeds_from_config(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config").mkdir()
            (root / "config" / "datasources.yaml").write_text(
                "\n".join(
                    [
                        "profiles:",
                        "  - id: pg-main",
                        "    name: Main Postgres",
                        "    backend: postgres",
                        "    connection_url: postgresql://localhost/app",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            store = SQLiteStore(root / "cockpit.db")
            repo = DataSourceProfileRepository(store)
            sql = FakeDatasourceAdapter("postgres")
            mongo = FakeDatasourceAdapter("mongodb")
            redis = FakeDatasourceAdapter("redis")
            chroma = FakeDatasourceAdapter("chromadb")
            service = DataSourceService(
                repo,
                config_loader=ConfigLoader(start=root),
                sql_adapter=sql,
                mongo_adapter=mongo,
                redis_adapter=redis,
                chroma_adapter=chroma,
            )

            profiles = service.list_profiles()
            self.assertEqual([profile.id for profile in profiles], ["pg-main"])

            created = service.create_profile(
                name="Vector DB",
                backend="chromadb",
                connection_url="http://localhost:8000",
            )
            inspection = service.inspect_profile("pg-main")
            result = service.run_statement(created.id, '{"collection":"docs"}', operation="query")

            self.assertTrue(inspection.success)
            self.assertTrue(result.success)
            self.assertEqual(sql.inspect_calls, ["pg-main"])
            self.assertEqual(chroma.run_calls, [(created.id, '{"collection":"docs"}', "query")])
            store.close()
