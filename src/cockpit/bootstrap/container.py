"""Application container dataclass."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cockpit.core.dispatch.command_dispatcher import CommandDispatcher
from cockpit.core.dispatch.command_parser import CommandParser
from cockpit.core.dispatch.event_bus import EventBus
from cockpit.datasources.services.datasource_service import DataSourceService
from cockpit.ops.services.approval_service import ApprovalService
from cockpit.ops.services.component_watch_service import ComponentWatchService
from cockpit.ops.services.escalation_policy_service import (
    EscalationPolicyService,
)
from cockpit.ops.services.escalation_service import EscalationService
from cockpit.ops.services.guard_policy_service import GuardPolicyService
from cockpit.ops.services.incident_service import IncidentService
from cockpit.notifications.services.policy_service import (
    NotificationPolicyService,
)
from cockpit.notifications.services.notification_service import NotificationService
from cockpit.ops.services.diagnostics_service import (
    OperationsDiagnosticsService,
)
from cockpit.ops.services.oncall_resolution_service import (
    OnCallResolutionService,
)
from cockpit.ops.services.oncall_service import OnCallService
from cockpit.ops.services.postincident_service import PostIncidentService
from cockpit.ops.services.response_run_service import ResponseRunService
from cockpit.ops.services.runbook_catalog_service import RunbookCatalogService
from cockpit.notifications.services.suppression_service import SuppressionService
from cockpit.ops.services.self_healing_service import SelfHealingService
from cockpit.workspace.services.activity_log_service import ActivityLogService
from cockpit.workspace.services.layout_service import LayoutService
from cockpit.workspace.services.navigation_controller import NavigationController
from cockpit.plugins.services.plugin_service import PluginService
from cockpit.datasources.services.secret_service import SecretService
from cockpit.workspace.services.session_service import SessionService
from cockpit.admin.web_admin_service import WebAdminService
from cockpit.infrastructure.cron.cron_adapter import CronAdapter
from cockpit.datasources.adapters.database_adapter import DatabaseAdapter
from cockpit.infrastructure.docker.docker_adapter import DockerAdapter
from cockpit.infrastructure.filesystem.remote_filesystem_adapter import (
    RemoteFilesystemAdapter,
)
from cockpit.infrastructure.git.git_adapter import GitAdapter
from cockpit.infrastructure.http.http_adapter import HttpAdapter
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.datasources.adapters.tunnel_manager import SSHTunnelManager
from cockpit.infrastructure.system.clipboard import ClipboardService
from cockpit.runtime.pty_manager import PTYManager
from cockpit.ops.runtime.health_monitor import RuntimeHealthMonitor
from cockpit.ops.runtime.escalation_monitor import EscalationMonitor
from cockpit.ops.runtime.response_monitor import ResponseMonitor
from cockpit.runtime.stream_router import StreamRouter
from cockpit.runtime.task_supervisor import TaskSupervisor
from cockpit.ui.panels.registry import PanelRegistry


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
    runbook_catalog_service: RunbookCatalogService
    approval_service: ApprovalService
    response_run_service: ResponseRunService
    postincident_service: PostIncidentService
    health_monitor: RuntimeHealthMonitor
    escalation_monitor: EscalationMonitor
    response_monitor: ResponseMonitor
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
        self.response_monitor.stop()
        self.pty_manager.shutdown()
        self.plugin_service.shutdown()
        self.tunnel_manager.shutdown()
        self.store.close()
