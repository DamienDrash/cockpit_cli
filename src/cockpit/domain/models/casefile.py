"""Stage 5 case-file and evidence models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from cockpit.shared.enums import (
    CaseFileExportStatus,
    CaseFileStatus,
    EvidenceCompletenessStatus,
    EvidenceRedactionState,
)
from cockpit.shared.utils import serialize_contract


@dataclass(slots=True)
class CaseFile:
    """Structured evidence package for one incident lifecycle."""

    id: str
    incident_id: str
    engagement_id: str | None = None
    response_run_id: str | None = None
    remediation_run_id: str | None = None
    review_id: str | None = None
    status: CaseFileStatus = CaseFileStatus.OPEN
    completeness_status: EvidenceCompletenessStatus = EvidenceCompletenessStatus.INCOMPLETE
    manifest_version: int = 1
    summary: str | None = None
    opened_at: datetime | None = None
    updated_at: datetime | None = None
    sealed_at: datetime | None = None
    payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class CaseFileEvidenceItem:
    """Structured evidence item included in a case file."""

    id: str
    case_file_id: str
    category: str
    source_kind: str
    source_ref: str
    label: str
    payload: dict[str, object] = field(default_factory=dict)
    redaction_state: EvidenceRedactionState = EvidenceRedactionState.RAW
    required: bool = False
    included_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class CaseFileExport:
    """Export record for one case-file export attempt."""

    id: str
    case_file_id: str
    status: CaseFileExportStatus = CaseFileExportStatus.PENDING
    requested_by: str | None = None
    requested_at: datetime | None = None
    completed_at: datetime | None = None
    format: str = "json_bundle"
    storage_ref: str | None = None
    manifest_payload: dict[str, object] = field(default_factory=dict)
    error_message: str | None = None

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)
