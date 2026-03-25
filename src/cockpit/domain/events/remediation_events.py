"""Stage 5 remediation and case-file domain events."""

from __future__ import annotations

from dataclasses import dataclass

from cockpit.domain.events.base import DomainEvent
from cockpit.shared.enums import (
    CaseFileExportStatus,
    CaseFileStatus,
    EvidenceCompletenessStatus,
    RemediationLeaseStatus,
    RemediationRunStatus,
    RemediationTargetStatus,
)


@dataclass(slots=True, kw_only=True)
class RemediationRunCreated(DomainEvent):
    remediation_run_id: str
    incident_id: str
    plan_id: str
    plan_version: str


@dataclass(slots=True, kw_only=True)
class RemediationRunStatusChanged(DomainEvent):
    remediation_run_id: str
    incident_id: str
    previous_status: RemediationRunStatus | None = None
    new_status: RemediationRunStatus
    message: str


@dataclass(slots=True, kw_only=True)
class RemediationTargetStatusChanged(DomainEvent):
    remediation_run_id: str
    target_run_id: str
    incident_id: str
    target_ref: str
    previous_status: RemediationTargetStatus | None = None
    new_status: RemediationTargetStatus
    message: str


@dataclass(slots=True, kw_only=True)
class RemediationLeaseChanged(DomainEvent):
    lease_id: str
    remediation_run_id: str
    target_run_id: str
    incident_id: str
    scope_ref: str
    status: RemediationLeaseStatus
    message: str


@dataclass(slots=True, kw_only=True)
class CaseFileCreated(DomainEvent):
    case_file_id: str
    incident_id: str


@dataclass(slots=True, kw_only=True)
class CaseFileStatusChanged(DomainEvent):
    case_file_id: str
    incident_id: str
    previous_status: CaseFileStatus | None = None
    new_status: CaseFileStatus
    message: str


@dataclass(slots=True, kw_only=True)
class CaseFileCompletenessChanged(DomainEvent):
    case_file_id: str
    incident_id: str
    previous_status: EvidenceCompletenessStatus | None = None
    new_status: EvidenceCompletenessStatus
    message: str


@dataclass(slots=True, kw_only=True)
class CaseFileExportStatusChanged(DomainEvent):
    case_file_id: str
    export_id: str
    incident_id: str
    status: CaseFileExportStatus
    message: str
