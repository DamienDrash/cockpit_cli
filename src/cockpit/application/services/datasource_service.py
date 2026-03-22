"""Datasource profile management and execution."""

from __future__ import annotations

from dataclasses import dataclass, replace

from cockpit.domain.models.datasource import DataSourceOperationResult, DataSourceProfile
from cockpit.infrastructure.config.config_loader import ConfigLoader
from cockpit.infrastructure.datasources.base import DataSourceAdapter
from cockpit.infrastructure.datasources.chroma_adapter import ChromaDatasourceAdapter
from cockpit.infrastructure.datasources.mongodb_adapter import MongoDatasourceAdapter
from cockpit.infrastructure.datasources.redis_adapter import RedisDatasourceAdapter
from cockpit.infrastructure.datasources.url_tools import (
    connection_host_and_port,
    rewrite_connection_url,
)
from cockpit.infrastructure.secrets.secret_resolver import SecretResolver
from cockpit.infrastructure.ssh.tunnel_manager import SSHTunnelManager
from cockpit.infrastructure.datasources.sqlalchemy_adapter import (
    SQLAlchemyDatasourceAdapter,
    SQL_BACKENDS,
)
from cockpit.infrastructure.persistence.repositories import DataSourceProfileRepository
from cockpit.shared.enums import SessionTargetKind
from cockpit.shared.utils import make_id


DEFAULT_CAPABILITIES: dict[str, list[str]] = {
    "sqlite": ["can_query", "can_mutate", "supports_schema_browser", "supports_transactions"],
    "postgres": ["can_query", "can_mutate", "supports_schema_browser", "supports_transactions", "can_explain"],
    "postgresql": ["can_query", "can_mutate", "supports_schema_browser", "supports_transactions", "can_explain"],
    "mysql": ["can_query", "can_mutate", "supports_schema_browser", "supports_transactions", "can_explain"],
    "mariadb": ["can_query", "can_mutate", "supports_schema_browser", "supports_transactions", "can_explain"],
    "mssql": ["can_query", "can_mutate", "supports_schema_browser", "supports_transactions"],
    "duckdb": ["can_query", "can_mutate", "supports_schema_browser", "supports_transactions"],
    "bigquery": ["can_query", "can_mutate", "supports_schema_browser", "can_explain"],
    "snowflake": ["can_query", "can_mutate", "supports_schema_browser"],
    "mongodb": ["can_query", "can_mutate", "supports_schema_browser"],
    "redis": ["can_query", "can_mutate", "supports_keys"],
    "chromadb": ["can_query", "can_mutate", "supports_vectors"],
}

DEFAULT_REMOTE_PORTS: dict[str, int] = {
    "postgres": 5432,
    "postgresql": 5432,
    "mysql": 3306,
    "mariadb": 3306,
    "mssql": 1433,
    "mongodb": 27017,
    "redis": 6379,
    "chromadb": 8000,
}


@dataclass(slots=True)
class DatasourceDiagnostics:
    total_profiles: int
    enabled_profiles: int
    backends: list[str]


