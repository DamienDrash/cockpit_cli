"""Common type aliases."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeAlias

JsonPrimitive: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonPrimitive | "JsonDict" | "JsonList"
JsonDict: TypeAlias = Mapping[str, JsonValue]
JsonList: TypeAlias = Sequence[JsonValue]
