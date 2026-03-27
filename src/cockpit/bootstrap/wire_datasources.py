"""Datasource context wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cockpit.core.dispatch.command_dispatcher import CommandDispatcher
from cockpit.datasources.services.datasource_service import DataSourceService
from cockpit.datasources.services.secret_service import SecretService
from cockpit.workspace.config_loader import ConfigLoader
from cockpit.infrastructure.cron.cron_adapter import CronAdapter
from cockpit.datasources.adapters.database_adapter import DatabaseAdapter
from cockpit.infrastructure.docker.docker_adapter import DockerAdapter
from cockpit.infrastructure.git.git_adapter import GitAdapter
from cockpit.infrastructure.http.http_adapter import HttpAdapter
from cockpit.workspace.repositories import (
    DataSourceProfileRepository,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.datasources.adapters.secret_resolver import SecretResolver
from cockpit.datasources.adapters.ssh_command_runner import SSHCommandRunner
from cockpit.datasources.adapters.tunnel_manager import SSHTunnelManager
from cockpit.infrastructure.cron.cron_handlers import SetCronJobEnabledHandler


def wire_datasources(
    store: SQLiteStore,
    config_loader: ConfigLoader,
    secret_service: SecretService,
    project_root: Path,
    command_dispatcher: CommandDispatcher,
    ssh_command_runner: SSHCommandRunner,
) -> dict[str, Any]:
    """Wire datasource, secret, and adapter components."""
    datasource_repository = DataSourceProfileRepository(store)

    cron_adapter = CronAdapter(ssh_command_runner=ssh_command_runner)
    docker_adapter = DockerAdapter(ssh_command_runner=ssh_command_runner)
    database_adapter = DatabaseAdapter(ssh_command_runner=ssh_command_runner)
    http_adapter = HttpAdapter()
    git_adapter = GitAdapter(ssh_command_runner=ssh_command_runner)

    secret_resolver = SecretResolver(
        base_path=project_root,
        named_reference_lookup=secret_service.lookup_reference,
        vault_reference_lookup=secret_service.resolve_vault_reference,
    )

    tunnel_manager = SSHTunnelManager()

    datasource_service = DataSourceService(
        datasource_repository,
        config_loader=config_loader,
        secret_resolver=secret_resolver,
        tunnel_manager=tunnel_manager,
    )

    # Handlers (without circular dependencies)
    command_dispatcher.register(
        "cron.enable",
        SetCronJobEnabledHandler(cron_adapter, enabled=True),
    )
    command_dispatcher.register(
        "cron.disable",
        SetCronJobEnabledHandler(cron_adapter, enabled=False),
    )

    return {
        "datasource_service": datasource_service,
        "secret_resolver": secret_resolver,
        "tunnel_manager": tunnel_manager,
        "cron_adapter": cron_adapter,
        "docker_adapter": docker_adapter,
        "database_adapter": database_adapter,
        "http_adapter": http_adapter,
        "git_adapter": git_adapter,
    }
