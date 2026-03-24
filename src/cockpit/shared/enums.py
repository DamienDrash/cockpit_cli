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
    PLUGIN_HOST = "plugin_host"
    WEB_ADMIN = "web_admin"
    DATASOURCE_WATCH = "datasource_watch"
    DOCKER_CONTAINER_WATCH = "docker_container_watch"
    RESPONSE_RUN = "response_run"


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
    SHELL_READ = "shell_read"
    SHELL_MUTATION = "shell_mutation"
    SHELL_DESTRUCTIVE = "shell_destructive"


class GuardDecisionOutcome(StrEnum):
    ALLOW = "allow"
    REQUIRE_CONFIRMATION = "require_confirmation"
    REQUIRE_ELEVATED_MODE = "require_elevated_mode"
    BLOCK = "block"


class OperationFamily(StrEnum):
    DOCKER = "docker"
    DB = "db"
    CURL = "curl"
    NOTIFICATION = "notification"
    ENGAGEMENT = "engagement"
    RESPONSE = "response"
    REVIEW = "review"


class NotificationChannelKind(StrEnum):
    INTERNAL = "internal"
    WEBHOOK = "webhook"
    SLACK = "slack"
    NTFY = "ntfy"


class NotificationEventClass(StrEnum):
    INCIDENT_OPENED = "incident_opened"
    INCIDENT_STATUS_CHANGED = "incident_status_changed"
    COMPONENT_QUARANTINED = "component_quarantined"
    COMPONENT_RECOVERED = "component_recovered"
    COMPONENT_DEGRADED = "component_degraded"
    DELIVERY_FAILURE = "delivery_failure"
    ENGAGEMENT_PAGED = "engagement_paged"
    ENGAGEMENT_REMINDER = "engagement_reminder"
    ENGAGEMENT_ESCALATED = "engagement_escalated"
    ENGAGEMENT_HANDOFF = "engagement_handoff"
    ENGAGEMENT_EXHAUSTED = "engagement_exhausted"
    APPROVAL_REQUESTED = "approval_requested"
    RESPONSE_BLOCKED = "response_blocked"
    RESPONSE_COMPLETED = "response_completed"


class NotificationStatus(StrEnum):
    QUEUED = "queued"
    SUPPRESSED = "suppressed"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    FAILED = "failed"


class NotificationDeliveryStatus(StrEnum):
    SCHEDULED = "scheduled"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUPPRESSED = "suppressed"


class WatchProbeOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"


class WatchSubjectKind(StrEnum):
    DATASOURCE = "datasource"
    DOCKER_CONTAINER = "docker_container"


class TeamMembershipRole(StrEnum):
    MEMBER = "member"
    LEAD = "lead"


class OwnershipSubjectKind(StrEnum):
    COMPONENT = "component"
    DATASOURCE = "datasource"
    DOCKER_CONTAINER = "docker_container"
    HTTP_TARGET = "http_target"
    WATCH = "watch"


class ScheduleCoverageKind(StrEnum):
    ALWAYS = "always"
    WEEKLY_WINDOW = "weekly_window"


class RotationIntervalKind(StrEnum):
    HOURS = "hours"
    DAYS = "days"
    WEEKS = "weeks"


class ResolutionOutcome(StrEnum):
    RESOLVED = "resolved"
    UNASSIGNED = "unassigned"
    BLOCKED = "blocked"


class EscalationTargetKind(StrEnum):
    PERSON = "person"
    TEAM = "team"
    CHANNEL = "channel"


class EngagementStatus(StrEnum):
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    BLOCKED = "blocked"
    EXHAUSTED = "exhausted"
    RESOLVED = "resolved"
    CLOSED = "closed"


class EngagementDeliveryPurpose(StrEnum):
    PAGE = "page"
    REMINDER = "reminder"
    REPAGE = "repage"
    HANDOFF = "handoff"


class RunbookExecutorKind(StrEnum):
    MANUAL = "manual"
    SHELL = "shell"
    HTTP = "http"
    DOCKER = "docker"
    DB = "db"


class RunbookRiskClass(StrEnum):
    LOW = "low"
    GUARDED = "guarded"
    HIGH = "high"


class ResponseRunStatus(StrEnum):
    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_OPERATOR = "waiting_operator"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPENSATING = "compensating"
    COMPLETED = "completed"
    ABORTED = "aborted"


class ResponseStepStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_OPERATOR = "waiting_operator"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    ABORTED = "aborted"
    COMPENSATED = "compensated"


class ApprovalRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalDecisionKind(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class CompensationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PostIncidentReviewStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CLOSED = "closed"


class ActionItemStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    CLOSED = "closed"


class ReviewFindingCategory(StrEnum):
    ROOT_CAUSE = "root_cause"
    CONTRIBUTING_FACTOR = "contributing_factor"
    OBSERVATION = "observation"
    LESSON = "lesson"


class ClosureQuality(StrEnum):
    INCOMPLETE = "incomplete"
    PARTIAL = "partial"
    COMPLETE = "complete"
