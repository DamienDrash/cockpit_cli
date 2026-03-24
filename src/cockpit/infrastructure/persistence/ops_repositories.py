"""SQLite repositories for operational health, incidents, policy, and diagnostics."""

from __future__ import annotations

from datetime import datetime, timedelta
import json

from cockpit.domain.models.diagnostics import OperationDiagnosticRecord
from cockpit.domain.models.escalation import (
    EngagementDeliveryLink,
    EngagementTimelineEntry,
    EscalationPolicy,
    EscalationStep,
    IncidentEngagement,
)
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
from cockpit.domain.models.oncall import (
    OnCallSchedule,
    OperatorContactTarget,
    OperatorPerson,
    OperatorTeam,
    OwnershipBinding,
    RotationRule,
    ScheduleOverride,
    TeamMembership,
)
from cockpit.domain.models.policy import GuardDecision
from cockpit.domain.models.response import (
    ApprovalDecision,
    ApprovalRequest,
    CompensationRun,
    ResponseArtifact,
    ResponseRun,
    ResponseStepRun,
    RunbookDefinition,
    RunbookCompensationDefinition,
    RunbookStepDefinition,
    RunbookArtifactDefinition,
)
from cockpit.domain.models.review import ActionItem, PostIncidentReview, ReviewFinding
from cockpit.domain.models.watch import ComponentWatchConfig, ComponentWatchState
from cockpit.infrastructure.persistence.sqlite_store import SQLiteStore
from cockpit.shared.enums import (
    ActionItemStatus,
    ApprovalDecisionKind,
    ApprovalRequestStatus,
    ClosureQuality,
    ComponentKind,
    CompensationStatus,
    EngagementDeliveryPurpose,
    EngagementStatus,
    EscalationTargetKind,
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
    OwnershipSubjectKind,
    PostIncidentReviewStatus,
    RecoveryAttemptStatus,
    ResolutionOutcome,
    ResponseRunStatus,
    ResponseStepStatus,
    ReviewFindingCategory,
    RotationIntervalKind,
    RunbookExecutorKind,
    RunbookRiskClass,
    ScheduleCoverageKind,
    SessionTargetKind,
    TargetRiskLevel,
    TeamMembershipRole,
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


class OperatorPersonRepository:
    """Persist operator people and contact metadata."""

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
                json.dumps([target.to_dict() for target in person.contact_targets], sort_keys=True),
                json.dumps(person.metadata, sort_keys=True),
                json.dumps(payload, sort_keys=True),
                created_at.isoformat(),
                updated_at.isoformat(),
            ),
        )

    def get(self, person_id: str) -> OperatorPerson | None:
        row = self._store.fetchone("SELECT * FROM operator_people WHERE id = ?", (person_id,))
        return _operator_person_from_row(row) if row is not None else None

    def list_all(self, *, enabled_only: bool = False) -> list[OperatorPerson]:
        sql = "SELECT * FROM operator_people"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY display_name ASC, id ASC"
        rows = self._store.fetchall(sql)
        return [_operator_person_from_row(row) for row in rows]

    def delete(self, person_id: str) -> None:
        self._store.execute("DELETE FROM operator_people WHERE id = ?", (person_id,))


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
        row = self._store.fetchone("SELECT * FROM operator_teams WHERE id = ?", (team_id,))
        return _operator_team_from_row(row) if row is not None else None

    def list_all(self, *, enabled_only: bool = False) -> list[OperatorTeam]:
        sql = "SELECT * FROM operator_teams"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY name ASC, id ASC"
        rows = self._store.fetchall(sql)
        return [_operator_team_from_row(row) for row in rows]

    def delete(self, team_id: str) -> None:
        self._store.execute("DELETE FROM operator_teams WHERE id = ?", (team_id,))


class TeamMembershipRepository:
    """Persist team memberships."""

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

    def list_all(self, *, enabled_only: bool = False) -> list[TeamMembership]:
        sql = "SELECT * FROM team_memberships"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY team_id ASC, person_id ASC"
        rows = self._store.fetchall(sql)
        return [_team_membership_from_row(row) for row in rows]

    def list_for_team(self, team_id: str, *, enabled_only: bool = False) -> list[TeamMembership]:
        sql = "SELECT * FROM team_memberships WHERE team_id = ?"
        params: list[object] = [team_id]
        if enabled_only:
            sql += " AND enabled = 1"
        sql += " ORDER BY person_id ASC, id ASC"
        rows = self._store.fetchall(sql, tuple(params))
        return [_team_membership_from_row(row) for row in rows]

    def delete(self, membership_id: str) -> None:
        self._store.execute("DELETE FROM team_memberships WHERE id = ?", (membership_id,))


class OwnershipBindingRepository:
    """Persist ownership bindings from runtime subjects to teams."""

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
                binding.component_kind.value if binding.component_kind is not None else None,
                binding.component_id,
                binding.subject_kind.value if binding.subject_kind is not None else None,
                binding.subject_ref,
                binding.risk_level.value if binding.risk_level is not None else None,
                binding.escalation_policy_id,
                json.dumps(payload, sort_keys=True),
                created_at.isoformat(),
                updated_at.isoformat(),
            ),
        )

    def get(self, binding_id: str) -> OwnershipBinding | None:
        row = self._store.fetchone("SELECT * FROM ownership_bindings WHERE id = ?", (binding_id,))
        return _ownership_binding_from_row(row) if row is not None else None

    def list_all(self, *, enabled_only: bool = False) -> list[OwnershipBinding]:
        sql = "SELECT * FROM ownership_bindings"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY updated_at DESC, id DESC"
        rows = self._store.fetchall(sql)
        return [_ownership_binding_from_row(row) for row in rows]

    def delete(self, binding_id: str) -> None:
        self._store.execute("DELETE FROM ownership_bindings WHERE id = ?", (binding_id,))


