"""SQLite repositories for post-incident reviews."""

from __future__ import annotations

from datetime import datetime
import json

from cockpit.ops.models.review import ActionItem, PostIncidentReview, ReviewFinding
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.core.enums import (
    ActionItemStatus,
    ClosureQuality,
    IncidentSeverity,
    PostIncidentReviewStatus,
    ReviewFindingCategory,
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


class PostIncidentReviewRepository:
    """Persist post-incident reviews."""

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
                status = excluded.status,
                owner_ref = excluded.owner_ref,
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
        row = self._store.fetchone(
            "SELECT * FROM postincident_reviews WHERE id = ?", (review_id,)
        )
        return _postincident_review_from_row(row) if row is not None else None

    def find_for_incident(self, incident_id: str) -> PostIncidentReview | None:
        row = self._store.fetchone(
            "SELECT * FROM postincident_reviews WHERE incident_id = ?", (incident_id,)
        )
        return _postincident_review_from_row(row) if row is not None else None

    def list_recent(self, limit: int = 25) -> list[PostIncidentReview]:
        rows = self._store.fetchall(
            "SELECT * FROM postincident_reviews ORDER BY opened_at DESC LIMIT ?",
            (limit,),
        )
        return [_postincident_review_from_row(row) for row in rows]


class ReviewFindingRepository:
    """Persist structured findings from reviews."""

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
                category = excluded.category,
                severity = excluded.severity,
                title = excluded.title,
                detail = excluded.detail,
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
            "SELECT * FROM review_findings WHERE review_id = ? ORDER BY id ASC",
            (review_id,),
        )
        return [_review_finding_from_row(row) for row in rows]


class ActionItemRepository:
    """Persist follow-up action items."""

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
                owner_ref = excluded.owner_ref,
                status = excluded.status,
                title = excluded.title,
                detail = excluded.detail,
                due_at = excluded.due_at,
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
        row = self._store.fetchone(
            "SELECT * FROM action_items WHERE id = ?", (item_id,)
        )
        return _action_item_from_row(row) if row is not None else None

    def list_for_review(self, review_id: str) -> list[ActionItem]:
        rows = self._store.fetchall(
            "SELECT * FROM action_items WHERE review_id = ? ORDER BY id ASC",
            (review_id,),
        )
        return [_action_item_from_row(row) for row in rows]

    def list_pending(self, owner_ref: str | None = None) -> list[ActionItem]:
        sql = "SELECT * FROM action_items WHERE status != ?"
        params: list[object] = [ActionItemStatus.CLOSED.value]
        if owner_ref is not None:
            sql += " AND owner_ref = ?"
            params.append(owner_ref)
        sql += " ORDER BY due_at ASC"
        rows = self._store.fetchall(sql, tuple(params))
        return [_action_item_from_row(row) for row in rows]


def _postincident_review_from_row(row: object) -> PostIncidentReview:
    assert row is not None
    return PostIncidentReview(
        id=str(row["id"]),
        incident_id=str(row["incident_id"]),
        response_run_id=str(row["response_run_id"])
        if row["response_run_id"] is not None
        else None,
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
