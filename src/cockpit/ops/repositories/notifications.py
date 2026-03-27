"""SQLite repositories for notifications."""

from __future__ import annotations

from datetime import datetime, timedelta
import json

from cockpit.notifications.models import (
    NotificationChannel,
    NotificationDeliveryAttempt,
    NotificationRecord,
    NotificationRule,
    NotificationSuppressionRule,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.core.enums import (
    ComponentKind,
    IncidentSeverity,
    IncidentStatus,
    NotificationChannelKind,
    NotificationDeliveryStatus,
    NotificationEventClass,
    NotificationStatus,
    TargetRiskLevel,
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


class NotificationChannelRepository:
    """Persist notification channels."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, channel: NotificationChannel) -> None:
        payload = channel.to_dict()
        created_at = channel.created_at or utc_now()
        updated_at = channel.updated_at or created_at
        self._store.execute(
            """
            INSERT INTO notification_channels (
                id,
                name,
                kind,
                enabled,
                target_json,
                secret_refs_json,
                timeout_seconds,
                max_attempts,
                base_backoff_seconds,
                max_backoff_seconds,
                risk_level,
                payload_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                kind = excluded.kind,
                enabled = excluded.enabled,
                target_json = excluded.target_json,
                secret_refs_json = excluded.secret_refs_json,
                timeout_seconds = excluded.timeout_seconds,
                max_attempts = excluded.max_attempts,
                base_backoff_seconds = excluded.base_backoff_seconds,
                max_backoff_seconds = excluded.max_backoff_seconds,
                risk_level = excluded.risk_level,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                channel.id,
                channel.name,
                channel.kind.value,
                int(channel.enabled),
                json.dumps(channel.target, sort_keys=True),
                json.dumps(channel.secret_refs, sort_keys=True),
                int(channel.timeout_seconds),
                int(channel.max_attempts),
                int(channel.base_backoff_seconds),
                int(channel.max_backoff_seconds),
                channel.risk_level.value,
                json.dumps(payload, sort_keys=True),
                created_at.isoformat(),
                updated_at.isoformat(),
            ),
        )

    def get(self, channel_id: str) -> NotificationChannel | None:
        row = self._store.fetchone(
            "SELECT * FROM notification_channels WHERE id = ?",
            (channel_id,),
        )
        return _notification_channel_from_row(row) if row is not None else None

    def list_all(self, *, enabled_only: bool = False) -> list[NotificationChannel]:
        sql = "SELECT * FROM notification_channels"
        params: tuple[object, ...] = ()
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY name ASC, id ASC"
        rows = self._store.fetchall(sql, params)
        return [_notification_channel_from_row(row) for row in rows]

    def delete(self, channel_id: str) -> None:
        self._store.execute(
            "DELETE FROM notification_channels WHERE id = ?", (channel_id,)
        )


class NotificationRuleRepository:
    """Persist routing rules for notifications."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, rule: NotificationRule) -> None:
        payload = rule.to_dict()
        created_at = rule.created_at or utc_now()
        updated_at = rule.updated_at or created_at
        self._store.execute(
            """
            INSERT INTO notification_rules (
                id,
                name,
                enabled,
                event_classes_json,
                component_kinds_json,
                severities_json,
                risk_levels_json,
                incident_statuses_json,
                channel_ids_json,
                delivery_priority,
                dedupe_window_seconds,
                payload_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                enabled = excluded.enabled,
                event_classes_json = excluded.event_classes_json,
                component_kinds_json = excluded.component_kinds_json,
                severities_json = excluded.severities_json,
                risk_levels_json = excluded.risk_levels_json,
                incident_statuses_json = excluded.incident_statuses_json,
                channel_ids_json = excluded.channel_ids_json,
                delivery_priority = excluded.delivery_priority,
                dedupe_window_seconds = excluded.dedupe_window_seconds,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                rule.id,
                rule.name,
                int(rule.enabled),
                json.dumps([item.value for item in rule.event_classes], sort_keys=True),
                json.dumps(
                    [item.value for item in rule.component_kinds], sort_keys=True
                ),
                json.dumps([item.value for item in rule.severities], sort_keys=True),
                json.dumps([item.value for item in rule.risk_levels], sort_keys=True),
                json.dumps(
                    [item.value for item in rule.incident_statuses], sort_keys=True
                ),
                json.dumps(list(rule.channel_ids), sort_keys=True),
                int(rule.delivery_priority),
                int(rule.dedupe_window_seconds),
                json.dumps(payload, sort_keys=True),
                created_at.isoformat(),
                updated_at.isoformat(),
            ),
        )

    def list_all(self, *, enabled_only: bool = False) -> list[NotificationRule]:
        sql = "SELECT * FROM notification_rules"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY delivery_priority ASC, updated_at DESC"
        rows = self._store.fetchall(sql)
        return [_notification_rule_from_row(row) for row in rows]

    def get(self, rule_id: str) -> NotificationRule | None:
        row = self._store.fetchone(
            "SELECT * FROM notification_rules WHERE id = ?", (rule_id,)
        )
        return _notification_rule_from_row(row) if row is not None else None

    def delete(self, rule_id: str) -> None:
        self._store.execute("DELETE FROM notification_rules WHERE id = ?", (rule_id,))


