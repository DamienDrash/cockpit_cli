"""Shared contracts for Stage 4 runbook executors."""

from __future__ import annotations

from dataclasses import dataclass, field

from cockpit.domain.models.health import IncidentRecord
from cockpit.domain.models.response import ResponseRun, ResponseStepRun, RunbookStepDefinition


@dataclass(slots=True, frozen=True)
class ExecutorArtifact:
    """Structured artifact emitted by a response executor."""

    kind: str
    label: str
    summary: str | None = None
    storage_ref: str | None = None
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ExecutorContext:
    """Context passed to concrete executors."""

    response_run: ResponseRun
    step_run: ResponseStepRun
    step_definition: RunbookStepDefinition
    incident: IncidentRecord
    resolved_config: dict[str, object]
    actor: str


@dataclass(slots=True, frozen=True)
class ExecutorResult:
    """Normalized execution result returned by concrete executors."""

    success: bool
    summary: str
    payload: dict[str, object] = field(default_factory=dict)
    artifacts: tuple[ExecutorArtifact, ...] = ()
    error_message: str | None = None

