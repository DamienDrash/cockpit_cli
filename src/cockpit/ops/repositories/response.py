"""SQLite repositories for runbooks and incident response runs."""

from __future__ import annotations

from datetime import datetime
import json

from cockpit.ops.models.response import (
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
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.core.enums import (
    ApprovalDecisionKind,
    ApprovalRequestStatus,
    CompensationStatus,
    ResponseRunStatus,
    ResponseStepStatus,
    RunbookExecutorKind,
    RunbookRiskClass,
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


class RunbookCatalogRepository:
    """Persist and query runbook definitions."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

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
                runbook_id = excluded.runbook_id,
                runbook_version = excluded.runbook_version,
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
                runbook.source_path,
                runbook.checksum,
                json.dumps(list(runbook.tags), sort_keys=True),
                json.dumps(runbook.scope, sort_keys=True),
                json.dumps(payload, sort_keys=True),
                (runbook.loaded_at or utc_now()).isoformat(),
            ),
        )

    def get(self, runbook_id: str) -> RunbookDefinition | None:
        row = self._store.fetchone(
            "SELECT * FROM runbook_catalog WHERE runbook_id = ? ORDER BY runbook_version DESC LIMIT 1",
            (runbook_id,),
        )
        return _runbook_from_row(row) if row is not None else None

    def replace_catalog(self, definitions: list[RunbookDefinition]) -> None:
        """Clear and replace the entire runbook catalog."""
        self._store.execute("DELETE FROM runbook_catalog", ())
        for definition in definitions:
            self.save(definition)

    def list_all(self) -> list[RunbookDefinition]:
        rows = self._store.fetchall("SELECT * FROM runbook_catalog ORDER BY title ASC")
        return [_runbook_from_row(row) for row in rows]


class ResponseRunRepository:
    """Persist runbook execution runs."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, run: ResponseRun) -> None:
        payload = run.to_dict()
        self._store.execute(
            """
            INSERT INTO response_runs (
                id,
                incident_id,
                runbook_id,
                runbook_version,
                status,
                engagement_id,
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
                runbook_id = excluded.runbook_id,
                runbook_version = excluded.runbook_version,
                status = excluded.status,
                engagement_id = excluded.engagement_id,
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
                run.runbook_id,
                run.runbook_version,
                run.status.value,
                run.engagement_id,
                int(run.current_step_index),
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
        row = self._store.fetchone(
            "SELECT * FROM response_runs WHERE id = ?", (run_id,)
        )
        return _response_run_from_row(row) if row is not None else None

    def list_recent(self, limit: int = 50) -> list[ResponseRun]:
        rows = self._store.fetchall(
            "SELECT * FROM response_runs ORDER BY updated_at DESC LIMIT ?", (limit,)
        )
        return [_response_run_from_row(row) for row in rows]

    def list_active(self, *, limit: int = 50) -> list[ResponseRun]:
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

    def find_active_for_incident(self, incident_id: str) -> ResponseRun | None:
        row = self._store.fetchone(
            """
            SELECT *
            FROM response_runs
            WHERE incident_id = ?
              AND status NOT IN (?, ?)
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (incident_id, ResponseRunStatus.COMPLETED.value, ResponseRunStatus.FAILED.value),
        )
        return _response_run_from_row(row) if row is not None else None


class ResponseStepRunRepository:
    """Persist individual step execution state."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, step_run: ResponseStepRun) -> None:
        payload = {"payload": step_run.output_payload}
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
                int(step_run.step_index),
                step_run.executor_kind.value,
                step_run.status.value,
                int(step_run.attempt_count),
                step_run.guard_decision_id,
                step_run.approval_request_id,
                step_run.started_at.isoformat() if step_run.started_at else None,
                step_run.finished_at.isoformat() if step_run.finished_at else None,
                step_run.output_summary,
                json.dumps(payload, sort_keys=True),
                step_run.last_error,
            ),
        )

    def list_for_run(self, run_id: str) -> list[ResponseStepRun]:
        rows = self._store.fetchall(
            "SELECT * FROM response_step_runs WHERE response_run_id = ? ORDER BY step_index ASC",
            (run_id,),
        )
        return [_response_step_run_from_row(row) for row in rows]

    def get(self, step_run_id: str) -> ResponseStepRun | None:
        row = self._store.fetchone(
            "SELECT * FROM response_step_runs WHERE id = ?", (step_run_id,)
        )
        return _response_step_run_from_row(row) if row is not None else None

    def get_by_run_and_index(self, run_id: str, step_index: int) -> ResponseStepRun | None:
        row = self._store.fetchone(
            """
            SELECT *
            FROM response_step_runs
            WHERE response_run_id = ?
              AND step_index = ?
            """,
            (run_id, int(step_index)),
        )
        return _response_step_run_from_row(row) if row is not None else None


class ApprovalRequestRepository:
    """Persist approval requests for gated steps."""

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
                status = excluded.status,
                resolved_at = excluded.resolved_at,
                payload_json = excluded.payload_json
            """,
            (
                request.id,
                request.response_run_id,
                request.step_run_id,
                request.status.value,
                request.requested_by,
                int(request.required_approver_count),
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
        row = self._store.fetchone(
            "SELECT * FROM approval_requests WHERE id = ?", (request_id,)
        )
        return _approval_request_from_row(row) if row is not None else None

    def get_active_for_step(self, step_run_id: str) -> ApprovalRequest | None:
        row = self._store.fetchone(
            """
            SELECT *
            FROM approval_requests
            WHERE step_run_id = ?
              AND status = ?
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

    def find_pending(self, response_run_id: str) -> list[ApprovalRequest]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM approval_requests
            WHERE response_run_id = ?
              AND status = ?
            """,
            (response_run_id, ApprovalRequestStatus.PENDING.value),
        )
        return [_approval_request_from_row(row) for row in rows]

    def list_pending(self, *, limit: int = 50) -> list[ApprovalRequest]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM approval_requests
            WHERE status = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (ApprovalRequestStatus.PENDING.value, limit),
        )
        return [_approval_request_from_row(row) for row in rows]

    def list_expired(self, now: datetime) -> list[ApprovalRequest]:
        rows = self._store.fetchall(
            """
            SELECT *
            FROM approval_requests
            WHERE status = ?
              AND expires_at IS NOT NULL
              AND expires_at < ?
            """,
            (ApprovalRequestStatus.PENDING.value, now.isoformat()),
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

    def list_for_request(self, request_id: str) -> list[ApprovalDecision]:
        rows = self._store.fetchall(
            "SELECT * FROM approval_decisions WHERE approval_request_id = ? ORDER BY created_at ASC",
            (request_id,),
        )
        return [_approval_decision_from_row(row) for row in rows]


class ResponseArtifactRepository:
    """Persist references to runbook artifacts (logs, snapshots, outputs)."""

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

    def list_for_run(self, run_id: str) -> list[ResponseArtifact]:
        rows = self._store.fetchall(
            "SELECT * FROM response_artifacts WHERE response_run_id = ? ORDER BY created_at ASC",
            (run_id,),
        )
        return [_response_artifact_from_row(row) for row in rows]


class CompensationRunRepository:
    """Persist compensation step runs."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, compensation: CompensationRun) -> None:
        payload = compensation.to_dict()
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
                status = excluded.status,
                finished_at = excluded.finished_at,
                summary = excluded.summary,
                last_error = excluded.last_error,
                payload_json = excluded.payload_json
            """,
            (
                compensation.id,
                compensation.response_run_id,
                compensation.step_run_id,
                compensation.status.value,
                compensation.started_at.isoformat() if compensation.started_at else None,
                compensation.finished_at.isoformat() if compensation.finished_at else None,
                compensation.summary,
                compensation.last_error,
                json.dumps(payload, sort_keys=True),
            ),
        )

    def find_for_step(self, step_run_id: str) -> CompensationRun | None:
        row = self._store.fetchone(
            "SELECT * FROM compensation_runs WHERE step_run_id = ?", (step_run_id,)
        )
        return _compensation_run_from_row(row) if row is not None else None

    def latest_for_step(self, step_run_id: str) -> CompensationRun | None:
        row = self._store.fetchone(
            "SELECT * FROM compensation_runs WHERE step_run_id = ? ORDER BY started_at DESC LIMIT 1",
            (step_run_id,),
        )
        return _compensation_run_from_row(row) if row is not None else None


class ResponseTimelineRepository:
    """Persist response-wide timeline events."""

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
                "response_run_id": row["response_run_id"],
                "incident_id": row["incident_id"],
                "event_type": row["event_type"],
                "message": row["message"],
                "recorded_at": row["recorded_at"],
                "payload": _load_json(row["payload_json"]),
            }
            for row in rows
        ]


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
        steps=tuple(
            _runbook_step_from_payload(item)
            for item in steps_payload
            if isinstance(item, dict)
        ),
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
        description=str(payload["description"])
        if payload.get("description") is not None
        else None,
        requires_confirmation=bool(payload.get("requires_confirmation", False)),
        requires_elevated_mode=bool(payload.get("requires_elevated_mode", False)),
        approval_required=bool(payload.get("approval_required", False)),
        required_approver_count=int(payload.get("required_approver_count", 0) or 0),
        required_roles=tuple(
            str(item)
            for item in payload.get("required_roles", [])
            if isinstance(item, str)
        ),
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
                executor_kind=RunbookExecutorKind(
                    str(compensation_raw["executor_kind"])
                ),
                operation_kind=str(compensation_raw["operation_kind"]),
                step_config=dict(compensation_raw.get("step_config", {}))
                if isinstance(compensation_raw.get("step_config", {}), dict)
                else {},
                requires_confirmation=bool(
                    compensation_raw.get("requires_confirmation", False)
                ),
                requires_elevated_mode=bool(
                    compensation_raw.get("requires_elevated_mode", False)
                ),
                approval_required=bool(
                    compensation_raw.get("approval_required", False)
                ),
                required_approver_count=int(
                    compensation_raw.get("required_approver_count", 0) or 0
                ),
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
        engagement_id=str(row["engagement_id"])
        if row["engagement_id"] is not None
        else None,
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
        guard_decision_id=int(row["guard_decision_id"])
        if row["guard_decision_id"] is not None
        else None,
        approval_request_id=(
            str(row["approval_request_id"])
            if row["approval_request_id"] is not None
            else None
        ),
        started_at=_decode_datetime(row["started_at"]),
        finished_at=_decode_datetime(row["finished_at"]),
        output_summary=str(row["output_summary"])
        if row["output_summary"] is not None
        else None,
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
        requested_by=str(row["requested_by"])
        if row["requested_by"] is not None
        else None,
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
