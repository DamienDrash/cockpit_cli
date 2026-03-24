"""Application bootstrap and dependency wiring."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cockpit.application.dispatch.command_dispatcher import CommandDispatcher
from cockpit.application.dispatch.command_parser import CommandParser
from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.services.datasource_service import DataSourceService
from cockpit.application.services.component_watch_service import ComponentWatchService
from cockpit.application.services.escalation_policy_service import EscalationPolicyService
from cockpit.application.services.escalation_service import EscalationService
from cockpit.application.services.guard_policy_service import GuardPolicyService
from cockpit.application.handlers.curl_handlers import SendHttpRequestHandler
from cockpit.application.handlers.cron_handlers import SetCronJobEnabledHandler
from cockpit.application.handlers.db_handlers import RunDatabaseQueryHandler
from cockpit.application.handlers.docker_handlers import (
    RemoveDockerContainerHandler,
    RestartDockerContainerHandler,
    StopDockerContainerHandler,
)
from cockpit.application.handlers.escalation_handlers import (
    AcknowledgeEngagementHandler,
    HandoffEngagementHandler,
    RepageEngagementHandler,
)
from cockpit.application.services.incident_service import IncidentService
from cockpit.application.services.notification_policy_service import NotificationPolicyService
from cockpit.application.services.notification_service import NotificationService
from cockpit.application.handlers.layout_handlers import (
    AdjustActiveLayoutRatioHandler,
    ApplyDefaultLayoutHandler,
    FocusNextPanelHandler,
    ToggleActiveLayoutOrientationHandler,
)
from cockpit.application.services.operations_diagnostics_service import (
    OperationsDiagnosticsService,
)
from cockpit.application.services.oncall_resolution_service import OnCallResolutionService
from cockpit.application.services.oncall_service import OnCallService
from cockpit.application.services.recovery_policy_service import RecoveryPolicyService
from cockpit.application.services.suppression_service import SuppressionService
from cockpit.application.handlers.session_handlers import RestoreSessionHandler
from cockpit.application.services.self_healing_service import SelfHealingService
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
from cockpit.domain.events.notification_events import (
    NotificationDelivered,
    NotificationDeliveryFailed,
    NotificationQueued,
    NotificationSuppressed,
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
from cockpit.infrastructure.persistence.ops_repositories import (
    ComponentHealthRepository,
    ComponentWatchRepository,
    EngagementDeliveryLinkRepository,
    EngagementTimelineRepository,
    EscalationPolicyRepository,
    EscalationStepRepository,
    GuardDecisionRepository,
    IncidentRepository,
    IncidentEngagementRepository,
    NotificationChannelRepository,
    NotificationDeliveryRepository,
    NotificationRepository,
    NotificationRuleRepository,
    NotificationSuppressionRepository,
    OnCallScheduleRepository,
    OperationDiagnosticsRepository,
    OperatorPersonRepository,
    OperatorTeamRepository,
    OwnershipBindingRepository,
    RecoveryAttemptRepository,
    RotationRuleRepository,
    ScheduleOverrideRepository,
    TeamMembershipRepository,
)
from cockpit.infrastructure.notifications.ntfy_adapter import NtfyNotificationAdapter
from cockpit.infrastructure.notifications.slack_adapter import SlackNotificationAdapter
from cockpit.infrastructure.notifications.webhook_adapter import WebhookNotificationAdapter
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
from cockpit.runtime.health_monitor import RuntimeHealthMonitor
from cockpit.runtime.escalation_monitor import EscalationMonitor
from cockpit.runtime.stream_router import StreamRouter
from cockpit.runtime.task_supervisor import TaskSupervisor
from cockpit.shared.config import default_db_path, discover_project_root
from cockpit.shared.enums import NotificationChannelKind
from cockpit.ui.panels.curl_panel import CurlPanel
from cockpit.ui.panels.db_panel import DBPanel
from cockpit.ui.panels.git_panel import GitPanel
from cockpit.ui.panels.docker_panel import DockerPanel
from cockpit.ui.panels.cron_panel import CronPanel
from cockpit.ui.panels.logs_panel import LogsPanel
from cockpit.ui.panels.ops_panel import OpsPanel
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
    self_healing_service: SelfHealingService
    incident_service: IncidentService
    operations_diagnostics_service: OperationsDiagnosticsService
    notification_service: NotificationService
    notification_policy_service: NotificationPolicyService
    suppression_service: SuppressionService
    component_watch_service: ComponentWatchService
    guard_policy_service: GuardPolicyService
    oncall_service: OnCallService
    oncall_resolution_service: OnCallResolutionService
    escalation_policy_service: EscalationPolicyService
    escalation_service: EscalationService
    health_monitor: RuntimeHealthMonitor
    escalation_monitor: EscalationMonitor
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
    task_supervisor: TaskSupervisor
    panel_registry: PanelRegistry
    store: SQLiteStore

    def shutdown(self) -> None:
        self.health_monitor.stop()
        self.escalation_monitor.stop()
        self.pty_manager.shutdown()
        self.plugin_service.shutdown()
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
    component_health_repository = ComponentHealthRepository(store)
    incident_repository = IncidentRepository(store)
    recovery_attempt_repository = RecoveryAttemptRepository(store)
    guard_decision_repository = GuardDecisionRepository(store)
    operation_diagnostics_repository = OperationDiagnosticsRepository(store)
    notification_channel_repository = NotificationChannelRepository(store)
    notification_rule_repository = NotificationRuleRepository(store)
    notification_suppression_repository = NotificationSuppressionRepository(store)
    notification_repository = NotificationRepository(store)
    notification_delivery_repository = NotificationDeliveryRepository(store)
    component_watch_repository = ComponentWatchRepository(store)
    operator_person_repository = OperatorPersonRepository(store)
    operator_team_repository = OperatorTeamRepository(store)
    team_membership_repository = TeamMembershipRepository(store)
    ownership_binding_repository = OwnershipBindingRepository(store)
    schedule_repository = OnCallScheduleRepository(store)
    rotation_repository = RotationRuleRepository(store)
    override_repository = ScheduleOverrideRepository(store)
    escalation_policy_repository = EscalationPolicyRepository(store)
    escalation_step_repository = EscalationStepRepository(store)
    incident_engagement_repository = IncidentEngagementRepository(store)
    engagement_timeline_repository = EngagementTimelineRepository(store)
    engagement_delivery_link_repository = EngagementDeliveryLinkRepository(store)
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
    secret_service = SecretService(web_admin_state_repository, start=start)
    secret_resolver = SecretResolver(
        base_path=project_root,
        named_reference_lookup=secret_service.lookup_reference,
        vault_reference_lookup=secret_service.resolve_vault_reference,
    )
    tunnel_manager = SSHTunnelManager()
    clipboard_service = ClipboardService()
    pty_manager = PTYManager(
        event_bus=event_bus,
        shell_adapter=shell_adapter,
        stream_router=stream_router,
        task_supervisor=task_supervisor,
    )
    recovery_policy_service = RecoveryPolicyService()
    guard_policy_service = GuardPolicyService(guard_decision_repository)
    notification_policy_service = NotificationPolicyService(
        channel_repository=notification_channel_repository,
        rule_repository=notification_rule_repository,
    )
    escalation_policy_service = EscalationPolicyService(
        policy_repository=escalation_policy_repository,
        step_repository=escalation_step_repository,
    )
    suppression_service = SuppressionService(
        repository=notification_suppression_repository,
        event_bus=event_bus,
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
        allowed_permissions=tuple(
            item
            for item in plugin_config.get("allowed_permissions", [])
            if isinstance(item, str) and item
        )
        if isinstance(plugin_config.get("allowed_permissions", []), list)
        else (),
    )
    component_watch_service = ComponentWatchService(
        event_bus=event_bus,
        repository=component_watch_repository,
        datasource_service=data_source_service,
        docker_adapter=docker_adapter,
        operation_diagnostics_repository=operation_diagnostics_repository,
    )
    self_healing_service = SelfHealingService(
        event_bus=event_bus,
        recovery_policy_service=recovery_policy_service,
        component_health_repository=component_health_repository,
        incident_repository=incident_repository,
        recovery_attempt_repository=recovery_attempt_repository,
        pty_manager=pty_manager,
        tunnel_manager=tunnel_manager,
        task_supervisor=task_supervisor,
        plugin_service=plugin_service,
        component_watch_service=component_watch_service,
    )
    incident_service = IncidentService(
        event_bus=event_bus,
        incident_repository=incident_repository,
        recovery_attempt_repository=recovery_attempt_repository,
        component_health_repository=component_health_repository,
        self_healing_service=self_healing_service,
    )
    oncall_service = OnCallService(
        person_repository=operator_person_repository,
        team_repository=operator_team_repository,
        membership_repository=team_membership_repository,
        ownership_binding_repository=ownership_binding_repository,
        schedule_repository=schedule_repository,
        rotation_repository=rotation_repository,
        override_repository=override_repository,
        escalation_policy_repository=escalation_policy_repository,
    )
    oncall_resolution_service = OnCallResolutionService(
        person_repository=operator_person_repository,
        team_repository=operator_team_repository,
        ownership_binding_repository=ownership_binding_repository,
        schedule_repository=schedule_repository,
        rotation_repository=rotation_repository,
        override_repository=override_repository,
    )
    operations_diagnostics_service = OperationsDiagnosticsService(
        docker_adapter=docker_adapter,
        database_adapter=database_adapter,
        http_adapter=http_adapter,
        datasource_service=data_source_service,
        tunnel_manager=tunnel_manager,
        component_health_repository=component_health_repository,
        incident_repository=incident_repository,
        guard_decision_repository=guard_decision_repository,
        operation_diagnostics_repository=operation_diagnostics_repository,
    )
    notification_service = NotificationService(
        event_bus=event_bus,
        notification_repository=notification_repository,
        delivery_repository=notification_delivery_repository,
        notification_policy_service=notification_policy_service,
        suppression_service=suppression_service,
        secret_resolver=secret_resolver,
        operation_diagnostics_repository=operation_diagnostics_repository,
        adapters={
            NotificationChannelKind.WEBHOOK: WebhookNotificationAdapter(),
            NotificationChannelKind.SLACK: SlackNotificationAdapter(),
            NotificationChannelKind.NTFY: NtfyNotificationAdapter(),
        },
    )
    escalation_service = EscalationService(
        event_bus=event_bus,
        incident_repository=incident_repository,
        engagement_repository=incident_engagement_repository,
        timeline_repository=engagement_timeline_repository,
        delivery_link_repository=engagement_delivery_link_repository,
        oncall_resolution_service=oncall_resolution_service,
        escalation_policy_service=escalation_policy_service,
        notification_service=notification_service,
        operations_diagnostics_service=operations_diagnostics_service,
    )
    health_monitor = RuntimeHealthMonitor(
        event_bus=event_bus,
        task_supervisor=task_supervisor,
        tunnel_manager=tunnel_manager,
        self_healing_service=self_healing_service,
        plugin_service=plugin_service,
        component_watch_service=component_watch_service,
        notification_service=notification_service,
    )
    escalation_monitor = EscalationMonitor(
        escalation_service=escalation_service,
        task_supervisor=task_supervisor,
    )
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
    panel_registry.register(
        PanelSpec(
            panel_type=OpsPanel.PANEL_TYPE,
            panel_id=OpsPanel.PANEL_ID,
            display_name="Ops",
            factory=lambda container: OpsPanel(
                event_bus=container.event_bus,
                self_healing_service=container.self_healing_service,
                incident_service=container.incident_service,
                notification_service=container.notification_service,
                component_watch_service=container.component_watch_service,
                escalation_service=container.escalation_service,
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
        NotificationQueued,
        NotificationSuppressed,
        NotificationDelivered,
        NotificationDeliveryFailed,
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
        "docker.restart",
        RestartDockerContainerHandler(
            docker_adapter,
            guard_policy_service=guard_policy_service,
            operations_diagnostics_service=operations_diagnostics_service,
        ),
    )
    command_dispatcher.register(
        "docker.stop",
        StopDockerContainerHandler(
            docker_adapter,
            guard_policy_service=guard_policy_service,
            operations_diagnostics_service=operations_diagnostics_service,
        ),
    )
    command_dispatcher.register(
        "docker.remove",
        RemoveDockerContainerHandler(
            docker_adapter,
            guard_policy_service=guard_policy_service,
            operations_diagnostics_service=operations_diagnostics_service,
        ),
    )
    command_dispatcher.register(
        "cron.enable",
        SetCronJobEnabledHandler(cron_adapter, enabled=True),
    )
    command_dispatcher.register(
        "cron.disable",
        SetCronJobEnabledHandler(cron_adapter, enabled=False),
    )
    command_dispatcher.register(
        "db.run_query",
        RunDatabaseQueryHandler(
            database_adapter,
            data_source_service,
            guard_policy_service=guard_policy_service,
            operations_diagnostics_service=operations_diagnostics_service,
        ),
    )
    command_dispatcher.register(
        "curl.send",
        SendHttpRequestHandler(
            http_adapter,
            guard_policy_service=guard_policy_service,
            operations_diagnostics_service=operations_diagnostics_service,
        ),
    )
    command_dispatcher.register(
        "engagement.ack",
        AcknowledgeEngagementHandler(escalation_service),
    )
    command_dispatcher.register(
        "engagement.repage",
        RepageEngagementHandler(escalation_service),
    )
    command_dispatcher.register(
        "engagement.handoff",
        HandoffEngagementHandler(escalation_service),
    )

    plugin_loader = PluginLoader(allowed_module_prefixes=("cockpit.plugins.",))
    plugin_payload = dict(plugin_config)
    plugin_loader.load_from_config(
        plugin_payload,
        context=PluginBootstrapContext(
            project_root=project_root,
            panel_registry=panel_registry,
            command_dispatcher=command_dispatcher,
            command_catalog=command_catalog_entries,
        ),
    )
    plugin_service.register_managed_plugins(
        panel_registry=panel_registry,
        command_dispatcher=command_dispatcher,
        command_catalog=command_catalog_entries,
    )
    web_admin_service = WebAdminService(
        datasource_service=data_source_service,
        secret_service=secret_service,
        plugin_service=plugin_service,
        layout_service=layout_service,
        incident_service=incident_service,
        self_healing_service=self_healing_service,
        operations_diagnostics_service=operations_diagnostics_service,
        notification_service=notification_service,
        notification_policy_service=notification_policy_service,
        suppression_service=suppression_service,
        component_watch_service=component_watch_service,
        guard_policy_service=guard_policy_service,
        oncall_service=oncall_service,
        escalation_policy_service=escalation_policy_service,
        escalation_service=escalation_service,
        panel_registry=panel_registry,
        state_repository=web_admin_state_repository,
        command_catalog=tuple(command_catalog_entries),
        tunnel_manager=tunnel_manager,
        task_supervisor=task_supervisor,
        project_root=project_root,
    )
    health_monitor.start()
    escalation_monitor.start()

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
        self_healing_service=self_healing_service,
        incident_service=incident_service,
        operations_diagnostics_service=operations_diagnostics_service,
        notification_service=notification_service,
        notification_policy_service=notification_policy_service,
        suppression_service=suppression_service,
        component_watch_service=component_watch_service,
        guard_policy_service=guard_policy_service,
        oncall_service=oncall_service,
        oncall_resolution_service=oncall_resolution_service,
        escalation_policy_service=escalation_policy_service,
        escalation_service=escalation_service,
        health_monitor=health_monitor,
        escalation_monitor=escalation_monitor,
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
        task_supervisor=task_supervisor,
        panel_registry=panel_registry,
        store=store,
    )
