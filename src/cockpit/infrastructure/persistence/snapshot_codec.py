"""Snapshot encoding and recovery helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json

from cockpit.shared.config import SCHEMA_VERSION
from cockpit.shared.enums import SnapshotKind
from cockpit.shared.utils import serialize_value, utc_now


@dataclass(slots=True)
class SnapshotEnvelope:
    snapshot_kind: SnapshotKind
    payload: dict[str, object]
    schema_version: int = SCHEMA_VERSION
    created_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "snapshot_kind": self.snapshot_kind.value,
            "created_at": self.created_at.isoformat(),
            "payload": serialize_value(self.payload),
        }


@dataclass(slots=True)
class SnapshotDecodeResult:
    success: bool
    envelope: SnapshotEnvelope | None = None
    error: str | None = None


def encode_snapshot(snapshot_kind: SnapshotKind, payload: dict[str, object]) -> str:
    envelope = SnapshotEnvelope(snapshot_kind=snapshot_kind, payload=payload)
    return json.dumps(envelope.to_dict(), sort_keys=True)


def decode_snapshot(raw_payload: str) -> SnapshotDecodeResult:
    try:
        decoded = json.loads(raw_payload)
    except json.JSONDecodeError:
        return SnapshotDecodeResult(
            success=False,
            error="Snapshot payload is not valid JSON.",
        )

    if not isinstance(decoded, dict):
        return SnapshotDecodeResult(
            success=False,
            error="Snapshot payload must decode to a mapping.",
        )

    schema_version = decoded.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        return SnapshotDecodeResult(
            success=False,
            error=(
                "Snapshot schema version is incompatible: "
                f"expected {SCHEMA_VERSION}, got {schema_version}."
            ),
        )

    kind_value = decoded.get("snapshot_kind")
    try:
        snapshot_kind = SnapshotKind(str(kind_value))
    except ValueError:
        return SnapshotDecodeResult(
            success=False,
            error=f"Unknown snapshot kind '{kind_value}'.",
        )

    payload = decoded.get("payload")
    if not isinstance(payload, dict):
        return SnapshotDecodeResult(
            success=False,
            error="Snapshot payload body must be a mapping.",
        )

    created_at_value = decoded.get("created_at")
    try:
        created_at = (
            datetime.fromisoformat(str(created_at_value))
            if created_at_value is not None
            else utc_now()
        )
    except ValueError:
        created_at = utc_now()

    return SnapshotDecodeResult(
        success=True,
        envelope=SnapshotEnvelope(
            snapshot_kind=snapshot_kind,
            payload=payload,
            schema_version=int(schema_version),
            created_at=created_at,
        ),
    )