class DataSourceService:
    """Manage datasource profiles and route execution to adapter families."""

    def __init__(
        self,
        repository: DataSourceProfileRepository,
        *,
        config_loader: ConfigLoader,
        sql_adapter: DataSourceAdapter | None = None,
        mongo_adapter: DataSourceAdapter | None = None,
        redis_adapter: DataSourceAdapter | None = None,
        chroma_adapter: DataSourceAdapter | None = None,
        secret_resolver: SecretResolver | None = None,
        tunnel_manager: SSHTunnelManager | None = None,
    ) -> None:
        self._repository = repository
        self._config_loader = config_loader
        self._sql_adapter = sql_adapter or SQLAlchemyDatasourceAdapter()
        self._mongo_adapter = mongo_adapter or MongoDatasourceAdapter()
        self._redis_adapter = redis_adapter or RedisDatasourceAdapter()
        self._chroma_adapter = chroma_adapter or ChromaDatasourceAdapter()
        self._secret_resolver = secret_resolver or SecretResolver()
        self._tunnel_manager = tunnel_manager

    def ensure_seed_profiles(self) -> None:
        payload = self._config_loader.load_datasources()
        raw_profiles = payload.get("profiles", [])
        if not isinstance(raw_profiles, list):
            return
        for raw_profile in raw_profiles:
            if not isinstance(raw_profile, dict):
                continue
            profile_id = raw_profile.get("id")
            if not isinstance(profile_id, str) or not profile_id:
                continue
            if self._repository.get(profile_id) is not None:
                continue
            profile = self._profile_from_mapping(raw_profile, profile_id=profile_id)
            self._repository.save(profile)

    def list_profiles(self) -> list[DataSourceProfile]:
        self.ensure_seed_profiles()
        return self._repository.list_all()

    def get_profile(self, profile_id: str) -> DataSourceProfile | None:
        self.ensure_seed_profiles()
        return self._repository.get(profile_id)

    def save_profile(self, profile: DataSourceProfile) -> None:
        self._repository.save(profile)

    def create_profile(
        self,
        *,
        name: str,
        backend: str,
        driver: str | None = None,
        connection_url: str | None = None,
        database_name: str | None = None,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
        risk_level: str = "dev",
        options: dict[str, object] | None = None,
        secret_refs: dict[str, object] | None = None,
        tags: list[str] | None = None,
    ) -> DataSourceProfile:
        normalized_backend = backend.strip().lower()
        profile = DataSourceProfile(
            id=make_id("dsp"),
            name=name.strip() or normalized_backend.title(),
            backend=normalized_backend,
            driver=driver.strip() if isinstance(driver, str) and driver.strip() else None,
            connection_url=connection_url.strip() if isinstance(connection_url, str) and connection_url.strip() else None,
            target_kind=target_kind,
            target_ref=target_ref,
            database_name=database_name.strip() if isinstance(database_name, str) and database_name.strip() else None,
            risk_level=risk_level,
            capabilities=list(DEFAULT_CAPABILITIES.get(normalized_backend, ["can_query"])),
            options=dict(options or {}),
            secret_refs=dict(secret_refs or {}),
            tags=list(tags or []),
        )
        self._repository.save(profile)
        return profile

    def delete_profile(self, profile_id: str) -> None:
        self._repository.delete(profile_id)

    def inspect_profile(self, profile_id: str) -> DataSourceOperationResult:
        profile = self._require_profile(profile_id)
        prepared_profile = self._prepared_profile(profile)
        return self._adapter_for(prepared_profile).inspect(prepared_profile).to_operation_result()

    def run_statement(
        self,
        profile_id: str,
        statement: str,
        *,
        operation: str = "query",
        row_limit: int = 50,
    ) -> DataSourceOperationResult:
        profile = self._require_profile(profile_id)
        prepared_profile = self._prepared_profile(profile)
        return self._adapter_for(prepared_profile).run(
            prepared_profile,
            statement,
            operation=operation,
            row_limit=row_limit,
        )

    def diagnostics(self) -> DatasourceDiagnostics:
        profiles = self.list_profiles()
        return DatasourceDiagnostics(
            total_profiles=len(profiles),
            enabled_profiles=sum(1 for profile in profiles if profile.enabled),
            backends=sorted({profile.backend for profile in profiles}),
        )

    def _require_profile(self, profile_id: str) -> DataSourceProfile:
        profile = self.get_profile(profile_id)
        if profile is None:
            raise LookupError(f"Datasource profile '{profile_id}' was not found.")
        return profile

    def _adapter_for(self, profile: DataSourceProfile) -> DataSourceAdapter:
        backend = profile.backend.lower()
        if backend in SQL_BACKENDS:
            return self._sql_adapter
        if backend == "mongodb":
            return self._mongo_adapter
        if backend == "redis":
            return self._redis_adapter
        if backend == "chromadb":
            return self._chroma_adapter
        return self._sql_adapter

    def _prepared_profile(self, profile: DataSourceProfile) -> DataSourceProfile:
        connection_url = self._secret_resolver.resolve_text(
            profile.connection_url,
            profile.secret_refs,
        )
        target_ref = self._secret_resolver.resolve_text(
            profile.target_ref,
            profile.secret_refs,
        )
        database_name = self._secret_resolver.resolve_text(
            profile.database_name,
            profile.secret_refs,
        )
        resolved_options = self._secret_resolver.resolve_value(
            profile.options,
            profile.secret_refs,
        )
        if not isinstance(resolved_options, dict):
            resolved_options = dict(profile.options)
        if (
            isinstance(connection_url, str)
            and connection_url
            and profile.target_kind is SessionTargetKind.SSH
            and isinstance(target_ref, str)
            and target_ref
            and self._tunnel_manager is not None
            and profile.backend.lower() not in {"sqlite", "bigquery", "snowflake"}
        ):
            remote_host, remote_port = connection_host_and_port(connection_url)
            if remote_host:
                effective_remote_port = remote_port or DEFAULT_REMOTE_PORTS.get(
                    profile.backend.lower()
                )
                if not effective_remote_port or int(effective_remote_port) <= 0:
                    raise ValueError(
                        f"Datasource '{profile.name}' needs an explicit remote port in its connection URL."
                    )
                tunnel = self._tunnel_manager.open_tunnel(
                    profile_id=profile.id,
                    target_ref=target_ref,
                    remote_host=remote_host,
                    remote_port=int(effective_remote_port),
                )
                if tunnel.remote_port > 0:
                    connection_url = rewrite_connection_url(
                        connection_url,
                        host="127.0.0.1",
                        port=tunnel.local_port,
                    )
        return replace(
            profile,
            connection_url=connection_url,
            target_ref=target_ref,
            database_name=database_name,
            options=resolved_options,
        )

    def _profile_from_mapping(
        self,
        payload: dict[str, object],
        *,
        profile_id: str,
    ) -> DataSourceProfile:
        target_kind = payload.get("target_kind", "local")
        return DataSourceProfile(
            id=profile_id,
            name=str(payload.get("name", profile_id)),
            backend=str(payload.get("backend", "sqlite")).lower(),
            driver=str(payload["driver"]) if payload.get("driver") is not None else None,
            connection_url=(
                str(payload["connection_url"])
                if payload.get("connection_url") is not None
                else None
            ),
            target_kind=(
                target_kind
                if isinstance(target_kind, SessionTargetKind)
                else SessionTargetKind(str(target_kind))
            ),
            target_ref=str(payload["target_ref"]) if payload.get("target_ref") is not None else None,
            database_name=(
                str(payload["database_name"])
                if payload.get("database_name") is not None
                else None
            ),
            risk_level=str(payload.get("risk_level", "dev")),
            capabilities=[
                str(item)
                for item in payload.get(
                    "capabilities",
                    DEFAULT_CAPABILITIES.get(str(payload.get("backend", "sqlite")).lower(), ["can_query"]),
                )
                if isinstance(item, str)
            ],
            options=payload.get("options", {}) if isinstance(payload.get("options"), dict) else {},
            secret_refs=(
                payload.get("secret_refs", {})
                if isinstance(payload.get("secret_refs"), dict)
                else {}
            ),
            tags=[str(item) for item in payload.get("tags", []) if isinstance(item, str)],
            managed_by_plugin=(
                str(payload["managed_by_plugin"])
                if payload.get("managed_by_plugin") is not None
                else None
            ),
            enabled=bool(payload.get("enabled", True)),
        )
