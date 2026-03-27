"""SQLite repositories for on-call management."""

from __future__ import annotations

from datetime import datetime
import json

from cockpit.ops.models.oncall import (
    OnCallSchedule,
    OperatorContactTarget,
    OperatorPerson,
    OperatorTeam,
    OwnershipBinding,
    RotationRule,
    ScheduleOverride,
    TeamMembership,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.core.enums import (
    ComponentKind,
    OwnershipSubjectKind,
    RotationIntervalKind,
    ScheduleCoverageKind,
    TargetRiskLevel,
    TeamMembershipRole,
)
from cockpit.core.utils import utc_now


def _load_json(raw_value: str) -> dict[str, object]:
    payload = json.loads(raw_value)
    if not isinstance(payload, dict):
        msg = "Expected JSON object payload."
        raise TypeError(msg)
    return payload


def _decode_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class OperatorPersonRepository:
    """Persist operator personas and contact metadata."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, person: OperatorPerson) -> None:
        payload = person.to_dict()
        created_at = person.created_at or utc_now()
        updated_at = person.updated_at or created_at
        self._store.execute(
            """
            INSERT INTO operator_people (
                id,
                display_name,
                handle,
                enabled,
                timezone,
                contact_targets_json,
                metadata_json,
                payload_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                display_name = excluded.display_name,
                handle = excluded.handle,
                enabled = excluded.enabled,
                timezone = excluded.timezone,
                contact_targets_json = excluded.contact_targets_json,
                metadata_json = excluded.metadata_json,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                person.id,
                person.display_name,
                person.handle,
                int(person.enabled),
                person.timezone,
                json.dumps(
                    [item.to_dict() for item in person.contact_targets], sort_keys=True
                ),
                json.dumps(person.metadata, sort_keys=True),
                json.dumps(payload, sort_keys=True),
                created_at.isoformat(),
                updated_at.isoformat(),
            ),
        )

    def get(self, person_id: str) -> OperatorPerson | None:
        row = self._store.fetchone(
            "SELECT * FROM operator_people WHERE id = ?", (person_id,)
        )
        return _operator_person_from_row(row) if row is not None else None

    def list_all(self, *, enabled_only: bool = False) -> list[OperatorPerson]:
        sql = "SELECT * FROM operator_people"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY display_name ASC"
        rows = self._store.fetchall(sql)
        return [_operator_person_from_row(row) for row in rows]


class OperatorTeamRepository:
    """Persist operator teams."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, team: OperatorTeam) -> None:
        payload = team.to_dict()
        created_at = team.created_at or utc_now()
        updated_at = team.updated_at or created_at
        self._store.execute(
            """
            INSERT INTO operator_teams (
                id,
                name,
                enabled,
                description,
                default_escalation_policy_id,
                payload_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                enabled = excluded.enabled,
                description = excluded.description,
                default_escalation_policy_id = excluded.default_escalation_policy_id,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                team.id,
                team.name,
                int(team.enabled),
                team.description,
                team.default_escalation_policy_id,
                json.dumps(payload, sort_keys=True),
                created_at.isoformat(),
                updated_at.isoformat(),
            ),
        )

    def get(self, team_id: str) -> OperatorTeam | None:
        row = self._store.fetchone(
            "SELECT * FROM operator_teams WHERE id = ?", (team_id,)
        )
        return _operator_team_from_row(row) if row is not None else None

    def list_all(self, *, enabled_only: bool = False) -> list[OperatorTeam]:
        sql = "SELECT * FROM operator_teams"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY name ASC"
        rows = self._store.fetchall(sql)
        return [_operator_team_from_row(row) for row in rows]


class TeamMembershipRepository:
    """Persist team membership and roles."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, membership: TeamMembership) -> None:
        payload = membership.to_dict()
        created_at = membership.created_at or utc_now()
        updated_at = membership.updated_at or created_at
        self._store.execute(
            """
            INSERT INTO team_memberships (
                id,
                team_id,
                person_id,
                role,
                enabled,
                payload_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                team_id = excluded.team_id,
                person_id = excluded.person_id,
                role = excluded.role,
                enabled = excluded.enabled,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                membership.id,
                membership.team_id,
                membership.person_id,
                membership.role.value,
                int(membership.enabled),
                json.dumps(payload, sort_keys=True),
                created_at.isoformat(),
                updated_at.isoformat(),
            ),
        )

    def get(self, membership_id: str) -> TeamMembership | None:
        row = self._store.fetchone(
            "SELECT * FROM team_memberships WHERE id = ?", (membership_id,)
        )
        return _team_membership_from_row(row) if row is not None else None

    def list_all(self, *, enabled_only: bool = False) -> list[TeamMembership]:
        sql = "SELECT * FROM team_memberships"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY id ASC"
        rows = self._store.fetchall(sql)
        return [_team_membership_from_row(row) for row in rows]

    def list_for_team(
        self, team_id: str, *, enabled_only: bool = False
    ) -> list[TeamMembership]:
        sql = "SELECT * FROM team_memberships WHERE team_id = ?"
        if enabled_only:
            sql += " AND enabled = 1"
        sql += " ORDER BY id ASC"
        rows = self._store.fetchall(sql, (team_id,))
        return [_team_membership_from_row(row) for row in rows]

    def list_for_person(self, person_id: str) -> list[TeamMembership]:
        rows = self._store.fetchall(
            "SELECT * FROM team_memberships WHERE person_id = ? ORDER BY id ASC",
            (person_id,),
        )
        return [_team_membership_from_row(row) for row in rows]


