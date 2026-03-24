"""Watch configuration and probe state models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from cockpit.shared.enums import ComponentKind, SessionTargetKind, WatchProbeOutcome, WatchSubjectKind
from cockpit.shared.utils import serialize_contract


@dataclass(slots=True)
class ComponentWatchConfig:
    """Persisted watch definition for Stage 2 monitored components."""

    id: str
    name: str
    component_id: str
    component_kind: ComponentKind
    subject_kind: WatchSubjectKind
    subject_ref: str
    enabled: bool = True
    probe_interval_seconds: int = 30
    stale_timeout_seconds: int = 90
    target_kind: SessionTargetKind = SessionTargetKind.LOCAL
    target_ref: str | None = None
    recovery_policy_override: dict[str, object] = field(default_factory=dict)
    monitor_config: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class ComponentWatchState:
    """Latest runtime outcome for a watch config."""

    component_id: str
    watch_id: str
    component_kind: ComponentKind
    subject_kind: WatchSubjectKind
    subject_ref: str
    last_probe_at: datetime | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_outcome: WatchProbeOutcome = WatchProbeOutcome.SKIPPED
    last_status: str = "unknown"
    payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)
