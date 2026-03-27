"""Structured post-incident review models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from cockpit.core.enums import (
    ActionItemStatus,
    ClosureQuality,
    IncidentSeverity,
    PostIncidentReviewStatus,
    ReviewFindingCategory,
)
from cockpit.core.utils import serialize_contract


@dataclass(slots=True)
class PostIncidentReview:
    """Structured review header for one incident and optional response run."""

    id: str
    incident_id: str
    response_run_id: str | None = None
    status: PostIncidentReviewStatus = PostIncidentReviewStatus.OPEN
    owner_ref: str | None = None
    opened_at: datetime | None = None
    completed_at: datetime | None = None
    summary: str | None = None
    root_cause: str | None = None
    closure_quality: ClosureQuality = ClosureQuality.INCOMPLETE
    payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class ReviewFinding:
    """Structured review finding or contributing factor."""

    id: str
    review_id: str
    category: ReviewFindingCategory
    severity: IncidentSeverity
    title: str
    detail: str
    created_at: datetime | None = None
    payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class ActionItem:
    """Follow-up work item created from a review."""

    id: str
    review_id: str
    owner_ref: str | None = None
    status: ActionItemStatus = ActionItemStatus.OPEN
    title: str = ""
    detail: str = ""
    due_at: datetime | None = None
    created_at: datetime | None = None
    closed_at: datetime | None = None
    payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)