class OwnershipBindingRepository:
    """Persist component ownership bindings."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, binding: OwnershipBinding) -> None:
        payload = binding.to_dict()
        created_at = binding.created_at or utc_now()
        updated_at = binding.updated_at or created_at
        self._store.execute(
            """
            INSERT INTO ownership_bindings (
                id,
                name,
                team_id,
                enabled,
                component_kind,
                component_id,
                subject_kind,
                subject_ref,
                risk_level,
                escalation_policy_id,
                payload_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                team_id = excluded.team_id,
                enabled = excluded.enabled,
                component_kind = excluded.component_kind,
                component_id = excluded.component_id,
                subject_kind = excluded.subject_kind,
                subject_ref = excluded.subject_ref,
                risk_level = excluded.risk_level,
                escalation_policy_id = excluded.escalation_policy_id,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                binding.id,
                binding.name,
                binding.team_id,
                int(binding.enabled),
                binding.component_kind.value if binding.component_kind else None,
                binding.component_id,
                binding.subject_kind.value if binding.subject_kind else None,
                binding.subject_ref,
                binding.risk_level.value if binding.risk_level else None,
                binding.escalation_policy_id,
                json.dumps(payload, sort_keys=True),
                created_at.isoformat(),
                updated_at.isoformat(),
            ),
        )

    def get(self, binding_id: str) -> OwnershipBinding | None:
        row = self._store.fetchone(
            "SELECT * FROM ownership_bindings WHERE id = ?", (binding_id,)
        )
        return _ownership_binding_from_row(row) if row is not None else None

    def list_all(self, *, enabled_only: bool = False) -> list[OwnershipBinding]:
        sql = "SELECT * FROM ownership_bindings"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY name ASC"
        rows = self._store.fetchall(sql)
        return [_ownership_binding_from_row(row) for row in rows]

    def find_for_subject(
        self, subject_kind: OwnershipSubjectKind, subject_ref: str
    ) -> list[OwnershipBinding]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM ownership_bindings
            WHERE enabled = 1
              AND subject_kind = ?
              AND subject_ref = ?
            ORDER BY risk_level DESC, id ASC
            """,
            (subject_kind.value, subject_ref),
        )
        return [_ownership_binding_from_row(row) for row in rows]


class OnCallScheduleRepository:
    """Persist on-call schedules."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, schedule: OnCallSchedule) -> None:
        payload = schedule.to_dict()
        created_at = schedule.created_at or utc_now()
        updated_at = schedule.updated_at or created_at
        self._store.execute(
            """
            INSERT INTO oncall_schedules (
                id,
                team_id,
                name,
                timezone,
                enabled,
                coverage_kind,
                schedule_config_json,
                payload_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                team_id = excluded.team_id,
                name = excluded.name,
                timezone = excluded.timezone,
                enabled = excluded.enabled,
                coverage_kind = excluded.coverage_kind,
                schedule_config_json = excluded.schedule_config_json,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                schedule.id,
                schedule.team_id,
                schedule.name,
                schedule.timezone,
                int(schedule.enabled),
                schedule.coverage_kind.value,
                json.dumps(schedule.schedule_config, sort_keys=True),
                json.dumps(payload, sort_keys=True),
                created_at.isoformat(),
                updated_at.isoformat(),
            ),
        )

    def list_for_team(
        self, team_id: str, *, enabled_only: bool = False
    ) -> list[OnCallSchedule]:
        sql = "SELECT * FROM oncall_schedules WHERE team_id = ?"
        if enabled_only:
            sql += " AND enabled = 1"
        sql += " ORDER BY name ASC"
        rows = self._store.fetchall(sql, (team_id,))
        return [_oncall_schedule_from_row(row) for row in rows]

    def get(self, schedule_id: str) -> OnCallSchedule | None:
        row = self._store.fetchone(
            "SELECT * FROM oncall_schedules WHERE id = ?", (schedule_id,)
        )
        return _oncall_schedule_from_row(row) if row is not None else None


class RotationRuleRepository:
    """Persist rotation rules."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, rule: RotationRule) -> None:
        payload = rule.to_dict()
        created_at = rule.created_at or utc_now()
        updated_at = rule.updated_at or created_at
        self._store.execute(
            """
            INSERT INTO schedule_rotations (
                id,
                schedule_id,
                name,
                participant_ids_json,
                enabled,
                anchor_at,
                interval_kind,
                interval_count,
                handoff_time,
                payload_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                schedule_id = excluded.schedule_id,
                name = excluded.name,
                participant_ids_json = excluded.participant_ids_json,
                enabled = excluded.enabled,
                anchor_at = excluded.anchor_at,
                interval_kind = excluded.interval_kind,
                interval_count = excluded.interval_count,
                handoff_time = excluded.handoff_time,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                rule.id,
                rule.schedule_id,
                rule.name,
                json.dumps(list(rule.participant_ids), sort_keys=True),
                int(rule.enabled),
                rule.anchor_at.isoformat() if rule.anchor_at else None,
                rule.interval_kind.value,
                int(rule.interval_count),
                rule.handoff_time,
                json.dumps(payload, sort_keys=True),
                created_at.isoformat(),
                updated_at.isoformat(),
            ),
        )

    def list_for_schedule(
        self, schedule_id: str, *, enabled_only: bool = False
    ) -> list[RotationRule]:
        sql = "SELECT * FROM schedule_rotations WHERE schedule_id = ?"
        if enabled_only:
            sql += " AND enabled = 1"
        sql += " ORDER BY name ASC"
        rows = self._store.fetchall(sql, (schedule_id,))
        return [_rotation_rule_from_row(row) for row in rows]


class ScheduleOverrideRepository:
    """Persist schedule overrides."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, override: ScheduleOverride) -> None:
        payload = override.to_dict()
        created_at = override.created_at or utc_now()
        updated_at = override.updated_at or created_at
        self._store.execute(
            """
            INSERT INTO schedule_overrides (
                id,
                schedule_id,
                replacement_person_id,
                replaced_person_id,
                starts_at,
                ends_at,
                reason,
                priority,
                enabled,
                actor,
                payload_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                schedule_id = excluded.schedule_id,
                replacement_person_id = excluded.replacement_person_id,
                replaced_person_id = excluded.replaced_person_id,
                starts_at = excluded.starts_at,
                ends_at = excluded.ends_at,
                reason = excluded.reason,
                priority = excluded.priority,
                enabled = excluded.enabled,
                actor = excluded.actor,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                override.id,
                override.schedule_id,
                override.replacement_person_id,
                override.replaced_person_id,
                override.starts_at.isoformat(),
                override.ends_at.isoformat(),
                override.reason,
                int(override.priority),
                int(override.enabled),
                override.actor,
                json.dumps(payload, sort_keys=True),
                created_at.isoformat(),
                updated_at.isoformat(),
            ),
        )

    def list_active_for_schedule(
        self, schedule_id: str, *, effective_at: datetime | None = None
    ) -> list[ScheduleOverride]:
        effective = (effective_at or utc_now()).isoformat()
        rows = self._store.fetchall(
            """
            SELECT *
            FROM schedule_overrides
            WHERE schedule_id = ?
              AND enabled = 1
              AND starts_at <= ?
              AND ends_at >= ?
            ORDER BY priority DESC, created_at DESC
            """,
            (schedule_id, effective, effective),
        )
        return [_schedule_override_from_row(row) for row in rows]

    def list_upcoming(
        self, schedule_id: str, now: datetime | None = None
    ) -> list[ScheduleOverride]:
        effective_now = (now or utc_now()).isoformat()
        rows = self._store.fetchall(
            """
            SELECT *
            FROM schedule_overrides
            WHERE schedule_id = ?
              AND enabled = 1
              AND ends_at > ?
            ORDER BY starts_at ASC, priority DESC
            """,
            (schedule_id, effective_now),
        )
        return [_schedule_override_from_row(row) for row in rows]


def _operator_contact_target_from_value(value: object) -> OperatorContactTarget:
    if not isinstance(value, dict):
        msg = "Operator contact target payload must be an object."
        raise TypeError(msg)
    return OperatorContactTarget(
        channel_id=str(value.get("channel_id", "")),
        label=str(value.get("label", "")),
        enabled=bool(value.get("enabled", True)),
        priority=int(value.get("priority", 100) or 100),
    )


def _operator_person_from_row(row: object) -> OperatorPerson:
    assert row is not None
    contact_targets = tuple(
        _operator_contact_target_from_value(item)
        for item in json.loads(str(row["contact_targets_json"]))
    )
    return OperatorPerson(
        id=str(row["id"]),
        display_name=str(row["display_name"]),
        handle=str(row["handle"]),
        enabled=bool(row["enabled"]),
        timezone=str(row["timezone"]),
        contact_targets=contact_targets,
        metadata=_load_json(str(row["metadata_json"])),
        created_at=_decode_datetime(row["created_at"]),
        updated_at=_decode_datetime(row["updated_at"]),
    )


def _operator_team_from_row(row: object) -> OperatorTeam:
    assert row is not None
    return OperatorTeam(
        id=str(row["id"]),
        name=str(row["name"]),
        enabled=bool(row["enabled"]),
        description=str(row["description"]) if row["description"] is not None else None,
        default_escalation_policy_id=(
            str(row["default_escalation_policy_id"])
            if row["default_escalation_policy_id"] is not None
            else None
        ),
        created_at=_decode_datetime(row["created_at"]),
        updated_at=_decode_datetime(row["updated_at"]),
    )


def _team_membership_from_row(row: object) -> TeamMembership:
    assert row is not None
    return TeamMembership(
        id=str(row["id"]),
        team_id=str(row["team_id"]),
        person_id=str(row["person_id"]),
        role=TeamMembershipRole(str(row["role"])),
        enabled=bool(row["enabled"]),
        created_at=_decode_datetime(row["created_at"]),
        updated_at=_decode_datetime(row["updated_at"]),
    )


def _ownership_binding_from_row(row: object) -> OwnershipBinding:
    assert row is not None
    return OwnershipBinding(
        id=str(row["id"]),
        name=str(row["name"]),
        team_id=str(row["team_id"]),
        enabled=bool(row["enabled"]),
        component_kind=(
            ComponentKind(str(row["component_kind"]))
            if row["component_kind"] is not None
            else None
        ),
        component_id=str(row["component_id"])
        if row["component_id"] is not None
        else None,
        subject_kind=(
            OwnershipSubjectKind(str(row["subject_kind"]))
            if row["subject_kind"] is not None
            else None
        ),
        subject_ref=str(row["subject_ref"]) if row["subject_ref"] is not None else None,
        risk_level=(
            TargetRiskLevel(str(row["risk_level"]))
            if row["risk_level"] is not None
            else None
        ),
        escalation_policy_id=(
            str(row["escalation_policy_id"])
            if row["escalation_policy_id"] is not None
            else None
        ),
        created_at=_decode_datetime(row["created_at"]),
        updated_at=_decode_datetime(row["updated_at"]),
    )


def _oncall_schedule_from_row(row: object) -> OnCallSchedule:
    assert row is not None
    return OnCallSchedule(
        id=str(row["id"]),
        team_id=str(row["team_id"]),
        name=str(row["name"]),
        timezone=str(row["timezone"]),
        enabled=bool(row["enabled"]),
        coverage_kind=ScheduleCoverageKind(str(row["coverage_kind"])),
        schedule_config=_load_json(str(row["schedule_config_json"])),
        created_at=_decode_datetime(row["created_at"]),
        updated_at=_decode_datetime(row["updated_at"]),
    )


def _rotation_rule_from_row(row: object) -> RotationRule:
    assert row is not None
    participant_ids = tuple(
        str(item) for item in json.loads(str(row["participant_ids_json"]))
    )
    return RotationRule(
        id=str(row["id"]),
        schedule_id=str(row["schedule_id"]),
        name=str(row["name"]),
        participant_ids=participant_ids,
        enabled=bool(row["enabled"]),
        anchor_at=_decode_datetime(row["anchor_at"]),
        interval_kind=RotationIntervalKind(str(row["interval_kind"])),
        interval_count=int(row["interval_count"] or 1),
        handoff_time=str(row["handoff_time"])
        if row["handoff_time"] is not None
        else None,
        created_at=_decode_datetime(row["created_at"]),
        updated_at=_decode_datetime(row["updated_at"]),
    )


def _schedule_override_from_row(row: object) -> ScheduleOverride:
    assert row is not None
    return ScheduleOverride(
        id=str(row["id"]),
        schedule_id=str(row["schedule_id"]),
        replacement_person_id=str(row["replacement_person_id"]),
        replaced_person_id=(
            str(row["replaced_person_id"])
            if row["replaced_person_id"] is not None
            else None
        ),
        starts_at=datetime.fromisoformat(str(row["starts_at"])),
        ends_at=datetime.fromisoformat(str(row["ends_at"])),
        reason=str(row["reason"]),
        priority=int(row["priority"] or 0),
        enabled=bool(row["enabled"]),
        actor=str(row["actor"]) if row["actor"] is not None else None,
        created_at=_decode_datetime(row["created_at"]),
        updated_at=_decode_datetime(row["updated_at"]),
    )
