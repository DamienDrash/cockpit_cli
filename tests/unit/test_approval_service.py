from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.core.dispatch.event_bus import EventBus
from cockpit.ops.services.approval_service import ApprovalService
from cockpit.ops.models.health import IncidentRecord
from cockpit.ops.models.response import ResponseRun, ResponseStepRun
from cockpit.ops.repositories import (
    ApprovalDecisionRepository,
    ApprovalRequestRepository,
    IncidentRepository,
    ResponseRunRepository,
    ResponseStepRunRepository,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.core.utils import make_id, utc_now
from cockpit.core.enums import (
    ApprovalDecisionKind,
    ApprovalRequestStatus,
    ComponentKind,
    IncidentSeverity,
    IncidentStatus,
    ResponseRunStatus,
    ResponseStepStatus,
    RunbookExecutorKind,
    TargetRiskLevel,
)


class _FakeNotificationService:
    def __init__(self) -> None:
        self.candidates = []

    def send(self, candidate) -> None:
        self.candidates.append(candidate)


class ApprovalServiceTests(unittest.TestCase):
    def test_ensure_request_persists_and_notifies(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            notifications = _FakeNotificationService()
            service = ApprovalService(
                event_bus=EventBus(),
                request_repository=ApprovalRequestRepository(store),
                decision_repository=ApprovalDecisionRepository(store),
                notification_service=notifications,
            )
            IncidentRepository(store).save(
                IncidentRecord(
                    id="inc-1",
                    component_id="docker:web",
                    component_kind=ComponentKind.DOCKER_RUNTIME,
                    severity=IncidentSeverity.HIGH,
                    status=IncidentStatus.OPEN,
                    title="Web unhealthy",
                    summary="Health checks failed.",
                )
            )
            response_run = ResponseRun(
                id="rrn-1",
                incident_id="inc-1",
                runbook_id="docker-restart",
                runbook_version="1.0.0",
                status=ResponseRunStatus.WAITING_APPROVAL,
                risk_level=TargetRiskLevel.PROD,
            )
            step_run = ResponseStepRun(
                id="rsp-1",
                response_run_id="rrn-1",
                step_key="restart",
                step_index=0,
                executor_kind=RunbookExecutorKind.DOCKER,
                status=ResponseStepStatus.WAITING_APPROVAL,
            )
            ResponseRunRepository(store).save(response_run)
            ResponseStepRunRepository(store).save(step_run)

            request = service.ensure_request(
                response_run=response_run,
                step_run=step_run,
                requested_by="alice",
                required_approver_count=2,
                required_roles=("lead",),
                allow_self_approval=False,
                expires_after_seconds=600,
                reason="Production restart requires approval.",
            )

            self.assertEqual(request.status, ApprovalRequestStatus.PENDING)
            self.assertEqual(len(service.list_pending()), 1)
            self.assertEqual(len(notifications.candidates), 1)

    def test_decision_threshold_and_expiry(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            service = ApprovalService(
                event_bus=EventBus(),
                request_repository=ApprovalRequestRepository(store),
                decision_repository=ApprovalDecisionRepository(store),
            )
            IncidentRepository(store).save(
                IncidentRecord(
                    id="inc-1",
                    component_id="docker:web",
                    component_kind=ComponentKind.DOCKER_RUNTIME,
                    severity=IncidentSeverity.HIGH,
                    status=IncidentStatus.OPEN,
                    title="Web unhealthy",
                    summary="Health checks failed.",
                )
            )
            response_run = ResponseRun(
                id="rrn-1",
                incident_id="inc-1",
                runbook_id="docker-restart",
                runbook_version="1.0.0",
                status=ResponseRunStatus.WAITING_APPROVAL,
                risk_level=TargetRiskLevel.PROD,
            )
            step_run = ResponseStepRun(
                id="rsp-1",
                response_run_id="rrn-1",
                step_key="restart",
                step_index=0,
                executor_kind=RunbookExecutorKind.DOCKER,
                status=ResponseStepStatus.WAITING_APPROVAL,
            )
            ResponseRunRepository(store).save(response_run)
            ResponseStepRunRepository(store).save(step_run)
            request = service.ensure_request(
                response_run=response_run,
                step_run=step_run,
                requested_by="alice",
                required_approver_count=2,
                required_roles=("lead",),
                allow_self_approval=False,
                expires_after_seconds=60,
                reason="Need two-person approval.",
            )

            with self.assertRaises(ValueError):
                service.decide(
                    request.id,
                    approver_ref="alice",
                    decision=ApprovalDecisionKind.APPROVE,
                )

            pending = service.decide(
                request.id,
                approver_ref="bob",
                decision=ApprovalDecisionKind.APPROVE,
            )
            self.assertEqual(pending.status, ApprovalRequestStatus.PENDING)

            approved = service.decide(
                request.id,
                approver_ref="carol",
                decision=ApprovalDecisionKind.APPROVE,
            )
            self.assertEqual(approved.status, ApprovalRequestStatus.APPROVED)

            IncidentRepository(store).save(
                IncidentRecord(
                    id="inc-2",
                    component_id="db:main",
                    component_kind=ComponentKind.DATASOURCE,
                    severity=IncidentSeverity.HIGH,
                    status=IncidentStatus.OPEN,
                    title="DB unavailable",
                    summary="Database needs verification.",
                )
            )
            response_run_two = ResponseRun(
                id="rrn-2",
                incident_id="inc-2",
                runbook_id="db-check",
                runbook_version="1.0.0",
                status=ResponseRunStatus.WAITING_APPROVAL,
                risk_level=TargetRiskLevel.STAGE,
            )
            step_run_two = ResponseStepRun(
                id="rsp-2",
                response_run_id="rrn-2",
                step_key="verify",
                step_index=0,
                executor_kind=RunbookExecutorKind.MANUAL,
                status=ResponseStepStatus.WAITING_APPROVAL,
            )
            ResponseRunRepository(store).save(response_run_two)
            ResponseStepRunRepository(store).save(step_run_two)
            expiring = service.ensure_request(
                response_run=response_run_two,
                step_run=step_run_two,
                requested_by="dana",
                required_approver_count=1,
                required_roles=(),
                allow_self_approval=True,
                expires_after_seconds=1,
                reason="Confirm remediation.",
            )

            expired = service.expire_pending(
                now=utc_now() + timedelta(seconds=2),
            )
            self.assertIn(expiring.id, {item.id for item in expired})
            self.assertEqual(
                service.get_detail(expiring.id).request.status,
                ApprovalRequestStatus.EXPIRED,
            )


if __name__ == "__main__":
    unittest.main()
