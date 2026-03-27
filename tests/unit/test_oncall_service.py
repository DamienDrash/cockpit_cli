from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.ops.services.oncall_service import (
    OnCallService,
    OnCallValidationError,
)
from cockpit.ops.models.escalation import EscalationPolicy
from cockpit.ops.models.oncall import (
    OnCallSchedule,
    OperatorPerson,
    OperatorTeam,
    RotationRule,
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
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.core.enums import (
    RotationIntervalKind,
    ScheduleCoverageKind,
    TeamMembershipRole,
)


def _build_service(store: SQLiteStore) -> OnCallService:
    return OnCallService(
        person_repository=OperatorPersonRepository(store),
        team_repository=OperatorTeamRepository(store),
        membership_repository=TeamMembershipRepository(store),
        ownership_binding_repository=OwnershipBindingRepository(store),
        schedule_repository=OnCallScheduleRepository(store),
        rotation_repository=RotationRuleRepository(store),
        override_repository=ScheduleOverrideRepository(store),
        escalation_policy_repository=EscalationPolicyRepository(store),
    )


class OnCallServiceTests(unittest.TestCase):
    def test_rejects_duplicate_operator_handle(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            service = _build_service(store)
            service.save_person(
                OperatorPerson(
                    id="opr-1",
                    display_name="Alice Example",
                    handle="alice",
                )
            )

            with self.assertRaises(OnCallValidationError):
                service.save_person(
                    OperatorPerson(
                        id="opr-2",
                        display_name="Alice Clone",
                        handle="alice",
                    )
                )

    def test_rejects_overlapping_enabled_weekly_schedules(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            service = _build_service(store)
            service.save_team(OperatorTeam(id="team-1", name="Platform Ops"))
            service.save_schedule(
                OnCallSchedule(
                    id="sch-1",
                    team_id="team-1",
                    name="Business Hours",
                    timezone="UTC",
                    coverage_kind=ScheduleCoverageKind.WEEKLY_WINDOW,
                    schedule_config={
                        "days": [0, 1, 2, 3, 4],
                        "start_time": "09:00",
                        "end_time": "17:00",
                    },
                )
            )

            with self.assertRaises(OnCallValidationError):
                service.save_schedule(
                    OnCallSchedule(
                        id="sch-2",
                        team_id="team-1",
                        name="Overlapping Hours",
                        timezone="UTC",
                        coverage_kind=ScheduleCoverageKind.WEEKLY_WINDOW,
                        schedule_config={
                            "days": [1, 2],
                            "start_time": "12:00",
                            "end_time": "18:00",
                        },
                    )
                )

    def test_rejects_rotation_participant_outside_enabled_team_members(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            service = _build_service(store)
            EscalationPolicyRepository(store).save(
                EscalationPolicy(id="epc-1", name="Default")
            )
            service.save_team(
                OperatorTeam(
                    id="team-1",
                    name="Platform Ops",
                    default_escalation_policy_id="epc-1",
                )
            )
            service.save_person(
                OperatorPerson(
                    id="opr-1",
                    display_name="Alice Example",
                    handle="alice",
                )
            )
            service.save_schedule(
                OnCallSchedule(
                    id="sch-1",
                    team_id="team-1",
                    name="Primary",
                    coverage_kind=ScheduleCoverageKind.ALWAYS,
                )
            )
            service.save_membership(
                TeamMembership(
                    id="mem-1",
                    team_id="team-1",
                    person_id="opr-1",
                    role=TeamMembershipRole.MEMBER,
                )
            )

            with self.assertRaises(OnCallValidationError):
                service.save_rotation(
                    RotationRule(
                        id="rot-1",
                        schedule_id="sch-1",
                        name="Rotation",
                        participant_ids=("opr-2",),
                        anchor_at=datetime(2026, 3, 24, tzinfo=UTC),
                        interval_kind=RotationIntervalKind.DAYS,
                        interval_count=7,
                    )
                )


if __name__ == "__main__":
    unittest.main()
