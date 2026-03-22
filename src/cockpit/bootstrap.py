"""Application bootstrap and dependency wiring."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cockpit.application.dispatch.command_dispatcher import CommandDispatcher
from cockpit.application.dispatch.command_parser import CommandParser
from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.handlers.layout_handlers import ApplyDefaultLayoutHandler
from cockpit.application.handlers.session_handlers import RestoreSessionHandler
from cockpit.application.handlers.tab_handlers import FocusTabHandler
from cockpit.application.handlers.terminal_handlers import (
    FocusTerminalHandler,
    RestartTerminalHandler,
)
from cockpit.application.handlers.workspace_handlers import (
    OpenWorkspaceHandler,
    ReopenLastWorkspaceHandler,
)
from cockpit.application.services.activity_log_service import ActivityLogService
from cockpit.application.services.layout_service import LayoutService
from cockpit.application.services.navigation_controller import NavigationController
from cockpit.application.services.session_service import SessionService
from cockpit.application.services.workspace_service import WorkspaceService
from cockpit.domain.events.domain_events import (
    LayoutApplied,
    SessionCreated,
    SessionRestored,
    SnapshotSaved,
    WorkspaceOpened,
)
from cockpit.domain.events.runtime_events import PTYStarted, PTYStartupFailed, TerminalExited
from cockpit.infrastructure.config.config_loader import ConfigLoader
from cockpit.infrastructure.git.git_adapter import GitAdapter
from cockpit.infrastructure.persistence.repositories import (
    AuditLogRepository,
    CommandHistoryRepository,
    LayoutRepository,
    SessionRepository,
    SnapshotRepository,
    WorkspaceRepository,
)
from cockpit.infrastructure.persistence.sqlite_store import SQLiteStore
from cockpit.infrastructure.shell.local_shell_adapter import LocalShellAdapter
from cockpit.runtime.pty_manager import PTYManager
from cockpit.runtime.stream_router import StreamRouter
from cockpit.runtime.task_supervisor import TaskSupervisor
from cockpit.shared.config import default_db_path, discover_project_root


@dataclass(slots=True)
class ApplicationContainer:
    """Holds the bootstrap-time application dependencies."""

    project_root: Path
    command_catalog: tuple[str, ...]
    event_bus: EventBus
    command_parser: CommandParser
    command_dispatcher: CommandDispatcher
    navigation_controller: NavigationController
    session_service: SessionService
    activity_log_service: ActivityLogService
    stream_router: StreamRouter
    pty_manager: PTYManager
    git_adapter: GitAdapter
    store: SQLiteStore

    def shutdown(self) -> None:
        self.pty_manager.shutdown()
        self.store.close()


def build_container(
    *,
    start: Path | None = None,
    shell_adapter: LocalShellAdapter | None = None,
) -> ApplicationContainer:
    """Create the minimum runnable application dependency graph."""
    project_root = discover_project_root(start)
    event_bus = EventBus()
    command_parser = CommandParser()
    command_dispatcher = CommandDispatcher(event_bus=event_bus)
    store = SQLiteStore(default_db_path(project_root))
    config_loader = ConfigLoader(start=start)
    command_catalog_payload = config_loader.load_command_catalog()
    raw_commands = command_catalog_payload.get("commands", [])
    command_catalog = tuple(
        command_name
        for command_name in raw_commands
        if isinstance(command_name, str) and command_name
    )
    workspace_repository = WorkspaceRepository(store)
    layout_repository = LayoutRepository(store)
    session_repository = SessionRepository(store)
    snapshot_repository = SnapshotRepository(store)
    history_repository = CommandHistoryRepository(store)
    audit_repository = AuditLogRepository(store)
    stream_router = StreamRouter()
    task_supervisor = TaskSupervisor()
    shell_adapter = shell_adapter or LocalShellAdapter()
    git_adapter = GitAdapter()
    pty_manager = PTYManager(
        event_bus=event_bus,
        shell_adapter=shell_adapter,
        stream_router=stream_router,
        task_supervisor=task_supervisor,
    )
    workspace_service = WorkspaceService(workspace_repository)
    layout_service = LayoutService(layout_repository, config_loader)
    session_service = SessionService(session_repository, snapshot_repository)
    activity_log_service = ActivityLogService(
        history_repository=history_repository,
        audit_repository=audit_repository,
    )
    navigation_controller = NavigationController(
        event_bus=event_bus,
        workspace_service=workspace_service,
        layout_service=layout_service,
        session_service=session_service,
    )
    command_dispatcher.observe(activity_log_service.record_command)
    for event_type in (
        WorkspaceOpened,
        SessionCreated,
        SessionRestored,
        LayoutApplied,
        SnapshotSaved,
        PTYStarted,
        PTYStartupFailed,
        TerminalExited,
    ):
        event_bus.subscribe(event_type, activity_log_service.record_event)

    command_dispatcher.register(
        "workspace.open",
        OpenWorkspaceHandler(
            event_bus,
            navigation_controller=navigation_controller,
        ),
    )
    command_dispatcher.register(
        "workspace.reopen_last",
        ReopenLastWorkspaceHandler(
            event_bus,
            navigation_controller=navigation_controller,
        ),
    )
    command_dispatcher.register(
        "session.restore",
        RestoreSessionHandler(
            event_bus,
            navigation_controller=navigation_controller,
        ),
    )
    command_dispatcher.register("tab.focus", FocusTabHandler())
    command_dispatcher.register(
        "layout.apply_default", ApplyDefaultLayoutHandler(event_bus)
    )
    command_dispatcher.register(
        "terminal.focus", FocusTerminalHandler(event_bus)
    )
    command_dispatcher.register(
        "terminal.restart", RestartTerminalHandler(pty_manager)
    )

    return ApplicationContainer(
        project_root=project_root,
        command_catalog=command_catalog,
        event_bus=event_bus,
        command_parser=command_parser,
        command_dispatcher=command_dispatcher,
        navigation_controller=navigation_controller,
        session_service=session_service,
        activity_log_service=activity_log_service,
        stream_router=stream_router,
        pty_manager=pty_manager,
        git_adapter=git_adapter,
        store=store,
    )
