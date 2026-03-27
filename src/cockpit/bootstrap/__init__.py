from __future__ import annotations

from pathlib import Path
from typing import Any

from cockpit.bootstrap.container import ApplicationContainer
from cockpit.bootstrap.wire_admin import wire_admin as wire_admin_func
from cockpit.bootstrap.wire_core import wire_core
from cockpit.bootstrap.wire_datasources import wire_datasources
from cockpit.bootstrap.wire_notifications import wire_notifications
from cockpit.bootstrap.wire_ops import wire_ops
from cockpit.bootstrap.wire_plugins import wire_plugins
from cockpit.bootstrap.wire_ui import wire_ui
from cockpit.bootstrap.wire_workspace import wire_workspace
from cockpit.workspace.events import (
    LayoutApplied,
    SessionCreated,
    SessionRestored,
    SnapshotSaved,
    WorkspaceOpened,
)
from cockpit.notifications.events import (
    NotificationDelivered,
    NotificationDeliveryFailed,
    NotificationQueued,
    NotificationSuppressed,
)
from cockpit.core.events.runtime import (
    PTYStarted,
    PTYStartupFailed,
    TerminalExited,
)
from cockpit.infrastructure.filesystem.remote_filesystem_adapter import (
    RemoteFilesystemAdapter,
)
from cockpit.infrastructure.shell.local_shell_adapter import LocalShellAdapter
from cockpit.infrastructure.shell.shell_adapter_router import ShellAdapterRouter
from cockpit.datasources.adapters.ssh_command_runner import SSHCommandRunner
from cockpit.infrastructure.ssh.ssh_shell_adapter import SSHShellAdapter
from cockpit.runtime.pty_manager import PTYManager
from cockpit.core.config import discover_project_root
from cockpit.admin.web_admin_service import WebAdminService
from cockpit.plugins.loader import PluginBootstrapContext, PluginLoader
from cockpit.core.dispatch.terminal_handlers import (
    CopyTerminalBufferHandler,
    CopyTerminalSelectionHandler,
    ExportTerminalBufferHandler,
    FocusTerminalHandler,
    NavigateTerminalSearchHandler,
    RestartTerminalHandler,
    SearchTerminalHandler,
)


