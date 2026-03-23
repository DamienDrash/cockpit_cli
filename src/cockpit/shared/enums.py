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


class ComponentKind(StrEnum):
    PTY_SESSION = "pty_session"
    SSH_TUNNEL = "ssh_tunnel"
    BACKGROUND_TASK = "background_task"
    DOCKER_RUNTIME = "docker_runtime"
    DATASOURCE = "datasource"
    HTTP_REQUEST = "http_request"


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RECOVERING = "recovering"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class IncidentSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RECOVERING = "recovering"
    RESOLVED = "resolved"
    QUARANTINED = "quarantined"
    CLOSED = "closed"


class RecoveryAttemptStatus(StrEnum):
    SCHEDULED = "scheduled"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    QUARANTINED = "quarantined"


class GuardActionKind(StrEnum):
    DOCKER_RESTART = "docker_restart"
    DOCKER_STOP = "docker_stop"
    DOCKER_REMOVE = "docker_remove"
    DB_QUERY = "db_query"
    DB_MUTATION = "db_mutation"
    DB_DESTRUCTIVE = "db_destructive"
    HTTP_READ = "http_read"
    HTTP_MUTATION = "http_mutation"
    HTTP_DESTRUCTIVE = "http_destructive"


class GuardDecisionOutcome(StrEnum):
    ALLOW = "allow"
    REQUIRE_CONFIRMATION = "require_confirmation"
    REQUIRE_ELEVATED_MODE = "require_elevated_mode"
    BLOCK = "block"


class OperationFamily(StrEnum):
    DOCKER = "docker"
    DB = "db"
    CURL = "curl"
