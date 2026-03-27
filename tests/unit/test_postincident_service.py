from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.core.dispatch.event_bus import EventBus
from cockpit.ops.services.postincident_service import PostIncidentService
from cockpit.ops.models.health import IncidentRecord
from cockpit.ops.models.response import ResponseRun
from cockpit.ops.repositories import (
    ActionItemRepository,
    IncidentRepository,
    PostIncidentReviewRepository,
    ResponseRunRepository,
    ReviewFindingRepository,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.core.enums import (
    ActionItemStatus,
    ComponentKind,
    ClosureQuality,
    IncidentSeverity,
    IncidentStatus,
    ReviewFindingCategory,
    ResponseRunStatus,
    TargetRiskLevel,
)


class PostIncidentServiceTests(unittest.TestCase):
    def test_review_lifecycle(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            service = PostIncidentService(
                event_bus=EventBus(),
                review_repository=PostIncidentReviewRepository(store),
                finding_repository=ReviewFindingRepository(store),
                action_item_repository=ActionItemRepository(store),
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
            ResponseRunRepository(store).save(
                ResponseRun(
                    id="rrn-1",
                    incident_id="inc-1",
                    runbook_id="docker-restart",
                    runbook_version="1.0.0",
                    status=ResponseRunStatus.COMPLETED,
                    risk_level=TargetRiskLevel.PROD,
                )
            )

            review = service.ensure_review(
                incident_id="inc-1",
                response_run_id="rrn-1",
                owner_ref="alice",
            )
            finding = service.add_finding(
                review.id,
                category=ReviewFindingCategory.OBSERVATION,
                severity=IncidentSeverity.HIGH,
                title="Missed alert threshold",
                detail="Threshold was too permissive.",
            )
            action_item = service.add_action_item(
                review.id,
                owner_ref="bob",
                title="Tune threshold",
                detail="Tighten the unhealthy threshold.",
            )
            updated_action_item = service.set_action_item_status(
                action_item.id,
                status=ActionItemStatus.CLOSED,
            )
            completed = service.complete_review(
                review.id,
                summary="Incident handled successfully.",
                root_cause="Threshold configuration drift.",
                closure_quality=ClosureQuality.COMPLETE,
            )
            detail = service.get_review_detail(review.id)

            self.assertEqual(finding.review_id, review.id)
            self.assertEqual(updated_action_item.status, ActionItemStatus.CLOSED)
            self.assertEqual(completed.summary, "Incident handled successfully.")
            self.assertEqual(len(detail.findings), 1)
            self.assertEqual(len(detail.action_items), 1)


if __name__ == "__main__":
    unittest.main()
