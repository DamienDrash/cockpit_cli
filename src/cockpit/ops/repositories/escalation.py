"""SQLite repositories for escalation policies and engagements."""

from __future__ import annotations

from datetime import datetime
import json

from cockpit.ops.models.escalation import (
    EngagementDeliveryLink,
    EngagementTimelineEntry,
    EscalationPolicy,
    EscalationStep,
    IncidentEngagement,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.core.enums import (
    EngagementDeliveryPurpose,
    EngagementStatus,
    EscalationTargetKind,
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


class EscalationPolicyRepository:
    """Persist escalation policies."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, policy: EscalationPolicy) -> None:
        payload = policy.to_dict()
        created_at = policy.created_at or utc_now()
        updated_at = policy.updated_at or created_at
        self._store.execute(
            """
            INSERT INTO escalation_policies (
                id,
                name,
                enabled,
                default_ack_timeout_seconds,
                default_repeat_page_seconds,
                max_repeat_pages,
                terminal_behavior,
                payload_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                enabled = excluded.enabled,
                default_ack_timeout_seconds = excluded.default_ack_timeout_seconds,
                default_repeat_page_seconds = excluded.default_repeat_page_seconds,
                max_repeat_pages = excluded.max_repeat_pages,
                terminal_behavior = excluded.terminal_behavior,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                policy.id,
                policy.name,
                int(policy.enabled),
                int(policy.default_ack_timeout_seconds),
                int(policy.default_repeat_page_seconds),
                int(policy.max_repeat_pages),
                policy.terminal_behavior,
                json.dumps(payload, sort_keys=True),
                created_at.isoformat(),
                updated_at.isoformat(),
            ),
        )

    def get(self, policy_id: str) -> EscalationPolicy | None:
        row = self._store.fetchone(
            "SELECT * FROM escalation_policies WHERE id = ?", (policy_id,)
        )
        return _escalation_policy_from_row(row) if row is not None else None

    def list_all(self, *, enabled_only: bool = False) -> list[EscalationPolicy]:
        sql = "SELECT * FROM escalation_policies"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY name ASC"
        rows = self._store.fetchall(sql)
        return [_escalation_policy_from_row(row) for row in rows]


class EscalationStepRepository:
    """Persist individual escalation steps."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, step: EscalationStep) -> None:
        payload = step.to_dict()
        created_at = step.created_at or utc_now()
        updated_at = step.updated_at or created_at
        self._store.execute(
            """
            INSERT INTO escalation_steps (
                id,
                policy_id,
                step_index,
                target_kind,
                target_ref,
                ack_timeout_seconds,
                repeat_page_seconds,
                max_repeat_pages,
                reminder_enabled,
                stop_on_ack,
                payload_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                policy_id = excluded.policy_id,
                step_index = excluded.step_index,
                target_kind = excluded.target_kind,
                target_ref = excluded.target_ref,
                ack_timeout_seconds = excluded.ack_timeout_seconds,
                repeat_page_seconds = excluded.repeat_page_seconds,
                max_repeat_pages = excluded.max_repeat_pages,
                reminder_enabled = excluded.reminder_enabled,
                stop_on_ack = excluded.stop_on_ack,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                step.id,
                step.policy_id,
                int(step.step_index),
                step.target_kind.value,
                step.target_ref,
                step.ack_timeout_seconds,
                step.repeat_page_seconds,
                step.max_repeat_pages,
                int(step.reminder_enabled),
                int(step.stop_on_ack),
                json.dumps(payload, sort_keys=True),
                created_at.isoformat(),
                updated_at.isoformat(),
            ),
        )

    def list_for_policy(self, policy_id: str) -> list[EscalationStep]:
        rows = self._store.fetchall(
            "SELECT * FROM escalation_steps WHERE policy_id = ? ORDER BY step_index ASC",
            (policy_id,),
        )
        return [_escalation_step_from_row(row) for row in rows]

    def delete_for_policy(self, policy_id: str) -> None:
        self._store.execute("DELETE FROM escalation_steps WHERE policy_id = ?", (policy_id,))


