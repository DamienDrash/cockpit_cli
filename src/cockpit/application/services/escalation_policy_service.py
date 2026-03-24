"""Escalation policy persistence and runtime evaluation helpers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from cockpit.domain.models.escalation import EscalationPolicy, EscalationStep
from cockpit.infrastructure.persistence.ops_repositories import (
    EscalationPolicyRepository,
    EscalationStepRepository,
)
from cockpit.shared.utils import make_id, utc_now


class EscalationPolicyValidationError(ValueError):
    """Raised when escalation policy definitions are invalid."""


@dataclass(slots=True, frozen=True)
class EscalationPolicyDetail:
    """Structured policy detail payload."""

    policy: EscalationPolicy
    steps: tuple[EscalationStep, ...]


class EscalationPolicyService:
    """Persist and evaluate escalation policy definitions."""

    def __init__(
        self,
        *,
        policy_repository: EscalationPolicyRepository,
        step_repository: EscalationStepRepository,
    ) -> None:
        self._policy_repository = policy_repository
        self._step_repository = step_repository

    def list_policies(self, *, enabled_only: bool = False) -> list[EscalationPolicy]:
        return self._policy_repository.list_all(enabled_only=enabled_only)

    def get_policy(self, policy_id: str) -> EscalationPolicy | None:
        return self._policy_repository.get(policy_id)

    def get_policy_detail(self, policy_id: str) -> EscalationPolicyDetail | None:
        policy = self._policy_repository.get(policy_id)
        if policy is None:
            return None
        return EscalationPolicyDetail(
            policy=policy,
            steps=tuple(self._step_repository.list_for_policy(policy_id)),
        )

    def save_policy(
        self,
        policy: EscalationPolicy,
        *,
        steps: tuple[EscalationStep, ...],
    ) -> EscalationPolicyDetail:
        self._validate_policy(policy, steps)
        now = utc_now()
        existing = self._policy_repository.get(policy.id)
        persisted_policy = replace(
            policy,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        self._policy_repository.save(persisted_policy)
        self._step_repository.delete_for_policy(policy.id)
        for step in steps:
            persisted_step = replace(
                step,
                policy_id=policy.id,
                created_at=now if step.created_at is None else step.created_at,
                updated_at=now,
            )
            self._step_repository.save(persisted_step)
        detail = self.get_policy_detail(policy.id)
        if detail is None:
            msg = f"Escalation policy '{policy.id}' was not found after save."
            raise LookupError(msg)
        return detail

    def delete_policy(self, policy_id: str) -> None:
        self._step_repository.delete_for_policy(policy_id)
        self._policy_repository.delete(policy_id)

    def steps_for_policy(self, policy_id: str) -> tuple[EscalationStep, ...]:
        return tuple(self._step_repository.list_for_policy(policy_id))

    def first_step(self, policy_id: str) -> EscalationStep:
        steps = self._step_repository.list_for_policy(policy_id)
        if not steps:
            raise EscalationPolicyValidationError(
                f"Escalation policy '{policy_id}' has no steps."
            )
        return steps[0]

    def step_at(self, policy_id: str, step_index: int) -> EscalationStep | None:
        for step in self._step_repository.list_for_policy(policy_id):
            if step.step_index == step_index:
                return step
        return None

    def next_step(self, policy_id: str, current_step_index: int) -> EscalationStep | None:
        steps = self._step_repository.list_for_policy(policy_id)
        for step in steps:
            if step.step_index > current_step_index:
                return step
        return None

    def ack_deadline_for(
        self,
        *,
        policy: EscalationPolicy,
        step: EscalationStep,
        effective_at: datetime,
    ) -> datetime:
        timeout_seconds = self.ack_timeout_seconds(policy=policy, step=step)
        return effective_at + timedelta(seconds=max(1, timeout_seconds))

    def next_repeat_at(
        self,
        *,
        policy: EscalationPolicy,
        step: EscalationStep,
        effective_at: datetime,
    ) -> datetime:
        repeat_seconds = self.repeat_page_seconds(policy=policy, step=step)
        return effective_at + timedelta(seconds=max(1, repeat_seconds))

    def ack_timeout_seconds(
        self,
        *,
        policy: EscalationPolicy,
        step: EscalationStep,
    ) -> int:
        return int(step.ack_timeout_seconds or policy.default_ack_timeout_seconds)

    def repeat_page_seconds(
        self,
        *,
        policy: EscalationPolicy,
        step: EscalationStep,
    ) -> int:
        return int(step.repeat_page_seconds or policy.default_repeat_page_seconds)

    def max_repeat_pages(
        self,
        *,
        policy: EscalationPolicy,
        step: EscalationStep,
    ) -> int:
        if step.max_repeat_pages is not None:
            return int(step.max_repeat_pages)
        return int(policy.max_repeat_pages)

    @staticmethod
    def new_policy(*, name: str) -> EscalationPolicy:
        now = utc_now()
        return EscalationPolicy(
            id=make_id("epc"),
            name=name,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def new_step(
        *,
        step_index: int,
        target_kind,
        target_ref: str,
    ) -> EscalationStep:
        now = utc_now()
        return EscalationStep(
            id=make_id("est"),
            policy_id="",
            step_index=step_index,
            target_kind=target_kind,
            target_ref=target_ref,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _validate_policy(policy: EscalationPolicy, steps: tuple[EscalationStep, ...]) -> None:
        if not policy.name.strip():
            raise EscalationPolicyValidationError("Escalation policy name is required.")
        if policy.default_ack_timeout_seconds <= 0:
            raise EscalationPolicyValidationError(
                "Default acknowledgement timeout must be positive."
            )
        if policy.default_repeat_page_seconds <= 0:
            raise EscalationPolicyValidationError(
                "Default repeat-page interval must be positive."
            )
        if policy.max_repeat_pages < 0:
            raise EscalationPolicyValidationError("Max repeat pages cannot be negative.")
        if not steps:
            raise EscalationPolicyValidationError(
                "Escalation policies require at least one step."
            )
        ordered = sorted(steps, key=lambda item: item.step_index)
        for expected_index, step in enumerate(ordered):
            if step.step_index != expected_index:
                raise EscalationPolicyValidationError(
                    "Escalation steps must use contiguous step indexes starting at 0."
                )
            if not step.target_ref:
                raise EscalationPolicyValidationError(
                    f"Escalation step {step.step_index} requires a target reference."
                )
            if step.ack_timeout_seconds is not None and step.ack_timeout_seconds <= 0:
                raise EscalationPolicyValidationError(
                    f"Escalation step {step.step_index} has invalid ack timeout."
                )
            if step.repeat_page_seconds is not None and step.repeat_page_seconds <= 0:
                raise EscalationPolicyValidationError(
                    f"Escalation step {step.step_index} has invalid repeat-page interval."
                )
            if step.max_repeat_pages is not None and step.max_repeat_pages < 0:
                raise EscalationPolicyValidationError(
                    f"Escalation step {step.step_index} has invalid repeat-page limit."
                )
