"""Central execution service for Stage 4 response steps."""

from __future__ import annotations

from dataclasses import dataclass

from cockpit.application.services.datasource_service import DataSourceService
from cockpit.application.services.guard_policy_service import GuardPolicyService
from cockpit.application.services.operations_diagnostics_service import (
    OperationsDiagnosticsService,
)
from cockpit.domain.models.health import IncidentRecord
from cockpit.domain.models.policy import GuardContext, GuardDecision
from cockpit.domain.models.response import (
    RunbookCompensationDefinition,
    RunbookStepDefinition,
    ResponseRun,
    ResponseStepRun,
)
from cockpit.infrastructure.db.database_adapter import DatabaseAdapter
from cockpit.infrastructure.docker.docker_adapter import DockerAdapter
from cockpit.infrastructure.http.http_adapter import HttpAdapter
from cockpit.infrastructure.runbooks.executors.base import (
    ExecutorArtifact,
    ExecutorContext,
    ExecutorResult,
)
from cockpit.infrastructure.runbooks.executors.db import DatabaseStepExecutor
from cockpit.infrastructure.runbooks.executors.docker import DockerStepExecutor
from cockpit.infrastructure.runbooks.executors.http import HttpStepExecutor
from cockpit.infrastructure.runbooks.executors.manual import ManualStepExecutor
from cockpit.infrastructure.runbooks.executors.shell import ShellStepExecutor
from cockpit.shared.enums import (
    ComponentKind,
    GuardActionKind,
    GuardDecisionOutcome,
    OperationFamily,
    ResponseRunStatus,
    RunbookExecutorKind,
)


@dataclass(slots=True, frozen=True)
class ResponseExecutionOutcome:
    """Normalized runtime result for one response step execution."""

    result: ExecutorResult
    guard_decision: GuardDecision | None = None
    waiting_for_operator: bool = False
    blocked: bool = False