class IncidentEngagementRepository:
    """Persist active incident engagements and responder tracking."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, engagement: IncidentEngagement) -> None:
        payload = engagement.to_dict()
        created_at = engagement.created_at or utc_now()
        updated_at = engagement.updated_at or created_at
        self._store.execute(
            """
            INSERT INTO incident_engagements (
                id,
                incident_id,
                incident_component_id,
                team_id,
                policy_id,
                status,
                current_step_index,
                current_target_kind,
                current_target_ref,
                resolved_person_id,
                acknowledged_by,
                acknowledged_at,
                handoff_count,
                repeat_page_count,
                next_action_at,
                ack_deadline_at,
                last_page_at,
                exhausted,
                payload_json,
                created_at,
                updated_at,
                closed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                incident_id = excluded.incident_id,
                incident_component_id = excluded.incident_component_id,
                team_id = excluded.team_id,
                policy_id = excluded.policy_id,
                status = excluded.status,
                current_step_index = excluded.current_step_index,
                current_target_kind = excluded.current_target_kind,
                current_target_ref = excluded.current_target_ref,
                resolved_person_id = excluded.resolved_person_id,
                acknowledged_by = excluded.acknowledged_by,
                acknowledged_at = excluded.acknowledged_at,
                handoff_count = excluded.handoff_count,
                repeat_page_count = excluded.repeat_page_count,
                next_action_at = excluded.next_action_at,
                ack_deadline_at = excluded.ack_deadline_at,
                last_page_at = excluded.last_page_at,
                exhausted = excluded.exhausted,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                closed_at = excluded.closed_at
            """,
            (
                engagement.id,
                engagement.incident_id,
                engagement.incident_component_id,
                engagement.team_id,
                engagement.policy_id,
                engagement.status.value,
                int(engagement.current_step_index),
                engagement.current_target_kind.value
                if engagement.current_target_kind
                else None,
                engagement.current_target_ref,
                engagement.resolved_person_id,
                engagement.acknowledged_by,
                engagement.acknowledged_at.isoformat()
                if engagement.acknowledged_at
                else None,
                int(engagement.handoff_count),
                int(engagement.repeat_page_count),
                engagement.next_action_at.isoformat()
                if engagement.next_action_at
                else None,
                engagement.ack_deadline_at.isoformat()
                if engagement.ack_deadline_at
                else None,
                engagement.last_page_at.isoformat() if engagement.last_page_at else None,
                int(engagement.exhausted),
                json.dumps(payload, sort_keys=True),
                created_at.isoformat(),
                updated_at.isoformat(),
                engagement.closed_at.isoformat() if engagement.closed_at else None,
            ),
        )

    def get(self, engagement_id: str) -> IncidentEngagement | None:
        row = self._store.fetchone(
            "SELECT * FROM incident_engagements WHERE id = ?", (engagement_id,)
        )
        return _incident_engagement_from_row(row) if row is not None else None

    def find_active_for_incident(self, incident_id: str) -> IncidentEngagement | None:
        row = self._store.fetchone(
            """
            SELECT *
            FROM incident_engagements
            WHERE incident_id = ?
              AND status IN (?, ?, ?)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (
                incident_id,
                EngagementStatus.ACTIVE.value,
                EngagementStatus.ACKNOWLEDGED.value,
                EngagementStatus.BLOCKED.value,
            ),
        )
        return _incident_engagement_from_row(row) if row is not None else None

    def list_active(self, *, limit: int = 50) -> list[IncidentEngagement]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM incident_engagements
            WHERE status IN (?, ?, ?)
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (
                EngagementStatus.ACTIVE.value,
                EngagementStatus.ACKNOWLEDGED.value,
                EngagementStatus.BLOCKED.value,
                limit,
            ),
        )
        return [_incident_engagement_from_row(row) for row in rows]

    def list_recent(self, *, limit: int = 50) -> list[IncidentEngagement]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM incident_engagements
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [_incident_engagement_from_row(row) for row in rows]


    def list_due_actions(self, now: datetime | None = None) -> list[IncidentEngagement]:
        effective_now = (now or utc_now()).isoformat()
        rows = self._store.fetchall(
            """
            SELECT *
            FROM incident_engagements
            WHERE status IN (?, ?)
              AND next_action_at IS NOT NULL
              AND next_action_at <= ?
            ORDER BY next_action_at ASC
            """,
            (
                EngagementStatus.ACTIVE.value,
                EngagementStatus.ACKNOWLEDGED.value,
                effective_now,
            ),
        )
        return [_incident_engagement_from_row(row) for row in rows]


