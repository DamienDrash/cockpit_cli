from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.domain.models.response import (
    ApprovalDecision,
    ApprovalRequest,
    CompensationRun,
    ResponseArtifact,
    ResponseRun,
    ResponseStepRun,
    RunbookDefinition,
    RunbookStepDefinition,
)
from cockpit.domain.models.health import IncidentRecord
from cockpit.domain.models.review import ActionItem, PostIncidentReview, ReviewFinding
from cockpit.infrastructure.persistence.ops_repositories import (
    ActionItemRepository,
    ApprovalDecisionRepository,
    ApprovalRequestRepository,
    CompensationRunRepository,
    IncidentRepository,
    PostIncidentReviewRepository,
    ResponseArtifactRepository,
    ResponseRunRepository,
    ResponseStepRunRepository,
    ResponseTimelineRepository,
    ReviewFindingRepository,
    RunbookCatalogRepository,
)
from cockpit.infrastructure.persistence.sqlite_store import SQLiteStore
from cockpit.shared.enums import (
    ActionItemStatus,
    ApprovalDecisionKind,
    ApprovalRequestStatus,
    ComponentKind,
    ClosureQuality,
    CompensationStatus,
    IncidentSeverity,
    IncidentStatus,
    PostIncidentReviewStatus,
    ReviewFindingCategory,
    ResponseRunStatus,
    ResponseStepStatus,
    RunbookExecutorKind,
    RunbookRiskClass,
    TargetRiskLevel,
)


