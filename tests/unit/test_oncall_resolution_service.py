from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.ops.services.oncall_resolution_service import (
    OnCallResolutionService,
)
from cockpit.ops.models.oncall import (
    OnCallSchedule,
    OperatorContactTarget,
    OperatorPerson,
    OperatorTeam,
    OwnershipBinding,
    RotationRule,
    ScheduleOverride,
)
from cockpit.ops.repositories import (
    OnCallScheduleRepository,
    OperatorPersonRepository,
    OperatorTeamRepository,
    OwnershipBindingRepository,
    RotationRuleRepository,
    ScheduleOverrideRepository,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.core.enums import (
    ComponentKind,
    EscalationTargetKind,
    ResolutionOutcome,
    RotationIntervalKind,
    ScheduleCoverageKind,
    TargetRiskLevel,
)


def _build_service(store: SQLiteStore) -> OnCallResolutionService:
    return OnCallResolutionService(
        person_repository=OperatorPersonRepository(store),
        team_repository=OperatorTeamRepository(store),
        ownership_binding_repository=OwnershipBindingRepository(store),
        schedule_repository=OnCallScheduleRepository(store),
        rotation_repository=RotationRuleRepository(store),
        override_repository=ScheduleOverrideRepository(store),
    )


class OnCallResolutionServiceTests(unittest.TestCase):
    def test_resolves_most_specific_ownership_binding(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            team_repo = OperatorTeamRepository(store)
            binding_repo = OwnershipBindingRepository(store)
            team_repo.save(OperatorTeam(id="team-1", name="Platform Ops"))
            binding_repo.save(
                OwnershipBinding(
                    id="own-1",
                    name="Generic Docker",
                    team_id="team-1",
                    component_kind=ComponentKind.DOCKER_RUNTIME,
                    escalation_policy_id="epc-generic",
                )
            )
            binding_repo.save(
                OwnershipBinding(
                    id="own-2",
                    name="Specific Web",
                    team_id="team-1",
                    component_kind=ComponentKind.DOCKER_RUNTIME,
                    component_id="docker:web",
                    risk_level=TargetRiskLevel.PROD,
                    escalation_policy_id="epc-web",
                )
            )
            service = _build_service(store)

            resolution = service.resolve_ownership(
                component_kind=ComponentKind.DOCKER_RUNTIME,
                component_id="docker:web",
                risk_level=TargetRiskLevel.PROD,
            )

            self.assertEqual(resolution.outcome, ResolutionOutcome.RESOLVED)
            self.assertEqual(resolution.binding_id, "own-2")
            self.assertEqual(resolution.escalation_policy_id, "epc-web")

    def test_resolves_team_recipient_with_override(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            team_repo = OperatorTeamRepository(store)
            person_repo = OperatorPersonRepository(store)
            schedule_repo = OnCallScheduleRepository(store)
            rotation_repo = RotationRuleRepository(store)
            override_repo = ScheduleOverrideRepository(store)
            team_repo.save(OperatorTeam(id="team-1", name="Platform Ops"))
            person_repo.save(
                OperatorPerson(
                    id="opr-1",
                    display_name="Alice Example",
                    handle="alice",
                    contact_targets=(
                        OperatorContactTarget(channel_id="slack-alice", label="Slack"),
                    ),
                )
            )
            person_repo.save(
                OperatorPerson(
                    id="opr-2",
                    display_name="Bob Example",
                    handle="bob",
                    contact_targets=(
                        OperatorContactTarget(channel_id="slack-bob", label="Slack"),
                    ),
                )
            )
            schedule_repo.save(
                OnCallSchedule(
                    id="sch-1",
                    team_id="team-1",
                    name="Always",
                    coverage_kind=ScheduleCoverageKind.ALWAYS,
                )
            )
            rotation_repo.save(
                RotationRule(
                    id="rot-1",
                    schedule_id="sch-1",
                    name="Primary",
                    participant_ids=("opr-1",),
                    anchor_at=datetime(2026, 3, 24, tzinfo=UTC),
                    interval_kind=RotationIntervalKind.DAYS,
                    interval_count=7,
                )
            )
            override_repo.save(
                ScheduleOverride(
                    id="ovr-1",
                    schedule_id="sch-1",
                    replacement_person_id="opr-2",
                    starts_at=datetime(2026, 3, 24, 0, 0, tzinfo=UTC),
                    ends_at=datetime(2026, 3, 25, 0, 0, tzinfo=UTC),
                    reason="Vacation",
                )
            )
            service = _build_service(store)

            recipient = service.resolve_recipient(
                target_kind=EscalationTargetKind.TEAM,
                target_ref="team-1",
                effective_at=datetime(2026, 3, 24, 12, 0, tzinfo=UTC),
            )

            self.assertEqual(recipient.outcome, ResolutionOutcome.RESOLVED)
            self.assertEqual(recipient.person_id, "opr-2")
            self.assertEqual(recipient.channel_ids, ("slack-bob",))

    def test_blocks_conflicting_same_priority_overrides(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            team_repo = OperatorTeamRepository(store)
            person_repo = OperatorPersonRepository(store)
            schedule_repo = OnCallScheduleRepository(store)
            rotation_repo = RotationRuleRepository(store)
            override_repo = ScheduleOverrideRepository(store)
            team_repo.save(OperatorTeam(id="team-1", name="Platform Ops"))
            person_repo.save(
                OperatorPerson(id="opr-1", display_name="Alice", handle="alice")
            )
            person_repo.save(
                OperatorPerson(id="opr-2", display_name="Bob", handle="bob")
            )
            person_repo.save(
                OperatorPerson(id="opr-3", display_name="Carol", handle="carol")
            )
            schedule_repo.save(
                OnCallSchedule(
                    id="sch-1",
                    team_id="team-1",
                    name="Always",
                    coverage_kind=ScheduleCoverageKind.ALWAYS,
                )
            )
            rotation_repo.save(
                RotationRule(
                    id="rot-1",
                    schedule_id="sch-1",
                    name="Primary",
                    participant_ids=("opr-1",),
                    anchor_at=datetime(2026, 3, 24, tzinfo=UTC),
                    interval_kind=RotationIntervalKind.DAYS,
                    interval_count=7,
                )
            )
            for override_id, person_id in (("ovr-1", "opr-2"), ("ovr-2", "opr-3")):
                override_repo.save(
                    ScheduleOverride(
                        id=override_id,
                        schedule_id="sch-1",
                        replacement_person_id=person_id,
                        starts_at=datetime(2026, 3, 24, 0, 0, tzinfo=UTC),
                        ends_at=datetime(2026, 3, 25, 0, 0, tzinfo=UTC),
                        reason="Conflict",
                        priority=100,
                    )
                )
            service = _build_service(store)

            resolution = service.resolve_oncall(
                team_id="team-1",
                effective_at=datetime(2026, 3, 24, 12, 0, tzinfo=UTC),
            )

            self.assertEqual(resolution.outcome, ResolutionOutcome.BLOCKED)
            self.assertIn("Conflicting overrides", resolution.explanation)


if __name__ == "__main__":
    unittest.main()