class ResponseExecutorService:
    """Resolve, guard, and execute response and compensation steps."""

    def __init__(
        self,
        *,
        guard_policy_service: GuardPolicyService,
        operations_diagnostics_service: OperationsDiagnosticsService,
        http_adapter: HttpAdapter,
        docker_adapter: DockerAdapter,
        database_adapter: DatabaseAdapter,
        datasource_service: DataSourceService,
    ) -> None:
        self._guard_policy_service = guard_policy_service
        self._operations_diagnostics_service = operations_diagnostics_service
        self._executors = {
            RunbookExecutorKind.MANUAL: ManualStepExecutor(),
            RunbookExecutorKind.SHELL: ShellStepExecutor(),
            RunbookExecutorKind.HTTP: HttpStepExecutor(http_adapter),
            RunbookExecutorKind.DOCKER: DockerStepExecutor(docker_adapter),
            RunbookExecutorKind.DB: DatabaseStepExecutor(
                database_adapter=database_adapter,
                datasource_service=datasource_service,
            ),
        }

    def execute_step(
        self,
        *,
        command_id: str,
        response_run: ResponseRun,
        step_run: ResponseStepRun,
        step_definition: RunbookStepDefinition,
        incident: IncidentRecord,
        actor: str,
        confirmed: bool,
        elevated_mode: bool,
        notes: str | None = None,
    ) -> ResponseExecutionOutcome:
        resolved_config = self._resolve_config(
            step_definition.step_config,
            incident=incident,
            response_run=response_run,
            actor=actor,
            notes=notes,
        )
        guard_decision = self._evaluate_guard(
            command_id=command_id,
            response_run=response_run,
            step_definition=step_definition,
            incident=incident,
            resolved_config=resolved_config,
            confirmed=confirmed,
            elevated_mode=elevated_mode,
        )
        if guard_decision is not None and guard_decision.outcome is not GuardDecisionOutcome.ALLOW:
            return ResponseExecutionOutcome(
                result=ExecutorResult(
                    success=False,
                    summary=guard_decision.explanation,
                    payload={"guard_decision": guard_decision.to_dict()},
                    error_message=guard_decision.explanation,
                ),
                guard_decision=guard_decision,
                waiting_for_operator=guard_decision.outcome in {
                    GuardDecisionOutcome.REQUIRE_CONFIRMATION,
                    GuardDecisionOutcome.REQUIRE_ELEVATED_MODE,
                },
                blocked=guard_decision.outcome is GuardDecisionOutcome.BLOCK,
            )

        executor = self._executors[step_definition.executor_kind]
        result = executor.execute(
            ExecutorContext(
                response_run=response_run,
                step_run=step_run,
                step_definition=step_definition,
                incident=incident,
                resolved_config=resolved_config,
                actor=actor,
            )
        )
        self._record_operation(
            response_run=response_run,
            step_title=step_definition.title,
            success=result.success,
            payload=result.payload,
        )
        return ResponseExecutionOutcome(result=result, guard_decision=guard_decision)

    def execute_compensation(
        self,
        *,
        command_id: str,
        response_run: ResponseRun,
        step_run: ResponseStepRun,
        compensation: RunbookCompensationDefinition,
        incident: IncidentRecord,
        actor: str,
        confirmed: bool,
        elevated_mode: bool,
    ) -> ResponseExecutionOutcome:
        resolved_config = self._resolve_config(
            compensation.step_config,
            incident=incident,
            response_run=response_run,
            actor=actor,
            notes=None,
        )
        guard_decision = self._evaluate_compensation_guard(
            command_id=command_id,
            response_run=response_run,
            compensation=compensation,
            incident=incident,
            resolved_config=resolved_config,
            confirmed=confirmed,
            elevated_mode=elevated_mode,
        )
        if guard_decision is not None and guard_decision.outcome is not GuardDecisionOutcome.ALLOW:
            return ResponseExecutionOutcome(
                result=ExecutorResult(
                    success=False,
                    summary=guard_decision.explanation,
                    payload={"guard_decision": guard_decision.to_dict()},
                    error_message=guard_decision.explanation,
                ),
                guard_decision=guard_decision,
                waiting_for_operator=guard_decision.outcome in {
                    GuardDecisionOutcome.REQUIRE_CONFIRMATION,
                    GuardDecisionOutcome.REQUIRE_ELEVATED_MODE,
                },
                blocked=guard_decision.outcome is GuardDecisionOutcome.BLOCK,
            )
        executor = self._executors[compensation.executor_kind]
        result = executor.execute(
            ExecutorContext(
                response_run=response_run,
                step_run=step_run,
                step_definition=RunbookStepDefinition(
                    key=f"{step_run.step_key}.compensation",
                    title=compensation.title,
                    executor_kind=compensation.executor_kind,
                    operation_kind=compensation.operation_kind,
                    requires_confirmation=compensation.requires_confirmation,
                    requires_elevated_mode=compensation.requires_elevated_mode,
                    approval_required=compensation.approval_required,
                    required_approver_count=compensation.required_approver_count,
                    required_roles=compensation.required_roles,
                    step_config=compensation.step_config,
                ),
                incident=incident,
                resolved_config=resolved_config,
                actor=actor,
            )
        )
        self._record_operation(
            response_run=response_run,
            step_title=compensation.title,
            success=result.success,
            payload=result.payload,
        )
        return ResponseExecutionOutcome(result=result, guard_decision=guard_decision)

    def _record_operation(
        self,
        *,
        response_run: ResponseRun,
        step_title: str,
        success: bool,
        payload: dict[str, object],
    ) -> None:
        self._operations_diagnostics_service.record_operation(
            family=OperationFamily.RESPONSE,
            component_id=f"response:{response_run.id}",
            subject_ref=response_run.incident_id,
            success=success,
            severity="info" if success else "high",
            summary=step_title,
            payload=payload,
        )

    def _evaluate_guard(
        self,
        *,
        command_id: str,
        response_run: ResponseRun,
        step_definition: RunbookStepDefinition,
        incident: IncidentRecord,
        resolved_config: dict[str, object],
        confirmed: bool,
        elevated_mode: bool,
    ) -> GuardDecision | None:
        action_kind = _guard_action_for_step(step_definition, resolved_config)
        if action_kind is None:
            return None
        return self._guard_policy_service.evaluate(
            GuardContext(
                command_id=command_id,
                action_kind=action_kind,
                component_kind=ComponentKind.RESPONSE_RUN,
                target_risk=response_run.risk_level,
                confirmed=confirmed,
                elevated_mode=elevated_mode,
                subject_ref=incident.id,
                target_ref=incident.component_id,
                description=f"response step '{step_definition.title}'",
                metadata={
                    "step_key": step_definition.key,
                    "step_title": step_definition.title,
                    "incident_id": incident.id,
                    "response_run_id": response_run.id,
                    **resolved_config,
                },
            )
        )

    def _evaluate_compensation_guard(
        self,
        *,
        command_id: str,
        response_run: ResponseRun,
        compensation: RunbookCompensationDefinition,
        incident: IncidentRecord,
        resolved_config: dict[str, object],
        confirmed: bool,
        elevated_mode: bool,
    ) -> GuardDecision | None:
        synthetic_step = RunbookStepDefinition(
            key="compensation",
            title=compensation.title,
            executor_kind=compensation.executor_kind,
            operation_kind=compensation.operation_kind,
            requires_confirmation=compensation.requires_confirmation,
            requires_elevated_mode=compensation.requires_elevated_mode,
            approval_required=compensation.approval_required,
            required_approver_count=compensation.required_approver_count,
            required_roles=compensation.required_roles,
            step_config=compensation.step_config,
        )
        return self._evaluate_guard(
            command_id=command_id,
            response_run=response_run,
            step_definition=synthetic_step,
            incident=incident,
            resolved_config=resolved_config,
            confirmed=confirmed,
            elevated_mode=elevated_mode,
        )

    def _resolve_config(
        self,
        config: dict[str, object],
        *,
        incident: IncidentRecord,
        response_run: ResponseRun,
        actor: str,
        notes: str | None,
    ) -> dict[str, object]:
        replacements = {
            "{incident.id}": incident.id,
            "{incident.component_id}": incident.component_id,
            "{incident.component_kind}": incident.component_kind.value,
            "{incident.severity}": incident.severity.value,
            "{response.id}": response_run.id,
            "{response.risk_level}": response_run.risk_level.value,
            "{actor}": actor,
            "{note}": notes or "",
        }
        return _resolve_value(config, replacements)


