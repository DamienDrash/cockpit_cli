from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.ops.services.guard_policy_service import GuardPolicyService
from cockpit.ops.services.response_executor_service import (
    ResponseExecutorService,
)
from cockpit.ops.models.health import IncidentRecord
from cockpit.ops.models.response import (
    ResponseRun,
    ResponseStepRun,
    RunbookStepDefinition,
)
from cockpit.ops.repositories import GuardDecisionRepository
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.core.enums import (
    ComponentKind,
    IncidentSeverity,
    IncidentStatus,
    ResponseRunStatus,
    ResponseStepStatus,
    RunbookExecutorKind,
    TargetRiskLevel,
)


class _FakeOperationsDiagnosticsService:
    def __init__(self) -> None:
        self.calls = []

    def record_operation(self, **kwargs) -> None:
        self.calls.append(kwargs)


class ResponseExecutorServiceTests(unittest.TestCase):
    def test_manual_step_resolves_placeholders_and_records_operation(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            operations = _FakeOperationsDiagnosticsService()
            service = ResponseExecutorService(
                guard_policy_service=GuardPolicyService(GuardDecisionRepository(store)),
                operations_diagnostics_service=operations,
                http_adapter=object(),
                docker_adapter=object(),
                database_adapter=object(),
                datasource_service=object(),
            )

            outcome = service.execute_step(
                command_id="cmd-1",
                response_run=ResponseRun(
                    id="rrn-1",
                    incident_id="inc-1",
                    runbook_id="manual-note",
                    runbook_version="1.0.0",
                    status=ResponseRunStatus.RUNNING,
                    risk_level=TargetRiskLevel.DEV,
                ),
                step_run=ResponseStepRun(
                    id="rsp-1",
                    response_run_id="rrn-1",
                    step_key="note",
                    step_index=0,
                    executor_kind=RunbookExecutorKind.MANUAL,
                    status=ResponseStepStatus.RUNNING,
                ),
                step_definition=RunbookStepDefinition(
                    key="note",
                    title="Capture operator note",
                    executor_kind=RunbookExecutorKind.MANUAL,
                    operation_kind="read",
                    step_config={"instructions": "Investigate incident {incident.id}"},
                ),
                incident=IncidentRecord(
                    id="inc-1",
                    component_id="docker:web",
                    component_kind=ComponentKind.DOCKER_RUNTIME,
                    severity=IncidentSeverity.HIGH,
                    status=IncidentStatus.OPEN,
                    title="Web unhealthy",
                    summary="Container failed health checks.",
                ),
                actor="alice",
                confirmed=True,
                elevated_mode=False,
                notes="Captured evidence",
            )

            self.assertTrue(outcome.result.success)
            self.assertEqual(
                outcome.result.payload["instructions"], "Investigate incident inc-1"
            )
            self.assertEqual(len(operations.calls), 1)

    def test_shell_destructive_step_is_blocked_by_guard_policy(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            operations = _FakeOperationsDiagnosticsService()
            service = ResponseExecutorService(
                guard_policy_service=GuardPolicyService(GuardDecisionRepository(store)),
                operations_diagnostics_service=operations,
                http_adapter=object(),
                docker_adapter=object(),
                database_adapter=object(),
                datasource_service=object(),
            )

            outcome = service.execute_step(
                command_id="cmd-2",
                response_run=ResponseRun(
                    id="rrn-1",
                    incident_id="inc-1",
                    runbook_id="shell-cleanup",
                    runbook_version="1.0.0",
                    status=ResponseRunStatus.RUNNING,
                    risk_level=TargetRiskLevel.PROD,
                ),
                step_run=ResponseStepRun(
                    id="rsp-1",
                    response_run_id="rrn-1",
                    step_key="cleanup",
                    step_index=0,
                    executor_kind=RunbookExecutorKind.SHELL,
                    status=ResponseStepStatus.RUNNING,
                ),
                step_definition=RunbookStepDefinition(
                    key="cleanup",
                    title="Dangerous cleanup",
                    executor_kind=RunbookExecutorKind.SHELL,
                    operation_kind="destructive",
                    step_config={"command": "rm -rf /srv/app/tmp"},
                ),
                incident=IncidentRecord(
                    id="inc-1",
                    component_id="docker:web",
                    component_kind=ComponentKind.DOCKER_RUNTIME,
                    severity=IncidentSeverity.HIGH,
                    status=IncidentStatus.OPEN,
                    title="Web unhealthy",
                    summary="Container failed health checks.",
                ),
                actor="alice",
                confirmed=False,
                elevated_mode=False,
            )

            self.assertTrue(outcome.blocked)
            self.assertFalse(outcome.result.success)
            self.assertEqual(operations.calls, [])


if __name__ == "__main__":
    unittest.main()
