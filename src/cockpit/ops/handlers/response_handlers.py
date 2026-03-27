"""Command handlers for Stage 4 response operations."""

from __future__ import annotations

from cockpit.core.dispatch.handler_base import CommandContextError, DispatchResult
from cockpit.ops.services.response_run_service import ResponseRunService
from cockpit.core.command import Command
from cockpit.core.enums import ApprovalDecisionKind


class StartResponseRunHandler:
    """Start a response run for an incident and runbook."""

    def __init__(self, response_run_service: ResponseRunService) -> None:
        self._response_run_service = response_run_service

    def __call__(self, command: Command) -> DispatchResult:
        argv = _argv(command)
        if len(argv) < 2:
            raise CommandContextError(
                "Response start requires an incident id and runbook id."
            )
        incident_id = str(argv[0])
        runbook_id = str(argv[1])
        response_run = self._response_run_service.start_run(
            incident_id=incident_id,
            runbook_id=runbook_id,
            actor=_actor(command),
        )
        return DispatchResult(
            success=True,
            message=f"Started response run {response_run.id}.",
            data={"response_run_id": response_run.id},
        )


class ExecuteResponseStepHandler:
    """Execute the currently selected response step."""

    def __init__(self, response_run_service: ResponseRunService) -> None:
        self._response_run_service = response_run_service

    def __call__(self, command: Command) -> DispatchResult:
        response_run = self._response_run_service.execute_current_step(
            _response_run_id(command),
            actor=_actor(command),
            command_id=command.id,
            confirmed=bool(command.args.get("confirmed", False)),
            elevated_mode=bool(command.args.get("elevated_mode", False)),
            notes=_optional_str(command.args.get("notes")),
        )
        return DispatchResult(
            success=True,
            message=response_run.summary
            or f"Executed response step for {response_run.id}.",
            data={"response_run_id": response_run.id},
        )


class RetryResponseStepHandler:
    """Retry the current response step when policy still allows it."""

    def __init__(self, response_run_service: ResponseRunService) -> None:
        self._response_run_service = response_run_service

    def __call__(self, command: Command) -> DispatchResult:
        response_run = self._response_run_service.retry_current_step(
            _response_run_id(command),
            actor=_actor(command),
            command_id=command.id,
            confirmed=bool(command.args.get("confirmed", False)),
            elevated_mode=bool(command.args.get("elevated_mode", False)),
            notes=_optional_str(command.args.get("notes")),
        )
        return DispatchResult(
            success=True,
            message=response_run.summary
            or f"Retried response step for {response_run.id}.",
            data={"response_run_id": response_run.id},
        )


class AbortResponseRunHandler:
    """Abort the selected response run."""

    def __init__(self, response_run_service: ResponseRunService) -> None:
        self._response_run_service = response_run_service

    def __call__(self, command: Command) -> DispatchResult:
        response_run = self._response_run_service.abort_run(
            _response_run_id(command),
            actor=_actor(command),
            reason=_optional_str(command.args.get("reason")) or "operator abort",
        )
        return DispatchResult(
            success=True,
            message=response_run.summary or f"Aborted response run {response_run.id}.",
            data={"response_run_id": response_run.id},
        )


class CompensateResponseRunHandler:
    """Execute the latest available compensation step."""

    def __init__(self, response_run_service: ResponseRunService) -> None:
        self._response_run_service = response_run_service

    def __call__(self, command: Command) -> DispatchResult:
        response_run = self._response_run_service.compensate_latest_step(
            _response_run_id(command),
            actor=_actor(command),
            command_id=command.id,
            confirmed=bool(command.args.get("confirmed", False)),
            elevated_mode=bool(command.args.get("elevated_mode", False)),
        )
        return DispatchResult(
            success=True,
            message=response_run.summary
            or f"Compensation handled for {response_run.id}.",
            data={"response_run_id": response_run.id},
        )


class DecideApprovalHandler:
    """Approve or reject the selected approval request."""

    def __init__(
        self,
        response_run_service: ResponseRunService,
        *,
        decision: ApprovalDecisionKind,
    ) -> None:
        self._response_run_service = response_run_service
        self._decision = decision

    def __call__(self, command: Command) -> DispatchResult:
        request_id = _approval_request_id(command)
        response_run = self._response_run_service.decide_approval(
            request_id,
            approver_ref=_actor(command),
            decision=self._decision,
            comment=_optional_str(command.args.get("comment")),
        )
        return DispatchResult(
            success=True,
            message=response_run.summary or f"Handled approval request {request_id}.",
            data={
                "response_run_id": response_run.id,
                "approval_request_id": request_id,
            },
        )


def _argv(command: Command) -> list[object]:
    argv = command.args.get("argv", [])
    return argv if isinstance(argv, list) else []


def _response_run_id(command: Command) -> str:
    argv = _argv(command)
    if argv and isinstance(argv[0], str) and argv[0]:
        return argv[0]
    selected = command.context.get("selected_response_run_id")
    if isinstance(selected, str) and selected:
        return selected
    raise CommandContextError("No response run is selected.")


def _approval_request_id(command: Command) -> str:
    argv = _argv(command)
    if argv and isinstance(argv[0], str) and argv[0]:
        return argv[0]
    selected = command.context.get("selected_approval_request_id")
    if isinstance(selected, str) and selected:
        return selected
    raise CommandContextError("No approval request is selected.")


def _actor(command: Command) -> str:
    actor = command.args.get("actor") or command.context.get("operator_actor")
    if isinstance(actor, str) and actor.strip():
        return actor.strip()
    return "operator"


def _optional_str(raw_value: object) -> str | None:
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    return value or None
