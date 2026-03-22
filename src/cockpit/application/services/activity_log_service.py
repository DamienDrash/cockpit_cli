"""Command history and audit metadata recording."""

from __future__ import annotations

from cockpit.application.handlers.base import DispatchResult
from cockpit.domain.commands.command import Command, CommandAuditEntry, CommandHistoryEntry
from cockpit.domain.events.base import BaseEvent
from cockpit.domain.events.domain_events import (
    LayoutApplied,
    SessionCreated,
    SessionRestored,
    SnapshotSaved,
    WorkspaceOpened,
)
from cockpit.domain.events.runtime_events import PTYStarted, PTYStartupFailed, TerminalExited
from cockpit.infrastructure.persistence.repositories import (
    AuditLogRepository,
    CommandHistoryRepository,
)


class ActivityLogService:
    """Persists command history plus audit metadata for important lifecycle events."""

    def __init__(
        self,
        *,
        history_repository: CommandHistoryRepository,
        audit_repository: AuditLogRepository,
    ) -> None:
        self._history_repository = history_repository
        self._audit_repository = audit_repository

    def record_command(self, command: Command, result: DispatchResult) -> None:
        self._history_repository.record(
            CommandHistoryEntry(
                command_id=command.id,
                name=command.name,
                source=command.source,
                args=command.args,
                context=command.context,
                success=result.success,
                message=result.message,
            )
        )

    def record_event(self, event: BaseEvent) -> None:
        entry = self._entry_from_event(event)
        if entry is not None:
            self._audit_repository.record(entry)

    def _entry_from_event(self, event: BaseEvent) -> CommandAuditEntry | None:
        if isinstance(event, WorkspaceOpened):
            return CommandAuditEntry(
                command_id=event.event_id,
                action="workspace.opened",
                workspace_id=event.workspace_id,
                metadata={
                    "name": event.name,
                    "root_path": event.root_path,
                    "target_kind": event.target_kind.value,
                },
            )
        if isinstance(event, SessionCreated):
            return CommandAuditEntry(
                command_id=event.event_id,
                action="session.created",
                workspace_id=event.workspace_id,
                session_id=event.session_id,
            )
        if isinstance(event, SessionRestored):
            return CommandAuditEntry(
                command_id=event.event_id,
                action="session.restored",
                workspace_id=event.workspace_id,
                session_id=event.session_id,
            )
        if isinstance(event, LayoutApplied):
            return CommandAuditEntry(
                command_id=event.event_id,
                action="layout.applied",
                session_id=event.session_id,
                metadata={"layout_id": event.layout_id},
            )
        if isinstance(event, SnapshotSaved):
            return CommandAuditEntry(
                command_id=event.event_id,
                action="snapshot.saved",
                session_id=event.session_id,
                metadata={"snapshot_kind": event.snapshot_kind.value},
            )
        if isinstance(event, PTYStarted):
            return CommandAuditEntry(
                command_id=event.event_id,
                action="terminal.started",
                metadata={
                    "panel_id": event.panel_id,
                    "cwd": event.cwd,
                    "pid": event.pid,
                },
            )
        if isinstance(event, PTYStartupFailed):
            return CommandAuditEntry(
                command_id=event.event_id,
                action="terminal.start_failed",
                metadata={
                    "panel_id": event.panel_id,
                    "cwd": event.cwd,
                    "reason": event.reason,
                },
            )
        if isinstance(event, TerminalExited):
            return CommandAuditEntry(
                command_id=event.event_id,
                action="terminal.exited",
                metadata={
                    "panel_id": event.panel_id,
                    "exit_code": event.exit_code,
                },
            )
        return None
