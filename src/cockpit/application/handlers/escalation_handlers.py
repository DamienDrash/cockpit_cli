"""Command handlers for active engagement operations."""

from __future__ import annotations

from cockpit.application.handlers.base import CommandContextError, DispatchResult
from cockpit.application.services.escalation_service import EscalationService
from cockpit.domain.commands.command import Command
from cockpit.shared.enums import EscalationTargetKind


class AcknowledgeEngagementHandler:
    """Acknowledge the selected or explicit active engagement."""

    def __init__(self, escalation_service: EscalationService) -> None:
        self._escalation_service = escalation_service

    def __call__(self, command: Command) -> DispatchResult:
        engagement_id = _resolve_engagement_id(command)
        actor = _resolve_actor(command)
        engagement = self._escalation_service.acknowledge_engagement(
            engagement_id,
            actor=actor,
        )
        return DispatchResult(
            success=True,
            message=f"Acknowledged engagement {engagement.id}.",
            data={"engagement_id": engagement.id},
        )


class RepageEngagementHandler:
    """Force a fresh page for the selected or explicit engagement."""

    def __init__(self, escalation_service: EscalationService) -> None:
        self._escalation_service = escalation_service

    def __call__(self, command: Command) -> DispatchResult:
        engagement_id = _resolve_engagement_id(command)
        actor = _resolve_actor(command)
        engagement = self._escalation_service.repage_engagement(
            engagement_id,
            actor=actor,
        )
        return DispatchResult(
            success=True,
            message=f"Triggered re-page for engagement {engagement.id}.",
            data={"engagement_id": engagement.id},
        )


class HandoffEngagementHandler:
    """Hand off an active engagement to another target."""

    def __init__(self, escalation_service: EscalationService) -> None:
        self._escalation_service = escalation_service

    def __call__(self, command: Command) -> DispatchResult:
        engagement_id = _resolve_engagement_id(command)
        argv = command.args.get("argv", [])
        if not isinstance(argv, list) or len(argv) < 2:
            raise CommandContextError(
                "Handoff requires an engagement id and target reference."
            )
        if len(argv) == 2:
            target_kind = EscalationTargetKind.PERSON
            target_ref = str(argv[1])
        else:
            target_kind = EscalationTargetKind(str(argv[1]))
            target_ref = str(argv[2])
        actor = _resolve_actor(command)
        engagement = self._escalation_service.handoff_engagement(
            engagement_id,
            actor=actor,
            target_kind=target_kind,
            target_ref=target_ref,
        )
        return DispatchResult(
            success=True,
            message=f"Handed off engagement {engagement.id}.",
            data={"engagement_id": engagement.id},
        )


def _resolve_engagement_id(command: Command) -> str:
    argv = command.args.get("argv", [])
    if isinstance(argv, list) and argv and isinstance(argv[0], str) and argv[0]:
        return argv[0]
    selected_engagement_id = command.context.get("selected_engagement_id")
    if isinstance(selected_engagement_id, str) and selected_engagement_id:
        return selected_engagement_id
    raise CommandContextError("No engagement is selected.")


def _resolve_actor(command: Command) -> str:
    actor = command.args.get("actor") or command.context.get("operator_actor")
    if isinstance(actor, str) and actor.strip():
        return actor.strip()
    return "operator"
