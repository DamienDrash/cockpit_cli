from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.core.dispatch.event_bus import EventBus
from cockpit.ops.services.approval_service import ApprovalService
from cockpit.ops.services.postincident_service import PostIncidentService
from cockpit.ops.services.response_executor_service import (
    ResponseExecutionOutcome,
)
from cockpit.ops.services.response_run_service import ResponseRunService
from cockpit.ops.models.health import IncidentRecord
from cockpit.ops.models.response import (
    RunbookDefinition,
    RunbookStepDefinition,
)
from cockpit.ops.repositories import (
    ActionItemRepository,
    ApprovalDecisionRepository,
    ApprovalRequestRepository,
    ComponentHealthRepository,
    CompensationRunRepository,
    IncidentRepository,
    PostIncidentReviewRepository,
    ResponseArtifactRepository,
    ResponseRunRepository,
    ResponseStepRunRepository,
    ResponseTimelineRepository,
    ReviewFindingRepository,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.infrastructure.runbooks.executors.base import ExecutorResult
from cockpit.core.enums import (
    ApprovalDecisionKind,
    ComponentKind,
    IncidentSeverity,
    IncidentStatus,
    ResponseRunStatus,
    ResponseStepStatus,
    RunbookExecutorKind,
    RunbookRiskClass,
)


class _FakeRunbookCatalogService:
    def __init__(self, runbooks: dict[str, RunbookDefinition]) -> None:
        self._runbooks = runbooks

    def get_runbook(
        self, runbook_id: str, version: str | None = None
    ) -> RunbookDefinition:
        if version is None:
            return self._runbooks[runbook_id]
        return self._runbooks[f"{runbook_id}:{version}"]


class _FakeResponseExecutorService:
    def __init__(self, *, success: bool = True) -> None:
        self.success = success
        self.calls = []

    def execute_step(self, **kwargs) -> ResponseExecutionOutcome:
        self.calls.append(kwargs)
        return ResponseExecutionOutcome(
            result=ExecutorResult(
                success=self.success,
                summary="Step executed." if self.success else "Step failed.",
                payload={"executor": "fake"},
                error_message=None if self.success else "boom",
            ),
        )

    def execute_compensation(self, **kwargs) -> ResponseExecutionOutcome:
        self.calls.append(kwargs)
        return ResponseExecutionOutcome(
            result=ExecutorResult(
                success=True,
                summary="Compensation executed.",
                payload={"executor": "fake"},
            ),
        )


class ResponseRunServiceTests(unittest.TestCase):
    def _build_service(
        self,
        temp_dir: str,
        runbook: RunbookDefinition,
        *,
        executor_success: bool = True,
    ) -> tuple[ResponseRunService, SQLiteStore]:
        store = SQLiteStore(Path(temp_dir) / "cockpit.db")
        bus = EventBus()
        approval_service = ApprovalService(
            event_bus=bus,
            request_repository=ApprovalRequestRepository(store),
            decision_repository=ApprovalDecisionRepository(store),
        )
        postincident_service = PostIncidentService(
            event_bus=bus,
            review_repository=PostIncidentReviewRepository(store),
            finding_repository=ReviewFindingRepository(store),
            action_item_repository=ActionItemRepository(store),
        )
        service = ResponseRunService(
            event_bus=bus,
            incident_repository=IncidentRepository(store),
            component_health_repository=ComponentHealthRepository(store),
            response_run_repository=ResponseRunRepository(store),
            step_run_repository=ResponseStepRunRepository(store),
            approval_request_repository=ApprovalRequestRepository(store),
            artifact_repository=ResponseArtifactRepository(store),
            compensation_repository=CompensationRunRepository(store),
            timeline_repository=ResponseTimelineRepository(store),
            runbook_catalog_service=_FakeRunbookCatalogService(
                {
                    runbook.id: runbook,
                    f"{runbook.id}:{runbook.version}": runbook,
                }
            ),
            response_executor_service=_FakeResponseExecutorService(
                success=executor_success
            ),
            approval_service=approval_service,
            postincident_service=postincident_service,
        )
        IncidentRepository(store).save(
            IncidentRecord(
                id="inc-1",
                component_id="docker:web",
                component_kind=ComponentKind.DOCKER_RUNTIME,
                severity=IncidentSeverity.HIGH,
                status=IncidentStatus.OPEN,
                title="Web unhealthy",
                summary="Health checks are failing.",
            )
        )
        return service, store

    def test_execute_flow_waits_for_approval_then_completes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook = RunbookDefinition(
                id="docker-restart",
                version="1.0.0",
                title="Restart Docker container",
                risk_class=RunbookRiskClass.GUARDED,
                steps=(
                    RunbookStepDefinition(
                        key="restart",
                        title="Restart container",
                        executor_kind=RunbookExecutorKind.MANUAL,
                        operation_kind="mutation",
                        approval_required=True,
                        required_approver_count=1,
                        step_config={"instructions": "Restart the container."},
                    ),
                ),
            )
            service, store = self._build_service(temp_dir, runbook)

            started = service.start_run(
                incident_id="inc-1",
                runbook_id=runbook.id,
                actor="alice",
            )
            waiting = service.execute_current_step(started.id, actor="alice")

            self.assertEqual(waiting.status, ResponseRunStatus.WAITING_APPROVAL)
            pending = service.list_pending_approvals()
            self.assertEqual(len(pending), 1)
            request_id = pending[0]["request"]["id"]

            ready = service.decide_approval(
                request_id,
                approver_ref="bob",
                decision=ApprovalDecisionKind.APPROVE,
            )
            self.assertEqual(ready.status, ResponseRunStatus.READY)

            completed = service.execute_current_step(
                started.id, actor="alice", confirmed=True
            )
            self.assertEqual(completed.status, ResponseRunStatus.COMPLETED)
            self.assertIsNotNone(
                PostIncidentReviewRepository(store).find_for_incident("inc-1")
            )
    def test_requires_confirmation_before_running_mutating_step(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook = RunbookDefinition(
                id="docker-restart",
                version="1.0.0",
                title="Restart Docker container",
                risk_class=RunbookRiskClass.GUARDED,
                steps=(
                    RunbookStepDefinition(
                        key="restart",
                        title="Restart container",
                        executor_kind=RunbookExecutorKind.MANUAL,
                        operation_kind="mutation",
                        requires_confirmation=True,
                        step_config={"instructions": "Restart the container."},
                    ),
                ),
            )
            service, _store = self._build_service(temp_dir, runbook)
            started = service.start_run(
                incident_id="inc-1",
                runbook_id=runbook.id,
                actor="alice",
            )

            waiting = service.execute_current_step(started.id, actor="alice")

            self.assertEqual(waiting.status, ResponseRunStatus.WAITING_OPERATOR)
            step_run = ResponseStepRunRepository(_store).get_by_run_and_index(
                started.id, 0
            )
            self.assertEqual(step_run.status, ResponseStepStatus.WAITING_OPERATOR)


if __name__ == "__main__":
    unittest.main()