class EngagementTimelineRepository:
    """Persist engagement-specific timeline events."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def add_entry(
        self,
        *,
        engagement_id: str,
        incident_id: str,
        event_type: str,
        message: str,
        payload: dict[str, object] | None = None,
        recorded_at: datetime | None = None,
    ) -> None:
        self._store.execute(
            """
            INSERT INTO engagement_timeline (
                engagement_id,
                incident_id,
                event_type,
                message,
                recorded_at,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                engagement_id,
                incident_id,
                event_type,
                message,
                (recorded_at or utc_now()).isoformat(),
                json.dumps(payload or {}, sort_keys=True),
            ),
        )

    def list_for_engagement(self, engagement_id: str) -> list[EngagementTimelineEntry]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM engagement_timeline
            WHERE engagement_id = ?
            ORDER BY recorded_at ASC, id ASC
            """,
            (engagement_id,),
        )
        return [_engagement_timeline_from_row(row) for row in rows]


class EngagementDeliveryLinkRepository:
    """Link engagement steps to notification deliveries."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, link: EngagementDeliveryLink) -> None:
        created_at = link.created_at or utc_now()
        self._store.execute(
            """
            INSERT INTO engagement_delivery_links (
                engagement_id,
                notification_id,
                delivery_id,
                purpose,
                step_index,
                created_at,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                link.engagement_id,
                link.notification_id,
                link.delivery_id,
                link.purpose.value,
                int(link.step_index),
                created_at.isoformat(),
                json.dumps(link.payload, sort_keys=True),
            ),
        )

    def list_for_engagement(self, engagement_id: str) -> list[EngagementDeliveryLink]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM engagement_delivery_links
            WHERE engagement_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (engagement_id,),
        )
        return [_engagement_delivery_link_from_row(row) for row in rows]


def _escalation_policy_from_row(row: object) -> EscalationPolicy:
    assert row is not None
    return EscalationPolicy(
        id=str(row["id"]),
        name=str(row["name"]),
        enabled=bool(row["enabled"]),
        default_ack_timeout_seconds=int(row["default_ack_timeout_seconds"] or 0),
        default_repeat_page_seconds=int(row["default_repeat_page_seconds"] or 0),
        max_repeat_pages=int(row["max_repeat_pages"] or 0),
        terminal_behavior=str(row["terminal_behavior"]),
        created_at=_decode_datetime(row["created_at"]),
        updated_at=_decode_datetime(row["updated_at"]),
    )


def _escalation_step_from_row(row: object) -> EscalationStep:
    assert row is not None
    return EscalationStep(
        id=str(row["id"]),
        policy_id=str(row["policy_id"]),
        step_index=int(row["step_index"] or 0),
        target_kind=EscalationTargetKind(str(row["target_kind"])),
        target_ref=str(row["target_ref"]),
        ack_timeout_seconds=(
            int(row["ack_timeout_seconds"])
            if row["ack_timeout_seconds"] is not None
            else None
        ),
        repeat_page_seconds=(
            int(row["repeat_page_seconds"])
            if row["repeat_page_seconds"] is not None
            else None
        ),
        max_repeat_pages=(
            int(row["max_repeat_pages"])
            if row["max_repeat_pages"] is not None
            else None
        ),
        reminder_enabled=bool(row["reminder_enabled"]),
        stop_on_ack=bool(row["stop_on_ack"]),
        created_at=_decode_datetime(row["created_at"]),
        updated_at=_decode_datetime(row["updated_at"]),
    )


def _incident_engagement_from_row(row: object) -> IncidentEngagement:
    assert row is not None
    return IncidentEngagement(
        id=str(row["id"]),
        incident_id=str(row["incident_id"]),
        incident_component_id=str(row["incident_component_id"]),
        team_id=str(row["team_id"]) if row["team_id"] is not None else None,
        policy_id=str(row["policy_id"]) if row["policy_id"] is not None else None,
        status=EngagementStatus(str(row["status"])),
        current_step_index=int(row["current_step_index"] or 0),
        current_target_kind=(
            EscalationTargetKind(str(row["current_target_kind"]))
            if row["current_target_kind"] is not None
            else None
        ),
        current_target_ref=(
            str(row["current_target_ref"])
            if row["current_target_ref"] is not None
            else None
        ),
        resolved_person_id=(
            str(row["resolved_person_id"])
            if row["resolved_person_id"] is not None
            else None
        ),
        acknowledged_by=(
            str(row["acknowledged_by"]) if row["acknowledged_by"] is not None else None
        ),
        acknowledged_at=_decode_datetime(row["acknowledged_at"]),
        handoff_count=int(row["handoff_count"] or 0),
        repeat_page_count=int(row["repeat_page_count"] or 0),
        next_action_at=_decode_datetime(row["next_action_at"]),
        ack_deadline_at=_decode_datetime(row["ack_deadline_at"]),
        last_page_at=_decode_datetime(row["last_page_at"]),
        exhausted=bool(row["exhausted"]),
        created_at=_decode_datetime(row["created_at"]),
        updated_at=_decode_datetime(row["updated_at"]),
        closed_at=_decode_datetime(row["closed_at"]),
        payload=_load_json(str(row["payload_json"])),
    )


def _engagement_timeline_from_row(row: object) -> EngagementTimelineEntry:
    assert row is not None
    return EngagementTimelineEntry(
        id=int(row["id"]),
        engagement_id=str(row["engagement_id"]),
        incident_id=str(row["incident_id"]),
        event_type=str(row["event_type"]),
        message=str(row["message"]),
        recorded_at=datetime.fromisoformat(str(row["recorded_at"])),
        payload=_load_json(str(row["payload_json"])),
    )


def _engagement_delivery_link_from_row(row: object) -> EngagementDeliveryLink:
    assert row is not None
    return EngagementDeliveryLink(
        id=int(row["id"]),
        engagement_id=str(row["engagement_id"]),
        notification_id=str(row["notification_id"]),
        delivery_id=str(row["delivery_id"]) if row["delivery_id"] is not None else None,
        purpose=EngagementDeliveryPurpose(str(row["purpose"])),
        step_index=int(row["step_index"] or 0),
        created_at=_decode_datetime(row["created_at"]),
        payload=_load_json(str(row["payload_json"])),
    )