def _resolve_value(value: object, replacements: dict[str, str]) -> object:
    if isinstance(value, str):
        resolved = value
        for placeholder, replacement in replacements.items():
            resolved = resolved.replace(placeholder, replacement)
        return resolved
    if isinstance(value, list):
        return [_resolve_value(item, replacements) for item in value]
    if isinstance(value, tuple):
        return tuple(_resolve_value(item, replacements) for item in value)
    if isinstance(value, dict):
        return {
            str(key): _resolve_value(item, replacements)
            for key, item in value.items()
        }
    return value


def _guard_action_for_step(
    step_definition: RunbookStepDefinition,
    resolved_config: dict[str, object],
) -> GuardActionKind | None:
    if step_definition.executor_kind is RunbookExecutorKind.MANUAL:
        return None
    if step_definition.executor_kind is RunbookExecutorKind.HTTP:
        method = str(resolved_config.get("method", "GET")).upper()
        if method in {"GET", "HEAD"}:
            return GuardActionKind.HTTP_READ
        if method in {"DELETE", "TRACE", "CONNECT"}:
            return GuardActionKind.HTTP_DESTRUCTIVE
        return GuardActionKind.HTTP_MUTATION
    if step_definition.executor_kind is RunbookExecutorKind.DOCKER:
        operation = str(resolved_config.get("operation", "restart")).lower()
        if operation == "remove":
            return GuardActionKind.DOCKER_REMOVE
        if operation == "stop":
            return GuardActionKind.DOCKER_STOP
        return GuardActionKind.DOCKER_RESTART
    if step_definition.executor_kind is RunbookExecutorKind.DB:
        statement = str(resolved_config.get("statement", ""))
        from cockpit.infrastructure.db.database_adapter import DatabaseAdapter

        if DatabaseAdapter.is_destructive_query(statement):
            return GuardActionKind.DB_DESTRUCTIVE
        if DatabaseAdapter.is_mutating_query(statement):
            return GuardActionKind.DB_MUTATION
        return GuardActionKind.DB_QUERY
    if step_definition.executor_kind is RunbookExecutorKind.SHELL:
        operation_kind = step_definition.operation_kind.lower()
        if operation_kind in {"destructive", "delete", "drop", "remove"}:
            return GuardActionKind.SHELL_DESTRUCTIVE
        if operation_kind in {"mutation", "restart", "write", "remediate"}:
            return GuardActionKind.SHELL_MUTATION
        return GuardActionKind.SHELL_READ
    return None