class Stage4OpsRepositoriesTests(unittest.TestCase):
    def test_round_trips_runbooks_response_runs_and_reviews(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            runbook_repo = RunbookCatalogRepository(store)
            run_repo = ResponseRunRepository(store)
            step_repo = ResponseStepRunRepository(store)
            approval_repo = ApprovalRequestRepository(store)
            decision_repo = ApprovalDecisionRepository(store)
            artifact_repo = ResponseArtifactRepository(store)
            compensation_repo = CompensationRunRepository(store)
            timeline_repo = ResponseTimelineRepository(store)
            review_repo = PostIncidentReviewRepository(store)
            finding_repo = ReviewFindingRepository(store)
            action_item_repo = ActionItemRepository(store)

            runbook_repo.save(
                RunbookDefinition(
                    id="docker-restart",
                    version="1.0.0",
                    title="Restart Docker container",
                    risk_class=RunbookRiskClass.GUARDED,
                    steps=(
                        RunbookStepDefinition(
                            key="restart",
                            title="Restart container",
                            executor_kind=RunbookExecutorKind.DOCKER,
                            operation_kind="mutation",
                            step_config={"operation": "restart", "container_id": "web"},
                        ),
                    ),
                )
            )
            IncidentRepository(store).save(
                IncidentRecord(
                    id="inc-1",
                    component_id="docker:web",
                    component_kind=ComponentKind.DOCKER_RUNTIME,
                    severity=IncidentSeverity.HIGH,
                    status=IncidentStatus.OPEN,
                    title="Web unhealthy",
                    summary="Container restart loop detected",
                )
            )
            run_repo.save(
                ResponseRun(
                    id="rrn-1",
                    incident_id="inc-1",
                    runbook_id="docker-restart",
                    runbook_version="1.0.0",
                    status=ResponseRunStatus.RUNNING,
                    current_step_index=0,
                    risk_level=TargetRiskLevel.PROD,
                    started_by="alice",
                    started_at=datetime(2026, 3, 24, 10, 0, tzinfo=UTC),
                    updated_at=datetime(2026, 3, 24, 10, 1, tzinfo=UTC),
                )
            )
            step_repo.save(
                ResponseStepRun(
                    id="rsp-1",
                    response_run_id="rrn-1",
                    step_key="restart",
                    step_index=0,
                    executor_kind=RunbookExecutorKind.DOCKER,
                    status=ResponseStepStatus.WAITING_APPROVAL,
                )
            )
            approval_repo.save(
                ApprovalRequest(
                    id="apr-1",
                    response_run_id="rrn-1",
                    step_run_id="rsp-1",
                    status=ApprovalRequestStatus.PENDING,
                    requested_by="alice",
                    required_approver_count=1,
                    reason="Restart requires approval.",
                    created_at=datetime(2026, 3, 24, 10, 1, tzinfo=UTC),
                    payload={"incident_id": "inc-1"},
                )
            )
            decision_repo.save(
                ApprovalDecision(
                    id="apd-1",
                    approval_request_id="apr-1",
                    approver_ref="bob",
                    decision=ApprovalDecisionKind.APPROVE,
                    created_at=datetime(2026, 3, 24, 10, 2, tzinfo=UTC),
                )
            )
            artifact_repo.save(
                ResponseArtifact(
                    id="art-1",
                    response_run_id="rrn-1",
                    step_run_id="rsp-1",
                    artifact_kind="docker_inspect",
                    label="Inspect output",
                    summary="Container restarted",
                    created_at=datetime(2026, 3, 24, 10, 3, tzinfo=UTC),
                )
            )
            compensation_repo.save(
                CompensationRun(
                    id="cmp-1",
                    response_run_id="rrn-1",
                    step_run_id="rsp-1",
                    status=CompensationStatus.COMPLETED,
                    started_at=datetime(2026, 3, 24, 10, 4, tzinfo=UTC),
                    finished_at=datetime(2026, 3, 24, 10, 5, tzinfo=UTC),
                    summary="Rollback complete",
                )
            )
            timeline_repo.add_entry(
                response_run_id="rrn-1",
                incident_id="inc-1",
                event_type="step_succeeded",
                message="Restart completed.",
                payload={"step_key": "restart"},
            )
            review_repo.save(
                PostIncidentReview(
                    id="rvw-1",
                    incident_id="inc-1",
                    response_run_id="rrn-1",
                    status=PostIncidentReviewStatus.OPEN,
                    owner_ref="alice",
                    opened_at=datetime(2026, 3, 24, 10, 6, tzinfo=UTC),
                    closure_quality=ClosureQuality.PARTIAL,
                )
            )
            finding_repo.save(
                ReviewFinding(
                    id="rfn-1",
                    review_id="rvw-1",
                    category=ReviewFindingCategory.OBSERVATION,
                    severity=IncidentSeverity.HIGH,
                    title="Improve probe automation",
                    detail="The restart succeeded but verification was manual.",
                    created_at=datetime(2026, 3, 24, 10, 7, tzinfo=UTC),
                )
            )
            action_item_repo.save(
                ActionItem(
                    id="act-1",
                    review_id="rvw-1",
                    owner_ref="bob",
                    status=ActionItemStatus.OPEN,
                    title="Automate verification",
                    detail="Add automated post-restart verification.",
                    created_at=datetime(2026, 3, 24, 10, 8, tzinfo=UTC),
                )
            )

            self.assertEqual(runbook_repo.get("docker-restart").title, "Restart Docker container")
            self.assertEqual(run_repo.get_active_for_incident("inc-1").id, "rrn-1")
            self.assertEqual(step_repo.get_by_run_and_index("rrn-1", 0).step_key, "restart")
            self.assertEqual(approval_repo.get_active_for_step("rsp-1").id, "apr-1")
            self.assertEqual(len(decision_repo.list_for_request("apr-1")), 1)
            self.assertEqual(len(artifact_repo.list_for_run("rrn-1")), 1)
            self.assertEqual(compensation_repo.latest_for_step("rsp-1").id, "cmp-1")
            self.assertEqual(len(timeline_repo.list_for_run("rrn-1")), 1)
            self.assertEqual(review_repo.get_for_incident("inc-1").id, "rvw-1")
            self.assertEqual(len(finding_repo.list_for_review("rvw-1")), 1)
            self.assertEqual(len(action_item_repo.list_for_review("rvw-1")), 1)


if __name__ == "__main__":
    unittest.main()
