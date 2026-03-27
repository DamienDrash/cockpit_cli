"""Policy models for guard rails and action evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field

from cockpit.core.enums import (
    ComponentKind,
    GuardActionKind,
    GuardDecisionOutcome,
    TargetRiskLevel,
)
from cockpit.core.utils import serialize_contract


@dataclass(slots=True)
class GuardContext:
    """Input contract for central guard policy evaluation."""

    command_id: str
    action_kind: GuardActionKind
    component_kind: ComponentKind
    target_risk: TargetRiskLevel
    workspace_id: str | None = None
    session_id: str | None = None
    workspace_name: str | None = None
    target_ref: str | None = None
    confirmed: bool = False
    elevated_mode: bool = False
    dry_run_requested: bool = False
    subject_ref: str | None = None
    description: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class GuardDecision:
    """Structured policy decision returned by the guard engine."""

    command_id: str
    action_kind: GuardActionKind
    component_kind: ComponentKind
    target_risk: TargetRiskLevel
    outcome: GuardDecisionOutcome
    explanation: str
    requires_confirmation: bool = False
    requires_elevated_mode: bool = False
    requires_dry_run: bool = False
    audit_required: bool = True
    confirmation_message: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)
