"""Command history and audit metadata recording."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from cockpit.core.dispatch.handler_base import DispatchResult
from cockpit.core.command import (
    Command,
    CommandAuditEntry,
    CommandHistoryEntry,
)
from cockpit.core.events.base import BaseEvent
from cockpit.workspace.events import (
    LayoutApplied,
    SessionCreated,
    SessionRestored,
    SnapshotSaved,
    WorkspaceOpened,
)
from cockpit.core.events.runtime import (
    PTYStarted,
    PTYStartupFailed,
    TerminalExited,
)
from cockpit.workspace.repositories import (
    AuditLogRepository,
    CommandHistoryRepository,
)


@dataclass(slots=True, frozen=True)
class ActivityLogRecord:
    entry_id: str
    recorded_at: datetime
    category: str
    title: str
    detail: str
    workspace_id: str | None = None
    session_id: str | None = None
    status: str | None = None


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

    def recent_entries(
        self,
        *,
        limit: int = 20,
        workspace_id: str | None = None,
        session_id: str | None = None,
        workspace_root: str | None = None,
    ) -> list[ActivityLogRecord]:
        records: list[ActivityLogRecord] = []
        fetch_limit = max(limit * 4, 20)
        for payload in self._history_repository.list_recent(fetch_limit):
            record = self._record_from_command_payload(payload)
            if record is None:
                continue
            if self._matches_scope(
                record,
                workspace_id=workspace_id,
                session_id=session_id,
                workspace_root=workspace_root,
                payload=payload,
            ):
                records.append(record)
        for payload in self._audit_repository.list_recent(fetch_limit):
            record = self._record_from_audit_payload(payload)
            if record is None:
                continue
            if self._matches_scope(
                record,
                workspace_id=workspace_id,
                session_id=session_id,
                workspace_root=workspace_root,
                payload=payload,
            ):
                records.append(record)
        records.sort(key=lambda record: record.recorded_at, reverse=True)
        return records[:limit]

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
                    "target_kind": event.target_kind.value,
                    "target_ref": event.target_ref,
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
                    "target_kind": event.target_kind.value,
                    "target_ref": event.target_ref,
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

    @staticmethod
    def _record_from_command_payload(
        payload: dict[str, object],
    ) -> ActivityLogRecord | None:
        command_id = payload.get("command_id")
        name = payload.get("name")
        recorded_at = payload.get("recorded_at")
        if (
            not isinstance(command_id, str)
            or not isinstance(name, str)
            or not isinstance(recorded_at, str)
        ):
            return None
        context = payload.get("context", {})
        args = payload.get("args", {})
        if not isinstance(context, dict):
            context = {}
        if not isinstance(args, dict):
            args = {}
        argv = args.get("argv", [])
        argv_suffix = ""
        if isinstance(argv, list) and argv:
            argv_suffix = " ".join(str(token) for token in argv[:3])
        message = payload.get("message")
        success = payload.get("success")
        detail_parts: list[str] = []
        if isinstance(message, str) and message:
            detail_parts.append(message)
        if argv_suffix:
            detail_parts.append(f"argv={argv_suffix}")
        status = "ok" if success is True else "failed" if success is False else None
        if status and not detail_parts:
            detail_parts.append(status)
        return ActivityLogRecord(
            entry_id=f"command:{command_id}",
            recorded_at=datetime.fromisoformat(recorded_at),
            category="command",
            title=name,
            detail=" | ".join(detail_parts) or "command executed",
            workspace_id=context.get("workspace_id")
            if isinstance(context.get("workspace_id"), str)
            else None,
            session_id=context.get("session_id")
            if isinstance(context.get("session_id"), str)
            else None,
            status=status,
        )

    @staticmethod
    def _record_from_audit_payload(
        payload: dict[str, object],
    ) -> ActivityLogRecord | None:
        command_id = payload.get("command_id")
        action = payload.get("action")
        recorded_at = payload.get("recorded_at")
        if (
            not isinstance(command_id, str)
            or not isinstance(action, str)
            or not isinstance(recorded_at, str)
        ):
            return None
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        detail_parts: list[str] = []
        for key in (
            "root_path",
            "layout_id",
            "snapshot_kind",
            "cwd",
            "reason",
            "exit_code",
            "target_kind",
            "target_ref",
        ):
            value = metadata.get(key)
            if value is not None:
                detail_parts.append(f"{key}={value}")
        workspace_id = payload.get("workspace_id")
        session_id = payload.get("session_id")
        return ActivityLogRecord(
            entry_id=f"audit:{command_id}:{action}",
            recorded_at=datetime.fromisoformat(recorded_at),
            category="audit",
            title=action,
            detail=" | ".join(detail_parts) or "audit event recorded",
            workspace_id=workspace_id if isinstance(workspace_id, str) else None,
            session_id=session_id if isinstance(session_id, str) else None,
        )

    @staticmethod
    def _matches_scope(
        record: ActivityLogRecord,
        *,
        workspace_id: str | None,
        session_id: str | None,
        workspace_root: str | None,
        payload: dict[str, object],
    ) -> bool:
        if workspace_id and record.workspace_id:
            return record.workspace_id == workspace_id
        if session_id and record.session_id:
            return record.session_id == session_id
        if workspace_root:
            context = payload.get("context", {})
            if isinstance(context, dict):
                context_root = context.get("workspace_root")
                if isinstance(context_root, str) and context_root:
                    return context_root == workspace_root
            metadata = payload.get("metadata", {})
            if isinstance(metadata, dict):
                root_path = metadata.get("root_path")
                if isinstance(root_path, str) and root_path:
                    return root_path == workspace_root
        return not any((workspace_id, session_id, workspace_root))
