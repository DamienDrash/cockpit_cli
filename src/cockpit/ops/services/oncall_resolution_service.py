"""Deterministic ownership and on-call resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cockpit.ops.models.oncall import (
    OnCallResolution,
    OnCallSchedule,
    OperatorPerson,
    OwnershipResolution,
    RotationRule,
)
from cockpit.ops.repositories import (
    OnCallScheduleRepository,
    OperatorPersonRepository,
    OperatorTeamRepository,
    OwnershipBindingRepository,
    RotationRuleRepository,
    ScheduleOverrideRepository,
)
from cockpit.core.enums import (
    ComponentKind,
    EscalationTargetKind,
    OwnershipSubjectKind,
    ResolutionOutcome,
    RotationIntervalKind,
    ScheduleCoverageKind,
    TargetRiskLevel,
)
from cockpit.core.utils import serialize_contract


@dataclass(slots=True, frozen=True)
class ResolvedEscalationRecipient:
    """Resolved target for an escalation step."""

    outcome: ResolutionOutcome
    target_kind: EscalationTargetKind
    target_ref: str
    person_id: str | None
    channel_ids: tuple[str, ...]
    explanation: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


class OnCallResolutionService:
    """Resolve ownership, schedules, and effective recipients."""

    def __init__(
        self,
        *,
        person_repository: OperatorPersonRepository,
        team_repository: OperatorTeamRepository,
        ownership_binding_repository: OwnershipBindingRepository,
        schedule_repository: OnCallScheduleRepository,
        rotation_repository: RotationRuleRepository,
        override_repository: ScheduleOverrideRepository,
    ) -> None:
        self._person_repository = person_repository
        self._team_repository = team_repository
        self._ownership_binding_repository = ownership_binding_repository
        self._schedule_repository = schedule_repository
        self._rotation_repository = rotation_repository
        self._override_repository = override_repository

    def resolve_ownership(
        self,
        *,
        component_kind: ComponentKind,
        component_id: str,
        subject_kind: OwnershipSubjectKind | None = None,
        subject_ref: str | None = None,
        risk_level: TargetRiskLevel | None = None,
    ) -> OwnershipResolution:
        matches = []
        for binding in self._ownership_binding_repository.list_all(enabled_only=True):
            if not self._binding_matches(
                binding_component_kind=binding.component_kind,
                binding_component_id=binding.component_id,
                binding_subject_kind=binding.subject_kind,
                binding_subject_ref=binding.subject_ref,
                binding_risk_level=binding.risk_level,
                component_kind=component_kind,
                component_id=component_id,
                subject_kind=subject_kind,
                subject_ref=subject_ref,
                risk_level=risk_level,
            ):
                continue
            matches.append((self._binding_specificity(binding), binding))
        if not matches:
            return OwnershipResolution(
                outcome=ResolutionOutcome.UNASSIGNED,
                explanation=f"No ownership binding matched {component_id}.",
            )
        matches.sort(key=lambda item: item[0], reverse=True)
        top_score = matches[0][0]
        top_bindings = [binding for score, binding in matches if score == top_score]
        if len(top_bindings) > 1:
            return OwnershipResolution(
                outcome=ResolutionOutcome.BLOCKED,
                explanation=f"Multiple ownership bindings matched {component_id}.",
            )
        binding = top_bindings[0]
        team = self._team_repository.get(binding.team_id)
        if team is None or not team.enabled:
            return OwnershipResolution(
                outcome=ResolutionOutcome.BLOCKED,
                binding_id=binding.id,
                explanation=f"Bound team '{binding.team_id}' is not available.",
            )
        escalation_policy_id = (
            binding.escalation_policy_id or team.default_escalation_policy_id
        )
        if not escalation_policy_id:
            return OwnershipResolution(
                outcome=ResolutionOutcome.BLOCKED,
                team_id=team.id,
                binding_id=binding.id,
                explanation=f"Team '{team.name}' has no escalation policy.",
            )
        return OwnershipResolution(
            outcome=ResolutionOutcome.RESOLVED,
            team_id=team.id,
            escalation_policy_id=escalation_policy_id,
            binding_id=binding.id,
            explanation=f"Ownership resolved via binding '{binding.name}'.",
        )

    def resolve_oncall(
        self, *, team_id: str, effective_at: datetime
    ) -> OnCallResolution:
        team = self._team_repository.get(team_id)
        if team is None or not team.enabled:
            return OnCallResolution(
                outcome=ResolutionOutcome.BLOCKED,
                team_id=team_id,
                explanation=f"Team '{team_id}' is not available.",
            )
        schedules = [
            schedule
            for schedule in self._schedule_repository.list_for_team(
                team.id, enabled_only=True
            )
            if self._schedule_matches(schedule, effective_at)
        ]
        if not schedules:
            return OnCallResolution(
                outcome=ResolutionOutcome.UNASSIGNED,
                team_id=team.id,
                explanation=f"No active schedule matched team '{team.name}'.",
            )
        if len(schedules) > 1:
            return OnCallResolution(
                outcome=ResolutionOutcome.BLOCKED,
                team_id=team.id,
                explanation=f"Multiple schedules matched team '{team.name}'.",
            )
        schedule = schedules[0]
        rotations = self._rotation_repository.list_for_schedule(
            schedule.id, enabled_only=True
        )
        if not rotations:
            return OnCallResolution(
                outcome=ResolutionOutcome.BLOCKED,
                team_id=team.id,
                schedule_id=schedule.id,
                explanation=f"Schedule '{schedule.name}' has no enabled rotation.",
            )
        if len(rotations) > 1:
            return OnCallResolution(
                outcome=ResolutionOutcome.BLOCKED,
                team_id=team.id,
                schedule_id=schedule.id,
                explanation=f"Schedule '{schedule.name}' has multiple enabled rotations.",
            )
        rotation = rotations[0]
        base_person_id = self._resolve_rotation_person(rotation, effective_at)
        active_overrides = [
            override
            for override in self._override_repository.list_active_for_schedule(
                schedule.id,
                effective_at=effective_at,
            )
            if override.replaced_person_id is None
            or override.replaced_person_id == base_person_id
        ]
        if active_overrides:
            top_priority = active_overrides[0].priority
            top = [item for item in active_overrides if item.priority == top_priority]
            if len(top) > 1:
                return OnCallResolution(
                    outcome=ResolutionOutcome.BLOCKED,
                    team_id=team.id,
                    schedule_id=schedule.id,
                    rotation_id=rotation.id,
                    explanation=f"Conflicting overrides matched schedule '{schedule.name}'.",
                )
            override = top[0]
            base_person_id = override.replacement_person_id
            override_id = override.id
        else:
            override_id = None
        person = self._person_repository.get(base_person_id)
        if person is None or not person.enabled:
            return OnCallResolution(
                outcome=ResolutionOutcome.BLOCKED,
                team_id=team.id,
                schedule_id=schedule.id,
                rotation_id=rotation.id,
                override_id=override_id,
                explanation=f"Resolved operator '{base_person_id}' is not available.",
            )
        return OnCallResolution(
            outcome=ResolutionOutcome.RESOLVED,
            team_id=team.id,
            schedule_id=schedule.id,
            rotation_id=rotation.id,
            person_id=person.id,
            override_id=override_id,
            explanation=f"Resolved operator '{person.handle}' for team '{team.name}'.",
        )

    def resolve_recipient(
        self,
        *,
        target_kind: EscalationTargetKind,
        target_ref: str,
        effective_at: datetime,
    ) -> ResolvedEscalationRecipient:
        if target_kind is EscalationTargetKind.CHANNEL:
            return ResolvedEscalationRecipient(
                outcome=ResolutionOutcome.RESOLVED,
                target_kind=target_kind,
                target_ref=target_ref,
                person_id=None,
                channel_ids=(target_ref,),
                explanation=f"Fixed channel '{target_ref}' selected.",
            )
        if target_kind is EscalationTargetKind.PERSON:
            person = self._person_repository.get(target_ref)
            if person is None or not person.enabled:
                return ResolvedEscalationRecipient(
                    outcome=ResolutionOutcome.BLOCKED,
                    target_kind=target_kind,
                    target_ref=target_ref,
                    person_id=None,
                    channel_ids=(),
                    explanation=f"Operator '{target_ref}' is not available.",
                )
            channels = self._channel_ids_for_person(person)
            if not channels:
                return ResolvedEscalationRecipient(
                    outcome=ResolutionOutcome.BLOCKED,
                    target_kind=target_kind,
                    target_ref=target_ref,
                    person_id=person.id,
                    channel_ids=(),
                    explanation=f"Operator '{person.handle}' has no enabled contact targets.",
                )
            return ResolvedEscalationRecipient(
                outcome=ResolutionOutcome.RESOLVED,
                target_kind=target_kind,
                target_ref=target_ref,
                person_id=person.id,
                channel_ids=channels,
                explanation=f"Paging operator '{person.handle}'.",
            )
        team_resolution = self.resolve_oncall(
            team_id=target_ref, effective_at=effective_at
        )
        if (
            team_resolution.outcome is not ResolutionOutcome.RESOLVED
            or not team_resolution.person_id
        ):
            return ResolvedEscalationRecipient(
                outcome=team_resolution.outcome,
                target_kind=target_kind,
                target_ref=target_ref,
                person_id=None,
                channel_ids=(),
                explanation=team_resolution.explanation,
            )
        person = self._person_repository.get(team_resolution.person_id)
        if person is None or not person.enabled:
            return ResolvedEscalationRecipient(
                outcome=ResolutionOutcome.BLOCKED,
                target_kind=target_kind,
                target_ref=target_ref,
                person_id=team_resolution.person_id,
                channel_ids=(),
                explanation=f"Resolved operator '{team_resolution.person_id}' is not available.",
            )
        channels = self._channel_ids_for_person(person)
        if not channels:
            return ResolvedEscalationRecipient(
                outcome=ResolutionOutcome.BLOCKED,
                target_kind=target_kind,
                target_ref=target_ref,
                person_id=person.id,
                channel_ids=(),
                explanation=f"Resolved operator '{person.handle}' has no enabled contact targets.",
            )
        return ResolvedEscalationRecipient(
            outcome=ResolutionOutcome.RESOLVED,
            target_kind=target_kind,
            target_ref=target_ref,
            person_id=person.id,
            channel_ids=channels,
            explanation=team_resolution.explanation,
        )

    @staticmethod
    def _binding_matches(
        *,
        binding_component_kind: ComponentKind | None,
        binding_component_id: str | None,
        binding_subject_kind: OwnershipSubjectKind | None,
        binding_subject_ref: str | None,
        binding_risk_level: TargetRiskLevel | None,
        component_kind: ComponentKind,
        component_id: str,
        subject_kind: OwnershipSubjectKind | None,
        subject_ref: str | None,
        risk_level: TargetRiskLevel | None,
    ) -> bool:
        if (
            binding_component_kind is not None
            and binding_component_kind is not component_kind
        ):
            return False
        if binding_component_id is not None and binding_component_id != component_id:
            return False
        if (
            binding_subject_kind is not None
            and binding_subject_kind is not subject_kind
        ):
            return False
        if binding_subject_ref is not None and binding_subject_ref != subject_ref:
            return False
        if binding_risk_level is not None and binding_risk_level is not risk_level:
            return False
        return True

    @staticmethod
    def _binding_specificity(binding) -> int:
        score = 0
        if binding.component_id:
            score += 100
        if binding.subject_ref:
            score += 80
        if binding.component_kind is not None:
            score += 40
        if binding.subject_kind is not None:
            score += 20
        if binding.risk_level is not None:
            score += 10
        return score

    def _schedule_matches(
        self, schedule: OnCallSchedule, effective_at: datetime
    ) -> bool:
        if schedule.coverage_kind is ScheduleCoverageKind.ALWAYS:
            return True
        zone = self._zoneinfo_for(schedule.timezone)
        local_dt = effective_at.astimezone(zone)
        weekday = local_dt.weekday()
        minute_of_day = local_dt.hour * 60 + local_dt.minute
        config = schedule.schedule_config
        raw_days = config.get("days", [])
        if not isinstance(raw_days, list):
            return False
        days = {item for item in raw_days if isinstance(item, int)}
        start_hour, start_minute = self._parse_time(config.get("start_time", "00:00"))
        end_hour, end_minute = self._parse_time(config.get("end_time", "23:59"))
        start_minutes = start_hour * 60 + start_minute
        end_minutes = end_hour * 60 + end_minute
        if start_minutes < end_minutes:
            return weekday in days and start_minutes <= minute_of_day < end_minutes
        previous_weekday = (weekday - 1) % 7
        return (weekday in days and minute_of_day >= start_minutes) or (
            previous_weekday in days and minute_of_day < end_minutes
        )

    def _resolve_rotation_person(
        self, rotation: RotationRule, effective_at: datetime
    ) -> str:
        if not rotation.participant_ids:
            msg = "Rotation has no participants."
            raise RuntimeError(msg)
        anchor_at = rotation.anchor_at or effective_at.astimezone(UTC)
        elapsed_seconds = max(
            0.0,
            (effective_at.astimezone(UTC) - anchor_at.astimezone(UTC)).total_seconds(),
        )
        interval_seconds = self._interval_seconds(
            rotation.interval_kind, rotation.interval_count
        )
        step_index = (
            int(elapsed_seconds // interval_seconds) if interval_seconds > 0 else 0
        )
        return rotation.participant_ids[step_index % len(rotation.participant_ids)]

    @staticmethod
    def _interval_seconds(kind: RotationIntervalKind, count: int) -> int:
        if kind is RotationIntervalKind.HOURS:
            return max(1, count) * 60 * 60
        if kind is RotationIntervalKind.WEEKS:
            return max(1, count) * 7 * 24 * 60 * 60
        return max(1, count) * 24 * 60 * 60

    @staticmethod
    def _channel_ids_for_person(person: OperatorPerson) -> tuple[str, ...]:
        targets = sorted(
            (
                target
                for target in person.contact_targets
                if target.enabled and target.channel_id
            ),
            key=lambda item: (item.priority, item.channel_id),
        )
        return tuple(target.channel_id for target in targets)

    @staticmethod
    def _parse_time(raw_value: object) -> tuple[int, int]:
        if not isinstance(raw_value, str) or ":" not in raw_value:
            return (0, 0)
        hour_text, minute_text = raw_value.split(":", 1)
        if not hour_text.isdigit() or not minute_text.isdigit():
            return (0, 0)
        hour = min(max(int(hour_text), 0), 23)
        minute = min(max(int(minute_text), 0), 59)
        return (hour, minute)

    @staticmethod
    def _zoneinfo_for(name: str) -> ZoneInfo:
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")
