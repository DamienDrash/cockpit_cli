"""Explicit approval orchestration for Stage 4 response steps."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.services.notification_service import NotificationService
from cockpit.domain.events.response_events import ApprovalRequested, ApprovalResolved
from cockpit.domain.models.notifications import NotificationCandidate
from cockpit.domain.models.response import ApprovalDecision, ApprovalRequest, ResponseRun, ResponseStepRun
from cockpit.infrastructure.persistence.ops_repositories import (
    ApprovalDecisionRepository,
    ApprovalRequestRepository,
)
from cockpit.shared.enums import (
    ApprovalDecisionKind,
    ApprovalRequestStatus,
    IncidentSeverity,
    NotificationEventClass,
)
from cockpit.shared.utils import make_id, utc_now


@dataclass(slots=True, frozen=True)
class ApprovalDetail:
    """Structured approval detail payload."""

    request: ApprovalRequest
    decisions: tuple[ApprovalDecision, ...]


class ApprovalService:
    """Persist, evaluate, and expire step approval requests."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        request_repository: ApprovalRequestRepository,
        decision_repository: ApprovalDecisionRepository,
        notification_service: NotificationService | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._request_repository = request_repository
        self._decision_repository = decision_repository
        self._notification_service = notification_service

    def list_pending(self, *, limit: int = 50) -> list[ApprovalRequest]:
        return self._request_repository.list_pending(limit=limit)

    def get_detail(self, request_id: str) -> ApprovalDetail | None:
        request = self._request_repository.get(request_id)
        if request is None:
            return None
        return ApprovalDetail(
            request=request,
            decisions=tuple(self._decision_repository.list_for_request(request_id)),
        )

    def ensure_request(
        self,
        *,
        response_run: ResponseRun,
        step_run: ResponseStepRun,
        requested_by: str,
        required_approver_count: int,
        required_roles: tuple[str, ...],
        allow_self_approval: bool,
        expires_after_seconds: int | None,
        reason: str,
    ) -> ApprovalRequest:
        existing = self._request_repository.get_active_for_step(step_run.id)
        if existing is not None:
            return existing
        request = ApprovalRequest(
            id=make_id("apr"),
            response_run_id=response_run.id,
            step_run_id=step_run.id,
            status=ApprovalRequestStatus.PENDING,
            requested_by=requested_by,
            required_approver_count=max(1, int(required_approver_count or 1)),
            required_roles=tuple(required_roles),
            allow_self_approval=allow_self_approval,
            reason=reason,
            expires_at=(
                utc_now() + timedelta(seconds=int(expires_after_seconds))
                if expires_after_seconds is not None
                else None
            ),
            created_at=utc_now(),
            payload={"incident_id": response_run.incident_id},
        )
        self._request_repository.save(request)
        self._event_bus.publish(
            ApprovalRequested(
                approval_request_id=request.id,
                response_run_id=response_run.id,
                step_run_id=step_run.id,
                incident_id=response_run.incident_id,
                required_approver_count=request.required_approver_count,
            )
        )
        if self._notification_service is not None:
            self._notification_service.send(
                NotificationCandidate(
                    event_class=NotificationEventClass.APPROVAL_REQUESTED,
                    severity=IncidentSeverity.HIGH,
                    risk_level=response_run.risk_level,
                    title="Approval requested",
                    summary=reason,
                    dedupe_key=f"approval:{request.id}",
                    incident_id=response_run.incident_id,
                    component_id=f"response:{response_run.id}",
                    source_event_id=request.id,
                    payload={
                        "approval_request_id": request.id,
                        "response_run_id": response_run.id,
                        "step_run_id": step_run.id,
                    },
                )
            )
        return request

    def decide(
        self,
        request_id: str,
        *,
        approver_ref: str,
        decision: ApprovalDecisionKind,
        comment: str | None = None,
    ) -> ApprovalRequest:
        request = self._require_request(request_id)
        if request.status is not ApprovalRequestStatus.PENDING:
            raise ValueError("Only pending approval requests can be decided.")
        if not request.allow_self_approval and request.requested_by == approver_ref:
            raise ValueError("Self-approval is not permitted for this request.")
        existing = {
            item.approver_ref: item
            for item in self._decision_repository.list_for_request(request_id)
        }
        if approver_ref in existing:
            raise ValueError(f"Approver '{approver_ref}' has already decided this request.")
        decision_record = ApprovalDecision(
            id=make_id("apd"),
            approval_request_id=request.id,
            approver_ref=approver_ref,
            decision=decision,
            comment=comment,
            created_at=utc_now(),
        )
        self._decision_repository.save(decision_record)
        decisions = self._decision_repository.list_for_request(request_id)
        previous_status = request.status
        if any(item.decision is ApprovalDecisionKind.REJECT for item in decisions):
            request.status = ApprovalRequestStatus.REJECTED
            request.resolved_at = utc_now()
        else:
            unique_approvers = {
                item.approver_ref
                for item in decisions
                if item.decision is ApprovalDecisionKind.APPROVE
            }
            if len(unique_approvers) >= request.required_approver_count:
                request.status = ApprovalRequestStatus.APPROVED
                request.resolved_at = utc_now()
        self._request_repository.save(request)
        if request.status is not previous_status:
            self._event_bus.publish(
                ApprovalResolved(
                    approval_request_id=request.id,
                    response_run_id=request.response_run_id,
                    step_run_id=request.step_run_id,
                    incident_id=str(request.payload.get("incident_id", "")),
                    status=request.status,
                    message=f"Approval request {request.id} is now {request.status.value}.",
                )
            )
        return request

    def expire_pending(self, *, now: datetime | None = None) -> list[ApprovalRequest]:
        expired: list[ApprovalRequest] = []
        for request in self._request_repository.list_expired(now or utc_now()):
            previous_status = request.status
            request.status = ApprovalRequestStatus.EXPIRED
            request.resolved_at = now or utc_now()
            self._request_repository.save(request)
            expired.append(request)
            if previous_status is not request.status:
                self._event_bus.publish(
                    ApprovalResolved(
                        approval_request_id=request.id,
                        response_run_id=request.response_run_id,
                        step_run_id=request.step_run_id,
                        incident_id=str(request.payload.get("incident_id", "")),
                        status=request.status,
                        message=f"Approval request {request.id} expired.",
                    )
                )
        return expired

    def _require_request(self, request_id: str) -> ApprovalRequest:
        request = self._request_repository.get(request_id)
        if request is None:
            raise LookupError(f"Approval request '{request_id}' was not found.")
        return request

