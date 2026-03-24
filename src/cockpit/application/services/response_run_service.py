"""Stage 4 response runtime orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.services.approval_service import ApprovalService
from cockpit.application.services.postincident_service import PostIncidentService
from cockpit.application.services.response_executor_service import (
    ResponseExecutionOutcome,
    ResponseExecutorService,
)
from cockpit.application.services.runbook_catalog_service import RunbookCatalogService
from cockpit.domain.events.health_events import IncidentStatusChanged
from cockpit.domain.events.response_events import (
    CompensationStatusChanged,
    ResponseRunCreated,
    ResponseRunStatusChanged,
    ResponseStepStatusChanged,
)
from cockpit.domain.models.health import ComponentHealthState, IncidentRecord
from cockpit.domain.models.response import (
    CompensationRun,
    ResponseArtifact,
    ResponseRun,
    ResponseStepRun,
    RunbookCompensationDefinition,
    RunbookDefinition,
    RunbookStepDefinition,
)
from cockpit.domain.models.review import PostIncidentReview
from cockpit.infrastructure.persistence.ops_repositories import (
    ApprovalRequestRepository,
    ComponentHealthRepository,
    CompensationRunRepository,
    IncidentRepository,
    ResponseArtifactRepository,
    ResponseRunRepository,
    ResponseStepRunRepository,
    ResponseTimelineRepository,
)
from cockpit.shared.enums import (
    ApprovalDecisionKind,
    ApprovalRequestStatus,
    CompensationStatus,
    IncidentStatus,
    PostIncidentReviewStatus,
    ResponseRunStatus,
    ResponseStepStatus,
    TargetRiskLevel,
)
from cockpit.shared.risk import classify_target_risk
from cockpit.shared.utils import make_id, utc_now


@dataclass(slots=True, frozen=True)
class ResponseRunDetail:
    """Structured response run detail payload."""

    response_run: ResponseRun
    incident: IncidentRecord
    runbook: RunbookDefinition
    step_runs: tuple[ResponseStepRun, ...]
    approvals: tuple[dict[str, object], ...]
    artifacts: tuple[ResponseArtifact, ...]
    compensations: tuple[CompensationRun, ...]
    timeline: tuple[dict[str, object], ...]
    review: PostIncidentReview | None


class ResponseRunService:
    """Drive deterministic Stage 4 response runs."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        incident_repository: IncidentRepository,
        component_health_repository: ComponentHealthRepository,
        response_run_repository: ResponseRunRepository,
        step_run_repository: ResponseStepRunRepository,
        approval_request_repository: ApprovalRequestRepository,
        artifact_repository: ResponseArtifactRepository,
        compensation_repository: CompensationRunRepository,
        timeline_repository: ResponseTimelineRepository,
        runbook_catalog_service: RunbookCatalogService,
        response_executor_service: ResponseExecutorService,
        approval_service: ApprovalService,
        postincident_service: PostIncidentService,
    ) -> None:
        self._event_bus = event_bus
        self._incident_repository = incident_repository
        self._component_health_repository = component_health_repository
        self._response_run_repository = response_run_repository
        self._step_run_repository = step_run_repository
        self._approval_request_repository = approval_request_repository
        self._artifact_repository = artifact_repository
        self._compensation_repository = compensation_repository
        self._timeline_repository = timeline_repository
        self._runbook_catalog_service = runbook_catalog_service
        self._response_executor_service = response_executor_service
        self._approval_service = approval_service
        self._postincident_service = postincident_service
        self._event_bus.subscribe(IncidentStatusChanged, self._on_incident_status_changed)

    def list_active_runs(self, *, limit: int = 25) -> list[ResponseRun]:
        return self._response_run_repository.list_active(limit=limit)

    def list_recent_runs(self, *, limit: int = 50) -> list[ResponseRun]:
        return self._response_run_repository.list_recent(limit=limit)

    def list_pending_approvals(self, *, limit: int = 50) -> list[dict[str, object]]:
        details = []
        for request in self._approval_service.list_pending(limit=limit):
            detail = self._approval_service.get_detail(request.id)
            if detail is None:
                continue
            details.append(
                {
                    "request": detail.request.to_dict(),
                    "decisions": [item.to_dict() for item in detail.decisions],
                }
            )
        return details

    def get_response_detail(self, run_id: str) -> ResponseRunDetail | None:
        response_run = self._response_run_repository.get(run_id)
        if response_run is None:
            return None
        incident = self._require_incident(response_run.incident_id)
        runbook = self._runbook_catalog_service.get_runbook(
            response_run.runbook_id,
            version=response_run.runbook_version,
        )
        approvals = []
        for request in self._approval_request_repository.list_for_run(response_run.id):
            detail = self._approval_service.get_detail(request.id)
            if detail is None:
                continue
            approvals.append(
                {
                    "request": detail.request.to_dict(),
                    "decisions": [item.to_dict() for item in detail.decisions],
                }
            )
        review = self._postincident_service.get_review_detail_for_incident(incident.id)
        return ResponseRunDetail(
            response_run=response_run,
            incident=incident,
            runbook=runbook,
            step_runs=tuple(self._step_run_repository.list_for_run(response_run.id)),
            approvals=tuple(approvals),
            artifacts=tuple(self._artifact_repository.list_for_run(response_run.id)),
            compensations=tuple(self._compensation_repository.list_for_run(response_run.id)),
            timeline=tuple(self._timeline_repository.list_for_run(response_run.id)),
            review=review.review if review is not None else None,
        )

    def start_run(
        self,
        *,
        incident_id: str,
        runbook_id: str,
        actor: str,
        runbook_version: str | None = None,
        engagement_id: str | None = None,
    ) -> ResponseRun:
        incident = self._require_incident(incident_id)
        existing = self._response_run_repository.get_active_for_incident(incident_id)
        if existing is not None:
            raise ValueError(f"Incident '{incident_id}' already has an active response run.")
        runbook = self._runbook_catalog_service.get_runbook(runbook_id, version=runbook_version)
        started_at = utc_now()
        response_run = ResponseRun(
            id=make_id("rrn"),
            incident_id=incident.id,
            engagement_id=engagement_id,
            runbook_id=runbook.id,
            runbook_version=runbook.version,
            status=ResponseRunStatus.READY,
            current_step_index=0,
            risk_level=self._risk_for_incident(incident),
            started_by=actor,
            started_at=started_at,
            updated_at=started_at,
            summary=f"Started response run from runbook '{runbook.title}'.",
            payload={"catalog_key": runbook.catalog_key},
        )
        self._response_run_repository.save(response_run)
        self._step_run_repository.save(self._new_step_run(response_run, runbook.steps[0], step_index=0))
        self._timeline_repository.add_entry(
            response_run_id=response_run.id,
            incident_id=incident.id,
            event_type="run_started",
            message=f"Response run started by {actor}.",
            payload={"runbook_id": runbook.id, "runbook_version": runbook.version},
        )
        self._event_bus.publish(
            ResponseRunCreated(
                response_run_id=response_run.id,
                incident_id=incident.id,
                runbook_id=runbook.id,
                runbook_version=runbook.version,
            )
        )
        self._publish_run_status_change(
            response_run=response_run,
            previous_status=None,
            message="Response run is ready.",
        )
        return response_run

    def execute_current_step(
        self,
        run_id: str,
        *,
        actor: str,
        command_id: str | None = None,
        confirmed: bool = False,
        elevated_mode: bool = False,
        notes: str | None = None,
    ) -> ResponseRun:
        response_run = self._require_run(run_id)
        incident = self._require_incident(response_run.incident_id)
        runbook = self._runbook_catalog_service.get_runbook(
            response_run.runbook_id,
            version=response_run.runbook_version,
        )
        step_definition = runbook.steps[response_run.current_step_index]
        step_run = self._require_current_step_run(response_run.id, response_run.current_step_index)
        if response_run.status in {ResponseRunStatus.COMPLETED, ResponseRunStatus.ABORTED}:
            raise ValueError("Closed response runs cannot execute more steps.")
        approved_request = self._approval_request_repository.get_latest_for_step(step_run.id)
        if step_definition.approval_required:
            if approved_request is None:
                self._move_to_waiting_approval(
                    response_run=response_run,
                    step_run=step_run,
                    step_definition=step_definition,
                    actor=actor,
                )
                return self._require_run(response_run.id)
            if approved_request.status is ApprovalRequestStatus.PENDING:
                return response_run
            if approved_request.status is not ApprovalRequestStatus.APPROVED:
                self._set_run_status(
                    response_run,
                    ResponseRunStatus.BLOCKED,
                    f"Approval request {approved_request.id} is {approved_request.status.value}.",
                )
                return response_run

        if step_definition.requires_confirmation and not confirmed:
            self._set_waiting_operator(
                response_run,
                step_run,
                "Step requires explicit confirmation.",
            )
            return response_run
        if step_definition.requires_elevated_mode and not (elevated_mode or response_run.elevated_mode):
            self._set_waiting_operator(
                response_run,
                step_run,
                "Step requires elevated mode.",
            )
            return response_run

        response_run.elevated_mode = response_run.elevated_mode or elevated_mode
        self._set_run_status(response_run, ResponseRunStatus.RUNNING, f"Executing step {step_definition.key}.")
        previous_step_status = step_run.status
        step_run.status = ResponseStepStatus.RUNNING
        step_run.attempt_count += 1
        step_run.started_at = utc_now()
        self._step_run_repository.save(step_run)
        self._publish_step_status_change(
            response_run=response_run,
            step_run=step_run,
            previous_status=previous_step_status,
            message=f"Step {step_definition.key} started.",
        )

        outcome = self._response_executor_service.execute_step(
            command_id=command_id or make_id("cmd"),
            response_run=response_run,
            step_run=step_run,
            step_definition=step_definition,
            incident=incident,
            actor=actor,
            confirmed=confirmed,
            elevated_mode=response_run.elevated_mode,
            notes=notes,
        )
        return self._handle_execution_outcome(
            response_run=response_run,
            incident=incident,
            runbook=runbook,
            step_definition=step_definition,
            step_run=step_run,
            outcome=outcome,
        )

    def retry_current_step(
        self,
        run_id: str,
        *,
        actor: str,
        command_id: str | None = None,
        confirmed: bool = False,
        elevated_mode: bool = False,
        notes: str | None = None,
    ) -> ResponseRun:
        response_run = self._require_run(run_id)
        runbook = self._runbook_catalog_service.get_runbook(
            response_run.runbook_id,
            version=response_run.runbook_version,
        )
        step_definition = runbook.steps[response_run.current_step_index]
        step_run = self._require_current_step_run(response_run.id, response_run.current_step_index)
        max_attempts = 1 + step_definition.max_retries
        if step_run.attempt_count >= max_attempts and step_run.status is ResponseStepStatus.FAILED:
            raise ValueError("Retry budget is exhausted for the current response step.")
        step_run.status = ResponseStepStatus.READY
        step_run.last_error = None
        step_run.finished_at = None
        self._step_run_repository.save(step_run)
        self._set_run_status(response_run, ResponseRunStatus.READY, "Retrying current step.")
        return self.execute_current_step(
            run_id,
            actor=actor,
            command_id=command_id,
            confirmed=confirmed,
            elevated_mode=elevated_mode,
            notes=notes,
        )

    def abort_run(self, run_id: str, *, actor: str, reason: str) -> ResponseRun:
        response_run = self._require_run(run_id)
        response_run.completed_at = utc_now()
        self._set_run_status(
            response_run,
            ResponseRunStatus.ABORTED,
            f"Response run aborted by {actor}: {reason}",
        )
        self._timeline_repository.add_entry(
            response_run_id=response_run.id,
            incident_id=response_run.incident_id,
            event_type="run_aborted",
            message=f"Response run aborted by {actor}.",
            payload={"reason": reason},
        )
        return response_run

    def compensate_latest_step(
        self,
        run_id: str,
        *,
        actor: str,
        command_id: str | None = None,
        confirmed: bool = False,
        elevated_mode: bool = False,
    ) -> ResponseRun:
        response_run = self._require_run(run_id)
        incident = self._require_incident(response_run.incident_id)
        runbook = self._runbook_catalog_service.get_runbook(
            response_run.runbook_id,
            version=response_run.runbook_version,
        )
        target_step_run, target_definition = self._latest_compensatable_step(response_run, runbook)
        compensation = target_definition.compensation
        if compensation is None:
            raise ValueError("No compensation step is available for this response run.")
        if compensation.approval_required:
            request = self._approval_request_repository.get_latest_for_step(target_step_run.id)
            if request is None:
                self._move_to_waiting_approval(
                    response_run=response_run,
                    step_run=target_step_run,
                    step_definition=RunbookStepDefinition(
                        key=f"{target_definition.key}.compensation",
                        title=compensation.title,
                        executor_kind=compensation.executor_kind,
                        operation_kind=compensation.operation_kind,
                        approval_required=True,
                        required_approver_count=compensation.required_approver_count,
                        required_roles=compensation.required_roles,
                        allow_self_approval=False,
                        step_config=compensation.step_config,
                    ),
                    actor=actor,
                    reason=f"Compensation approval required for {compensation.title}.",
                )
                return self._require_run(response_run.id)
            if request.status is ApprovalRequestStatus.PENDING:
                return response_run
            if request.status is not ApprovalRequestStatus.APPROVED:
                self._set_run_status(
                    response_run,
                    ResponseRunStatus.BLOCKED,
                    f"Compensation approval request {request.id} is {request.status.value}.",
                )
                return response_run
        if compensation.requires_confirmation and not confirmed:
            self._set_waiting_operator(response_run, target_step_run, "Compensation requires confirmation.")
            return response_run
        if compensation.requires_elevated_mode and not (elevated_mode or response_run.elevated_mode):
            self._set_waiting_operator(response_run, target_step_run, "Compensation requires elevated mode.")
            return response_run

        compensation_run = CompensationRun(
            id=make_id("cmp"),
            response_run_id=response_run.id,
            step_run_id=target_step_run.id,
            status=CompensationStatus.RUNNING,
            started_at=utc_now(),
            payload={"step_key": target_definition.key},
        )
        self._compensation_repository.save(compensation_run)
        self._set_run_status(response_run, ResponseRunStatus.COMPENSATING, f"Running compensation for {target_definition.key}.")
        self._event_bus.publish(
            CompensationStatusChanged(
                compensation_run_id=compensation_run.id,
                response_run_id=response_run.id,
                step_run_id=target_step_run.id,
                incident_id=response_run.incident_id,
                status=compensation_run.status,
                message="Compensation started.",
            )
        )
        outcome = self._response_executor_service.execute_compensation(
            command_id=command_id or make_id("cmd"),
            response_run=response_run,
            step_run=target_step_run,
            compensation=compensation,
            incident=incident,
            actor=actor,
            confirmed=confirmed,
            elevated_mode=response_run.elevated_mode or elevated_mode,
        )
        if outcome.waiting_for_operator:
            compensation_run.status = CompensationStatus.PENDING
            compensation_run.summary = outcome.result.summary
            self._compensation_repository.save(compensation_run)
            self._set_waiting_operator(response_run, target_step_run, outcome.result.summary)
            return response_run
        if outcome.blocked or not outcome.result.success:
            compensation_run.status = CompensationStatus.FAILED
            compensation_run.finished_at = utc_now()
            compensation_run.summary = outcome.result.summary
            compensation_run.last_error = outcome.result.error_message
            self._compensation_repository.save(compensation_run)
            self._set_run_status(response_run, ResponseRunStatus.BLOCKED, outcome.result.summary)
            self._event_bus.publish(
                CompensationStatusChanged(
                    compensation_run_id=compensation_run.id,
                    response_run_id=response_run.id,
                    step_run_id=target_step_run.id,
                    incident_id=response_run.incident_id,
                    status=compensation_run.status,
                    message=outcome.result.summary,
                )
            )
            return response_run

        compensation_run.status = CompensationStatus.COMPLETED
        compensation_run.finished_at = utc_now()
        compensation_run.summary = outcome.result.summary
        self._compensation_repository.save(compensation_run)
        self._save_artifacts(response_run, target_step_run, outcome.result.artifacts)
        previous_step_status = target_step_run.status
        target_step_run.status = ResponseStepStatus.COMPENSATED
        target_step_run.finished_at = utc_now()
        target_step_run.output_summary = outcome.result.summary
        target_step_run.output_payload = dict(outcome.result.payload)
        self._step_run_repository.save(target_step_run)
        self._publish_step_status_change(
            response_run=response_run,
            step_run=target_step_run,
            previous_status=previous_step_status,
            message="Compensation completed.",
        )
        response_run.completed_at = utc_now()
        self._set_run_status(response_run, ResponseRunStatus.ABORTED, "Response run compensated and aborted.")
        self._event_bus.publish(
            CompensationStatusChanged(
                compensation_run_id=compensation_run.id,
                response_run_id=response_run.id,
                step_run_id=target_step_run.id,
                incident_id=response_run.incident_id,
                status=compensation_run.status,
                message="Compensation completed.",
            )
        )
        self._postincident_service.ensure_review(
            incident_id=response_run.incident_id,
            response_run_id=response_run.id,
            owner_ref=actor,
        )
        return response_run

    def decide_approval(
        self,
        request_id: str,
        *,
        approver_ref: str,
        decision: ApprovalDecisionKind,
        comment: str | None = None,
    ) -> ResponseRun:
        request = self._approval_service.decide(
            request_id,
            approver_ref=approver_ref,
            decision=decision,
            comment=comment,
        )
        response_run = self._require_run(request.response_run_id)
        step_run = self._require_step_run(request.step_run_id)
        if request.status is ApprovalRequestStatus.APPROVED:
            previous_step_status = step_run.status
            step_run.status = ResponseStepStatus.READY
            self._step_run_repository.save(step_run)
            self._publish_step_status_change(
                response_run=response_run,
                step_run=step_run,
                previous_status=previous_step_status,
                message="Approval request approved; step is ready.",
            )
            self._set_run_status(response_run, ResponseRunStatus.READY, "Approval request approved.")
        elif request.status in {ApprovalRequestStatus.REJECTED, ApprovalRequestStatus.EXPIRED}:
            self._set_run_status(
                response_run,
                ResponseRunStatus.BLOCKED,
                f"Approval request {request.id} is {request.status.value}.",
            )
        return response_run

    def sweep_due(self) -> None:
        for request in self._approval_service.expire_pending():
            response_run = self._require_run(request.response_run_id)
            self._set_run_status(
                response_run,
                ResponseRunStatus.BLOCKED,
                f"Approval request {request.id} expired.",
            )

    def diagnostics(self) -> dict[str, object]:
        active_runs = self.list_active_runs(limit=20)
        pending_approvals = self.list_pending_approvals(limit=20)
        return {
            "active_runs": [item.to_dict() for item in active_runs],
            "pending_approvals": pending_approvals,
            "open_reviews": [
                review.to_dict()
                for review in self._postincident_service.list_reviews(limit=20)
                if review.status is not PostIncidentReviewStatus.CLOSED
            ],
        }

    def _handle_execution_outcome(
        self,
        *,
        response_run: ResponseRun,
        incident: IncidentRecord,
        runbook: RunbookDefinition,
        step_definition: RunbookStepDefinition,
        step_run: ResponseStepRun,
        outcome: ResponseExecutionOutcome,
    ) -> ResponseRun:
        if outcome.waiting_for_operator:
            self._set_waiting_operator(response_run, step_run, outcome.result.summary)
            return response_run
        if outcome.blocked:
            step_run.status = ResponseStepStatus.FAILED
            step_run.finished_at = utc_now()
            step_run.last_error = outcome.result.error_message
            self._step_run_repository.save(step_run)
            self._set_run_status(response_run, ResponseRunStatus.BLOCKED, outcome.result.summary)
            return response_run

        step_run.finished_at = utc_now()
        step_run.output_summary = outcome.result.summary
        step_run.output_payload = dict(outcome.result.payload)
        if outcome.result.success:
            previous_step_status = step_run.status
            step_run.status = ResponseStepStatus.SUCCEEDED
            self._step_run_repository.save(step_run)
            self._save_artifacts(response_run, step_run, outcome.result.artifacts)
            self._publish_step_status_change(
                response_run=response_run,
                step_run=step_run,
                previous_status=previous_step_status,
                message=outcome.result.summary,
            )
            self._timeline_repository.add_entry(
                response_run_id=response_run.id,
                incident_id=incident.id,
                event_type="step_succeeded",
                message=outcome.result.summary,
                payload={"step_key": step_definition.key},
            )
            next_index = response_run.current_step_index + 1
            if next_index >= len(runbook.steps):
                response_run.completed_at = utc_now()
                self._set_run_status(response_run, ResponseRunStatus.COMPLETED, "Response run completed.")
                self._postincident_service.ensure_review(
                    incident_id=incident.id,
                    response_run_id=response_run.id,
                    owner_ref=response_run.started_by,
                )
                return response_run
            response_run.current_step_index = next_index
            response_run.updated_at = utc_now()
            self._response_run_repository.save(response_run)
            if self._step_run_repository.get_by_run_and_index(response_run.id, next_index) is None:
                self._step_run_repository.save(
                    self._new_step_run(response_run, runbook.steps[next_index], step_index=next_index)
                )
            self._set_run_status(response_run, ResponseRunStatus.READY, "Next response step is ready.")
            return response_run

        previous_step_status = step_run.status
        step_run.status = ResponseStepStatus.FAILED
        step_run.last_error = outcome.result.error_message
        self._step_run_repository.save(step_run)
        self._publish_step_status_change(
            response_run=response_run,
            step_run=step_run,
            previous_status=previous_step_status,
            message=outcome.result.summary,
        )
        self._timeline_repository.add_entry(
            response_run_id=response_run.id,
            incident_id=incident.id,
            event_type="step_failed",
            message=outcome.result.summary,
            payload={"step_key": step_definition.key},
        )
        if step_definition.continue_on_failure:
            next_index = response_run.current_step_index + 1
            if next_index < len(runbook.steps):
                response_run.current_step_index = next_index
                self._response_run_repository.save(response_run)
                self._step_run_repository.save(
                    self._new_step_run(response_run, runbook.steps[next_index], step_index=next_index)
                )
                self._set_run_status(response_run, ResponseRunStatus.READY, "Continuing after step failure.")
                return response_run
        self._set_run_status(response_run, ResponseRunStatus.FAILED, outcome.result.summary)
        return response_run

    def _move_to_waiting_approval(
        self,
        *,
        response_run: ResponseRun,
        step_run: ResponseStepRun,
        step_definition: RunbookStepDefinition,
        actor: str,
        reason: str | None = None,
    ) -> None:
        request = self._approval_service.ensure_request(
            response_run=response_run,
            step_run=step_run,
            requested_by=actor,
            required_approver_count=step_definition.required_approver_count or 1,
            required_roles=step_definition.required_roles,
            allow_self_approval=step_definition.allow_self_approval,
            expires_after_seconds=step_definition.approval_expires_after_seconds,
            reason=reason or f"Approval required for step {step_definition.title}.",
        )
        previous_step_status = step_run.status
        step_run.status = ResponseStepStatus.WAITING_APPROVAL
        step_run.approval_request_id = request.id
        self._step_run_repository.save(step_run)
        self._publish_step_status_change(
            response_run=response_run,
            step_run=step_run,
            previous_status=previous_step_status,
            message=f"Waiting for approval request {request.id}.",
        )
        self._set_run_status(response_run, ResponseRunStatus.WAITING_APPROVAL, f"Waiting for approval request {request.id}.")

    def _set_waiting_operator(
        self,
        response_run: ResponseRun,
        step_run: ResponseStepRun,
        message: str,
    ) -> None:
        previous_step_status = step_run.status
        step_run.status = ResponseStepStatus.WAITING_OPERATOR
        step_run.output_summary = message
        self._step_run_repository.save(step_run)
        self._publish_step_status_change(
            response_run=response_run,
            step_run=step_run,
            previous_status=previous_step_status,
            message=message,
        )
        self._set_run_status(response_run, ResponseRunStatus.WAITING_OPERATOR, message)

    def _set_run_status(
        self,
        response_run: ResponseRun,
        new_status: ResponseRunStatus,
        message: str,
    ) -> None:
        previous_status = response_run.status
        response_run.status = new_status
        response_run.summary = message
        response_run.updated_at = utc_now()
        self._response_run_repository.save(response_run)
        self._publish_run_status_change(
            response_run=response_run,
            previous_status=previous_status,
            message=message,
        )

    def _publish_run_status_change(
        self,
        *,
        response_run: ResponseRun,
        previous_status: ResponseRunStatus | None,
        message: str,
    ) -> None:
        self._event_bus.publish(
            ResponseRunStatusChanged(
                response_run_id=response_run.id,
                incident_id=response_run.incident_id,
                previous_status=previous_status,
                new_status=response_run.status,
                message=message,
            )
        )

    def _publish_step_status_change(
        self,
        *,
        response_run: ResponseRun,
        step_run: ResponseStepRun,
        previous_status: ResponseStepStatus | None,
        message: str,
    ) -> None:
        self._event_bus.publish(
            ResponseStepStatusChanged(
                response_run_id=response_run.id,
                step_run_id=step_run.id,
                incident_id=response_run.incident_id,
                step_key=step_run.step_key,
                previous_status=previous_status,
                new_status=step_run.status,
                message=message,
            )
        )

    def _save_artifacts(
        self,
        response_run: ResponseRun,
        step_run: ResponseStepRun,
        artifacts: tuple[object, ...],
    ) -> None:
        for artifact in artifacts:
            if not hasattr(artifact, "kind"):
                continue
            self._artifact_repository.save(
                ResponseArtifact(
                    id=make_id("art"),
                    response_run_id=response_run.id,
                    step_run_id=step_run.id,
                    artifact_kind=str(getattr(artifact, "kind", "artifact")),
                    label=str(getattr(artifact, "label", "Artifact")),
                    summary=getattr(artifact, "summary", None),
                    storage_ref=getattr(artifact, "storage_ref", None),
                    payload=dict(getattr(artifact, "payload", {}) or {}),
                    created_at=utc_now(),
                )
            )

    def _new_step_run(
        self,
        response_run: ResponseRun,
        step_definition: RunbookStepDefinition,
        *,
        step_index: int,
    ) -> ResponseStepRun:
        return ResponseStepRun(
            id=make_id("rsr"),
            response_run_id=response_run.id,
            step_key=step_definition.key,
            step_index=step_index,
            executor_kind=step_definition.executor_kind,
            status=ResponseStepStatus.READY,
        )

    def _latest_compensatable_step(
        self,
        response_run: ResponseRun,
        runbook: RunbookDefinition,
    ) -> tuple[ResponseStepRun, RunbookStepDefinition]:
        step_runs = list(reversed(self._step_run_repository.list_for_run(response_run.id)))
        for step_run in step_runs:
            if step_run.status not in {ResponseStepStatus.SUCCEEDED, ResponseStepStatus.FAILED}:
                continue
            step_definition = runbook.steps[step_run.step_index]
            if step_definition.compensation is None:
                continue
            latest_compensation = self._compensation_repository.latest_for_step(step_run.id)
            if latest_compensation is not None and latest_compensation.status is CompensationStatus.COMPLETED:
                continue
            return step_run, step_definition
        raise ValueError("No compensatable step is available.")

    def _risk_for_incident(self, incident: IncidentRecord) -> TargetRiskLevel:
        state = self._component_health_repository.get(incident.component_id)
        if state is None:
            return TargetRiskLevel.DEV
        return classify_target_risk(
            target_kind=state.target_kind,
            target_ref=state.target_ref,
            workspace_name=incident.title,
            workspace_root=incident.summary,
        )

    def _require_incident(self, incident_id: str) -> IncidentRecord:
        incident = self._incident_repository.get(incident_id)
        if incident is None:
            raise LookupError(f"Incident '{incident_id}' was not found.")
        return incident

    def _require_run(self, run_id: str) -> ResponseRun:
        response_run = self._response_run_repository.get(run_id)
        if response_run is None:
            raise LookupError(f"Response run '{run_id}' was not found.")
        return response_run

    def _require_current_step_run(self, run_id: str, step_index: int) -> ResponseStepRun:
        step_run = self._step_run_repository.get_by_run_and_index(run_id, step_index)
        if step_run is None:
            raise LookupError(f"Response run '{run_id}' has no current step.")
        return step_run

    def _require_step_run(self, step_run_id: str) -> ResponseStepRun:
        step_run = self._step_run_repository.get(step_run_id)
        if step_run is None:
            raise LookupError(f"Response step run '{step_run_id}' was not found.")
        return step_run

    def _on_incident_status_changed(self, event: IncidentStatusChanged) -> None:
        if event.new_status not in {IncidentStatus.RESOLVED, IncidentStatus.CLOSED}:
            return
        response_run = self._response_run_repository.get_active_for_incident(event.incident_id)
        if response_run is None:
            return
        if response_run.status in {ResponseRunStatus.COMPLETED, ResponseRunStatus.ABORTED}:
            return
        response_run.completed_at = utc_now()
        self._set_run_status(
            response_run,
            ResponseRunStatus.ABORTED,
            f"Incident moved to {event.new_status.value}; response run aborted.",
        )
