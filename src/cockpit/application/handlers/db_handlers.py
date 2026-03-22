"""Database command handlers."""

from __future__ import annotations

from pathlib import Path

from cockpit.application.handlers.base import (
    CommandContextError,
    ConfirmationRequiredError,
    DispatchResult,
)
from cockpit.domain.commands.command import Command
from cockpit.infrastructure.db.database_adapter import DatabaseAdapter
from cockpit.shared.enums import SessionTargetKind
from cockpit.shared.risk import classify_target_risk, risk_presentation


class RunDatabaseQueryHandler:
    """Execute a SQL query for the currently selected database."""

    def __init__(self, database_adapter: DatabaseAdapter) -> None:
        self._database_adapter = database_adapter

    def __call__(self, command: Command) -> DispatchResult:
        database_path = self._resolve_database_path(command)
        query = self._resolve_query(command)
        target_kind = self._target_kind(command.context.get("target_kind"))
        target_ref = self._optional_str(command.context.get("target_ref"))
        workspace_root = self._optional_str(command.context.get("workspace_root")) or ""
        workspace_name = self._optional_str(command.context.get("workspace_name")) or "workspace"

        if DatabaseAdapter.is_mutating_query(query) and not self._is_confirmed(command):
            risk_level = classify_target_risk(
                target_kind=target_kind,
                target_ref=target_ref,
                workspace_name=workspace_name,
                workspace_root=workspace_root,
            )
            risk_label = risk_presentation(risk_level).label
            database_name = Path(database_path).name or database_path
            raise ConfirmationRequiredError(
                f"Confirm database write query on {database_name} ({risk_label}).",
                payload={
                    "pending_command_name": command.name,
                    "pending_args": dict(command.args),
                    "pending_context": dict(command.context),
                    "confirmation_message": (
                        f"Execute mutating SQL against {database_name}? "
                        "Press Enter/Y to confirm or Esc/N to cancel."
                    ),
                },
            )

        result = self._database_adapter.run_query(
            database_path,
            query,
            target_kind=target_kind,
            target_ref=target_ref,
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

    @staticmethod
    def _is_confirmed(command: Command) -> bool:
        confirmed = command.args.get("confirmed")
        return bool(confirmed is True or confirmed == "true")

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