class NotificationSuppressionRepository:
    """Persist time-bounded suppression rules."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, rule: NotificationSuppressionRule) -> None:
        payload = rule.to_dict()
        created_at = rule.created_at or utc_now()
        updated_at = rule.updated_at or created_at
        self._store.execute(
            """
            INSERT INTO notification_suppressions (
                id,
                name,
                enabled,
                reason,
                starts_at,
                ends_at,
                event_classes_json,
                component_kinds_json,
                severities_json,
                risk_levels_json,
                actor,
                payload_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                enabled = excluded.enabled,
                reason = excluded.reason,
                starts_at = excluded.starts_at,
                ends_at = excluded.ends_at,
                event_classes_json = excluded.event_classes_json,
                component_kinds_json = excluded.component_kinds_json,
                severities_json = excluded.severities_json,
                risk_levels_json = excluded.risk_levels_json,
                actor = excluded.actor,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                rule.id,
                rule.name,
                int(rule.enabled),
                rule.reason,
                rule.starts_at.isoformat() if rule.starts_at else None,
                rule.ends_at.isoformat() if rule.ends_at else None,
                json.dumps([item.value for item in rule.event_classes], sort_keys=True),
                json.dumps(
                    [item.value for item in rule.component_kinds], sort_keys=True
                ),
                json.dumps([item.value for item in rule.severities], sort_keys=True),
                json.dumps([item.value for item in rule.risk_levels], sort_keys=True),
                rule.actor,
                json.dumps(payload, sort_keys=True),
                created_at.isoformat(),
                updated_at.isoformat(),
            ),
        )

    def list_all(
        self, *, enabled_only: bool = False
    ) -> list[NotificationSuppressionRule]:
        sql = "SELECT * FROM notification_suppressions"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY updated_at DESC, id DESC"
        rows = self._store.fetchall(sql)
        return [_notification_suppression_from_row(row) for row in rows]

    def list_active(
        self, now: datetime | None = None
    ) -> list[NotificationSuppressionRule]:
        effective_now = (now or utc_now()).isoformat()
        rows = self._store.fetchall(
            """
            SELECT *
            FROM notification_suppressions
            WHERE enabled = 1
              AND (starts_at IS NULL OR starts_at <= ?)
              AND (ends_at IS NULL OR ends_at >= ?)
            ORDER BY updated_at DESC, id DESC
            """,
            (effective_now, effective_now),
        )
        return [_notification_suppression_from_row(row) for row in rows]

    def delete(self, suppression_id: str) -> None:
        self._store.execute(
            "DELETE FROM notification_suppressions WHERE id = ?",
            (suppression_id,),
        )


