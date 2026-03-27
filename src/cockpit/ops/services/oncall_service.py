"""Configuration and validation service for on-call entities."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from cockpit.ops.models.oncall import (
    OnCallSchedule,
    OperatorPerson,
    OperatorTeam,
    OwnershipBinding,
    RotationRule,
    ScheduleOverride,
    TeamMembership,
)
from cockpit.ops.repositories import (
    EscalationPolicyRepository,
    OnCallScheduleRepository,
    OperatorPersonRepository,
    OperatorTeamRepository,
    OwnershipBindingRepository,
    RotationRuleRepository,
    ScheduleOverrideRepository,
    TeamMembershipRepository,
)
from cockpit.core.enums import ScheduleCoverageKind
from cockpit.core.utils import make_id, utc_now


class OnCallValidationError(ValueError):
    """Raised when Stage 3 on-call configuration is invalid."""


class OnCallService:
    """Persist and validate on-call configuration entities."""

    def __init__(
        self,
        *,
        person_repository: OperatorPersonRepository,
        team_repository: OperatorTeamRepository,
        membership_repository: TeamMembershipRepository,
        ownership_binding_repository: OwnershipBindingRepository,
        schedule_repository: OnCallScheduleRepository,
        rotation_repository: RotationRuleRepository,
        override_repository: ScheduleOverrideRepository,
        escalation_policy_repository: EscalationPolicyRepository,
    ) -> None:
        self._person_repository = person_repository
        self._team_repository = team_repository
        self._membership_repository = membership_repository
        self._ownership_binding_repository = ownership_binding_repository
        self._schedule_repository = schedule_repository
        self._rotation_repository = rotation_repository
        self._override_repository = override_repository
        self._escalation_policy_repository = escalation_policy_repository

    def list_people(self, *, enabled_only: bool = False) -> list[OperatorPerson]:
        return self._person_repository.list_all(enabled_only=enabled_only)

    def get_person(self, person_id: str) -> OperatorPerson | None:
        return self._person_repository.get(person_id)

    def save_person(self, person: OperatorPerson) -> OperatorPerson:
        if not person.display_name.strip():
            raise OnCallValidationError("Operator display name is required.")
        if not person.handle.strip():
            raise OnCallValidationError("Operator handle is required.")
        for existing in self._person_repository.list_all():
            if (
                existing.id != person.id
                and existing.handle.lower() == person.handle.lower()
            ):
                raise OnCallValidationError(
                    f"Operator handle '{person.handle}' is already in use."
                )
        now = utc_now()
        existing = self._person_repository.get(person.id)
        persisted = replace(
            person,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        self._person_repository.save(persisted)
        return self._person_repository.get(persisted.id) or persisted

    def delete_person(self, person_id: str) -> None:
        self._person_repository.delete(person_id)

    def list_teams(self, *, enabled_only: bool = False) -> list[OperatorTeam]:
        return self._team_repository.list_all(enabled_only=enabled_only)

    def get_team(self, team_id: str) -> OperatorTeam | None:
        return self._team_repository.get(team_id)

    def save_team(self, team: OperatorTeam) -> OperatorTeam:
        if not team.name.strip():
            raise OnCallValidationError("Team name is required.")
        if team.default_escalation_policy_id:
            policy = self._escalation_policy_repository.get(
                team.default_escalation_policy_id
            )
            if policy is None:
                raise OnCallValidationError(
                    f"Escalation policy '{team.default_escalation_policy_id}' was not found."
                )
        now = utc_now()
        existing = self._team_repository.get(team.id)
        persisted = replace(
            team,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        self._team_repository.save(persisted)
        return self._team_repository.get(persisted.id) or persisted

    def delete_team(self, team_id: str) -> None:
        self._team_repository.delete(team_id)

    def list_memberships(self, *, enabled_only: bool = False) -> list[TeamMembership]:
        return self._membership_repository.list_all(enabled_only=enabled_only)

    def list_memberships_for_team(
        self,
        team_id: str,
        *,
        enabled_only: bool = False,
    ) -> list[TeamMembership]:
        return self._membership_repository.list_for_team(
            team_id, enabled_only=enabled_only
        )

    def save_membership(self, membership: TeamMembership) -> TeamMembership:
        if self._team_repository.get(membership.team_id) is None:
            raise OnCallValidationError(f"Team '{membership.team_id}' was not found.")
        if self._person_repository.get(membership.person_id) is None:
            raise OnCallValidationError(
                f"Operator '{membership.person_id}' was not found."
            )
        for existing in self._membership_repository.list_for_team(membership.team_id):
            if (
                existing.id != membership.id
                and existing.person_id == membership.person_id
            ):
                raise OnCallValidationError("Duplicate team membership is not allowed.")
        now = utc_now()
        existing = next(
            (
                item
                for item in self._membership_repository.list_all()
                if item.id == membership.id
            ),
            None,
        )
        persisted = replace(
            membership,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        self._membership_repository.save(persisted)
        return persisted

    def delete_membership(self, membership_id: str) -> None:
        self._membership_repository.delete(membership_id)

    def list_ownership_bindings(
        self, *, enabled_only: bool = False
    ) -> list[OwnershipBinding]:
        return self._ownership_binding_repository.list_all(enabled_only=enabled_only)

    def save_ownership_binding(self, binding: OwnershipBinding) -> OwnershipBinding:
        if self._team_repository.get(binding.team_id) is None:
            raise OnCallValidationError(f"Team '{binding.team_id}' was not found.")
        if not any(
            (
                binding.component_kind is not None,
                bool(binding.component_id),
                binding.subject_kind is not None,
                bool(binding.subject_ref),
                binding.risk_level is not None,
            )
        ):
            raise OnCallValidationError(
                "Ownership bindings need at least one matching field."
            )
        if binding.escalation_policy_id:
            policy = self._escalation_policy_repository.get(
                binding.escalation_policy_id
            )
            if policy is None:
                raise OnCallValidationError(
                    f"Escalation policy '{binding.escalation_policy_id}' was not found."
                )
        now = utc_now()
        existing = self._ownership_binding_repository.get(binding.id)
        persisted = replace(
            binding,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        self._ownership_binding_repository.save(persisted)
        return self._ownership_binding_repository.get(persisted.id) or persisted

    def delete_ownership_binding(self, binding_id: str) -> None:
        self._ownership_binding_repository.delete(binding_id)

    def list_schedules(self, *, enabled_only: bool = False) -> list[OnCallSchedule]:
        return self._schedule_repository.list_all(enabled_only=enabled_only)

    def list_schedules_for_team(
        self,
        team_id: str,
        *,
        enabled_only: bool = False,
    ) -> list[OnCallSchedule]:
        return self._schedule_repository.list_for_team(
            team_id, enabled_only=enabled_only
        )

    def save_schedule(self, schedule: OnCallSchedule) -> OnCallSchedule:
        if self._team_repository.get(schedule.team_id) is None:
            raise OnCallValidationError(f"Team '{schedule.team_id}' was not found.")
        if not schedule.name.strip():
            raise OnCallValidationError("Schedule name is required.")
        self._validate_schedule(schedule)
        now = utc_now()
        existing = self._schedule_repository.get(schedule.id)
        persisted = replace(
            schedule,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        self._schedule_repository.save(persisted)
        return self._schedule_repository.get(persisted.id) or persisted

    def delete_schedule(self, schedule_id: str) -> None:
        self._schedule_repository.delete(schedule_id)

    def list_rotations(self, schedule_id: str) -> list[RotationRule]:
        return self._rotation_repository.list_for_schedule(schedule_id)

    def save_rotation(self, rotation: RotationRule) -> RotationRule:
        schedule = self._schedule_repository.get(rotation.schedule_id)
        if schedule is None:
            raise OnCallValidationError(
                f"Schedule '{rotation.schedule_id}' was not found."
            )
        if not rotation.name.strip():
            raise OnCallValidationError("Rotation name is required.")
        if not rotation.participant_ids:
            raise OnCallValidationError("Rotation requires at least one participant.")
        if rotation.anchor_at is None:
            raise OnCallValidationError("Rotation anchor time is required.")
        if rotation.interval_count <= 0:
            raise OnCallValidationError("Rotation interval count must be positive.")
        memberships = {
            item.person_id
            for item in self._membership_repository.list_for_team(
                schedule.team_id, enabled_only=True
            )
        }
        missing = [
            person_id
            for person_id in rotation.participant_ids
            if person_id not in memberships
        ]
        if missing:
            raise OnCallValidationError(
                f"Rotation participants are not enabled team members: {', '.join(missing)}."
            )
        enabled_rotations = [
            item
            for item in self._rotation_repository.list_for_schedule(
                schedule.id, enabled_only=True
            )
            if item.id != rotation.id
        ]
        if rotation.enabled and enabled_rotations:
            raise OnCallValidationError(
                "Only one enabled rotation per schedule is supported in Stage 3."
            )
        now = utc_now()
        existing = self._rotation_repository.get(rotation.id)
        persisted = replace(
            rotation,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        self._rotation_repository.save(persisted)
        return self._rotation_repository.get(persisted.id) or persisted

    def delete_rotation(self, rotation_id: str) -> None:
        self._rotation_repository.delete(rotation_id)

    def list_overrides(self, schedule_id: str) -> list[ScheduleOverride]:
        return self._override_repository.list_for_schedule(schedule_id)

    def save_override(self, override: ScheduleOverride) -> ScheduleOverride:
        schedule = self._schedule_repository.get(override.schedule_id)
        if schedule is None:
            raise OnCallValidationError(
                f"Schedule '{override.schedule_id}' was not found."
            )
        if self._person_repository.get(override.replacement_person_id) is None:
            raise OnCallValidationError(
                f"Replacement operator '{override.replacement_person_id}' was not found."
            )
        if (
            override.replaced_person_id
            and self._person_repository.get(override.replaced_person_id) is None
        ):
            raise OnCallValidationError(
                f"Replaced operator '{override.replaced_person_id}' was not found."
            )
        if override.starts_at >= override.ends_at:
            raise OnCallValidationError("Override start time must be before end time.")
        for existing in self._override_repository.list_for_schedule(
            schedule.id, enabled_only=True
        ):
            if existing.id == override.id or not override.enabled:
                continue
            if existing.priority != override.priority:
                continue
            if self._ranges_overlap(
                existing.starts_at,
                existing.ends_at,
                override.starts_at,
                override.ends_at,
            ):
                raise OnCallValidationError(
                    "Overlapping overrides with the same priority are not allowed."
                )
        now = utc_now()
        existing = self._override_repository.get(override.id)
        persisted = replace(
            override,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        self._override_repository.save(persisted)
        return self._override_repository.get(persisted.id) or persisted

    def delete_override(self, override_id: str) -> None:
        self._override_repository.delete(override_id)

    @staticmethod
    def new_person(*, display_name: str, handle: str) -> OperatorPerson:
        now = utc_now()
        return OperatorPerson(
            id=make_id("opr"),
            display_name=display_name,
            handle=handle,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def new_team(*, name: str, description: str | None = None) -> OperatorTeam:
        now = utc_now()
        return OperatorTeam(
            id=make_id("team"),
            name=name,
            description=description,
            created_at=now,
            updated_at=now,
        )

    def _validate_schedule(self, schedule: OnCallSchedule) -> None:
        self._schedule_windows(schedule)
        if not schedule.enabled:
            return
        for existing in self._schedule_repository.list_for_team(
            schedule.team_id, enabled_only=True
        ):
            if existing.id == schedule.id:
                continue
            if self._schedules_overlap(existing, schedule):
                raise OnCallValidationError(
                    f"Schedule '{schedule.name}' overlaps enabled schedule '{existing.name}'."
                )

    def _schedules_overlap(self, left: OnCallSchedule, right: OnCallSchedule) -> bool:
        left_windows = self._schedule_windows(left)
        right_windows = self._schedule_windows(right)
        for left_start, left_end in left_windows:
            for right_start, right_end in right_windows:
                if left_start < right_end and right_start < left_end:
                    return True
        return False

    def _schedule_windows(self, schedule: OnCallSchedule) -> list[tuple[int, int]]:
        if schedule.coverage_kind is ScheduleCoverageKind.ALWAYS:
            return [(0, 7 * 24 * 60)]
        config = schedule.schedule_config
        raw_days = config.get("days")
        if not isinstance(raw_days, list) or not raw_days:
            raise OnCallValidationError(
                "Weekly schedules require a non-empty 'days' list."
            )
        days = []
        for item in raw_days:
            if not isinstance(item, int) or item < 0 or item > 6:
                raise OnCallValidationError(
                    "Schedule days must be integers from 0 to 6."
                )
            days.append(item)
        start_time = self._parse_time(config.get("start_time"))
        end_time = self._parse_time(config.get("end_time"))
        start_minutes = start_time[0] * 60 + start_time[1]
        end_minutes = end_time[0] * 60 + end_time[1]
        if start_minutes == end_minutes:
            raise OnCallValidationError(
                "Schedule start and end time cannot be identical."
            )
        windows: list[tuple[int, int]] = []
        for day in days:
            day_offset = day * 24 * 60
            if start_minutes < end_minutes:
                windows.append((day_offset + start_minutes, day_offset + end_minutes))
                continue
            windows.append((day_offset + start_minutes, day_offset + 24 * 60))
            next_day = ((day + 1) % 7) * 24 * 60
            windows.append((next_day, next_day + end_minutes))
        return windows

    @staticmethod
    def _parse_time(raw_value: object) -> tuple[int, int]:
        if not isinstance(raw_value, str) or ":" not in raw_value:
            raise OnCallValidationError("Times must use HH:MM format.")
        hour_text, minute_text = raw_value.split(":", 1)
        if not hour_text.isdigit() or not minute_text.isdigit():
            raise OnCallValidationError("Times must use HH:MM format.")
        hour = int(hour_text)
        minute = int(minute_text)
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise OnCallValidationError("Schedule times must be valid clock values.")
        return hour, minute

    @staticmethod
    def _ranges_overlap(
        left_start: datetime,
        left_end: datetime,
        right_start: datetime,
        right_end: datetime,
    ) -> bool:
        return left_start < right_end and right_start < left_end
