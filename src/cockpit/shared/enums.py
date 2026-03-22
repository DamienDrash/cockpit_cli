"""Shared enumerations."""

from __future__ import annotations

from enum import StrEnum


class CommandSource(StrEnum):
    SLASH = "slash"
    PALETTE = "palette"
    KEYBINDING = "keybinding"
    PANEL_ACTION = "panel_action"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class SessionTargetKind(StrEnum):
    LOCAL = "local"
    SSH = "ssh"


class SnapshotKind(StrEnum):
    LIGHT = "light"
    STRUCTURAL = "structural"
    RESUME = "resume"


class PanelPersistPolicy(StrEnum):
    FULL = "full"
    RUNTIME_RECREATED = "runtime_recreated"


class EventCategory(StrEnum):
    DOMAIN = "domain"
    RUNTIME = "runtime"


class StatusLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class TargetRiskLevel(StrEnum):
    DEV = "dev"
    STAGE = "stage"
    PROD = "prod"