class OnCallScheduleRepository:
    """Persist schedule envelopes for teams."""

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

    def get(self, schedule_id: str) -> OnCallSchedule | None:
        row = self._store.fetchone("SELECT * FROM oncall_schedules WHERE id = ?", (schedule_id,))
        return _oncall_schedule_from_row(row) if row is not None else None

    def list_all(self, *, enabled_only: bool = False) -> list[OnCallSchedule]:
        sql = "SELECT * FROM oncall_schedules"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY team_id ASC, name ASC"
        rows = self._store.fetchall(sql)
        return [_oncall_schedule_from_row(row) for row in rows]

    def list_for_team(self, team_id: str, *, enabled_only: bool = False) -> list[OnCallSchedule]:
        sql = "SELECT * FROM oncall_schedules WHERE team_id = ?"
        params: list[object] = [team_id]
        if enabled_only:
            sql += " AND enabled = 1"
        sql += " ORDER BY name ASC, id ASC"
        rows = self._store.fetchall(sql, tuple(params))
        return [_oncall_schedule_from_row(row) for row in rows]

    def delete(self, schedule_id: str) -> None:
        self._store.execute("DELETE FROM oncall_schedules WHERE id = ?", (schedule_id,))


class RotationRuleRepository:
    """Persist rotation rules for schedules."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, rotation: RotationRule) -> None:
        payload = rotation.to_dict()
        created_at = rotation.created_at or utc_now()
        updated_at = rotation.updated_at or created_at
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
                rotation.id,
                rotation.schedule_id,
                rotation.name,
                json.dumps(list(rotation.participant_ids), sort_keys=True),
                int(rotation.enabled),
                rotation.anchor_at.isoformat() if rotation.anchor_at else None,
                rotation.interval_kind.value,
                int(rotation.interval_count),
                rotation.handoff_time,
                json.dumps(payload, sort_keys=True),
                created_at.isoformat(),
                updated_at.isoformat(),
            ),
        )

    def get(self, rotation_id: str) -> RotationRule | None:
        row = self._store.fetchone("SELECT * FROM schedule_rotations WHERE id = ?", (rotation_id,))
        return _rotation_rule_from_row(row) if row is not None else None

    def list_for_schedule(self, schedule_id: str, *, enabled_only: bool = False) -> list[RotationRule]:
        sql = "SELECT * FROM schedule_rotations WHERE schedule_id = ?"
        params: list[object] = [schedule_id]
        if enabled_only:
            sql += " AND enabled = 1"
        sql += " ORDER BY name ASC, id ASC"
        rows = self._store.fetchall(sql, tuple(params))
        return [_rotation_rule_from_row(row) for row in rows]

    def delete(self, rotation_id: str) -> None:
        self._store.execute("DELETE FROM schedule_rotations WHERE id = ?", (rotation_id,))


class ScheduleOverrideRepository:
    """Persist temporary on-call overrides."""

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

    def get(self, override_id: str) -> ScheduleOverride | None:
        row = self._store.fetchone("SELECT * FROM schedule_overrides WHERE id = ?", (override_id,))
        return _schedule_override_from_row(row) if row is not None else None

    def list_for_schedule(self, schedule_id: str, *, enabled_only: bool = False) -> list[ScheduleOverride]:
        sql = "SELECT * FROM schedule_overrides WHERE schedule_id = ?"
        params: list[object] = [schedule_id]
        if enabled_only:
            sql += " AND enabled = 1"
        sql += " ORDER BY starts_at ASC, priority DESC, id ASC"
        rows = self._store.fetchall(sql, tuple(params))
        return [_schedule_override_from_row(row) for row in rows]

    def list_active_for_schedule(
        self,
        schedule_id: str,
        *,
        effective_at: datetime,
    ) -> list[ScheduleOverride]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM schedule_overrides
            WHERE schedule_id = ?
              AND enabled = 1
              AND starts_at <= ?
              AND ends_at >= ?
            ORDER BY priority DESC, starts_at ASC, id ASC
            """,
            (schedule_id, effective_at.isoformat(), effective_at.isoformat()),
        )
        return [_schedule_override_from_row(row) for row in rows]

    def delete(self, override_id: str) -> None:
        self._store.execute("DELETE FROM schedule_overrides WHERE id = ?", (override_id,))


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
        row = self._store.fetchone("SELECT * FROM escalation_policies WHERE id = ?", (policy_id,))
        return _escalation_policy_from_row(row) if row is not None else None

    def list_all(self, *, enabled_only: bool = False) -> list[EscalationPolicy]:
        sql = "SELECT * FROM escalation_policies"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY name ASC, id ASC"
        rows = self._store.fetchall(sql)
        return [_escalation_policy_from_row(row) for row in rows]

    def delete(self, policy_id: str) -> None:
        self._store.execute("DELETE FROM escalation_policies WHERE id = ?", (policy_id,))


class EscalationStepRepository:
    """Persist escalation steps."""

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
            """
            SELECT *
            FROM escalation_steps
            WHERE policy_id = ?
            ORDER BY step_index ASC, id ASC
            """,
            (policy_id,),
        )
        return [_escalation_step_from_row(row) for row in rows]

    def delete_for_policy(self, policy_id: str) -> None:
        self._store.execute("DELETE FROM escalation_steps WHERE policy_id = ?", (policy_id,))


