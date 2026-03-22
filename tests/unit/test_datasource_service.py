from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cockpit.application.services.datasource_service import DataSourceService
from cockpit.domain.models.datasource import DataSourceOperationResult, DataSourceProfile
from cockpit.infrastructure.config.config_loader import ConfigLoader
from cockpit.infrastructure.datasources.base import DataSourceInspection
from cockpit.infrastructure.persistence.repositories import DataSourceProfileRepository
from cockpit.infrastructure.persistence.sqlite_store import SQLiteStore
from cockpit.infrastructure.secrets.secret_resolver import SecretResolver
from cockpit.shared.enums import SessionTargetKind


class FakeDatasourceAdapter:
    def __init__(self, backend: str) -> None:
        self.backend = backend
        self.inspect_calls: list[str] = []
        self.run_calls: list[tuple[str, str, str]] = []
        self.inspect_profiles: list[DataSourceProfile] = []
        self.run_profiles: list[DataSourceProfile] = []

    def inspect(self, profile: DataSourceProfile) -> DataSourceInspection:
        self.inspect_calls.append(profile.id)
        self.inspect_profiles.append(profile)
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
        self.run_profiles.append(profile)
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

    def test_resolves_secret_refs_and_ssh_tunnels_before_routing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config").mkdir()
            store = SQLiteStore(root / "cockpit.db")
            repo = DataSourceProfileRepository(store)
            sql = FakeDatasourceAdapter("postgres")
            tunnel_manager = FakeTunnelManager()
            service = DataSourceService(
                repo,
                config_loader=ConfigLoader(start=root),
                sql_adapter=sql,
                secret_resolver=SecretResolver(base_path=root),
                tunnel_manager=tunnel_manager,
            )
            profile = service.create_profile(
                name="Remote Postgres",
                backend="postgres",
                connection_url="postgresql+psycopg://${DB_USER}:${DB_PASS}@db.internal/analytics",
                target_kind=SessionTargetKind.SSH,
                target_ref="${SSH_TARGET}",
                secret_refs={
                    "DB_USER": "literal:analytics",
                    "DB_PASS": "env:TEST_ANALYTICS_DB_PASS",
                    "SSH_TARGET": "literal:deploy@example.com",
                    "SSLMODE": "literal:require",
                },
                options={"connect_args": {"sslmode": "${SSLMODE}"}},
            )

            with patch.dict("os.environ", {"TEST_ANALYTICS_DB_PASS": "secret-pass"}):
                result = service.inspect_profile(profile.id)

            self.assertTrue(result.success)
            self.assertEqual(len(sql.inspect_profiles), 1)
            prepared = sql.inspect_profiles[0]
            self.assertEqual(
                prepared.connection_url,
                "postgresql+psycopg://analytics:secret-pass@127.0.0.1:15432/analytics",
            )
            self.assertEqual(prepared.target_ref, "deploy@example.com")
            self.assertEqual(
                prepared.options,
                {"connect_args": {"sslmode": "require"}},
            )
            self.assertEqual(len(tunnel_manager.calls), 1)
            self.assertTrue(tunnel_manager.calls[0][0].startswith("dsp_"))
            self.assertEqual(
                tunnel_manager.calls[0][1:],
                ("deploy@example.com", "db.internal", 5432),
            )
            store.close()

    def test_requires_explicit_remote_port_for_unknown_ssh_backend(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config").mkdir()
            store = SQLiteStore(root / "cockpit.db")
            repo = DataSourceProfileRepository(store)
            sql = FakeDatasourceAdapter("oracle")
            service = DataSourceService(
                repo,
                config_loader=ConfigLoader(start=root),
                sql_adapter=sql,
                tunnel_manager=FakeTunnelManager(),
            )
            profile = service.create_profile(
                name="Oracle",
                backend="oracle",
                connection_url="oracle://db.internal/service",
                target_kind=SessionTargetKind.SSH,
                target_ref="deploy@example.com",
            )

            with self.assertRaisesRegex(ValueError, "explicit remote port"):
                service.inspect_profile(profile.id)
            store.close()


class FakeTunnelManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, int]] = []

    def open_tunnel(
        self,
        *,
        profile_id: str,
        target_ref: str,
        remote_host: str,
        remote_port: int,
    ) -> SimpleNamespace:
        self.calls.append((profile_id, target_ref, remote_host, remote_port))
        return SimpleNamespace(remote_port=remote_port, local_port=15432)