def build_container(
    *,
    start: Path | None = None,
    shell_adapter: ShellAdapterRouter | None = None,
    ssh_command_runner: SSHCommandRunner | None = None,
    cron_adapter: Any | None = None,
    docker_adapter: Any | None = None,
    database_adapter: Any | None = None,
    http_adapter: Any | None = None,
) -> ApplicationContainer:
    """Create the orchestrated application dependency graph."""
    project_root = discover_project_root(start)

    # 1. Core Platform
    core = wire_core(project_root, start)
    event_bus = core["event_bus"]
    command_parser = core["command_parser"]

    command_dispatcher = core["command_dispatcher"]
    store = core["store"]
    config_loader = core["config_loader"]
    task_supervisor = core["task_supervisor"]
    stream_router = core["stream_router"]
    clipboard_service = core["clipboard_service"]

    # 2. Infrastructure/Adapters
    ssh_command_runner = ssh_command_runner or SSHCommandRunner()
    shell_adapter = shell_adapter or ShellAdapterRouter(
        local_adapter=LocalShellAdapter(),
        ssh_adapter=SSHShellAdapter(),
    )
    remote_filesystem_adapter = RemoteFilesystemAdapter(ssh_command_runner)

    pty_manager = PTYManager(
        event_bus=event_bus,
        shell_adapter=shell_adapter,
        stream_router=stream_router,
        task_supervisor=task_supervisor,
    )

    # 3. Domain Contexts
    admin = wire_admin_func(store, start)
    secret_service = admin["secret_service"]
    web_admin_state_repository = admin["web_admin_state_repository"]

    workspace = wire_workspace(store, config_loader, event_bus, command_dispatcher)

    datasources = wire_datasources(
        store,
        config_loader,
        secret_service,
        project_root,
        command_dispatcher,
        ssh_command_runner,
    )

    notifications = wire_notifications(store, event_bus, datasources["secret_resolver"])

    plugins = wire_plugins(store, start, config_loader.load_plugins())

    ops = wire_ops(
        store,
        event_bus,
        command_dispatcher,
        project_root,
        pty_manager,
        datasources["tunnel_manager"],
        task_supervisor,
        plugins["plugin_service"],
        datasources["datasource_service"],
        notifications["notification_service"],
        docker_adapter or datasources["docker_adapter"],
        database_adapter or datasources["database_adapter"],
        http_adapter or datasources["http_adapter"],
    )

    # 4. Patch back circular-ish dependencies in datasources
    # The RunDatabaseQueryHandler needs guard_policy_service and diagnostics.
    from cockpit.datasources.handlers.db_handlers import RunDatabaseQueryHandler
    from cockpit.datasources.handlers.curl_handlers import SendHttpRequestHandler

    command_dispatcher.register(
        "db.run_query",
        RunDatabaseQueryHandler(
            database_adapter or datasources["database_adapter"],
            datasources["datasource_service"],
            guard_policy_service=ops["guard_policy_service"],
            operations_diagnostics_service=ops["operations_diagnostics_service"],
        ),
    )
    command_dispatcher.register(
        "curl.send",
        SendHttpRequestHandler(
            http_adapter or datasources["http_adapter"],
            guard_policy_service=ops["guard_policy_service"],
            operations_diagnostics_service=ops["operations_diagnostics_service"],
        ),
    )

    # 5. UI Wiring
    # We pass a 'bundle' or the eventual container
    # Since UI factory takes 'container', we need a shim
    ui = wire_ui(None)  # registry will be filled

    # 6. Terminal Handlers (Global)
    command_dispatcher.register("terminal.focus", FocusTerminalHandler(event_bus))
    command_dispatcher.register("terminal.restart", RestartTerminalHandler(pty_manager))
    command_dispatcher.register("terminal.search", SearchTerminalHandler())
    command_dispatcher.register(
        "terminal.search_next", NavigateTerminalSearchHandler(direction="next")
    )
    command_dispatcher.register(
        "terminal.search_prev", NavigateTerminalSearchHandler(direction="previous")
    )
    command_dispatcher.register("terminal.export", ExportTerminalBufferHandler())
    command_dispatcher.register("terminal.copy", CopyTerminalBufferHandler())
    command_dispatcher.register(
        "terminal.copy_selection", CopyTerminalSelectionHandler()
    )

    # 7. Final Integrations
    from cockpit.workspace.services.activity_log_service import ActivityLogService

    activity_log_service = ActivityLogService(
        history_repository=core["history_repository"],
        audit_repository=core["audit_repository"],
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
        NotificationQueued,
        NotificationSuppressed,
        NotificationDelivered,
        NotificationDeliveryFailed,
    ):
        event_bus.subscribe(event_type, activity_log_service.record_event)

    # Plugin Loader
    command_catalog_payload = config_loader.load_command_catalog()
    command_catalog_entries = [
        c
        for c in command_catalog_payload.get("commands", [])
        if isinstance(c, str) and c
    ]

    plugin_loader = PluginLoader(allowed_module_prefixes=("cockpit.plugins.",))
    plugin_loader.load_from_config(
        dict(config_loader.load_plugins()),
        context=PluginBootstrapContext(
            project_root=project_root,
            panel_registry=ui["panel_registry"],
            command_dispatcher=command_dispatcher,
            command_catalog=command_catalog_entries,
        ),
    )
    plugins["plugin_service"].register_managed_plugins(
        panel_registry=ui["panel_registry"],
        command_dispatcher=command_dispatcher,
        command_catalog=command_catalog_entries,
    )

    # Web Admin
    web_admin_service = WebAdminService(
        datasource_service=datasources["datasource_service"],
        secret_service=secret_service,
        plugin_service=plugins["plugin_service"],
        layout_service=workspace["layout_service"],
        incident_service=ops["incident_service"],
        self_healing_service=ops["self_healing_service"],
        operations_diagnostics_service=ops["operations_diagnostics_service"],
        notification_service=notifications["notification_service"],
        notification_policy_service=notifications["notification_policy_service"],
        suppression_service=notifications["suppression_service"],
        component_watch_service=ops["component_watch_service"],
        guard_policy_service=ops["guard_policy_service"],
        oncall_service=ops["oncall_service"],
        escalation_policy_service=ops["escalation_policy_service"],
        escalation_service=ops["escalation_service"],
        runbook_catalog_service=ops["runbook_catalog_service"],
        response_run_service=ops["response_run_service"],
        approval_service=ops["approval_service"],
        postincident_service=ops["postincident_service"],
        panel_registry=ui["panel_registry"],
        state_repository=web_admin_state_repository,
        command_catalog=tuple(command_catalog_entries),
        tunnel_manager=datasources["tunnel_manager"],
        task_supervisor=task_supervisor,
        project_root=project_root,
    )

    ops["health_monitor"].start()
    ops["escalation_monitor"].start()
    ops["response_monitor"].start()

    return ApplicationContainer(
        project_root=project_root,
        command_catalog=tuple(command_catalog_entries),
        event_bus=event_bus,
        command_parser=command_parser,
        command_dispatcher=command_dispatcher,
        navigation_controller=workspace["navigation_controller"],
        layout_service=workspace["layout_service"],
        session_service=workspace["session_service"],
        activity_log_service=activity_log_service,
        data_source_service=datasources["datasource_service"],
        secret_service=secret_service,
        plugin_service=plugins["plugin_service"],
        web_admin_service=web_admin_service,
        self_healing_service=ops["self_healing_service"],
        incident_service=ops["incident_service"],
        operations_diagnostics_service=ops["operations_diagnostics_service"],
        notification_service=notifications["notification_service"],
        notification_policy_service=notifications["notification_policy_service"],
        suppression_service=notifications["suppression_service"],
        component_watch_service=ops["component_watch_service"],
        guard_policy_service=ops["guard_policy_service"],
        oncall_service=ops["oncall_service"],
        oncall_resolution_service=ops["oncall_resolution_service"],
        escalation_policy_service=ops["escalation_policy_service"],
        escalation_service=ops["escalation_service"],
        runbook_catalog_service=ops["runbook_catalog_service"],
        approval_service=ops["approval_service"],
        response_run_service=ops["response_run_service"],
        postincident_service=ops["postincident_service"],
        health_monitor=ops["health_monitor"],
        escalation_monitor=ops["escalation_monitor"],
        response_monitor=ops["response_monitor"],
        stream_router=stream_router,
        pty_manager=pty_manager,
        cron_adapter=cron_adapter or datasources["cron_adapter"],
        docker_adapter=docker_adapter or datasources["docker_adapter"],
        database_adapter=database_adapter or datasources["database_adapter"],
        http_adapter=http_adapter or datasources["http_adapter"],
        git_adapter=datasources["git_adapter"],
        remote_filesystem_adapter=remote_filesystem_adapter,
        clipboard_service=clipboard_service,
        tunnel_manager=datasources["tunnel_manager"],
        task_supervisor=task_supervisor,
        panel_registry=ui["panel_registry"],
        store=store,
    )