class NotificationRepository:
    """Persist notifications and query recent operator-visible state."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, notification: NotificationRecord) -> None:
        payload = notification.to_dict()
        created_at = notification.created_at or utc_now()
        self._store.execute(
            """
            INSERT INTO notifications (
                id,
                event_class,
                severity,
                risk_level,
                title,
                summary,
                status,
                dedupe_key,
                incident_id,
                component_id,
                component_kind,
                incident_status,
                source_event_id,
                suppression_reason,
                payload_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                event_class = excluded.event_class,
                severity = excluded.severity,
                risk_level = excluded.risk_level,
                title = excluded.title,
                summary = excluded.summary,
                status = excluded.status,
                dedupe_key = excluded.dedupe_key,
                incident_id = excluded.incident_id,
                component_id = excluded.component_id,
                component_kind = excluded.component_kind,
                incident_status = excluded.incident_status,
                source_event_id = excluded.source_event_id,
                suppression_reason = excluded.suppression_reason,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at
            """,
            (
                notification.id,
                notification.event_class.value,
                notification.severity.value,
                notification.risk_level.value,
                notification.title,
                notification.summary,
                notification.status.value,
                notification.dedupe_key,
                notification.incident_id,
                notification.component_id,
                notification.component_kind.value
                if notification.component_kind
                else None,
                notification.incident_status.value
                if notification.incident_status
                else None,
                notification.source_event_id,
                notification.suppression_reason,
                json.dumps(payload, sort_keys=True),
                created_at.isoformat(),
            ),
        )

    def get(self, notification_id: str) -> NotificationRecord | None:
        row = self._store.fetchone(
            "SELECT * FROM notifications WHERE id = ?", (notification_id,)
        )
        return _notification_from_row(row) if row is not None else None

    def list_recent(
        self,
        *,
        limit: int = 50,
        statuses: tuple[NotificationStatus, ...] | None = None,
    ) -> list[NotificationRecord]:
        sql = "SELECT * FROM notifications WHERE 1=1"
        params: list[object] = []
        if statuses:
            sql += f" AND status IN ({','.join('?' for _ in statuses)})"
            params.extend(item.value for item in statuses)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        rows = self._store.fetchall(sql, tuple(params))
        return [_notification_from_row(row) for row in rows]

    def count_by_status(self) -> dict[str, int]:
        rows = self._store.fetchall(
            """
            SELECT status, COUNT(*) AS count
            FROM notifications
            GROUP BY status
            """
        )
        return {str(row["status"]): int(row["count"]) for row in rows}

    def recent_by_dedupe_key(
        self,
        dedupe_key: str,
        *,
        within_seconds: int,
        now: datetime | None = None,
    ) -> list[NotificationRecord]:
        since = (now or utc_now()) - timedelta(seconds=max(1, within_seconds))
        rows = self._store.fetchall(
            """
            SELECT *
            FROM notifications
            WHERE dedupe_key = ?
              AND created_at >= ?
            ORDER BY created_at DESC, id DESC
            """,
            (dedupe_key, since.isoformat()),
        )
        return [_notification_from_row(row) for row in rows]


class NotificationDeliveryRepository:
    """Persist delivery attempts and query delivery health."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, attempt: NotificationDeliveryAttempt) -> None:
        payload = attempt.to_dict()
        self._store.execute(
            """
            INSERT INTO notification_deliveries (
                id,
                notification_id,
                channel_id,
                attempt_number,
                status,
                scheduled_for,
                started_at,
                finished_at,
                error_class,
                error_message,
                response_payload_json,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                notification_id = excluded.notification_id,
                channel_id = excluded.channel_id,
                attempt_number = excluded.attempt_number,
                status = excluded.status,
                scheduled_for = excluded.scheduled_for,
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                error_class = excluded.error_class,
                error_message = excluded.error_message,
                response_payload_json = excluded.response_payload_json,
                payload_json = excluded.payload_json
            """,
            (
                attempt.id,
                attempt.notification_id,
                attempt.channel_id,
                int(attempt.attempt_number),
                attempt.status.value,
                attempt.scheduled_for.isoformat() if attempt.scheduled_for else None,
                attempt.started_at.isoformat() if attempt.started_at else None,
                attempt.finished_at.isoformat() if attempt.finished_at else None,
                attempt.error_class,
                attempt.error_message,
                json.dumps(attempt.response_payload, sort_keys=True),
                json.dumps(payload, sort_keys=True),
            ),
        )

    def list_for_notification(
        self, notification_id: str
    ) -> list[NotificationDeliveryAttempt]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM notification_deliveries
            WHERE notification_id = ?
            ORDER BY attempt_number ASC, id ASC
            """,
            (notification_id,),
        )
        return [_notification_delivery_from_row(row) for row in rows]

    def list_recent_failures(
        self, *, limit: int = 25
    ) -> list[NotificationDeliveryAttempt]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM notification_deliveries
            WHERE status = ?
            ORDER BY COALESCE(finished_at, started_at, scheduled_for) DESC, id DESC
            LIMIT ?
            """,
            (NotificationDeliveryStatus.FAILED.value, limit),
        )
        return [_notification_delivery_from_row(row) for row in rows]

    def list_due_attempts(
        self, now: datetime | None = None
    ) -> list[NotificationDeliveryAttempt]:
        effective_now = (now or utc_now()).isoformat()
        rows = self._store.fetchall(
            """
            SELECT *
            FROM notification_deliveries
            WHERE status = ?
              AND scheduled_for IS NOT NULL
              AND scheduled_for <= ?
            ORDER BY scheduled_for ASC, id ASC
            """,
            (NotificationDeliveryStatus.SCHEDULED.value, effective_now),
        )
        return [_notification_delivery_from_row(row) for row in rows]


def _notification_channel_from_row(row: object) -> NotificationChannel:
    assert row is not None
    return NotificationChannel(
        id=str(row["id"]),
        name=str(row["name"]),
        kind=NotificationChannelKind(str(row["kind"])),
        enabled=bool(row["enabled"]),
        target=_load_json(str(row["target_json"])),
        secret_refs={
            str(key): str(value)
            for key, value in _load_json(str(row["secret_refs_json"])).items()
        },
        timeout_seconds=int(row["timeout_seconds"] or 0),
        max_attempts=int(row["max_attempts"] or 0),
        base_backoff_seconds=int(row["base_backoff_seconds"] or 0),
        max_backoff_seconds=int(row["max_backoff_seconds"] or 0),
        risk_level=TargetRiskLevel(str(row["risk_level"])),
        created_at=_decode_datetime(row["created_at"]),
        updated_at=_decode_datetime(row["updated_at"]),
    )


