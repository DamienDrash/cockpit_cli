"""Core platform wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cockpit.core.dispatch.command_dispatcher import CommandDispatcher
from cockpit.core.dispatch.command_parser import CommandParser
from cockpit.core.dispatch.event_bus import EventBus
from cockpit.workspace.config_loader import ConfigLoader
from cockpit.workspace.repositories import (
    AuditLogRepository,
    CommandHistoryRepository,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.infrastructure.system.clipboard import ClipboardService
from cockpit.runtime.stream_router import StreamRouter
from cockpit.runtime.task_supervisor import TaskSupervisor
from cockpit.core.config import default_db_path


def wire_core(project_root: Path, start: Path | None) -> dict[str, Any]:
    """Wire core platform components."""
    event_bus = EventBus()
    command_parser = CommandParser()
    command_dispatcher = CommandDispatcher(event_bus=event_bus)
    store = SQLiteStore(default_db_path(project_root))
    config_loader = ConfigLoader(start=start)

    history_repository = CommandHistoryRepository(store)
    audit_repository = AuditLogRepository(store)

    stream_router = StreamRouter()
    task_supervisor = TaskSupervisor()
    clipboard_service = ClipboardService()

    return {
        "event_bus": event_bus,
        "command_parser": command_parser,
        "command_dispatcher": command_dispatcher,
        "store": store,
        "config_loader": config_loader,
        "history_repository": history_repository,
        "audit_repository": audit_repository,
        "stream_router": stream_router,
        "task_supervisor": task_supervisor,
        "clipboard_service": clipboard_service,
    }
