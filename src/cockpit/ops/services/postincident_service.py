"""Structured post-incident review service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from cockpit.core.dispatch.event_bus import EventBus
from cockpit.ops.events.response import (
    ActionItemStatusChanged,
    PostIncidentReviewStatusChanged,
)
from cockpit.ops.models.review import ActionItem, PostIncidentReview, ReviewFinding
from cockpit.ops.repositories import (
    ActionItemRepository,
    PostIncidentReviewRepository,
    ReviewFindingRepository,
)
from cockpit.core.enums import (
    ActionItemStatus,
    ClosureQuality,
    IncidentSeverity,
    PostIncidentReviewStatus,
    ReviewFindingCategory,
)
from cockpit.core.utils import make_id, utc_now


@dataclass(slots=True, frozen=True)
class PostIncidentReviewDetail:
    """Structured review detail payload."""

    review: PostIncidentReview
    findings: tuple[ReviewFinding, ...]
    action_items: tuple[ActionItem, ...]


class PostIncidentService:
    """Manage structured post-incident reviews and action items."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        review_repository: PostIncidentReviewRepository,
        finding_repository: ReviewFindingRepository,
        action_item_repository: ActionItemRepository,
    ) -> None:
        self._event_bus = event_bus
        self._review_repository = review_repository
        self._finding_repository = finding_repository
        self._action_item_repository = action_item_repository

    def list_reviews(self, *, limit: int = 50) -> list[PostIncidentReview]:
        return self._review_repository.list_recent(limit=limit)

    def list_open_action_items(self, *, limit: int = 50) -> list[ActionItem]:
        return self._action_item_repository.list_open(limit=limit)
    def ensure_review(
        self,
        *,
        incident_id: str,
        response_run_id: str,
        owner_ref: str,
        summary: str | None = None,
    ) -> PostIncidentReview:
        existing = self._review_repository.find_for_incident(incident_id)
        if existing is not None:
            return existing

        review = PostIncidentReview(
            id=make_id("rvw"),
            incident_id=incident_id,
            response_run_id=response_run_id,
            status=PostIncidentReviewStatus.OPEN,
            owner_ref=owner_ref,
            opened_at=utc_now(),
        )
        self._review_repository.save(review)
        self._event_bus.publish(
            PostIncidentReviewStatusChanged(
                review_id=review.id,
                incident_id=incident_id,
                previous_status=None,
                new_status=review.status,
                message="Post-incident review opened.",
            )
        )
        return review

    def get_review_detail(self, review_id: str) -> PostIncidentReviewDetail | None:
        review = self._review_repository.get(review_id)
        if review is None:
            return None
        return PostIncidentReviewDetail(
            review=review,
            findings=tuple(self._finding_repository.list_for_review(review_id)),
            action_items=tuple(self._action_item_repository.list_for_review(review_id)),
        )

    def get_review_detail_for_incident(
        self, incident_id: str
    ) -> PostIncidentReviewDetail | None:
        review = self._review_repository.find_for_incident(incident_id)
        if review is None:
            return None
        return self.get_review_detail(review.id)

    def add_finding(
        self,
        review_id: str,
        *,
        category: ReviewFindingCategory,
        severity: IncidentSeverity,
        title: str,
        detail: str,
    ) -> ReviewFinding:
        self._require_review(review_id)
        finding = ReviewFinding(
            id=make_id("rfn"),
            review_id=review_id,
            category=category,
            severity=severity,
            title=title.strip(),
            detail=detail.strip(),
            created_at=utc_now(),
        )
        self._finding_repository.save(finding)
        return finding

    def add_action_item(
        self,
        review_id: str,
        *,
        owner_ref: str | None,
        title: str,
        detail: str,
        due_at: datetime | None = None,
    ) -> ActionItem:
        review = self._require_review(review_id)
        item = ActionItem(
            id=make_id("act"),
            review_id=review.id,
            owner_ref=owner_ref,
            status=ActionItemStatus.OPEN,
            title=title.strip(),
            detail=detail.strip(),
            due_at=due_at,
            created_at=utc_now(),
        )
        self._action_item_repository.save(item)
        self._event_bus.publish(
            ActionItemStatusChanged(
                action_item_id=item.id,
                review_id=review.id,
                incident_id=review.incident_id,
                previous_status=None,
                new_status=item.status,
                message="Action item created.",
            )
        )
        return item

    def set_action_item_status(
        self,
        action_item_id: str,
        *,
        status: ActionItemStatus,
    ) -> ActionItem:
        item = self._require_action_item(action_item_id)
        review = self._require_review(item.review_id)
        previous_status = item.status
        item.status = status
        if status is ActionItemStatus.CLOSED:
            item.closed_at = utc_now()
        self._action_item_repository.save(item)
        self._event_bus.publish(
            ActionItemStatusChanged(
                action_item_id=item.id,
                review_id=review.id,
                incident_id=review.incident_id,
                previous_status=previous_status,
                new_status=item.status,
                message=f"Action item {item.id} is now {item.status.value}.",
            )
        )
        return item

    def complete_review(
        self,
        review_id: str,
        *,
        summary: str,
        root_cause: str,
        closure_quality: ClosureQuality,
    ) -> PostIncidentReview:
        review = self._require_review(review_id)
        previous_status = review.status
        review.status = PostIncidentReviewStatus.COMPLETED
        review.summary = summary.strip()
        review.root_cause = root_cause.strip()
        review.closure_quality = closure_quality
        review.completed_at = utc_now()
        self._review_repository.save(review)
        self._event_bus.publish(
            PostIncidentReviewStatusChanged(
                review_id=review.id,
                incident_id=review.incident_id,
                previous_status=previous_status,
                new_status=review.status,
                message="Post-incident review completed.",
            )
        )
        return review

    def _require_review(self, review_id: str) -> PostIncidentReview:
        review = self._review_repository.get(review_id)
        if review is None:
            raise LookupError(f"Review '{review_id}' was not found.")
        return review

    def _require_action_item(self, action_item_id: str) -> ActionItem:
        item = self._action_item_repository.get(action_item_id)
        if item is None:
            raise LookupError(f"Action item '{action_item_id}' was not found.")
        return item
