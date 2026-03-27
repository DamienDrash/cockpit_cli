"""Stage 5 remediation catalog and runtime models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from cockpit.core.enums import (
    ExecutionWindowKind,
    LeaseScopeKind,
    RemediationFailureMode,
    RemediationLeaseStatus,
    RemediationRunStatus,
    RemediationTargetSelectorKind,
    RemediationTargetStatus,
    RunbookExecutorKind,
    RunbookRiskClass,
    TargetRiskLevel,
)
from cockpit.core.utils import serialize_contract


@dataclass(slots=True)
class ExecutionWindowPolicy:
    """Execution window contract for remediation targets."""

    kind: ExecutionWindowKind = ExecutionWindowKind.ALWAYS
    start_hour_utc: int | None = None
    end_hour_utc: int | None = None

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class EvidenceContractDefinition:
    """Evidence requirements emitted by a remediation unit."""

    required_categories: tuple[str, ...] = ()
    include_diagnostics_snapshot: bool = False
    include_guard_decision: bool = True
    include_output_payload: bool = True

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class RemediationTargetSelector:
    """Target materialization contract for a remediation unit."""

    kind: RemediationTargetSelectorKind
    target_kind: str
    targets: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class RemediationUnitDefinition:
    """One reusable remediation unit within a remediation plan."""

    key: str
    title: str
    executor_kind: RunbookExecutorKind
    operation_kind: str
    target_selector: RemediationTargetSelector
    unit_config: dict[str, object] = field(default_factory=dict)
    description: str | None = None
    lock_scope_kind: LeaseScopeKind = LeaseScopeKind.TARGET
    lock_scope_template: str = "{target.ref}"
    concurrency_class: str = "default"
    max_attempts: int = 1
    failure_mode: RemediationFailureMode = RemediationFailureMode.HALT
    requires_confirmation: bool = False
    requires_elevated_mode: bool = False
    approval_required: bool = False
    evidence_contract: EvidenceContractDefinition = field(
        default_factory=EvidenceContractDefinition
    )

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class RemediationPlanDefinition:
    """Versioned remediation plan loaded from the repository."""

    id: str
    version: str
    title: str
    description: str | None = None
    risk_class: RunbookRiskClass = RunbookRiskClass.GUARDED
    source_path: str | None = None
    checksum: str | None = None
    scope: dict[str, object] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    units: tuple[RemediationUnitDefinition, ...] = ()
    default_concurrency_limit: int = 1
    default_window_policy: ExecutionWindowPolicy = field(
        default_factory=ExecutionWindowPolicy
    )
    export_requires_review: bool = False
    loaded_at: datetime | None = None

    @property
    def catalog_key(self) -> str:
        return f"{self.id}:{self.version}"

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class RemediationRuntimePolicy:
    """Resolved runtime policy for a remediation run."""

    max_concurrency: int = 1
    window_policy: ExecutionWindowPolicy = field(default_factory=ExecutionWindowPolicy)
    export_requires_review: bool = False
    required_evidence_categories: tuple[str, ...] = ()
    partial_failure_mode: RemediationFailureMode = RemediationFailureMode.HALT

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class RemediationRun:
    """Primary remediation execution record."""

    id: str
    incident_id: str
    plan_id: str
    plan_version: str
    status: RemediationRunStatus = RemediationRunStatus.CREATED
    response_run_id: str | None = None
    engagement_id: str | None = None
    risk_level: TargetRiskLevel = TargetRiskLevel.DEV
    started_by: str | None = None
    started_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    summary: str | None = None
    last_error: str | None = None
    policy_payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class RemediationTargetRun:
    """Per-target remediation execution state."""

    id: str
    remediation_run_id: str
    unit_key: str
    target_ref: str
    target_kind: str
    status: RemediationTargetStatus = RemediationTargetStatus.PENDING
    attempt_count: int = 0
    guard_decision_id: int | None = None
    approval_request_id: str | None = None
    lease_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    output_summary: str | None = None
    output_payload: dict[str, object] = field(default_factory=dict)
    last_error: str | None = None
    evidence_complete: bool = False

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class RemediationExecutionLease:
    """Active lease protecting a lock scope."""

    id: str
    scope_ref: str
    scope_kind: LeaseScopeKind
    holder_run_id: str
    holder_target_run_id: str
    status: RemediationLeaseStatus = RemediationLeaseStatus.ACTIVE
    acquired_at: datetime | None = None
    expires_at: datetime | None = None
    released_at: datetime | None = None
    release_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)
