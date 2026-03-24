"""Repository-backed runbook catalog service."""

from __future__ import annotations

from pathlib import Path

from cockpit.domain.models.health import IncidentRecord
from cockpit.domain.models.response import RunbookDefinition
from cockpit.infrastructure.persistence.ops_repositories import RunbookCatalogRepository
from cockpit.infrastructure.runbooks.loader import RunbookLoader
from cockpit.shared.config import runbooks_dir
from cockpit.shared.enums import TargetRiskLevel
from cockpit.shared.utils import utc_now


class RunbookCatalogService:
    """Load, persist, and query declarative runbooks."""

    def __init__(
        self,
        repository: RunbookCatalogRepository,
        *,
        project_root: Path,
    ) -> None:
        self._repository = repository
        self._loader = RunbookLoader(runbooks_dir(project_root))
        self._cache: dict[str, RunbookDefinition] = {}

    def reload(self) -> list[RunbookDefinition]:
        """Reload runbooks from the repository and persist the catalog."""

        definitions = [
            _with_loaded_at(runbook)
            for runbook in self._loader.discover()
        ]
        self._cache = {runbook.catalog_key: runbook for runbook in definitions}
        self._repository.replace_catalog(definitions)
        return list(definitions)

    def list_runbooks(self) -> list[RunbookDefinition]:
        """Return all known runbooks, reloading on first use."""

        if not self._cache:
            self.reload()
        return sorted(
            self._cache.values(),
            key=lambda item: (item.id, item.version),
        )

    def get_runbook(self, runbook_id: str, version: str | None = None) -> RunbookDefinition:
        """Return one runbook definition or raise ``LookupError``."""

        if not self._cache:
            self.reload()
        if version is None:
            matches = [item for item in self._cache.values() if item.id == runbook_id]
            if not matches:
                raise LookupError(f"Runbook '{runbook_id}' was not found.")
            return sorted(matches, key=lambda item: item.version, reverse=True)[0]
        catalog_key = f"{runbook_id}:{version}"
        runbook = self._cache.get(catalog_key)
        if runbook is None:
            raise LookupError(f"Runbook '{runbook_id}' version '{version}' was not found.")
        return runbook

    def match_for_incident(
        self,
        incident: IncidentRecord,
        *,
        risk_level: TargetRiskLevel,
    ) -> list[RunbookDefinition]:
        """Return runbooks whose scope matches the incident context."""

        candidates = []
        for runbook in self.list_runbooks():
            scope = runbook.scope
            component_kinds = {
                str(item)
                for item in scope.get("component_kinds", [])
                if isinstance(item, str)
            }
            severities = {
                str(item)
                for item in scope.get("severities", [])
                if isinstance(item, str)
            }
            risk_levels = {
                str(item)
                for item in scope.get("risk_levels", [])
                if isinstance(item, str)
            }
            if component_kinds and incident.component_kind.value not in component_kinds:
                continue
            if severities and incident.severity.value not in severities:
                continue
            if risk_levels and risk_level.value not in risk_levels:
                continue
            candidates.append(runbook)
        return candidates


def _with_loaded_at(runbook: RunbookDefinition) -> RunbookDefinition:
    return RunbookDefinition(
        id=runbook.id,
        version=runbook.version,
        title=runbook.title,
        description=runbook.description,
        risk_class=runbook.risk_class,
        source_path=runbook.source_path,
        checksum=runbook.checksum,
        scope=dict(runbook.scope),
        tags=tuple(runbook.tags),
        steps=tuple(runbook.steps),
        loaded_at=utc_now(),
    )

