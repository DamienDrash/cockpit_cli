"""Stage 4 response and post-incident domain events."""

from __future__ import annotations

from dataclasses import dataclass

from cockpit.core.events.base import DomainEvent
from cockpit.core.enums import (
    ActionItemStatus,
    ApprovalRequestStatus,
    CompensationStatus,
    PostIncidentReviewStatus,
    ResponseRunStatus,
    ResponseStepStatus,
)


@dataclass(slots=True, kw_only=True)
class ResponseRunCreated(DomainEvent):
    response_run_id: str
    incident_id: str
    runbook_id: str
    runbook_version: str


@dataclass(slots=True, kw_only=True)
class ResponseRunStatusChanged(DomainEvent):
    response_run_id: str
    incident_id: str
    previous_status: ResponseRunStatus | None = None
    new_status: ResponseRunStatus
    message: str


@dataclass(slots=True, kw_only=True)
class ResponseStepStatusChanged(DomainEvent):
    response_run_id: str
    step_run_id: str
    incident_id: str
    step_key: str
    previous_status: ResponseStepStatus | None = None
    new_status: ResponseStepStatus
    message: str


@dataclass(slots=True, kw_only=True)
class ApprovalRequested(DomainEvent):
    approval_request_id: str
    response_run_id: str
    step_run_id: str
    incident_id: str
    required_approver_count: int


@dataclass(slots=True, kw_only=True)
class ApprovalResolved(DomainEvent):
    approval_request_id: str
    response_run_id: str
    step_run_id: str
    incident_id: str
    status: ApprovalRequestStatus
    message: str


@dataclass(slots=True, kw_only=True)
class CompensationStatusChanged(DomainEvent):
    compensation_run_id: str
    response_run_id: str
    step_run_id: str
    incident_id: str
    status: CompensationStatus
    message: str


@dataclass(slots=True, kw_only=True)
class PostIncidentReviewStatusChanged(DomainEvent):
    review_id: str
    incident_id: str
    previous_status: PostIncidentReviewStatus | None = None
    new_status: PostIncidentReviewStatus
    message: str


@dataclass(slots=True, kw_only=True)
class ActionItemStatusChanged(DomainEvent):
    action_item_id: str
    review_id: str
    incident_id: str
    previous_status: ActionItemStatus | None = None
    new_status: ActionItemStatus
    message: str