class IncidentEngagementRepository:
    """Persist active incident engagement runtime state."""

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
                engagement.current_target_kind.value if engagement.current_target_kind else None,
                engagement.current_target_ref,
                engagement.resolved_person_id,
                engagement.acknowledged_by,
                engagement.acknowledged_at.isoformat() if engagement.acknowledged_at else None,
                int(engagement.handoff_count),
                int(engagement.repeat_page_count),
                engagement.next_action_at.isoformat() if engagement.next_action_at else None,
                engagement.ack_deadline_at.isoformat() if engagement.ack_deadline_at else None,
                engagement.last_page_at.isoformat() if engagement.last_page_at else None,
                int(engagement.exhausted),
                json.dumps(payload, sort_keys=True),
                created_at.isoformat(),
                updated_at.isoformat(),
                engagement.closed_at.isoformat() if engagement.closed_at else None,
            ),
        )

    def get(self, engagement_id: str) -> IncidentEngagement | None:
        row = self._store.fetchone("SELECT * FROM incident_engagements WHERE id = ?", (engagement_id,))
        return _incident_engagement_from_row(row) if row is not None else None

    def get_active_for_incident(self, incident_id: str) -> IncidentEngagement | None:
        row = self._store.fetchone(
            """
            SELECT *
            FROM incident_engagements
            WHERE incident_id = ?
              AND status IN (?, ?, ?)
            ORDER BY updated_at DESC, created_at DESC
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

    def list_active(self, limit: int = 50) -> list[IncidentEngagement]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM incident_engagements
            WHERE status IN (?, ?, ?)
            ORDER BY updated_at DESC, created_at DESC
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

    def list_recent(self, limit: int = 50) -> list[IncidentEngagement]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM incident_engagements
            ORDER BY updated_at DESC, created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [_incident_engagement_from_row(row) for row in rows]

    def list_due_actions(self, effective_now: datetime) -> list[IncidentEngagement]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM incident_engagements
            WHERE status = ?
              AND next_action_at IS NOT NULL
              AND next_action_at <= ?
            ORDER BY next_action_at ASC, updated_at ASC
            """,
            (EngagementStatus.ACTIVE.value, effective_now.isoformat()),
        )
        return [_incident_engagement_from_row(row) for row in rows]


