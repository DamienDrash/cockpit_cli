"""Database command handlers."""

from __future__ import annotations

from pathlib import Path

from cockpit.application.handlers.base import (
    CommandContextError,
    ConfirmationRequiredError,
    DispatchResult,
    PolicyViolationError,
)
from cockpit.application.services.datasource_service import DataSourceService
from cockpit.application.services.guard_policy_service import GuardPolicyService
from cockpit.application.services.operations_diagnostics_service import (
    OperationsDiagnosticsService,
)
from cockpit.domain.commands.command import Command
from cockpit.domain.models.policy import GuardContext
from cockpit.infrastructure.db.database_adapter import DatabaseAdapter
from cockpit.shared.enums import (
    ComponentKind,
    GuardActionKind,
    GuardDecisionOutcome,
    OperationFamily,
    SessionTargetKind,
    TargetRiskLevel,
)
from cockpit.shared.risk import classify_target_risk, risk_presentation


class RunDatabaseQueryHandler:
    """Execute a SQL query for the currently selected database."""

    def __init__(
        self,
        database_adapter: DatabaseAdapter,
        data_source_service: DataSourceService | None = None,
        guard_policy_service: GuardPolicyService | None = None,
        operations_diagnostics_service: OperationsDiagnosticsService | None = None,
    ) -> None:
        self._database_adapter = database_adapter
        self._data_source_service = data_source_service
        if guard_policy_service is None:
            raise ValueError("guard_policy_service is required.")
        if operations_diagnostics_service is None:
            raise ValueError("operations_diagnostics_service is required.")
        self._guard_policy_service = guard_policy_service
        self._operations_diagnostics_service = operations_diagnostics_service

    def __call__(self, command: Command) -> DispatchResult:
        query = self._resolve_query(command)
        target_kind = self._target_kind(command.context.get("target_kind"))
        target_ref = self._optional_str(command.context.get("target_ref"))
        workspace_root = self._optional_str(command.context.get("workspace_root")) or ""
        workspace_name = self._optional_str(command.context.get("workspace_name")) or "workspace"
        selected_profile_id = self._resolve_profile_id(command)
        risk_level = classify_target_risk(
            target_kind=target_kind,
            target_ref=target_ref,
            workspace_name=workspace_name,
            workspace_root=workspace_root,
        )

        if selected_profile_id:
            return self._run_datasource_query(
                command,
                profile_id=selected_profile_id,
                query=query,
                risk_level=risk_level,
                target_kind=target_kind,
                target_ref=target_ref,
                workspace_name=workspace_name,
                workspace_root=workspace_root,
            )

        database_path = self._resolve_database_path(command)

        decision = self._evaluate_guard(
            command=command,
            risk_level=risk_level,
            subject_ref=database_path,
            description=f"SQL against {Path(database_path).name or database_path}",
            metadata={"query": query, "subject_ref": database_path},
        )
        self._enforce_guard_decision(command, decision, display_name=Path(database_path).name or database_path)

        result = self._database_adapter.run_query(
            database_path,
            query,
            target_kind=target_kind,
            target_ref=target_ref,
        )
        self._operations_diagnostics_service.record_operation(
            family=OperationFamily.DB,
            component_id=f"datasource:{database_path}",
            subject_ref=database_path,
            success=result.success,
            severity="info" if result.success else "high",
            summary=result.message or "database query executed",
            payload={
                "query": query,
                "operation": self._operation_name(query),
                "message": result.message,
                "row_count": result.row_count,
                "affected_rows": result.affected_rows,
                "risk_level": risk_level.value,
                "guard_outcome": decision.outcome.value,
                "backend": "sqlite",
            },
        )
        return DispatchResult(
            success=result.success,
            message=result.message,
            data={
                "result_panel_id": "db-panel",
                "result_payload": {
                    "database_path": database_path,
                    "query_result": result.to_dict(),
                },
            },
        )

    def _run_datasource_query(
        self,
        command: Command,
        *,
        profile_id: str,
        query: str,
        risk_level: TargetRiskLevel,
        target_kind: SessionTargetKind,
        target_ref: str | None,
        workspace_name: str,
        workspace_root: str,
    ) -> DispatchResult:
        if self._data_source_service is None:
            raise CommandContextError("Datasource support is not configured.")
        profile = self._data_source_service.get_profile(profile_id)
        if profile is None:
            raise CommandContextError(f"Datasource profile '{profile_id}' was not found.")
        operation = self._resolve_operation(command, query, profile.backend)
        effective_risk_level = self._profile_risk_level(
            profile.risk_level,
            target_kind=target_kind,
            target_ref=target_ref,
            workspace_name=workspace_name,
            workspace_root=workspace_root,
        )
        decision = self._evaluate_guard(
            command=command,
            risk_level=effective_risk_level,
            subject_ref=profile.id,
            description=f"datasource operation on {profile.name}",
            metadata={
                "query": query,
                "backend": profile.backend,
                "profile_id": profile.id,
                "subject_ref": profile.id,
            },
        )
        self._enforce_guard_decision(command, decision, display_name=profile.name)
        result = self._data_source_service.run_statement(
            profile.id,
            query,
            operation=operation,
        )
        self._operations_diagnostics_service.record_operation(
            family=OperationFamily.DB,
            component_id=f"datasource:{profile.id}",
            subject_ref=profile.id,
            success=result.success,
            severity="info" if result.success else "high",
            summary=result.message or "datasource statement executed",
            payload={
                "query": query,
                "operation": operation,
                "message": result.message,
                "affected_rows": result.affected_rows,
                "backend": profile.backend,
                "risk_level": effective_risk_level.value,
                "guard_outcome": decision.outcome.value,
            },
        )
        return DispatchResult(
            success=result.success,
            message=result.message,
            data={
                "result_panel_id": "db-panel",
                "result_payload": {
                    "selected_profile_id": profile.id,
                    "query_result": result.to_dict(),
                },
            },
        )

    def _resolve_database_path(self, command: Command) -> str:
        named_path = command.args.get("database")
        if isinstance(named_path, str) and named_path:
            return named_path
        context_path = command.context.get("selected_database_path")
        if isinstance(context_path, str) and context_path:
            return context_path
        argv = command.args.get("argv", [])
        if isinstance(argv, list) and len(argv) >= 2 and isinstance(argv[0], str):
            candidate = argv[0]
            if candidate.endswith((".db", ".sqlite", ".sqlite3")):
                return candidate
        raise CommandContextError("No database is selected.")

    def _resolve_query(self, command: Command) -> str:
        named_query = command.args.get("query")
        if isinstance(named_query, str) and named_query.strip():
            return named_query.strip()
        argv = command.args.get("argv", [])
        if not isinstance(argv, list):
            raise CommandContextError("A SQL query is required.")
        query_tokens = [str(token) for token in argv if isinstance(token, str)]
        if len(query_tokens) >= 2 and query_tokens[0].endswith((".db", ".sqlite", ".sqlite3")):
            query_tokens = query_tokens[1:]
        query = " ".join(query_tokens).strip()
        if not query:
            raise CommandContextError("A SQL query is required.")
        return query

    def _resolve_profile_id(self, command: Command) -> str | None:
        named_profile = command.args.get("profile")
        if isinstance(named_profile, str) and named_profile:
            return named_profile
        context_profile = command.context.get("selected_profile_id")
        if isinstance(context_profile, str) and context_profile:
            return context_profile
        return None

    def _evaluate_guard(
        self,
        *,
        command: Command,
        risk_level: TargetRiskLevel,
        subject_ref: str,
        description: str,
        metadata: dict[str, object],
    ):
        query = str(metadata.get("query", ""))
        return self._guard_policy_service.evaluate(
            GuardContext(
                command_id=command.id,
                action_kind=self._guard_action_kind(query),
                component_kind=ComponentKind.DATASOURCE,
                target_risk=risk_level,
                workspace_id=self._optional_str(command.context.get("workspace_id")),
                session_id=self._optional_str(command.context.get("session_id")),
                workspace_name=self._optional_str(command.context.get("workspace_name")),
                target_ref=self._optional_str(command.context.get("target_ref")),
                confirmed=self._is_confirmed(command),
                elevated_mode=self._is_elevated(command),
                subject_ref=subject_ref,
                description=description,
                metadata=metadata,
            )
        )

    def _enforce_guard_decision(
        self,
        command: Command,
        decision: object,
        *,
        display_name: str,
    ) -> None:
        assert hasattr(decision, "outcome")
        if decision.outcome is GuardDecisionOutcome.REQUIRE_CONFIRMATION:
            risk_label = risk_presentation(decision.target_risk).label
            raise ConfirmationRequiredError(
                f"Confirm database operation on {display_name} ({risk_label}).",
                payload={
                    "pending_command_name": command.name,
                    "pending_args": dict(command.args),
                    "pending_context": dict(command.context),
                    "confirmation_message": (
                        f"{decision.confirmation_message or 'Confirm database operation on'} "
                        f"{display_name}. Press Enter/Y to confirm or Esc/N to cancel."
                    ),
                    "guard_decision": decision.to_dict(),
                },
            )
        if decision.outcome in {
            GuardDecisionOutcome.REQUIRE_ELEVATED_MODE,
            GuardDecisionOutcome.BLOCK,
        }:
            raise PolicyViolationError(
                decision.explanation,
                payload={"guard_decision": decision.to_dict()},
            )

    def _resolve_operation(self, command: Command, query: str, backend: str) -> str:
        named_operation = command.args.get("operation")
        if isinstance(named_operation, str) and named_operation:
            return named_operation.strip().lower()
        if backend.lower() in {"mongodb", "redis", "chromadb"}:
            return "query"
        return "mutation" if DatabaseAdapter.is_mutating_query(query) else "query"

    @staticmethod
    def _is_confirmed(command: Command) -> bool:
        confirmed = command.args.get("confirmed")
        return bool(confirmed is True or confirmed == "true")

    @staticmethod
    def _is_elevated(command: Command) -> bool:
        elevated = command.args.get("elevated_mode", command.args.get("elevated"))
        return bool(elevated is True or elevated == "true")

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return value if isinstance(value, str) else None

    @staticmethod
    def _target_kind(value: object) -> SessionTargetKind:
        if isinstance(value, SessionTargetKind):
            return value
        if isinstance(value, str):
            try:
                return SessionTargetKind(value)
            except ValueError:
                return SessionTargetKind.LOCAL
        return SessionTargetKind.LOCAL

    @staticmethod
    def _profile_risk_level(
        raw_level: str,
        *,
        target_kind: SessionTargetKind,
        target_ref: str | None,
        workspace_name: str,
        workspace_root: str,
    ) -> TargetRiskLevel:
        try:
            return TargetRiskLevel(raw_level.lower())
        except ValueError:
            return classify_target_risk(
                target_kind=target_kind,
                target_ref=target_ref,
                workspace_name=workspace_name,
                workspace_root=workspace_root,
            )

    @staticmethod
    def _guard_action_kind(query: str) -> GuardActionKind:
        if DatabaseAdapter.is_destructive_query(query):
            return GuardActionKind.DB_DESTRUCTIVE
        if DatabaseAdapter.is_mutating_query(query):
            return GuardActionKind.DB_MUTATION
        return GuardActionKind.DB_QUERY

    @staticmethod
    def _operation_name(query: str) -> str:
        if DatabaseAdapter.is_destructive_query(query):
            return "destructive"
        if DatabaseAdapter.is_mutating_query(query):
            return "mutation"
        return "query"
