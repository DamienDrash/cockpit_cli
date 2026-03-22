"""Shared utility helpers."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from uuid import uuid4

from cockpit.shared.config import SCHEMA_VERSION


def utc_now() -> datetime:
    return datetime.now(UTC)


def make_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def serialize_value(value: object) -> object:
    """Convert dataclass-oriented values into JSON-like primitives."""
    if is_dataclass(value):
        return serialize_value(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): serialize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [serialize_value(item) for item in value]
    return value


def serialize_contract(value: object) -> dict[str, object]:
    """Serialize a top-level persisted contract with a schema marker."""
    payload = serialize_value(value)
    if not isinstance(payload, dict):
        msg = "Contract serialization must produce a dictionary payload."
        raise TypeError(msg)
    payload["schema_version"] = SCHEMA_VERSION
    return payload
