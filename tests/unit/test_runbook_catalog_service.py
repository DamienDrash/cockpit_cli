from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.application.services.runbook_catalog_service import RunbookCatalogService
from cockpit.domain.models.health import IncidentRecord
from cockpit.infrastructure.persistence.ops_repositories import RunbookCatalogRepository
from cockpit.infrastructure.persistence.sqlite_store import SQLiteStore
from cockpit.shared.enums import ComponentKind, IncidentSeverity, IncidentStatus, TargetRiskLevel


class RunbookCatalogServiceTests(unittest.TestCase):
    def test_reload_persists_and_matches_runbooks(self) -> None:
        with TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            runbooks_root = project_root / "config" / "runbooks"
            runbooks_root.mkdir(parents=True)
            (runbooks_root / "docker-v1.yaml").write_text(
                """
id: docker-container-unhealthy
version: 1.0.0
title: Recover unhealthy Docker container
risk_class: guarded
scope:
  component_kinds: [docker_runtime]
  severities: [high, critical]
  risk_levels: [stage, prod]
steps:
  - key: restart
    title: Restart container
    executor_kind: manual
    operation_kind: mutation
    step_config:
      instructions: Restart the affected container.
""".strip(),
                encoding="utf-8",
            )
            (runbooks_root / "docker-v2.yaml").write_text(
                """
id: docker-container-unhealthy
version: 2.0.0
title: Recover unhealthy Docker container
risk_class: guarded
scope:
  component_kinds: [docker_runtime]
  severities: [high, critical]
  risk_levels: [prod]
steps:
  - key: restart
    title: Restart container
    executor_kind: manual
    operation_kind: mutation
    step_config:
      instructions: Restart and verify the container.
""".strip(),
                encoding="utf-8",
            )
            (runbooks_root / "db-only.yaml").write_text(
                """
id: db-check
version: 1.0.0
title: Check database reachability
risk_class: guarded
scope:
  component_kinds: [datasource]
steps:
  - key: inspect
    title: Inspect datasource
    executor_kind: manual
    operation_kind: read
    step_config:
      instructions: Inspect datasource reachability.
""".strip(),
                encoding="utf-8",
            )
            store = SQLiteStore(project_root / "cockpit.db")
            service = RunbookCatalogService(
                RunbookCatalogRepository(store),
                project_root=project_root,
            )

            definitions = service.reload()

            self.assertEqual(len(definitions), 3)
            latest = service.get_runbook("docker-container-unhealthy")
            self.assertEqual(latest.version, "2.0.0")

            incident = IncidentRecord(
                id="inc-1",
                component_id="docker:web",
                component_kind=ComponentKind.DOCKER_RUNTIME,
                severity=IncidentSeverity.HIGH,
                status=IncidentStatus.OPEN,
                title="Web unhealthy",
                summary="Container health check failed.",
            )
            matches = service.match_for_incident(
                incident,
                risk_level=TargetRiskLevel.PROD,
            )

            self.assertEqual([item.version for item in matches], ["1.0.0", "2.0.0"])
            self.assertEqual(
                len(RunbookCatalogRepository(store).list_all()),
                3,
            )


if __name__ == "__main__":
    unittest.main()