class EngagementTimelineRepository:
    """Persist engagement timeline entries."""

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
    """Persist correlation between engagements and notifications."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, link: EngagementDeliveryLink) -> None:
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
                (link.created_at or utc_now()).isoformat(),
                json.dumps(link.payload, sort_keys=True),
            ),
        )

    def list_for_engagement(self, engagement_id: str) -> list[EngagementDeliveryLink]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM engagement_delivery_links
            WHERE engagement_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (engagement_id,),
        )
        return [_engagement_delivery_link_from_row(row) for row in rows]

    def list_for_notification(self, notification_id: str) -> list[EngagementDeliveryLink]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM engagement_delivery_links
            WHERE notification_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (notification_id,),
        )
        return [_engagement_delivery_link_from_row(row) for row in rows]


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
        component_id=str(row["component_id"]) if row["component_id"] is not None else None,
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
    participant_ids = tuple(str(item) for item in json.loads(str(row["participant_ids_json"])))
    return RotationRule(
        id=str(row["id"]),
        schedule_id=str(row["schedule_id"]),
        name=str(row["name"]),
        participant_ids=participant_ids,
        enabled=bool(row["enabled"]),
        anchor_at=_decode_datetime(row["anchor_at"]),
        interval_kind=RotationIntervalKind(str(row["interval_kind"])),
        interval_count=int(row["interval_count"] or 1),
        handoff_time=str(row["handoff_time"]) if row["handoff_time"] is not None else None,
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
            str(row["replaced_person_id"]) if row["replaced_person_id"] is not None else None
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
            str(row["current_target_ref"]) if row["current_target_ref"] is not None else None
        ),
        resolved_person_id=(
            str(row["resolved_person_id"]) if row["resolved_person_id"] is not None else None
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


class RunbookCatalogRepository:
    """Persist the loaded runbook catalog."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def replace_catalog(self, runbooks: list[RunbookDefinition]) -> None:
        catalog_keys = [runbook.catalog_key for runbook in runbooks]
        with self._store.transaction():
            if catalog_keys:
                placeholders = ", ".join("?" for _ in catalog_keys)
                self._store.execute(
                    f"DELETE FROM runbook_catalog WHERE catalog_key NOT IN ({placeholders})",
                    tuple(catalog_keys),
                )
            else:
                self._store.execute("DELETE FROM runbook_catalog")
            for runbook in runbooks:
                self.save(runbook)

    def save(self, runbook: RunbookDefinition) -> None:
        payload = runbook.to_dict()
        self._store.execute(
            """
            INSERT INTO runbook_catalog (
                catalog_key,
                runbook_id,
                runbook_version,
                title,
                description,
                risk_class,
                source_path,
                checksum,
                tags_json,
                scope_json,
                payload_json,
                loaded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(catalog_key) DO UPDATE SET
                title = excluded.title,
                description = excluded.description,
                risk_class = excluded.risk_class,
                source_path = excluded.source_path,
                checksum = excluded.checksum,
                tags_json = excluded.tags_json,
                scope_json = excluded.scope_json,
                payload_json = excluded.payload_json,
                loaded_at = excluded.loaded_at
            """,
            (
                runbook.catalog_key,
                runbook.id,
                runbook.version,
                runbook.title,
                runbook.description,
                runbook.risk_class.value,
                runbook.source_path or "",
                runbook.checksum or "",
                json.dumps(list(runbook.tags), sort_keys=True),
                json.dumps(dict(runbook.scope), sort_keys=True),
                json.dumps(payload, sort_keys=True),
                (runbook.loaded_at or utc_now()).isoformat(),
            ),
        )

    def get(self, runbook_id: str, version: str | None = None) -> RunbookDefinition | None:
        if version is None:
            row = self._store.fetchone(
                """
                SELECT *
                FROM runbook_catalog
                WHERE runbook_id = ?
                ORDER BY loaded_at DESC
                LIMIT 1
                """,
                (runbook_id,),
            )
        else:
            row = self._store.fetchone(
                """
                SELECT *
                FROM runbook_catalog
                WHERE runbook_id = ? AND runbook_version = ?
                LIMIT 1
                """,
                (runbook_id, version),
            )
        return _runbook_from_row(row) if row is not None else None

    def list_all(self) -> list[RunbookDefinition]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM runbook_catalog
            ORDER BY runbook_id ASC, runbook_version DESC
            """
        )
        return [_runbook_from_row(row) for row in rows]


class ResponseRunRepository:
    """Persist response runs."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, run: ResponseRun) -> None:
        payload = run.to_dict()
        self._store.execute(
            """
            INSERT INTO response_runs (
                id,
                incident_id,
                engagement_id,
                runbook_id,
                runbook_version,
                status,
                current_step_index,
                risk_level,
                elevated_mode,
                started_by,
                started_at,
                updated_at,
                completed_at,
                summary,
                last_error,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                incident_id = excluded.incident_id,
                engagement_id = excluded.engagement_id,
                runbook_id = excluded.runbook_id,
                runbook_version = excluded.runbook_version,
                status = excluded.status,
                current_step_index = excluded.current_step_index,
                risk_level = excluded.risk_level,
                elevated_mode = excluded.elevated_mode,
                started_by = excluded.started_by,
                started_at = excluded.started_at,
                updated_at = excluded.updated_at,
                completed_at = excluded.completed_at,
                summary = excluded.summary,
                last_error = excluded.last_error,
                payload_json = excluded.payload_json
            """,
            (
                run.id,
                run.incident_id,
                run.engagement_id,
                run.runbook_id,
                run.runbook_version,
                run.status.value,
                run.current_step_index,
                run.risk_level.value,
                int(run.elevated_mode),
                run.started_by,
                run.started_at.isoformat() if run.started_at else None,
                (run.updated_at or utc_now()).isoformat(),
                run.completed_at.isoformat() if run.completed_at else None,
                run.summary,
                run.last_error,
                json.dumps(payload, sort_keys=True),
            ),
        )

    def get(self, run_id: str) -> ResponseRun | None:
        row = self._store.fetchone("SELECT * FROM response_runs WHERE id = ?", (run_id,))
        return _response_run_from_row(row) if row is not None else None

    def get_active_for_incident(self, incident_id: str) -> ResponseRun | None:
        row = self._store.fetchone(
            """
            SELECT *
            FROM response_runs
            WHERE incident_id = ?
              AND status NOT IN (?, ?, ?)
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (
                incident_id,
                ResponseRunStatus.COMPLETED.value,
                ResponseRunStatus.ABORTED.value,
                ResponseRunStatus.FAILED.value,
            ),
        )
        return _response_run_from_row(row) if row is not None else None

    def list_active(self, *, limit: int = 25) -> list[ResponseRun]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM response_runs
            WHERE status NOT IN (?, ?, ?)
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (
                ResponseRunStatus.COMPLETED.value,
                ResponseRunStatus.ABORTED.value,
                ResponseRunStatus.FAILED.value,
                limit,
            ),
        )
        return [_response_run_from_row(row) for row in rows]

    def list_recent(self, *, limit: int = 50) -> list[ResponseRun]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM response_runs
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [_response_run_from_row(row) for row in rows]


class ResponseStepRunRepository:
    """Persist step-level execution state."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, step_run: ResponseStepRun) -> None:
        payload = step_run.to_dict()
        self._store.execute(
            """
            INSERT INTO response_step_runs (
                id,
                response_run_id,
                step_key,
                step_index,
                executor_kind,
                status,
                attempt_count,
                guard_decision_id,
                approval_request_id,
                started_at,
                finished_at,
                output_summary,
                output_payload_json,
                last_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                response_run_id = excluded.response_run_id,
                step_key = excluded.step_key,
                step_index = excluded.step_index,
                executor_kind = excluded.executor_kind,
                status = excluded.status,
                attempt_count = excluded.attempt_count,
                guard_decision_id = excluded.guard_decision_id,
                approval_request_id = excluded.approval_request_id,
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                output_summary = excluded.output_summary,
                output_payload_json = excluded.output_payload_json,
                last_error = excluded.last_error
            """,
            (
                step_run.id,
                step_run.response_run_id,
                step_run.step_key,
                step_run.step_index,
                step_run.executor_kind.value,
                step_run.status.value,
                step_run.attempt_count,
                step_run.guard_decision_id,
                step_run.approval_request_id,
                step_run.started_at.isoformat() if step_run.started_at else None,
                step_run.finished_at.isoformat() if step_run.finished_at else None,
                step_run.output_summary,
                json.dumps(
                    {
                        "payload": step_run.output_payload,
                        "contract": payload,
                    },
                    sort_keys=True,
                ),
                step_run.last_error,
            ),
        )

    def get(self, step_run_id: str) -> ResponseStepRun | None:
        row = self._store.fetchone(
            "SELECT * FROM response_step_runs WHERE id = ?",
            (step_run_id,),
        )
        return _response_step_run_from_row(row) if row is not None else None

    def get_current_for_run(self, response_run_id: str) -> ResponseStepRun | None:
        row = self._store.fetchone(
            """
            SELECT *
            FROM response_step_runs
            WHERE response_run_id = ?
            ORDER BY step_index DESC
            LIMIT 1
            """,
            (response_run_id,),
        )
        return _response_step_run_from_row(row) if row is not None else None

    def get_by_run_and_index(self, response_run_id: str, step_index: int) -> ResponseStepRun | None:
        row = self._store.fetchone(
            """
            SELECT *
            FROM response_step_runs
            WHERE response_run_id = ? AND step_index = ?
            LIMIT 1
            """,
            (response_run_id, step_index),
        )
        return _response_step_run_from_row(row) if row is not None else None

    def list_for_run(self, response_run_id: str) -> list[ResponseStepRun]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM response_step_runs
            WHERE response_run_id = ?
            ORDER BY step_index ASC
            """,
            (response_run_id,),
        )
        return [_response_step_run_from_row(row) for row in rows]


class ApprovalRequestRepository:
    """Persist approval requests for response steps."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, request: ApprovalRequest) -> None:
        payload = request.to_dict()
        self._store.execute(
            """
            INSERT INTO approval_requests (
                id,
                response_run_id,
                step_run_id,
                status,
                requested_by,
                required_approver_count,
                required_roles_json,
                allow_self_approval,
                reason,
                expires_at,
                created_at,
                resolved_at,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                response_run_id = excluded.response_run_id,
                step_run_id = excluded.step_run_id,
                status = excluded.status,
                requested_by = excluded.requested_by,
                required_approver_count = excluded.required_approver_count,
                required_roles_json = excluded.required_roles_json,
                allow_self_approval = excluded.allow_self_approval,
                reason = excluded.reason,
                expires_at = excluded.expires_at,
                created_at = excluded.created_at,
                resolved_at = excluded.resolved_at,
                payload_json = excluded.payload_json
            """,
            (
                request.id,
                request.response_run_id,
                request.step_run_id,
                request.status.value,
                request.requested_by,
                request.required_approver_count,
                json.dumps(list(request.required_roles), sort_keys=True),
                int(request.allow_self_approval),
                request.reason,
                request.expires_at.isoformat() if request.expires_at else None,
                (request.created_at or utc_now()).isoformat(),
                request.resolved_at.isoformat() if request.resolved_at else None,
                json.dumps(payload, sort_keys=True),
            ),
        )

    def get(self, request_id: str) -> ApprovalRequest | None:
        row = self._store.fetchone("SELECT * FROM approval_requests WHERE id = ?", (request_id,))
        return _approval_request_from_row(row) if row is not None else None

    def get_active_for_step(self, step_run_id: str) -> ApprovalRequest | None:
        row = self._store.fetchone(
            """
            SELECT *
            FROM approval_requests
            WHERE step_run_id = ?
              AND status = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (step_run_id, ApprovalRequestStatus.PENDING.value),
        )
        return _approval_request_from_row(row) if row is not None else None

    def get_latest_for_step(self, step_run_id: str) -> ApprovalRequest | None:
        row = self._store.fetchone(
            """
            SELECT *
            FROM approval_requests
            WHERE step_run_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (step_run_id,),
        )
        return _approval_request_from_row(row) if row is not None else None

    def list_for_run(self, response_run_id: str) -> list[ApprovalRequest]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM approval_requests
            WHERE response_run_id = ?
            ORDER BY created_at DESC
            """,
            (response_run_id,),
        )
        return [_approval_request_from_row(row) for row in rows]

    def list_pending(self, *, limit: int = 50) -> list[ApprovalRequest]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM approval_requests
            WHERE status = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (ApprovalRequestStatus.PENDING.value, limit),
        )
        return [_approval_request_from_row(row) for row in rows]

    def list_expired(self, now: datetime | None = None) -> list[ApprovalRequest]:
        effective_now = (now or utc_now()).isoformat()
        rows = self._store.fetchall(
            """
            SELECT *
            FROM approval_requests
            WHERE status = ?
              AND expires_at IS NOT NULL
              AND expires_at <= ?
            ORDER BY expires_at ASC
            """,
            (ApprovalRequestStatus.PENDING.value, effective_now),
        )
        return [_approval_request_from_row(row) for row in rows]


class ApprovalDecisionRepository:
    """Persist individual approval decisions."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, decision: ApprovalDecision) -> None:
        payload = decision.to_dict()
        self._store.execute(
            """
            INSERT INTO approval_decisions (
                id,
                approval_request_id,
                approver_ref,
                decision,
                comment,
                created_at,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                approval_request_id = excluded.approval_request_id,
                approver_ref = excluded.approver_ref,
                decision = excluded.decision,
                comment = excluded.comment,
                created_at = excluded.created_at,
                payload_json = excluded.payload_json
            """,
            (
                decision.id,
                decision.approval_request_id,
                decision.approver_ref,
                decision.decision.value,
                decision.comment,
                (decision.created_at or utc_now()).isoformat(),
                json.dumps(payload, sort_keys=True),
            ),
        )

    def list_for_request(self, approval_request_id: str) -> list[ApprovalDecision]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM approval_decisions
            WHERE approval_request_id = ?
            ORDER BY created_at ASC
            """,
            (approval_request_id,),
        )
        return [_approval_decision_from_row(row) for row in rows]


class ResponseArtifactRepository:
    """Persist response artifacts."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, artifact: ResponseArtifact) -> None:
        payload = artifact.to_dict()
        self._store.execute(
            """
            INSERT INTO response_artifacts (
                id,
                response_run_id,
                step_run_id,
                artifact_kind,
                label,
                storage_ref,
                summary,
                payload_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                response_run_id = excluded.response_run_id,
                step_run_id = excluded.step_run_id,
                artifact_kind = excluded.artifact_kind,
                label = excluded.label,
                storage_ref = excluded.storage_ref,
                summary = excluded.summary,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at
            """,
            (
                artifact.id,
                artifact.response_run_id,
                artifact.step_run_id,
                artifact.artifact_kind,
                artifact.label,
                artifact.storage_ref,
                artifact.summary,
                json.dumps(payload, sort_keys=True),
                (artifact.created_at or utc_now()).isoformat(),
            ),
        )

    def list_for_run(self, response_run_id: str) -> list[ResponseArtifact]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM response_artifacts
            WHERE response_run_id = ?
            ORDER BY created_at DESC
            """,
            (response_run_id,),
        )
        return [_response_artifact_from_row(row) for row in rows]


class CompensationRunRepository:
    """Persist compensation runs."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, compensation_run: CompensationRun) -> None:
        payload = compensation_run.to_dict()
        self._store.execute(
            """
            INSERT INTO compensation_runs (
                id,
                response_run_id,
                step_run_id,
                status,
                started_at,
                finished_at,
                summary,
                last_error,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                response_run_id = excluded.response_run_id,
                step_run_id = excluded.step_run_id,
                status = excluded.status,
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                summary = excluded.summary,
                last_error = excluded.last_error,
                payload_json = excluded.payload_json
            """,
            (
                compensation_run.id,
                compensation_run.response_run_id,
                compensation_run.step_run_id,
                compensation_run.status.value,
                compensation_run.started_at.isoformat() if compensation_run.started_at else None,
                compensation_run.finished_at.isoformat() if compensation_run.finished_at else None,
                compensation_run.summary,
                compensation_run.last_error,
                json.dumps(payload, sort_keys=True),
            ),
        )

    def latest_for_step(self, step_run_id: str) -> CompensationRun | None:
        row = self._store.fetchone(
            """
            SELECT *
            FROM compensation_runs
            WHERE step_run_id = ?
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (step_run_id,),
        )
        return _compensation_run_from_row(row) if row is not None else None

    def list_for_run(self, response_run_id: str) -> list[CompensationRun]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM compensation_runs
            WHERE response_run_id = ?
            ORDER BY started_at DESC
            """,
            (response_run_id,),
        )
        return [_compensation_run_from_row(row) for row in rows]


class ResponseTimelineRepository:
    """Persist response timeline entries."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def add_entry(
        self,
        *,
        response_run_id: str,
        incident_id: str,
        event_type: str,
        message: str,
        payload: dict[str, object] | None = None,
        recorded_at: datetime | None = None,
    ) -> None:
        self._store.execute(
            """
            INSERT INTO response_timeline (
                response_run_id,
                incident_id,
                event_type,
                message,
                recorded_at,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                response_run_id,
                incident_id,
                event_type,
                message,
                (recorded_at or utc_now()).isoformat(),
                json.dumps(payload or {}, sort_keys=True),
            ),
        )

    def list_for_run(self, response_run_id: str) -> list[dict[str, object]]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM response_timeline
            WHERE response_run_id = ?
            ORDER BY recorded_at ASC, id ASC
            """,
            (response_run_id,),
        )
        return [
            {
                "id": int(row["id"]),
                "response_run_id": str(row["response_run_id"]),
                "incident_id": str(row["incident_id"]),
                "event_type": str(row["event_type"]),
                "message": str(row["message"]),
                "recorded_at": str(row["recorded_at"]),
                "payload": _load_json(str(row["payload_json"])),
            }
            for row in rows
        ]


class PostIncidentReviewRepository:
    """Persist post-incident review headers."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, review: PostIncidentReview) -> None:
        payload = review.to_dict()
        self._store.execute(
            """
            INSERT INTO postincident_reviews (
                id,
                incident_id,
                response_run_id,
                status,
                owner_ref,
                opened_at,
                completed_at,
                summary,
                root_cause,
                closure_quality,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                incident_id = excluded.incident_id,
                response_run_id = excluded.response_run_id,
                status = excluded.status,
                owner_ref = excluded.owner_ref,
                opened_at = excluded.opened_at,
                completed_at = excluded.completed_at,
                summary = excluded.summary,
                root_cause = excluded.root_cause,
                closure_quality = excluded.closure_quality,
                payload_json = excluded.payload_json
            """,
            (
                review.id,
                review.incident_id,
                review.response_run_id,
                review.status.value,
                review.owner_ref,
                (review.opened_at or utc_now()).isoformat(),
                review.completed_at.isoformat() if review.completed_at else None,
                review.summary,
                review.root_cause,
                review.closure_quality.value,
                json.dumps(payload, sort_keys=True),
            ),
        )

    def get(self, review_id: str) -> PostIncidentReview | None:
        row = self._store.fetchone("SELECT * FROM postincident_reviews WHERE id = ?", (review_id,))
        return _postincident_review_from_row(row) if row is not None else None

    def get_for_incident(self, incident_id: str) -> PostIncidentReview | None:
        row = self._store.fetchone(
            """
            SELECT *
            FROM postincident_reviews
            WHERE incident_id = ?
            ORDER BY opened_at DESC
            LIMIT 1
            """,
            (incident_id,),
        )
        return _postincident_review_from_row(row) if row is not None else None

    def list_recent(self, *, limit: int = 50) -> list[PostIncidentReview]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM postincident_reviews
            ORDER BY opened_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [_postincident_review_from_row(row) for row in rows]


