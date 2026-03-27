"""Admin context wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cockpit.datasources.services.secret_service import SecretService
from cockpit.workspace.repositories import (
    WebAdminStateRepository,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore


def wire_admin(
    store: SQLiteStore,
    start: Path | None,
) -> dict[str, Any]:
    """Wire admin plane components."""
    web_admin_state_repository = WebAdminStateRepository(store)
    secret_service = SecretService(web_admin_state_repository, start=start)

    # In a full refactor, WebAdminService might be wired here too,
    # but it often needs many other services.
    # For now, we just wire the admin-specific infra.

    return {
        "web_admin_state_repository": web_admin_state_repository,
        "secret_service": secret_service,
    }
