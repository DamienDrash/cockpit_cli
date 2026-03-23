"""Application bootstrap and dependency wiring."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cockpit.application.dispatch.command_dispatcher import CommandDispatcher
from cockpit.application.dispatch.command_parser import CommandParser
from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.services.datasource_service import DataSourceService
from cockpit.application.handlers.curl_handlers import SendHttpRequestHandler
from cockpit.application.handlers.cron_handlers import SetCronJobEnabledHandler
from cockpit.application.handlers.db_handlers import RunDatabaseQueryHandler
from cockpit.application.handlers.docker_handlers import (
    RemoveDockerContainerHandler,
    RestartDockerContainerHandler,
    StopDockerContainerHandler,
)
from cockpit.application.handlers.layout_handlers import (
    AdjustActiveLayoutRatioHandler,
    ApplyDefaultLayoutHandler,
    FocusNextPanelHandler,
    ToggleActiveLayoutOrientationHandler,
)
from cockpit.application.handlers.session_handlers import RestoreSessionHandler
from cockpit.application.handlers.tab_handlers import FocusTabHandler
from cockpit.application.handlers.terminal_handlers import (
    CopyTerminalBufferHandler,
    CopyTerminalSelectionHandler,
    ExportTerminalBufferHandler,
    FocusTerminalHandler,
    NavigateTerminalSearchHandler,
    RestartTerminalHandler,
    SearchTerminalHandler,
)
from cockpit.application.handlers.workspace_handlers import (
    OpenWorkspaceHandler,
    ReopenLastWorkspaceHandler,
)
from cockpit.application.services.activity_log_service import ActivityLogService
from cockpit.application.services.connection_service import ConnectionService
from cockpit.application.services.layout_service import LayoutService
from cockpit.application.services.navigation_controller import NavigationController
from cockpit.application.services.plugin_service import PluginService
from cockpit.application.services.secret_service import SecretService
from cockpit.application.services.session_service import SessionService
from cockpit.application.services.web_admin_service import WebAdminService
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
from cockpit.infrastructure.cron.cron_adapter import CronAdapter
from cockpit.infrastructure.db.database_adapter import DatabaseAdapter
from cockpit.infrastructure.docker.docker_adapter import DockerAdapter
from cockpit.infrastructure.filesystem.remote_filesystem_adapter import RemoteFilesystemAdapter
from cockpit.infrastructure.git.git_adapter import GitAdapter
from cockpit.infrastructure.http.http_adapter import HttpAdapter
from cockpit.infrastructure.persistence.repositories import (
    AuditLogRepository,
    CommandHistoryRepository,
    DataSourceProfileRepository,
    InstalledPluginRepository,
    LayoutRepository,
    SessionRepository,
    SnapshotRepository,
    WebAdminStateRepository,
    WorkspaceRepository,
)
from cockpit.infrastructure.persistence.sqlite_store import SQLiteStore
from cockpit.infrastructure.secrets.secret_resolver import SecretResolver
from cockpit.infrastructure.shell.base import ShellAdapter
from cockpit.infrastructure.shell.local_shell_adapter import LocalShellAdapter
from cockpit.infrastructure.shell.shell_adapter_router import ShellAdapterRouter
from cockpit.infrastructure.ssh.command_runner import SSHCommandRunner
from cockpit.infrastructure.ssh.ssh_shell_adapter import SSHShellAdapter
from cockpit.infrastructure.ssh.tunnel_manager import SSHTunnelManager
from cockpit.infrastructure.system.clipboard import ClipboardService
from cockpit.plugins.loader import PluginBootstrapContext, PluginLoader
from cockpit.runtime.pty_manager import PTYManager
from cockpit.runtime.stream_router import StreamRouter
from cockpit.runtime.task_supervisor import TaskSupervisor
from cockpit.shared.config import default_db_path, discover_project_root
from cockpit.ui.panels.curl_panel import CurlPanel
from cockpit.ui.panels.db_panel import DBPanel
from cockpit.ui.panels.git_panel import GitPanel
from cockpit.ui.panels.docker_panel import DockerPanel
from cockpit.ui.panels.cron_panel import CronPanel
from cockpit.ui.panels.logs_panel import LogsPanel
from cockpit.ui.panels.registry import PanelRegistry, PanelSpec
from cockpit.ui.panels.work_panel import WorkPanel


@dataclass(slots=True)
class ApplicationContainer:
    """Holds the bootstrap-time application dependencies."""

    project_root: Path
    command_catalog: tuple[str, ...]
    event_bus: EventBus
    command_parser: CommandParser
    command_dispatcher: CommandDispatcher
    navigation_controller: NavigationController
    layout_service: LayoutService
    session_service: SessionService
    activity_log_service: ActivityLogService
    data_source_service: DataSourceService
    secret_service: SecretService
    plugin_service: PluginService
    web_admin_service: WebAdminService
    stream_router: StreamRouter
    pty_manager: PTYManager
    cron_adapter: CronAdapter
    docker_adapter: DockerAdapter
    database_adapter: DatabaseAdapter
    http_adapter: HttpAdapter
    git_adapter: GitAdapter
    remote_filesystem_adapter: RemoteFilesystemAdapter
    clipboard_service: ClipboardService
    tunnel_manager: SSHTunnelManager
    panel_registry: PanelRegistry
    store: SQLiteStore

    def shutdown(self) -> None:
        self.pty_manager.shutdown()
        self.tunnel_manager.shutdown()
        self.store.close()


def build_container(
    *,
    start: Path | None = None,
    shell_adapter: ShellAdapter | None = None,
    ssh_command_runner: SSHCommandRunner | None = None,
    cron_adapter: CronAdapter | None = None,
    docker_adapter: DockerAdapter | None = None,
    database_adapter: DatabaseAdapter | None = None,
    http_adapter: HttpAdapter | None = None,
) -> ApplicationContainer:
    """Create the minimum runnable application dependency graph."""
    project_root = discover_project_root(start)
    event_bus = EventBus()
    command_parser = CommandParser()
    command_dispatcher = CommandDispatcher(event_bus=event_bus)
    store = SQLiteStore(default_db_path(project_root))
    config_loader = ConfigLoader(start=start)
    plugin_config = config_loader.load_plugins()
    connection_service = ConnectionService(config_loader)
    command_catalog_payload = config_loader.load_command_catalog()
    raw_commands = command_catalog_payload.get("commands", [])
    command_catalog_entries = [
        command_name
        for command_name in raw_commands
        if isinstance(command_name, str) and command_name
    ]
    workspace_repository = WorkspaceRepository(store)
    layout_repository = LayoutRepository(store)
    session_repository = SessionRepository(store)
    snapshot_repository = SnapshotRepository(store)
    history_repository = CommandHistoryRepository(store)
    audit_repository = AuditLogRepository(store)
    datasource_repository = DataSourceProfileRepository(store)
    installed_plugin_repository = InstalledPluginRepository(store)
    web_admin_state_repository = WebAdminStateRepository(store)
    stream_router = StreamRouter()
    task_supervisor = TaskSupervisor()
    ssh_command_runner = ssh_command_runner or SSHCommandRunner()
    shell_adapter = shell_adapter or ShellAdapterRouter(
        local_adapter=LocalShellAdapter(),
        ssh_adapter=SSHShellAdapter(),
    )
    cron_adapter = cron_adapter or CronAdapter(ssh_command_runner=ssh_command_runner)
    docker_adapter = docker_adapter or DockerAdapter(ssh_command_runner=ssh_command_runner)
    database_adapter = database_adapter or DatabaseAdapter(ssh_command_runner=ssh_command_runner)
    http_adapter = http_adapter or HttpAdapter()
    git_adapter = GitAdapter(ssh_command_runner=ssh_command_runner)
    remote_filesystem_adapter = RemoteFilesystemAdapter(ssh_command_runner)
    secret_service = SecretService(web_admin_state_repository)
    secret_resolver = SecretResolver(
        base_path=project_root,
        named_reference_lookup=secret_service.lookup_reference,
    )
    tunnel_manager = SSHTunnelManager()
    clipboard_service = ClipboardService()
    pty_manager = PTYManager(
        event_bus=event_bus,
        shell_adapter=shell_adapter,
        stream_router=stream_router,
        task_supervisor=task_supervisor,
    )
    workspace_service = WorkspaceService(
        workspace_repository,
        connection_service=connection_service,
    )
    layout_service = LayoutService(layout_repository, config_loader)
    session_service = SessionService(session_repository, snapshot_repository)
    data_source_service = DataSourceService(
        datasource_repository,
        config_loader=config_loader,
        secret_resolver=secret_resolver,
        tunnel_manager=tunnel_manager,
    )
    plugin_service = PluginService(
        installed_plugin_repository,
        start=start,
        trusted_sources=tuple(
            item
            for item in plugin_config.get("trusted_sources", [])
            if isinstance(item, str) and item
        )
        if isinstance(plugin_config.get("trusted_sources", []), list)
        else (),
    )
    plugin_service.enable_runtime_paths()
    activity_log_service = ActivityLogService(
        history_repository=history_repository,
        audit_repository=audit_repository,
    )
    panel_registry = PanelRegistry()
    panel_registry.register(
        PanelSpec(
            panel_type=WorkPanel.PANEL_TYPE,
            panel_id=WorkPanel.PANEL_ID,
            display_name="Work",
            factory=lambda container: WorkPanel(
                event_bus=container.event_bus,
                pty_manager=container.pty_manager,
                stream_router=container.stream_router,
                remote_filesystem_adapter=container.remote_filesystem_adapter,
                clipboard_service=container.clipboard_service,
            ),
        )
    )
    panel_registry.register(
        PanelSpec(
            panel_type=GitPanel.PANEL_TYPE,
            panel_id=GitPanel.PANEL_ID,
            display_name="Git",
            factory=lambda container: GitPanel(
                event_bus=container.event_bus,
                git_adapter=container.git_adapter,
            ),
        )
    )
    panel_registry.register(
        PanelSpec(
            panel_type=DockerPanel.PANEL_TYPE,
            panel_id=DockerPanel.PANEL_ID,
            display_name="Docker",
            factory=lambda container: DockerPanel(
                event_bus=container.event_bus,
                docker_adapter=container.docker_adapter,
            ),
        )
    )
    panel_registry.register(
        PanelSpec(
            panel_type=CronPanel.PANEL_TYPE,
            panel_id=CronPanel.PANEL_ID,
            display_name="Cron",
            factory=lambda container: CronPanel(
                event_bus=container.event_bus,
                cron_adapter=container.cron_adapter,
            ),
        )
    )
    panel_registry.register(
        PanelSpec(
            panel_type=DBPanel.PANEL_TYPE,
            panel_id=DBPanel.PANEL_ID,
            display_name="DB",
            factory=lambda container: DBPanel(
                event_bus=container.event_bus,
                database_adapter=container.database_adapter,
                datasource_service=container.data_source_service,
            ),
        )
    )
    panel_registry.register(
        PanelSpec(
            panel_type=CurlPanel.PANEL_TYPE,
            panel_id=CurlPanel.PANEL_ID,
            display_name="Curl",
            factory=lambda container: CurlPanel(
                event_bus=container.event_bus,
            ),
        )
    )
    panel_registry.register(
        PanelSpec(
            panel_type=LogsPanel.PANEL_TYPE,
            panel_id=LogsPanel.PANEL_ID,
            display_name="Logs",
            factory=lambda container: LogsPanel(
                event_bus=container.event_bus,
                activity_log_service=container.activity_log_service,
            ),
        )
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
        "layout.toggle_orientation",
        ToggleActiveLayoutOrientationHandler(),
    )
    command_dispatcher.register(
        "layout.grow",
        AdjustActiveLayoutRatioHandler(delta=0.1),
    )
    command_dispatcher.register(
        "layout.shrink",
        AdjustActiveLayoutRatioHandler(delta=-0.1),
    )
    command_dispatcher.register("panel.focus_next", FocusNextPanelHandler())
    command_dispatcher.register(
        "terminal.focus", FocusTerminalHandler(event_bus)
    )
    command_dispatcher.register(
        "terminal.restart", RestartTerminalHandler(pty_manager)
    )
    command_dispatcher.register("terminal.search", SearchTerminalHandler())
    command_dispatcher.register(
        "terminal.search_next",
        NavigateTerminalSearchHandler(direction="next"),
    )
    command_dispatcher.register(
        "terminal.search_prev",
        NavigateTerminalSearchHandler(direction="previous"),
    )
    command_dispatcher.register(
        "terminal.export", ExportTerminalBufferHandler()
    )
    command_dispatcher.register(
        "terminal.copy", CopyTerminalBufferHandler()
    )
    command_dispatcher.register(
        "terminal.copy_selection", CopyTerminalSelectionHandler()
    )
    command_dispatcher.register(
        "docker.restart", RestartDockerContainerHandler(docker_adapter)
    )
    command_dispatcher.register("docker.stop", StopDockerContainerHandler(docker_adapter))
    command_dispatcher.register("docker.remove", RemoveDockerContainerHandler(docker_adapter))
    command_dispatcher.register(
        "cron.enable",
        SetCronJobEnabledHandler(cron_adapter, enabled=True),
    )
    command_dispatcher.register(
        "cron.disable",
        SetCronJobEnabledHandler(cron_adapter, enabled=False),
    )
    command_dispatcher.register(
        "db.run_query", RunDatabaseQueryHandler(database_adapter, data_source_service)
    )
    command_dispatcher.register(
        "curl.send", SendHttpRequestHandler(http_adapter)
    )

    plugin_loader = PluginLoader()
    plugin_payload = dict(plugin_config)
    combined_plugins = plugin_payload.get("plugins", [])
    if not isinstance(combined_plugins, list):
        combined_plugins = []
    combined_plugins.extend(
        module_name for module_name in plugin_service.enabled_modules() if module_name not in combined_plugins
    )
    plugin_payload["plugins"] = combined_plugins
    plugin_loader.load_from_config(
        plugin_payload,
        context=PluginBootstrapContext(
            project_root=project_root,
            panel_registry=panel_registry,
            command_dispatcher=command_dispatcher,
            command_catalog=command_catalog_entries,
        ),
    )
    web_admin_service = WebAdminService(
        datasource_service=data_source_service,
        secret_service=secret_service,
        plugin_service=plugin_service,
        layout_service=layout_service,
        panel_registry=panel_registry,
        state_repository=web_admin_state_repository,
        command_catalog=tuple(command_catalog_entries),
        tunnel_manager=tunnel_manager,
        project_root=project_root,
    )

    return ApplicationContainer(
        project_root=project_root,
        command_catalog=tuple(command_catalog_entries),
        event_bus=event_bus,
        command_parser=command_parser,
        command_dispatcher=command_dispatcher,
        navigation_controller=navigation_controller,
        layout_service=layout_service,
        session_service=session_service,
        activity_log_service=activity_log_service,
        data_source_service=data_source_service,
        secret_service=secret_service,
        plugin_service=plugin_service,
        web_admin_service=web_admin_service,
        stream_router=stream_router,
        pty_manager=pty_manager,
        cron_adapter=cron_adapter,
        docker_adapter=docker_adapter,
        database_adapter=database_adapter,
        http_adapter=http_adapter,
        git_adapter=git_adapter,
        remote_filesystem_adapter=remote_filesystem_adapter,
        clipboard_service=clipboard_service,
        tunnel_manager=tunnel_manager,
        panel_registry=panel_registry,
        store=store,
    )