class ReviewFindingRepository:
    """Persist structured review findings."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, finding: ReviewFinding) -> None:
        payload = finding.to_dict()
        self._store.execute(
            """
            INSERT INTO review_findings (
                id,
                review_id,
                category,
                severity,
                title,
                detail,
                created_at,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                review_id = excluded.review_id,
                category = excluded.category,
                severity = excluded.severity,
                title = excluded.title,
                detail = excluded.detail,
                created_at = excluded.created_at,
                payload_json = excluded.payload_json
            """,
            (
                finding.id,
                finding.review_id,
                finding.category.value,
                finding.severity.value,
                finding.title,
                finding.detail,
                (finding.created_at or utc_now()).isoformat(),
                json.dumps(payload, sort_keys=True),
            ),
        )

    def list_for_review(self, review_id: str) -> list[ReviewFinding]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM review_findings
            WHERE review_id = ?
            ORDER BY created_at ASC
            """,
            (review_id,),
        )
        return [_review_finding_from_row(row) for row in rows]


class ActionItemRepository:
    """Persist post-incident action items."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, item: ActionItem) -> None:
        payload = item.to_dict()
        self._store.execute(
            """
            INSERT INTO action_items (
                id,
                review_id,
                owner_ref,
                status,
                title,
                detail,
                due_at,
                created_at,
                closed_at,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                review_id = excluded.review_id,
                owner_ref = excluded.owner_ref,
                status = excluded.status,
                title = excluded.title,
                detail = excluded.detail,
                due_at = excluded.due_at,
                created_at = excluded.created_at,
                closed_at = excluded.closed_at,
                payload_json = excluded.payload_json
            """,
            (
                item.id,
                item.review_id,
                item.owner_ref,
                item.status.value,
                item.title,
                item.detail,
                item.due_at.isoformat() if item.due_at else None,
                (item.created_at or utc_now()).isoformat(),
                item.closed_at.isoformat() if item.closed_at else None,
                json.dumps(payload, sort_keys=True),
            ),
        )

    def get(self, item_id: str) -> ActionItem | None:
        row = self._store.fetchone("SELECT * FROM action_items WHERE id = ?", (item_id,))
        return _action_item_from_row(row) if row is not None else None

    def list_for_review(self, review_id: str) -> list[ActionItem]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM action_items
            WHERE review_id = ?
            ORDER BY created_at ASC
            """,
            (review_id,),
        )
        return [_action_item_from_row(row) for row in rows]

    def list_open(self, *, limit: int = 50) -> list[ActionItem]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM action_items
            WHERE status != ?
            ORDER BY due_at IS NULL ASC, due_at ASC, created_at DESC
            LIMIT ?
            """,
            (ActionItemStatus.CLOSED.value, limit),
        )
        return [_action_item_from_row(row) for row in rows]


def _runbook_from_row(row: object) -> RunbookDefinition:
    assert row is not None
    payload = _load_json(str(row["payload_json"]))
    steps_payload = payload.get("steps", [])
    if not isinstance(steps_payload, list):
        steps_payload = []
    return RunbookDefinition(
        id=str(row["runbook_id"]),
        version=str(row["runbook_version"]),
        title=str(row["title"]),
        description=str(row["description"]) if row["description"] is not None else None,
        risk_class=RunbookRiskClass(str(row["risk_class"])),
        source_path=str(row["source_path"]),
        checksum=str(row["checksum"]),
        tags=tuple(str(item) for item in json.loads(str(row["tags_json"]))),
        scope=_load_json(str(row["scope_json"])),
        steps=tuple(_runbook_step_from_payload(item) for item in steps_payload if isinstance(item, dict)),
        loaded_at=_decode_datetime(row["loaded_at"]),
    )


def _runbook_step_from_payload(payload: dict[str, object]) -> RunbookStepDefinition:
    artifacts_raw = payload.get("artifacts", [])
    compensation_raw = payload.get("compensation")
    return RunbookStepDefinition(
        key=str(payload["key"]),
        title=str(payload["title"]),
        executor_kind=RunbookExecutorKind(str(payload["executor_kind"])),
        operation_kind=str(payload["operation_kind"]),
        description=str(payload["description"]) if payload.get("description") is not None else None,
        requires_confirmation=bool(payload.get("requires_confirmation", False)),
        requires_elevated_mode=bool(payload.get("requires_elevated_mode", False)),
        approval_required=bool(payload.get("approval_required", False)),
        required_approver_count=int(payload.get("required_approver_count", 0) or 0),
        required_roles=tuple(str(item) for item in payload.get("required_roles", []) if isinstance(item, str)),
        allow_self_approval=bool(payload.get("allow_self_approval", False)),
        approval_expires_after_seconds=(
            int(payload["approval_expires_after_seconds"])
            if payload.get("approval_expires_after_seconds") is not None
            else None
        ),
        max_retries=int(payload.get("max_retries", 0) or 0),
        continue_on_failure=bool(payload.get("continue_on_failure", False)),
        step_config=dict(payload.get("step_config", {}))
        if isinstance(payload.get("step_config", {}), dict)
        else {},
        artifacts=tuple(
            RunbookArtifactDefinition(
                kind=str(item.get("kind", "artifact")),
                label=str(item.get("label", "Artifact")),
                required=bool(item.get("required", False)),
            )
            for item in artifacts_raw
            if isinstance(item, dict)
        ),
        compensation=(
            RunbookCompensationDefinition(
                title=str(compensation_raw.get("title", "Compensation")),
                executor_kind=RunbookExecutorKind(str(compensation_raw["executor_kind"])),
                operation_kind=str(compensation_raw["operation_kind"]),
                step_config=dict(compensation_raw.get("step_config", {}))
                if isinstance(compensation_raw.get("step_config", {}), dict)
                else {},
                requires_confirmation=bool(compensation_raw.get("requires_confirmation", False)),
                requires_elevated_mode=bool(compensation_raw.get("requires_elevated_mode", False)),
                approval_required=bool(compensation_raw.get("approval_required", False)),
                required_approver_count=int(compensation_raw.get("required_approver_count", 0) or 0),
                required_roles=tuple(
                    str(item)
                    for item in compensation_raw.get("required_roles", [])
                    if isinstance(item, str)
                ),
            )
            if isinstance(compensation_raw, dict)
            else None
        ),
    )


def _response_run_from_row(row: object) -> ResponseRun:
    assert row is not None
    return ResponseRun(
        id=str(row["id"]),
        incident_id=str(row["incident_id"]),
        runbook_id=str(row["runbook_id"]),
        runbook_version=str(row["runbook_version"]),
        status=ResponseRunStatus(str(row["status"])),
        engagement_id=str(row["engagement_id"]) if row["engagement_id"] is not None else None,
        current_step_index=int(row["current_step_index"] or 0),
        risk_level=TargetRiskLevel(str(row["risk_level"])),
        elevated_mode=bool(row["elevated_mode"]),
        started_by=str(row["started_by"]) if row["started_by"] is not None else None,
        started_at=_decode_datetime(row["started_at"]),
        updated_at=_decode_datetime(row["updated_at"]),
        completed_at=_decode_datetime(row["completed_at"]),
        summary=str(row["summary"]) if row["summary"] is not None else None,
        last_error=str(row["last_error"]) if row["last_error"] is not None else None,
        payload=_load_json(str(row["payload_json"])),
    )


def _response_step_run_from_row(row: object) -> ResponseStepRun:
    assert row is not None
    payload = _load_json(str(row["output_payload_json"]))
    output_payload = payload.get("payload", {})
    if not isinstance(output_payload, dict):
        output_payload = {}
    return ResponseStepRun(
        id=str(row["id"]),
        response_run_id=str(row["response_run_id"]),
        step_key=str(row["step_key"]),
        step_index=int(row["step_index"] or 0),
        executor_kind=RunbookExecutorKind(str(row["executor_kind"])),
        status=ResponseStepStatus(str(row["status"])),
        attempt_count=int(row["attempt_count"] or 0),
        guard_decision_id=int(row["guard_decision_id"]) if row["guard_decision_id"] is not None else None,
        approval_request_id=(
            str(row["approval_request_id"]) if row["approval_request_id"] is not None else None
        ),
        started_at=_decode_datetime(row["started_at"]),
        finished_at=_decode_datetime(row["finished_at"]),
        output_summary=str(row["output_summary"]) if row["output_summary"] is not None else None,
        output_payload=output_payload,
        last_error=str(row["last_error"]) if row["last_error"] is not None else None,
    )


def _approval_request_from_row(row: object) -> ApprovalRequest:
    assert row is not None
    return ApprovalRequest(
        id=str(row["id"]),
        response_run_id=str(row["response_run_id"]),
        step_run_id=str(row["step_run_id"]),
        status=ApprovalRequestStatus(str(row["status"])),
        requested_by=str(row["requested_by"]) if row["requested_by"] is not None else None,
        required_approver_count=int(row["required_approver_count"] or 0),
        required_roles=tuple(
            str(item) for item in json.loads(str(row["required_roles_json"]))
        ),
        allow_self_approval=bool(row["allow_self_approval"]),
        reason=str(row["reason"]) if row["reason"] is not None else None,
        expires_at=_decode_datetime(row["expires_at"]),
        created_at=_decode_datetime(row["created_at"]),
        resolved_at=_decode_datetime(row["resolved_at"]),
        payload=_load_json(str(row["payload_json"])),
    )


def _approval_decision_from_row(row: object) -> ApprovalDecision:
    assert row is not None
    return ApprovalDecision(
        id=str(row["id"]),
        approval_request_id=str(row["approval_request_id"]),
        approver_ref=str(row["approver_ref"]),
        decision=ApprovalDecisionKind(str(row["decision"])),
        comment=str(row["comment"]) if row["comment"] is not None else None,
        created_at=_decode_datetime(row["created_at"]),
        payload=_load_json(str(row["payload_json"])),
    )


def _response_artifact_from_row(row: object) -> ResponseArtifact:
    assert row is not None
    return ResponseArtifact(
        id=str(row["id"]),
        response_run_id=str(row["response_run_id"]),
        step_run_id=str(row["step_run_id"]) if row["step_run_id"] is not None else None,
        artifact_kind=str(row["artifact_kind"]),
        label=str(row["label"]),
        storage_ref=str(row["storage_ref"]) if row["storage_ref"] is not None else None,
        summary=str(row["summary"]) if row["summary"] is not None else None,
        payload=_load_json(str(row["payload_json"])),
        created_at=_decode_datetime(row["created_at"]),
    )


def _compensation_run_from_row(row: object) -> CompensationRun:
    assert row is not None
    return CompensationRun(
        id=str(row["id"]),
        response_run_id=str(row["response_run_id"]),
        step_run_id=str(row["step_run_id"]),
        status=CompensationStatus(str(row["status"])),
        started_at=_decode_datetime(row["started_at"]),
        finished_at=_decode_datetime(row["finished_at"]),
        summary=str(row["summary"]) if row["summary"] is not None else None,
        last_error=str(row["last_error"]) if row["last_error"] is not None else None,
        payload=_load_json(str(row["payload_json"])),
    )


def _postincident_review_from_row(row: object) -> PostIncidentReview:
    assert row is not None
    return PostIncidentReview(
        id=str(row["id"]),
        incident_id=str(row["incident_id"]),
        response_run_id=str(row["response_run_id"]) if row["response_run_id"] is not None else None,
        status=PostIncidentReviewStatus(str(row["status"])),
        owner_ref=str(row["owner_ref"]) if row["owner_ref"] is not None else None,
        opened_at=_decode_datetime(row["opened_at"]),
        completed_at=_decode_datetime(row["completed_at"]),
        summary=str(row["summary"]) if row["summary"] is not None else None,
        root_cause=str(row["root_cause"]) if row["root_cause"] is not None else None,
        closure_quality=ClosureQuality(str(row["closure_quality"])),
        payload=_load_json(str(row["payload_json"])),
    )


def _review_finding_from_row(row: object) -> ReviewFinding:
    assert row is not None
    return ReviewFinding(
        id=str(row["id"]),
        review_id=str(row["review_id"]),
        category=ReviewFindingCategory(str(row["category"])),
        severity=IncidentSeverity(str(row["severity"])),
        title=str(row["title"]),
        detail=str(row["detail"]),
        created_at=_decode_datetime(row["created_at"]),
        payload=_load_json(str(row["payload_json"])),
    )


def _action_item_from_row(row: object) -> ActionItem:
    assert row is not None
    return ActionItem(
        id=str(row["id"]),
        review_id=str(row["review_id"]),
        owner_ref=str(row["owner_ref"]) if row["owner_ref"] is not None else None,
        status=ActionItemStatus(str(row["status"])),
        title=str(row["title"]),
        detail=str(row["detail"]),
        due_at=_decode_datetime(row["due_at"]),
        created_at=_decode_datetime(row["created_at"]),
        closed_at=_decode_datetime(row["closed_at"]),
        payload=_load_json(str(row["payload_json"])),
    )
