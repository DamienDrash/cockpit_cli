"""Runbook catalog and response runtime models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

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
from cockpit.core.utils import serialize_contract


@dataclass(slots=True)
class RunbookArtifactDefinition:
    """Artifact contract declared by a runbook step.

    Parameters
    ----------
    kind:
        Artifact category such as ``log`` or ``http_response``.
    label:
        Operator-facing artifact name.
    required:
        Whether the step is expected to produce this artifact.
    """

    kind: str
    label: str
    required: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class RunbookCompensationDefinition:
    """Declarative rollback or compensation contract for a runbook step."""

    title: str
    executor_kind: RunbookExecutorKind
    operation_kind: str
    step_config: dict[str, object] = field(default_factory=dict)
    requires_confirmation: bool = False
    requires_elevated_mode: bool = False
    approval_required: bool = False
    required_approver_count: int = 0
    required_roles: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class RunbookStepDefinition:
    """One ordered step in a declarative runbook."""

    key: str
    title: str
    executor_kind: RunbookExecutorKind
    operation_kind: str
    description: str | None = None
    requires_confirmation: bool = False
    requires_elevated_mode: bool = False
    approval_required: bool = False
    required_approver_count: int = 0
    required_roles: tuple[str, ...] = ()
    allow_self_approval: bool = False
    approval_expires_after_seconds: int | None = None
    max_retries: int = 0
    continue_on_failure: bool = False
    step_config: dict[str, object] = field(default_factory=dict)
    artifacts: tuple[RunbookArtifactDefinition, ...] = ()
    compensation: RunbookCompensationDefinition | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class RunbookDefinition:
    """Versioned response runbook loaded from the repository."""

    id: str
    version: str
    title: str
    description: str | None = None
    risk_class: RunbookRiskClass = RunbookRiskClass.GUARDED
    source_path: str | None = None
    checksum: str | None = None
    scope: dict[str, object] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    steps: tuple[RunbookStepDefinition, ...] = ()
    loaded_at: datetime | None = None

    @property
    def catalog_key(self) -> str:
        """Return the stable catalog key used for persistence."""

        return f"{self.id}:{self.version}"

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class ResponseRun:
    """Primary response runtime record attached to an incident."""

    id: str
    incident_id: str
    runbook_id: str
    runbook_version: str
    status: ResponseRunStatus = ResponseRunStatus.CREATED
    engagement_id: str | None = None
    current_step_index: int = 0
    risk_level: TargetRiskLevel = TargetRiskLevel.DEV
    elevated_mode: bool = False
    started_by: str | None = None
    started_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    summary: str | None = None
    last_error: str | None = None
    payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class ResponseStepRun:
    """Persisted execution record for one response step."""

    id: str
    response_run_id: str
    step_key: str
    step_index: int
    executor_kind: RunbookExecutorKind
    status: ResponseStepStatus = ResponseStepStatus.PENDING
    attempt_count: int = 0
    guard_decision_id: int | None = None
    approval_request_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    output_summary: str | None = None
    output_payload: dict[str, object] = field(default_factory=dict)
    last_error: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class ApprovalRequest:
    """Persisted approval gate for a risky response step."""

    id: str
    response_run_id: str
    step_run_id: str
    status: ApprovalRequestStatus = ApprovalRequestStatus.PENDING
    requested_by: str | None = None
    required_approver_count: int = 1
    required_roles: tuple[str, ...] = ()
    allow_self_approval: bool = False
    reason: str | None = None
    expires_at: datetime | None = None
    created_at: datetime | None = None
    resolved_at: datetime | None = None
    payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class ApprovalDecision:
    """One operator decision for an approval request."""

    id: str
    approval_request_id: str
    approver_ref: str
    decision: ApprovalDecisionKind
    comment: str | None = None
    created_at: datetime | None = None
    payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class ResponseArtifact:
    """Structured artifact emitted by a response step or compensation run."""

    id: str
    response_run_id: str
    step_run_id: str | None = None
    artifact_kind: str = "artifact"
    label: str = "Artifact"
    storage_ref: str | None = None
    summary: str | None = None
    payload: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class CompensationRun:
    """Execution state for a compensation step."""

    id: str
    response_run_id: str
    step_run_id: str
    status: CompensationStatus = CompensationStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    summary: str | None = None
    last_error: str | None = None
    payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)
