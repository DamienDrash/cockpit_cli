"""Central guard policy engine for risky operator actions."""

from __future__ import annotations

from dataclasses import replace

from cockpit.domain.models.policy import GuardContext, GuardDecision
from cockpit.infrastructure.persistence.ops_repositories import GuardDecisionRepository
from cockpit.shared.enums import (
    ComponentKind,
    GuardActionKind,
    GuardDecisionOutcome,
    TargetRiskLevel,
)


class GuardPolicyService:
    """Evaluate risky actions against a centralized policy matrix."""

    _HTTP_BLOCKED_METHODS = {"CONNECT", "TRACE"}

    def __init__(self, repository: GuardDecisionRepository) -> None:
        self._repository = repository

    def evaluate(self, context: GuardContext) -> GuardDecision:
        decision = self._evaluate(context)
        self._repository.record(decision)
        return decision

    def _evaluate(self, context: GuardContext) -> GuardDecision:
        if context.action_kind in {
            GuardActionKind.DOCKER_RESTART,
            GuardActionKind.DOCKER_STOP,
            GuardActionKind.DOCKER_REMOVE,
        }:
            return self._evaluate_docker(context)
        if context.action_kind in {
            GuardActionKind.DB_QUERY,
            GuardActionKind.DB_MUTATION,
            GuardActionKind.DB_DESTRUCTIVE,
        }:
            return self._evaluate_db(context)
        if context.action_kind in {
            GuardActionKind.HTTP_READ,
            GuardActionKind.HTTP_MUTATION,
            GuardActionKind.HTTP_DESTRUCTIVE,
        }:
            return self._evaluate_http(context)
        if context.action_kind in {
            GuardActionKind.SHELL_READ,
            GuardActionKind.SHELL_MUTATION,
            GuardActionKind.SHELL_DESTRUCTIVE,
        }:
            return self._evaluate_shell(context)
        return GuardDecision(
            command_id=context.command_id,
            action_kind=context.action_kind,
            component_kind=context.component_kind,
            target_risk=context.target_risk,
            outcome=GuardDecisionOutcome.ALLOW,
            explanation="No guard rule matched; allowing action.",
            audit_required=True,
        )

    def _evaluate_docker(self, context: GuardContext) -> GuardDecision:
        description = context.description or "docker operation"
        if context.action_kind is GuardActionKind.DOCKER_REMOVE:
            if context.target_risk is TargetRiskLevel.PROD and not context.elevated_mode:
                return self._decision(
                    context,
                    outcome=GuardDecisionOutcome.REQUIRE_ELEVATED_MODE,
                    explanation=f"{description} targets a production-like runtime and requires elevated mode.",
                )
        if not context.confirmed:
            return self._decision(
                context,
                outcome=GuardDecisionOutcome.REQUIRE_CONFIRMATION,
                explanation=f"{description} is mutating and requires explicit confirmation.",
                confirmation_message=f"Confirm {description}.",
            )
        return self._decision(
            replace(context, confirmed=True),
            outcome=GuardDecisionOutcome.ALLOW,
            explanation=f"{description} allowed after guard checks.",
        )

    def _evaluate_shell(self, context: GuardContext) -> GuardDecision:
        description = context.description or "shell command"
        if context.action_kind is GuardActionKind.SHELL_READ:
            return self._decision(
                context,
                outcome=GuardDecisionOutcome.ALLOW,
                explanation=f"{description} classified as read-only.",
                audit_required=False,
            )
        if context.action_kind is GuardActionKind.SHELL_DESTRUCTIVE and context.target_risk is TargetRiskLevel.PROD:
            return self._decision(
                context,
                outcome=GuardDecisionOutcome.BLOCK,
                explanation=f"{description} is blocked on production-like targets.",
            )
        if context.target_risk in {TargetRiskLevel.STAGE, TargetRiskLevel.PROD} and not context.elevated_mode:
            return self._decision(
                context,
                outcome=GuardDecisionOutcome.REQUIRE_ELEVATED_MODE,
                explanation=f"{description} requires elevated mode on non-dev targets.",
            )
        if not context.confirmed:
            return self._decision(
                context,
                outcome=GuardDecisionOutcome.REQUIRE_CONFIRMATION,
                explanation=f"{description} mutates system state and requires confirmation.",
                confirmation_message=f"Confirm {description}.",
            )
        return self._decision(
            replace(context, confirmed=True),
            outcome=GuardDecisionOutcome.ALLOW,
            explanation=f"{description} allowed after guard checks.",
        )

    def _evaluate_db(self, context: GuardContext) -> GuardDecision:
        description = context.description or "database operation"
        if context.action_kind is GuardActionKind.DB_QUERY:
            return self._decision(
                context,
                outcome=GuardDecisionOutcome.ALLOW,
                explanation=f"{description} classified as read-only.",
                audit_required=False,
            )

        if context.action_kind is GuardActionKind.DB_DESTRUCTIVE and context.target_risk is TargetRiskLevel.PROD:
            return self._decision(
                context,
                outcome=GuardDecisionOutcome.BLOCK,
                explanation=f"{description} is blocked on production-like targets.",
            )

        if context.target_risk in {TargetRiskLevel.STAGE, TargetRiskLevel.PROD} and not context.elevated_mode:
            return self._decision(
                context,
                outcome=GuardDecisionOutcome.REQUIRE_ELEVATED_MODE,
                explanation=f"{description} requires elevated mode on non-dev targets.",
            )

        if not context.confirmed:
            return self._decision(
                context,
                outcome=GuardDecisionOutcome.REQUIRE_CONFIRMATION,
                explanation=f"{description} mutates data and requires confirmation.",
                confirmation_message=f"Confirm {description}.",
            )

        return self._decision(
            replace(context, confirmed=True),
            outcome=GuardDecisionOutcome.ALLOW,
            explanation=f"{description} allowed after guard checks.",
        )

    def _evaluate_http(self, context: GuardContext) -> GuardDecision:
        description = context.description or "HTTP request"
        method = str(context.metadata.get("method", "")).upper()
        if method in self._HTTP_BLOCKED_METHODS:
            return self._decision(
                context,
                outcome=GuardDecisionOutcome.BLOCK,
                explanation=f"{method} requests are blocked by policy.",
            )
        if context.action_kind is GuardActionKind.HTTP_READ:
            return self._decision(
                context,
                outcome=GuardDecisionOutcome.ALLOW,
                explanation=f"{description} classified as read-only.",
                audit_required=False,
            )
        if context.target_risk is TargetRiskLevel.PROD and not context.elevated_mode:
            return self._decision(
                context,
                outcome=GuardDecisionOutcome.REQUIRE_ELEVATED_MODE,
                explanation=f"{description} requires elevated mode on production-like targets.",
            )
        if not context.confirmed:
            return self._decision(
                context,
                outcome=GuardDecisionOutcome.REQUIRE_CONFIRMATION,
                explanation=f"{description} mutates remote state and requires confirmation.",
                confirmation_message=f"Confirm {description}.",
            )
        return self._decision(
            replace(context, confirmed=True),
            outcome=GuardDecisionOutcome.ALLOW,
            explanation=f"{description} allowed after guard checks.",
        )

    @staticmethod
    def _decision(
        context: GuardContext,
        *,
        outcome: GuardDecisionOutcome,
        explanation: str,
        confirmation_message: str | None = None,
        audit_required: bool = True,
    ) -> GuardDecision:
        return GuardDecision(
            command_id=context.command_id,
            action_kind=context.action_kind,
            component_kind=context.component_kind,
            target_risk=context.target_risk,
            outcome=outcome,
            explanation=explanation,
            requires_confirmation=outcome is GuardDecisionOutcome.REQUIRE_CONFIRMATION,
            requires_elevated_mode=outcome is GuardDecisionOutcome.REQUIRE_ELEVATED_MODE,
            requires_dry_run=False,
            audit_required=audit_required,
            confirmation_message=confirmation_message,
            metadata=dict(context.metadata),
        )
