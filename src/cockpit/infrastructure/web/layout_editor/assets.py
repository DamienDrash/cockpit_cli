"""Static asset helpers for the layout editor frontend."""

from __future__ import annotations

from pathlib import Path


def static_root() -> Path:
    return Path(__file__).resolve().parent / "static"


def index_path() -> Path:
    return static_root() / "index.html"


def resolve_asset(request_path: str) -> Path | None:
    normalized = request_path.lstrip("/")
    if normalized.startswith("layouts/editor/"):
        relative = normalized.removeprefix("layouts/editor/")
    elif normalized == "layouts/editor":
        relative = "index.html"
    else:
        return None
    candidate = (static_root() / relative).resolve()
    root = static_root().resolve()
    if root not in candidate.parents and candidate != root:
        return None
    if candidate.exists() and candidate.is_file():
        return candidate
    return None
