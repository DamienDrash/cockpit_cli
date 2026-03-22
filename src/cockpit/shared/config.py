"""Configuration discovery and project path helpers."""

from __future__ import annotations

from pathlib import Path

APP_NAME = "cockpit"
SCHEMA_VERSION = 1


def discover_project_root(start: Path | None = None) -> Path:
    """Find the nearest project root by locating a matching pyproject."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "src").exists():
            return candidate
    return current


def config_dir(start: Path | None = None) -> Path:
    return discover_project_root(start) / "config"


def layouts_dir(start: Path | None = None) -> Path:
    return config_dir(start) / "layouts"


def themes_dir(start: Path | None = None) -> Path:
    return config_dir(start) / "themes"


def state_dir(start: Path | None = None) -> Path:
    return discover_project_root(start) / ".cockpit"


def default_db_path(start: Path | None = None) -> Path:
    return state_dir(start) / f"{APP_NAME}.db"