def _notification_rule_from_row(row: object) -> NotificationRule:
    assert row is not None
    event_classes = tuple(
        NotificationEventClass(str(item))
        for item in json.loads(str(row["event_classes_json"]))
    )
    component_kinds = tuple(
        ComponentKind(str(item))
        for item in json.loads(str(row["component_kinds_json"]))
    )
    severities = tuple(
        IncidentSeverity(str(item)) for item in json.loads(str(row["severities_json"]))
    )
    risk_levels = tuple(
        TargetRiskLevel(str(item)) for item in json.loads(str(row["risk_levels_json"]))
    )
    incident_statuses = tuple(
        IncidentStatus(str(item))
        for item in json.loads(str(row["incident_statuses_json"]))
    )
    channel_ids = tuple(str(item) for item in json.loads(str(row["channel_ids_json"])))
    return NotificationRule(
        id=str(row["id"]),
        name=str(row["name"]),
        enabled=bool(row["enabled"]),
        event_classes=event_classes,
        component_kinds=component_kinds,
        severities=severities,
        risk_levels=risk_levels,
        incident_statuses=incident_statuses,
        channel_ids=channel_ids,
        delivery_priority=int(row["delivery_priority"] or 0),
        dedupe_window_seconds=int(row["dedupe_window_seconds"] or 0),
        created_at=_decode_datetime(row["created_at"]),
        updated_at=_decode_datetime(row["updated_at"]),
    )


def _notification_suppression_from_row(row: object) -> NotificationSuppressionRule:
    assert row is not None
    return NotificationSuppressionRule(
        id=str(row["id"]),
        name=str(row["name"]),
        enabled=bool(row["enabled"]),
        reason=str(row["reason"]),
        starts_at=_decode_datetime(row["starts_at"]),
        ends_at=_decode_datetime(row["ends_at"]),
        event_classes=tuple(
            NotificationEventClass(str(item))
            for item in json.loads(str(row["event_classes_json"]))
        ),
        component_kinds=tuple(
            ComponentKind(str(item))
            for item in json.loads(str(row["component_kinds_json"]))
        ),
        severities=tuple(
            IncidentSeverity(str(item))
            for item in json.loads(str(row["severities_json"]))
        ),
        risk_levels=tuple(
            TargetRiskLevel(str(item))
            for item in json.loads(str(row["risk_levels_json"]))
        ),
        actor=str(row["actor"]) if row["actor"] is not None else None,
        created_at=_decode_datetime(row["created_at"]),
        updated_at=_decode_datetime(row["updated_at"]),
    )


def _notification_from_row(row: object) -> NotificationRecord:
    assert row is not None
    return NotificationRecord(
        id=str(row["id"]),
        event_class=NotificationEventClass(str(row["event_class"])),
        severity=IncidentSeverity(str(row["severity"])),
        risk_level=TargetRiskLevel(str(row["risk_level"])),
        title=str(row["title"]),
        summary=str(row["summary"]),
        status=NotificationStatus(str(row["status"])),
        dedupe_key=str(row["dedupe_key"]),
        incident_id=str(row["incident_id"]) if row["incident_id"] is not None else None,
        component_id=str(row["component_id"])
        if row["component_id"] is not None
        else None,
        component_kind=(
            ComponentKind(str(row["component_kind"]))
            if row["component_kind"] is not None
            else None
        ),
        incident_status=(
            IncidentStatus(str(row["incident_status"]))
            if row["incident_status"] is not None
            else None
        ),
        source_event_id=(
            str(row["source_event_id"]) if row["source_event_id"] is not None else None
        ),
        suppression_reason=(
            str(row["suppression_reason"])
            if row["suppression_reason"] is not None
            else None
        ),
        payload=_load_json(str(row["payload_json"])),
        created_at=_decode_datetime(row["created_at"]),
    )


def _notification_delivery_from_row(row: object) -> NotificationDeliveryAttempt:
    assert row is not None
    return NotificationDeliveryAttempt(
        id=str(row["id"]),
        notification_id=str(row["notification_id"]),
        channel_id=str(row["channel_id"]),
        attempt_number=int(row["attempt_number"] or 0),
        status=NotificationDeliveryStatus(str(row["status"])),
        scheduled_for=_decode_datetime(row["scheduled_for"]),
        started_at=_decode_datetime(row["started_at"]),
        finished_at=_decode_datetime(row["finished_at"]),
        error_class=str(row["error_class"]) if row["error_class"] is not None else None,
        error_message=str(row["error_message"])
        if row["error_message"] is not None
        else None,
        response_payload=_load_json(str(row["response_payload_json"])),
    )
