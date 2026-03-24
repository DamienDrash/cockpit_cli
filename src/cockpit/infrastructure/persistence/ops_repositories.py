"""SQLite repositories for operational health, incidents, policy, and diagnostics."""

from __future__ import annotations

from datetime import datetime, timedelta
import json

from cockpit.domain.models.diagnostics import OperationDiagnosticRecord
from cockpit.domain.models.health import (
    ComponentHealthState,
    IncidentRecord,
    IncidentTimelineEntry,
    RecoveryAttempt,
)
from cockpit.domain.models.notifications import (
    NotificationChannel,
    NotificationDeliveryAttempt,
    NotificationRecord,
    NotificationRule,
    NotificationSuppressionRule,
)
from cockpit.domain.models.policy import GuardDecision
from cockpit.domain.models.watch import ComponentWatchConfig, ComponentWatchState
from cockpit.infrastructure.persistence.sqlite_store import SQLiteStore
from cockpit.shared.enums import (
    ComponentKind,
    GuardActionKind,
    GuardDecisionOutcome,
    HealthStatus,
    IncidentSeverity,
    IncidentStatus,
    NotificationChannelKind,
    NotificationDeliveryStatus,
    NotificationEventClass,
    NotificationStatus,
    OperationFamily,
    RecoveryAttemptStatus,
    SessionTargetKind,
    TargetRiskLevel,
    WatchProbeOutcome,
    WatchSubjectKind,
)
from cockpit.shared.utils import utc_now


def _load_json(raw_value: str) -> dict[str, object]:
    payload = json.loads(raw_value)
    if not isinstance(payload, dict):
        msg = "Expected JSON object payload."
        raise TypeError(msg)
    return payload


