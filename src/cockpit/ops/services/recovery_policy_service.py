"""Deterministic recovery policy evaluation for self-healing components."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from cockpit.ops.models.health import (
    ComponentHealthState,
    RecoveryAttempt,
    RecoveryPolicy,
)
from cockpit.core.enums import ComponentKind, HealthStatus
from cockpit.core.utils import utc_now


@dataclass(slots=True, frozen=True)
class RecoveryEvaluation:
    """Result of evaluating a failure against recovery policy."""

    should_schedule_attempt: bool
    should_enter_cooldown: bool
    should_quarantine: bool
    attempt_number: int
    backoff_seconds: int
    cooldown_until: datetime | None
    next_status: HealthStatus
    explanation: str


class RecoveryPolicyService:
    """Evaluate bounded retry, cooldown, and quarantine transitions."""

    def __init__(
        self,
        *,
        policies: dict[ComponentKind, RecoveryPolicy] | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self._policies = policies or self._default_policies()
        self._now_factory = now_factory or utc_now

    def policy_for(self, component_kind: ComponentKind) -> RecoveryPolicy:
        return self._policies.get(
            component_kind, self._default_policies()[component_kind]
        )

    def evaluate_failure(
        self,
        *,
        component_kind: ComponentKind,
        state: ComponentHealthState | None,
        recent_attempts: list[RecoveryAttempt],
        reason: str,
        now: datetime | None = None,
    ) -> RecoveryEvaluation:
        effective_now = now or self._now_factory()
        policy = self.policy_for(component_kind)
        lower_reason = reason.lower()
        if any(marker in lower_reason for marker in policy.non_recoverable_markers):
            return RecoveryEvaluation(
                should_schedule_attempt=False,
                should_enter_cooldown=False,
                should_quarantine=True,
                attempt_number=max(
                    (attempt.attempt_number for attempt in recent_attempts), default=0
                ),
                backoff_seconds=0,
                cooldown_until=None,
                next_status=HealthStatus.QUARANTINED,
                explanation=f"Recovery blocked because '{reason}' is classified as non-recoverable.",
            )

        if state is not None and state.quarantined:
            return RecoveryEvaluation(
                should_schedule_attempt=False,
                should_enter_cooldown=False,
                should_quarantine=True,
                attempt_number=max(
                    (attempt.attempt_number for attempt in recent_attempts), default=0
                ),
                backoff_seconds=0,
                cooldown_until=state.cooldown_until,
                next_status=HealthStatus.QUARANTINED,
                explanation="Component is already quarantined.",
            )

        if (
            state is not None
            and state.cooldown_until is not None
            and state.cooldown_until > effective_now
        ):
            return RecoveryEvaluation(
                should_schedule_attempt=False,
                should_enter_cooldown=False,
                should_quarantine=policy.quarantine_after_exhaustion,
                attempt_number=max(
                    (attempt.attempt_number for attempt in recent_attempts), default=0
                ),
                backoff_seconds=0,
                cooldown_until=state.cooldown_until,
                next_status=(
                    HealthStatus.QUARANTINED
                    if policy.quarantine_after_exhaustion
                    else HealthStatus.FAILED
                ),
                explanation="Failure repeated during cooldown window.",
            )

        window_start = effective_now - timedelta(
            seconds=max(1, policy.retry_window_seconds)
        )
        in_window = [
            attempt
            for attempt in recent_attempts
            if (
                (attempt.finished_at or attempt.started_at or attempt.scheduled_for)
                and (attempt.finished_at or attempt.started_at or attempt.scheduled_for)
                >= window_start
            )
        ]
        attempts_used = len(in_window)
        next_attempt_number = (
            max((attempt.attempt_number for attempt in recent_attempts), default=0) + 1
        )
        if attempts_used < policy.max_attempts:
            backoff_seconds = min(
                policy.max_backoff_seconds,
                policy.base_backoff_seconds * (2 ** max(0, attempts_used)),
            )
            return RecoveryEvaluation(
                should_schedule_attempt=True,
                should_enter_cooldown=False,
                should_quarantine=False,
                attempt_number=next_attempt_number,
                backoff_seconds=max(0, backoff_seconds),
                cooldown_until=None,
                next_status=HealthStatus.RECOVERING,
                explanation=(
                    f"Automatic recovery attempt {next_attempt_number} scheduled with "
                    f"{backoff_seconds}s backoff."
                ),
            )

        cooldown_until = effective_now + timedelta(
            seconds=max(1, policy.cooldown_seconds)
        )
        exhaustion_count = state.exhaustion_count if state is not None else 0
        if policy.quarantine_after_exhaustion and exhaustion_count >= 1:
            return RecoveryEvaluation(
                should_schedule_attempt=False,
                should_enter_cooldown=False,
                should_quarantine=True,
                attempt_number=next_attempt_number - 1,
                backoff_seconds=0,
                cooldown_until=cooldown_until,
                next_status=HealthStatus.QUARANTINED,
                explanation="Recovery attempts exhausted again after prior cooldown; component quarantined.",
            )

        return RecoveryEvaluation(
            should_schedule_attempt=False,
            should_enter_cooldown=True,
            should_quarantine=False,
            attempt_number=next_attempt_number - 1,
            backoff_seconds=0,
            cooldown_until=cooldown_until,
            next_status=HealthStatus.FAILED,
            explanation=(
                f"Recovery attempts exhausted; entering cooldown until {cooldown_until.isoformat()}."
            ),
        )

    @staticmethod
    def _default_policies() -> dict[ComponentKind, RecoveryPolicy]:
        return {
            ComponentKind.PTY_SESSION: RecoveryPolicy(
                component_kind=ComponentKind.PTY_SESSION,
                max_attempts=3,
                retry_window_seconds=300,
                base_backoff_seconds=1,
                max_backoff_seconds=8,
                cooldown_seconds=60,
                non_recoverable_markers=(
                    "permission denied",
                    "no such file",
                    "not found",
                ),
            ),
            ComponentKind.SSH_TUNNEL: RecoveryPolicy(
                component_kind=ComponentKind.SSH_TUNNEL,
                max_attempts=4,
                retry_window_seconds=300,
                base_backoff_seconds=2,
                max_backoff_seconds=16,
                cooldown_seconds=120,
                non_recoverable_markers=(
                    "permission denied",
                    "host key verification failed",
                ),
            ),
            ComponentKind.BACKGROUND_TASK: RecoveryPolicy(
                component_kind=ComponentKind.BACKGROUND_TASK,
                max_attempts=2,
                retry_window_seconds=180,
                base_backoff_seconds=1,
                max_backoff_seconds=4,
                cooldown_seconds=60,
                non_recoverable_markers=(),
            ),
            ComponentKind.DOCKER_RUNTIME: RecoveryPolicy(
                component_kind=ComponentKind.DOCKER_RUNTIME,
                max_attempts=1,
                retry_window_seconds=300,
                base_backoff_seconds=1,
                max_backoff_seconds=1,
                cooldown_seconds=60,
                quarantine_after_exhaustion=False,
                non_recoverable_markers=(),
            ),
            ComponentKind.DATASOURCE: RecoveryPolicy(
                component_kind=ComponentKind.DATASOURCE,
                max_attempts=1,
                retry_window_seconds=300,
                base_backoff_seconds=1,
                max_backoff_seconds=1,
                cooldown_seconds=60,
                quarantine_after_exhaustion=False,
                non_recoverable_markers=(),
            ),
            ComponentKind.HTTP_REQUEST: RecoveryPolicy(
                component_kind=ComponentKind.HTTP_REQUEST,
                max_attempts=1,
                retry_window_seconds=300,
                base_backoff_seconds=1,
                max_backoff_seconds=1,
                cooldown_seconds=60,
                quarantine_after_exhaustion=False,
                non_recoverable_markers=(),
            ),
            ComponentKind.PLUGIN_HOST: RecoveryPolicy(
                component_kind=ComponentKind.PLUGIN_HOST,
                max_attempts=3,
                retry_window_seconds=300,
                base_backoff_seconds=2,
                max_backoff_seconds=20,
                cooldown_seconds=120,
                non_recoverable_markers=(
                    "permission denied",
                    "integrity_failed",
                    "incompatible",
                ),
            ),
            ComponentKind.WEB_ADMIN: RecoveryPolicy(
                component_kind=ComponentKind.WEB_ADMIN,
                max_attempts=3,
                retry_window_seconds=300,
                base_backoff_seconds=1,
                max_backoff_seconds=8,
                cooldown_seconds=90,
                non_recoverable_markers=("address already in use",),
            ),
            ComponentKind.DATASOURCE_WATCH: RecoveryPolicy(
                component_kind=ComponentKind.DATASOURCE_WATCH,
                max_attempts=2,
                retry_window_seconds=300,
                base_backoff_seconds=5,
                max_backoff_seconds=30,
                cooldown_seconds=180,
                non_recoverable_markers=(),
            ),
            ComponentKind.DOCKER_CONTAINER_WATCH: RecoveryPolicy(
                component_kind=ComponentKind.DOCKER_CONTAINER_WATCH,
                max_attempts=2,
                retry_window_seconds=300,
                base_backoff_seconds=5,
                max_backoff_seconds=30,
                cooldown_seconds=180,
                non_recoverable_markers=(),
            ),
        }