def _decode_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class ComponentHealthRepository:
    """Persist and query current component health state."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, state: ComponentHealthState) -> None:
        payload = state.to_dict()
        updated_at = state.updated_at or utc_now()
        self._store.execute(
            """
            INSERT INTO component_health_state (
                component_id,
                component_kind,
                display_name,
                status,
                workspace_id,
                session_id,
                target_kind,
                target_ref,
                last_heartbeat_at,
                last_failure_at,
                last_recovery_at,
                next_recovery_at,
                cooldown_until,
                consecutive_failures,
                exhaustion_count,
                quarantined,
                quarantine_reason,
                last_incident_id,
                payload_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(component_id) DO UPDATE SET
                component_kind = excluded.component_kind,
                display_name = excluded.display_name,
                status = excluded.status,
                workspace_id = excluded.workspace_id,
                session_id = excluded.session_id,
                target_kind = excluded.target_kind,
                target_ref = excluded.target_ref,
                last_heartbeat_at = excluded.last_heartbeat_at,
                last_failure_at = excluded.last_failure_at,
                last_recovery_at = excluded.last_recovery_at,
                next_recovery_at = excluded.next_recovery_at,
                cooldown_until = excluded.cooldown_until,
                consecutive_failures = excluded.consecutive_failures,
                exhaustion_count = excluded.exhaustion_count,
                quarantined = excluded.quarantined,
                quarantine_reason = excluded.quarantine_reason,
                last_incident_id = excluded.last_incident_id,
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (
                state.component_id,
                state.component_kind.value,
                state.display_name,
                state.status.value,
                state.workspace_id,
                state.session_id,
                state.target_kind.value,
                state.target_ref,
                state.last_heartbeat_at.isoformat() if state.last_heartbeat_at else None,
                state.last_failure_at.isoformat() if state.last_failure_at else None,
                state.last_recovery_at.isoformat() if state.last_recovery_at else None,
                state.next_recovery_at.isoformat() if state.next_recovery_at else None,
                state.cooldown_until.isoformat() if state.cooldown_until else None,
                int(state.consecutive_failures),
                int(state.exhaustion_count),
                int(state.quarantined),
                state.quarantine_reason,
                state.last_incident_id,
                json.dumps(payload, sort_keys=True),
                updated_at.isoformat(),
            ),
        )

    def get(self, component_id: str) -> ComponentHealthState | None:
        row = self._store.fetchone(
            "SELECT * FROM component_health_state WHERE component_id = ?",
            (component_id,),
        )
        return _component_health_from_row(row) if row is not None else None

    def list_all(self) -> list[ComponentHealthState]:
        rows = self._store.fetchall(
            "SELECT * FROM component_health_state ORDER BY updated_at DESC"
        )
        return [_component_health_from_row(row) for row in rows]

    def list_unhealthy(self) -> list[ComponentHealthState]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM component_health_state
            WHERE status != ?
            ORDER BY quarantined DESC, updated_at DESC
            """,
            (HealthStatus.HEALTHY.value,),
        )
        return [_component_health_from_row(row) for row in rows]

    def list_quarantined(self) -> list[ComponentHealthState]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM component_health_state
            WHERE quarantined = 1
            ORDER BY updated_at DESC
            """
        )
        return [_component_health_from_row(row) for row in rows]

    def list_due_recoveries(self, now: datetime | None = None) -> list[ComponentHealthState]:
        effective_now = (now or utc_now()).isoformat()
        rows = self._store.fetchall(
            """
            SELECT *
            FROM component_health_state
            WHERE status = ?
              AND next_recovery_at IS NOT NULL
              AND next_recovery_at <= ?
              AND quarantined = 0
            ORDER BY next_recovery_at ASC
            """,
            (HealthStatus.RECOVERING.value, effective_now),
        )
        return [_component_health_from_row(row) for row in rows]

    def record_transition(
        self,
        *,
        component_id: str,
        component_kind: ComponentKind,
        previous_status: HealthStatus | None,
        new_status: HealthStatus,
        reason: str,
        payload: dict[str, object] | None = None,
        recorded_at: datetime | None = None,
    ) -> None:
        self._store.execute(
            """
            INSERT INTO component_health_history (
                component_id,
                component_kind,
                previous_status,
                new_status,
                reason,
                recorded_at,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                component_id,
                component_kind.value,
                previous_status.value if previous_status is not None else None,
                new_status.value,
                reason,
                (recorded_at or utc_now()).isoformat(),
                json.dumps(payload or {}, sort_keys=True),
            ),
        )

    def recent_history(self, component_id: str, limit: int = 20) -> list[dict[str, object]]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM component_health_history
            WHERE component_id = ?
            ORDER BY recorded_at DESC, id DESC
            LIMIT ?
            """,
            (component_id, limit),
        )
        return [
            {
                "id": int(row["id"]),
                "component_id": row["component_id"],
                "component_kind": row["component_kind"],
                "previous_status": row["previous_status"],
                "new_status": row["new_status"],
                "reason": row["reason"],
                "recorded_at": row["recorded_at"],
                "payload": _load_json(row["payload_json"]),
            }
            for row in rows
        ]


class IncidentRepository:
    """Persist incident records and structured timeline entries."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, incident: IncidentRecord) -> None:
        payload = incident.to_dict()
        opened_at = incident.opened_at or utc_now()
        updated_at = incident.updated_at or opened_at
        self._store.execute(
            """
            INSERT INTO incidents (
                id,
                component_id,
                component_kind,
                severity,
                status,
                title,
                summary,
                workspace_id,
                session_id,
                opened_at,
                updated_at,
                acknowledged_at,
                resolved_at,
                closed_at,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                component_id = excluded.component_id,
                component_kind = excluded.component_kind,
                severity = excluded.severity,
                status = excluded.status,
                title = excluded.title,
                summary = excluded.summary,
                workspace_id = excluded.workspace_id,
                session_id = excluded.session_id,
                opened_at = excluded.opened_at,
                updated_at = excluded.updated_at,
                acknowledged_at = excluded.acknowledged_at,
                resolved_at = excluded.resolved_at,
                closed_at = excluded.closed_at,
                payload_json = excluded.payload_json
            """,
            (
                incident.id,
                incident.component_id,
                incident.component_kind.value,
                incident.severity.value,
                incident.status.value,
                incident.title,
                incident.summary,
                incident.workspace_id,
                incident.session_id,
                opened_at.isoformat(),
                updated_at.isoformat(),
                incident.acknowledged_at.isoformat()
                if incident.acknowledged_at
                else None,
                incident.resolved_at.isoformat() if incident.resolved_at else None,
                incident.closed_at.isoformat() if incident.closed_at else None,
                json.dumps(payload, sort_keys=True),
            ),
        )

    def get(self, incident_id: str) -> IncidentRecord | None:
        row = self._store.fetchone("SELECT * FROM incidents WHERE id = ?", (incident_id,))
        return _incident_from_row(row) if row is not None else None

    def get_open_for_component(self, component_id: str) -> IncidentRecord | None:
        row = self._store.fetchone(
            """
            SELECT *
            FROM incidents
            WHERE component_id = ?
              AND status IN (?, ?, ?, ?)
            ORDER BY opened_at DESC
            LIMIT 1
            """,
            (
                component_id,
                IncidentStatus.OPEN.value,
                IncidentStatus.ACKNOWLEDGED.value,
                IncidentStatus.RECOVERING.value,
                IncidentStatus.QUARANTINED.value,
            ),
        )
        return _incident_from_row(row) if row is not None else None

    def list_recent(
        self,
        *,
        limit: int = 50,
        statuses: tuple[IncidentStatus, ...] | None = None,
        severities: tuple[IncidentSeverity, ...] | None = None,
        component_kind: ComponentKind | None = None,
        search: str | None = None,
    ) -> list[IncidentRecord]:
        sql = "SELECT * FROM incidents WHERE 1=1"
        params: list[object] = []
        if statuses:
            sql += f" AND status IN ({','.join('?' for _ in statuses)})"
            params.extend(item.value for item in statuses)
        if severities:
            sql += f" AND severity IN ({','.join('?' for _ in severities)})"
            params.extend(item.value for item in severities)
        if component_kind is not None:
            sql += " AND component_kind = ?"
            params.append(component_kind.value)
        if search:
            sql += " AND (title LIKE ? OR summary LIKE ? OR component_id LIKE ?)"
            pattern = f"%{search}%"
            params.extend([pattern, pattern, pattern])
        sql += " ORDER BY updated_at DESC, opened_at DESC LIMIT ?"
        params.append(limit)
        rows = self._store.fetchall(sql, tuple(params))
        return [_incident_from_row(row) for row in rows]

    def add_timeline_entry(
        self,
        *,
        incident_id: str,
        event_type: str,
        message: str,
        payload: dict[str, object] | None = None,
        recorded_at: datetime | None = None,
    ) -> None:
        self._store.execute(
            """
            INSERT INTO incident_timeline (
                incident_id,
                event_type,
                message,
                recorded_at,
                payload_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                incident_id,
                event_type,
                message,
                (recorded_at or utc_now()).isoformat(),
                json.dumps(payload or {}, sort_keys=True),
            ),
        )

    def list_timeline(self, incident_id: str) -> list[IncidentTimelineEntry]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM incident_timeline
            WHERE incident_id = ?
            ORDER BY recorded_at ASC, id ASC
            """,
            (incident_id,),
        )
        return [
            IncidentTimelineEntry(
                id=int(row["id"]),
                incident_id=str(row["incident_id"]),
                event_type=str(row["event_type"]),
                message=str(row["message"]),
                recorded_at=datetime.fromisoformat(str(row["recorded_at"])),
                payload=_load_json(str(row["payload_json"])),
            )
            for row in rows
        ]


class RecoveryAttemptRepository:
    """Persist and query recovery attempts."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, attempt: RecoveryAttempt) -> None:
        payload = attempt.to_dict()
        self._store.execute(
            """
            INSERT INTO recovery_attempts (
                id,
                incident_id,
                component_id,
                attempt_number,
                status,
                trigger,
                action,
                backoff_ms,
                scheduled_for,
                started_at,
                finished_at,
                error_message,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                incident_id = excluded.incident_id,
                component_id = excluded.component_id,
                attempt_number = excluded.attempt_number,
                status = excluded.status,
                trigger = excluded.trigger,
                action = excluded.action,
                backoff_ms = excluded.backoff_ms,
                scheduled_for = excluded.scheduled_for,
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                error_message = excluded.error_message,
                payload_json = excluded.payload_json
            """,
            (
                attempt.id,
                attempt.incident_id,
                attempt.component_id,
                int(attempt.attempt_number),
                attempt.status.value,
                attempt.trigger,
                attempt.action,
                int(attempt.backoff_ms),
                attempt.scheduled_for.isoformat() if attempt.scheduled_for else None,
                attempt.started_at.isoformat() if attempt.started_at else None,
                attempt.finished_at.isoformat() if attempt.finished_at else None,
                attempt.error_message,
                json.dumps(payload, sort_keys=True),
            ),
        )

    def get(self, attempt_id: str) -> RecoveryAttempt | None:
        row = self._store.fetchone(
            "SELECT * FROM recovery_attempts WHERE id = ?",
            (attempt_id,),
        )
        return _recovery_attempt_from_row(row) if row is not None else None

    def latest_pending_for_component(self, component_id: str) -> RecoveryAttempt | None:
        row = self._store.fetchone(
            """
            SELECT *
            FROM recovery_attempts
            WHERE component_id = ?
              AND status IN (?, ?)
            ORDER BY scheduled_for DESC, id DESC
            LIMIT 1
            """,
            (
                component_id,
                RecoveryAttemptStatus.SCHEDULED.value,
                RecoveryAttemptStatus.RUNNING.value,
            ),
        )
        return _recovery_attempt_from_row(row) if row is not None else None

    def list_for_incident(self, incident_id: str) -> list[RecoveryAttempt]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM recovery_attempts
            WHERE incident_id = ?
            ORDER BY attempt_number ASC, scheduled_for ASC
            """,
            (incident_id,),
        )
        return [_recovery_attempt_from_row(row) for row in rows]

    def recent_for_component(
        self,
        component_id: str,
        *,
        within_seconds: int,
        now: datetime | None = None,
    ) -> list[RecoveryAttempt]:
        since = (now or utc_now()) - timedelta(seconds=max(1, within_seconds))
        rows = self._store.fetchall(
            """
            SELECT *
            FROM recovery_attempts
            WHERE component_id = ?
              AND COALESCE(finished_at, started_at, scheduled_for) >= ?
            ORDER BY COALESCE(finished_at, started_at, scheduled_for) DESC, id DESC
            """,
            (component_id, since.isoformat()),
        )
        return [_recovery_attempt_from_row(row) for row in rows]

    def list_recent(self, limit: int = 25) -> list[RecoveryAttempt]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM recovery_attempts
            ORDER BY COALESCE(finished_at, started_at, scheduled_for) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [_recovery_attempt_from_row(row) for row in rows]


class GuardDecisionRepository:
    """Persist guard policy decisions for audit and diagnostics."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def record(self, decision: GuardDecision, *, recorded_at: datetime | None = None) -> None:
        payload = decision.to_dict()
        self._store.execute(
            """
            INSERT INTO guard_decisions (
                command_id,
                action_kind,
                component_kind,
                target_risk,
                outcome,
                requires_confirmation,
                requires_elevated_mode,
                requires_dry_run,
                audit_required,
                explanation,
                recorded_at,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.command_id,
                decision.action_kind.value,
                decision.component_kind.value,
                decision.target_risk.value,
                decision.outcome.value,
                int(decision.requires_confirmation),
                int(decision.requires_elevated_mode),
                int(decision.requires_dry_run),
                int(decision.audit_required),
                decision.explanation,
                (recorded_at or utc_now()).isoformat(),
                json.dumps(payload, sort_keys=True),
            ),
        )

    def list_recent(self, limit: int = 25) -> list[dict[str, object]]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM guard_decisions
            ORDER BY recorded_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [
            {
                "id": int(row["id"]),
                "command_id": row["command_id"],
                "action_kind": row["action_kind"],
                "component_kind": row["component_kind"],
                "target_risk": row["target_risk"],
                "outcome": row["outcome"],
                "requires_confirmation": bool(row["requires_confirmation"]),
                "requires_elevated_mode": bool(row["requires_elevated_mode"]),
                "requires_dry_run": bool(row["requires_dry_run"]),
                "audit_required": bool(row["audit_required"]),
                "explanation": row["explanation"],
                "recorded_at": row["recorded_at"],
                "payload": _load_json(row["payload_json"]),
            }
            for row in rows
        ]


class OperationDiagnosticsRepository:
    """Persist recent operation diagnostics and latest cached snapshots."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def record(
        self,
        *,
        operation_family: OperationFamily,
        component_id: str,
        subject_ref: str,
        success: bool,
        severity: str,
        summary: str,
        payload: dict[str, object] | None = None,
        recorded_at: datetime | None = None,
    ) -> None:
        effective_time = recorded_at or utc_now()
        self._store.execute(
            """
            INSERT INTO operation_diagnostics (
                operation_family,
                component_id,
                subject_ref,
                success,
                severity,
                summary,
                recorded_at,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                operation_family.value,
                component_id,
                subject_ref,
                int(success),
                severity,
                summary,
                effective_time.isoformat(),
                json.dumps(payload or {}, sort_keys=True),
            ),
        )

    def list_recent(
        self,
        *,
        family: OperationFamily | None = None,
        component_id: str | None = None,
        limit: int = 25,
    ) -> list[OperationDiagnosticRecord]:
        sql = "SELECT * FROM operation_diagnostics WHERE 1=1"
        params: list[object] = []
        if family is not None:
            sql += " AND operation_family = ?"
            params.append(family.value)
        if component_id is not None:
            sql += " AND component_id = ?"
            params.append(component_id)
        sql += " ORDER BY recorded_at DESC, id DESC LIMIT ?"
        params.append(limit)
        rows = self._store.fetchall(sql, tuple(params))
        return [_operation_record_from_row(row) for row in rows]

    def list_recent_failures(
        self,
        *,
        family: OperationFamily,
        subject_ref: str | None = None,
        limit: int = 10,
    ) -> list[OperationDiagnosticRecord]:
        sql = """
            SELECT *
            FROM operation_diagnostics
            WHERE operation_family = ?
              AND success = 0
        """
        params: list[object] = [family.value]
        if subject_ref is not None:
            sql += " AND subject_ref = ?"
            params.append(subject_ref)
        sql += " ORDER BY recorded_at DESC, id DESC LIMIT ?"
        params.append(limit)
        rows = self._store.fetchall(sql, tuple(params))
        return [_operation_record_from_row(row) for row in rows]

    def update_cache(
        self,
        *,
        component_id: str,
        component_kind: ComponentKind,
        snapshot: dict[str, object],
        updated_at: datetime | None = None,
    ) -> None:
        self._store.execute(
            """
            INSERT INTO component_diagnostics_cache (
                component_id,
                component_kind,
                snapshot_json,
                updated_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(component_id) DO UPDATE SET
                component_kind = excluded.component_kind,
                snapshot_json = excluded.snapshot_json,
                updated_at = excluded.updated_at
            """,
            (
                component_id,
                component_kind.value,
                json.dumps(snapshot, sort_keys=True),
                (updated_at or utc_now()).isoformat(),
            ),
        )

    def get_cache(self, component_id: str) -> dict[str, object] | None:
        row = self._store.fetchone(
            """
            SELECT snapshot_json
            FROM component_diagnostics_cache
            WHERE component_id = ?
            """,
            (component_id,),
        )
        if row is None:
            return None
        return _load_json(row["snapshot_json"])


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
        self._store.execute("DELETE FROM notification_channels WHERE id = ?", (channel_id,))


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
                json.dumps([item.value for item in rule.component_kinds], sort_keys=True),
                json.dumps([item.value for item in rule.severities], sort_keys=True),
                json.dumps([item.value for item in rule.risk_levels], sort_keys=True),
                json.dumps([item.value for item in rule.incident_statuses], sort_keys=True),
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
        row = self._store.fetchone("SELECT * FROM notification_rules WHERE id = ?", (rule_id,))
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
                json.dumps([item.value for item in rule.component_kinds], sort_keys=True),
                json.dumps([item.value for item in rule.severities], sort_keys=True),
                json.dumps([item.value for item in rule.risk_levels], sort_keys=True),
                rule.actor,
                json.dumps(payload, sort_keys=True),
                created_at.isoformat(),
                updated_at.isoformat(),
            ),
        )

    def list_all(self, *, enabled_only: bool = False) -> list[NotificationSuppressionRule]:
        sql = "SELECT * FROM notification_suppressions"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY updated_at DESC, id DESC"
        rows = self._store.fetchall(sql)
        return [_notification_suppression_from_row(row) for row in rows]

    def list_active(self, now: datetime | None = None) -> list[NotificationSuppressionRule]:
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
                notification.component_kind.value if notification.component_kind else None,
                notification.incident_status.value if notification.incident_status else None,
                notification.source_event_id,
                notification.suppression_reason,
                json.dumps(payload, sort_keys=True),
                created_at.isoformat(),
            ),
        )

    def get(self, notification_id: str) -> NotificationRecord | None:
        row = self._store.fetchone("SELECT * FROM notifications WHERE id = ?", (notification_id,))
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

    def list_for_notification(self, notification_id: str) -> list[NotificationDeliveryAttempt]:
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

    def list_recent_failures(self, *, limit: int = 25) -> list[NotificationDeliveryAttempt]:
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

    def list_due_attempts(self, now: datetime | None = None) -> list[NotificationDeliveryAttempt]:
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


class ComponentWatchRepository:
    """Persist watch configuration and latest watch state."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save_config(self, config: ComponentWatchConfig) -> None:
        payload = config.to_dict()
        created_at = config.created_at or utc_now()
        updated_at = config.updated_at or created_at
        self._store.execute(
            """
            INSERT INTO component_watch_config (
                id,
                name,
                component_id,
                component_kind,
                subject_kind,
                subject_ref,
                enabled,
                probe_interval_seconds,
                stale_timeout_seconds,
                target_kind,
                target_ref,
                recovery_policy_override_json,
                monitor_config_json,
                payload_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                component_id = excluded.component_id,
                component_kind = excluded.component_kind,
                subject_kind = excluded.subject_kind,
                subject_ref = excluded.subject_ref,
                enabled = excluded.enabled,
                probe_interval_seconds = excluded.probe_interval_seconds,
                stale_timeout_seconds = excluded.stale_timeout_seconds,
                target_kind = excluded.target_kind,
                target_ref = excluded.target_ref,
                recovery_policy_override_json = excluded.recovery_policy_override_json,
                monitor_config_json = excluded.monitor_config_json,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                config.id,
                config.name,
                config.component_id,
                config.component_kind.value,
                config.subject_kind.value,
                config.subject_ref,
                int(config.enabled),
                int(config.probe_interval_seconds),
                int(config.stale_timeout_seconds),
                config.target_kind.value,
                config.target_ref,
                json.dumps(config.recovery_policy_override, sort_keys=True),
                json.dumps(config.monitor_config, sort_keys=True),
                json.dumps(payload, sort_keys=True),
                created_at.isoformat(),
                updated_at.isoformat(),
            ),
        )

    def list_configs(self, *, enabled_only: bool = False) -> list[ComponentWatchConfig]:
        sql = "SELECT * FROM component_watch_config"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY updated_at DESC, id DESC"
        rows = self._store.fetchall(sql)
        return [_component_watch_config_from_row(row) for row in rows]

    def get_config(self, watch_id: str) -> ComponentWatchConfig | None:
        row = self._store.fetchone("SELECT * FROM component_watch_config WHERE id = ?", (watch_id,))
        return _component_watch_config_from_row(row) if row is not None else None

    def delete_config(self, watch_id: str) -> None:
        self._store.execute("DELETE FROM component_watch_config WHERE id = ?", (watch_id,))

    def save_state(self, state: ComponentWatchState) -> None:
        payload = state.to_dict()
        self._store.execute(
            """
            INSERT INTO component_watch_state (
                component_id,
                watch_id,
                component_kind,
                subject_kind,
                subject_ref,
                last_probe_at,
                last_success_at,
                last_failure_at,
                last_outcome,
                last_status,
                payload_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(component_id) DO UPDATE SET
                watch_id = excluded.watch_id,
                component_kind = excluded.component_kind,
                subject_kind = excluded.subject_kind,
                subject_ref = excluded.subject_ref,
                last_probe_at = excluded.last_probe_at,
                last_success_at = excluded.last_success_at,
                last_failure_at = excluded.last_failure_at,
                last_outcome = excluded.last_outcome,
                last_status = excluded.last_status,
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (
                state.component_id,
                state.watch_id,
                state.component_kind.value,
                state.subject_kind.value,
                state.subject_ref,
                state.last_probe_at.isoformat() if state.last_probe_at else None,
                state.last_success_at.isoformat() if state.last_success_at else None,
                state.last_failure_at.isoformat() if state.last_failure_at else None,
                state.last_outcome.value,
                state.last_status,
                json.dumps(payload, sort_keys=True),
                utc_now().isoformat(),
            ),
        )

    def get_state(self, component_id: str) -> ComponentWatchState | None:
        row = self._store.fetchone(
            "SELECT * FROM component_watch_state WHERE component_id = ?",
            (component_id,),
        )
        return _component_watch_state_from_row(row) if row is not None else None

    def list_states(self) -> list[ComponentWatchState]:
        rows = self._store.fetchall(
            "SELECT * FROM component_watch_state ORDER BY updated_at DESC, component_id ASC"
        )
        return [_component_watch_state_from_row(row) for row in rows]


def _component_health_from_row(row: object) -> ComponentHealthState:
    assert row is not None
    return ComponentHealthState(
        component_id=str(row["component_id"]),
        component_kind=ComponentKind(str(row["component_kind"])),
        display_name=str(row["display_name"]),
        status=HealthStatus(str(row["status"])),
        workspace_id=row["workspace_id"],
        session_id=row["session_id"],
        target_kind=SessionTargetKind(str(row["target_kind"])),
        target_ref=row["target_ref"],
        last_heartbeat_at=_decode_datetime(row["last_heartbeat_at"]),
        last_failure_at=_decode_datetime(row["last_failure_at"]),
        last_recovery_at=_decode_datetime(row["last_recovery_at"]),
        next_recovery_at=_decode_datetime(row["next_recovery_at"]),
        cooldown_until=_decode_datetime(row["cooldown_until"]),
        consecutive_failures=int(row["consecutive_failures"] or 0),
        exhaustion_count=int(row["exhaustion_count"] or 0),
        quarantined=bool(row["quarantined"]),
        quarantine_reason=row["quarantine_reason"],
        last_incident_id=row["last_incident_id"],
        payload=_load_json(str(row["payload_json"])),
        updated_at=_decode_datetime(row["updated_at"]),
    )


def _incident_from_row(row: object) -> IncidentRecord:
    assert row is not None
    return IncidentRecord(
        id=str(row["id"]),
        component_id=str(row["component_id"]),
        component_kind=ComponentKind(str(row["component_kind"])),
        severity=IncidentSeverity(str(row["severity"])),
        status=IncidentStatus(str(row["status"])),
        title=str(row["title"]),
        summary=str(row["summary"]),
        workspace_id=row["workspace_id"],
        session_id=row["session_id"],
        opened_at=_decode_datetime(row["opened_at"]),
        updated_at=_decode_datetime(row["updated_at"]),
        acknowledged_at=_decode_datetime(row["acknowledged_at"]),
        resolved_at=_decode_datetime(row["resolved_at"]),
        closed_at=_decode_datetime(row["closed_at"]),
        payload=_load_json(str(row["payload_json"])),
    )


def _recovery_attempt_from_row(row: object) -> RecoveryAttempt:
    assert row is not None
    return RecoveryAttempt(
        id=str(row["id"]),
        incident_id=str(row["incident_id"]),
        component_id=str(row["component_id"]),
        attempt_number=int(row["attempt_number"]),
        status=RecoveryAttemptStatus(str(row["status"])),
        trigger=str(row["trigger"]),
        action=str(row["action"]),
        backoff_ms=int(row["backoff_ms"] or 0),
        scheduled_for=_decode_datetime(row["scheduled_for"]),
        started_at=_decode_datetime(row["started_at"]),
        finished_at=_decode_datetime(row["finished_at"]),
        error_message=row["error_message"],
        payload=_load_json(str(row["payload_json"])),
    )


def _operation_record_from_row(row: object) -> OperationDiagnosticRecord:
    assert row is not None
    return OperationDiagnosticRecord(
        id=int(row["id"]),
        operation_family=OperationFamily(str(row["operation_family"])),
        component_id=str(row["component_id"]),
        subject_ref=str(row["subject_ref"]),
        success=bool(row["success"]),
        severity=str(row["severity"]),
        summary=str(row["summary"]),
        recorded_at=str(row["recorded_at"]),
        payload=_load_json(str(row["payload_json"])),
    )


def _notification_channel_from_row(row: object) -> NotificationChannel:
    assert row is not None
    return NotificationChannel(
        id=str(row["id"]),
        name=str(row["name"]),
        kind=NotificationChannelKind(str(row["kind"])),
        enabled=bool(row["enabled"]),
        target=_load_json(str(row["target_json"])),
        secret_refs={str(key): str(value) for key, value in _load_json(str(row["secret_refs_json"])).items()},
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
        IncidentSeverity(str(item))
        for item in json.loads(str(row["severities_json"]))
    )
    risk_levels = tuple(
        TargetRiskLevel(str(item))
        for item in json.loads(str(row["risk_levels_json"]))
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
        component_id=str(row["component_id"]) if row["component_id"] is not None else None,
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
            str(row["suppression_reason"]) if row["suppression_reason"] is not None else None
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
        error_message=str(row["error_message"]) if row["error_message"] is not None else None,
        response_payload=_load_json(str(row["response_payload_json"])),
    )


def _component_watch_config_from_row(row: object) -> ComponentWatchConfig:
    assert row is not None
    return ComponentWatchConfig(
        id=str(row["id"]),
        name=str(row["name"]),
        component_id=str(row["component_id"]),
        component_kind=ComponentKind(str(row["component_kind"])),
        subject_kind=WatchSubjectKind(str(row["subject_kind"])),
        subject_ref=str(row["subject_ref"]),
        enabled=bool(row["enabled"]),
        probe_interval_seconds=int(row["probe_interval_seconds"] or 0),
        stale_timeout_seconds=int(row["stale_timeout_seconds"] or 0),
        target_kind=SessionTargetKind(str(row["target_kind"])),
        target_ref=str(row["target_ref"]) if row["target_ref"] is not None else None,
        recovery_policy_override=_load_json(str(row["recovery_policy_override_json"])),
        monitor_config=_load_json(str(row["monitor_config_json"])),
        created_at=_decode_datetime(row["created_at"]),
        updated_at=_decode_datetime(row["updated_at"]),
    )


def _component_watch_state_from_row(row: object) -> ComponentWatchState:
    assert row is not None
    return ComponentWatchState(
        component_id=str(row["component_id"]),
        watch_id=str(row["watch_id"]),
        component_kind=ComponentKind(str(row["component_kind"])),
        subject_kind=WatchSubjectKind(str(row["subject_kind"])),
        subject_ref=str(row["subject_ref"]),
        last_probe_at=_decode_datetime(row["last_probe_at"]),
        last_success_at=_decode_datetime(row["last_success_at"]),
        last_failure_at=_decode_datetime(row["last_failure_at"]),
        last_outcome=WatchProbeOutcome(str(row["last_outcome"])),
        last_status=str(row["last_status"]),
        payload=_load_json(str(row["payload_json"])),
    )
