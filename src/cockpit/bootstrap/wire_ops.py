"""Ops context wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cockpit.core.dispatch.command_dispatcher import CommandDispatcher
from cockpit.core.dispatch.event_bus import EventBus
from cockpit.ops.handlers.escalation_handlers import (
    AcknowledgeEngagementHandler,
    HandoffEngagementHandler,
    RepageEngagementHandler,
)
from cockpit.ops.handlers.response_handlers import (
    AbortResponseRunHandler,
    CompensateResponseRunHandler,
    ExecuteResponseStepHandler,
    RetryResponseStepHandler,
    StartResponseRunHandler,
)
from cockpit.ops.services.approval_service import ApprovalService
from cockpit.ops.services.component_watch_service import ComponentWatchService
from cockpit.datasources.services.datasource_service import DataSourceService
from cockpit.ops.services.escalation_policy_service import (
    EscalationPolicyService,
)
from cockpit.ops.services.escalation_service import EscalationService
from cockpit.ops.services.guard_policy_service import GuardPolicyService
from cockpit.ops.services.incident_service import IncidentService
from cockpit.notifications.services.notification_service import NotificationService
from cockpit.ops.services.diagnostics_service import (
    OperationsDiagnosticsService,
)
from cockpit.ops.services.oncall_resolution_service import (
    OnCallResolutionService,
)
from cockpit.ops.services.oncall_service import OnCallService
from cockpit.ops.services.postincident_service import PostIncidentService
from cockpit.ops.services.recovery_policy_service import RecoveryPolicyService
from cockpit.ops.services.response_executor_service import (
    ResponseExecutorService,
)
from cockpit.ops.services.response_run_service import ResponseRunService
from cockpit.ops.services.runbook_catalog_service import RunbookCatalogService
from cockpit.ops.services.self_healing_service import SelfHealingService
from cockpit.datasources.adapters.database_adapter import DatabaseAdapter
from cockpit.infrastructure.docker.docker_adapter import DockerAdapter
from cockpit.infrastructure.http.http_adapter import HttpAdapter
from cockpit.ops.repositories import (
    ComponentHealthRepository,
    ApprovalDecisionRepository,
    ApprovalRequestRepository,
    ActionItemRepository,
    CompensationRunRepository,
    ComponentWatchRepository,
    EngagementDeliveryLinkRepository,
    EngagementTimelineRepository,
    EscalationPolicyRepository,
    EscalationStepRepository,
    GuardDecisionRepository,
    IncidentRepository,
    IncidentEngagementRepository,
    OnCallScheduleRepository,
    OperationDiagnosticsRepository,
    OperatorPersonRepository,
    OperatorTeamRepository,
    OwnershipBindingRepository,
    PostIncidentReviewRepository,
    RecoveryAttemptRepository,
    ResponseArtifactRepository,
    ResponseRunRepository,
    ResponseStepRunRepository,
    ResponseTimelineRepository,
    RotationRuleRepository,
    ReviewFindingRepository,
    RunbookCatalogRepository,
    ScheduleOverrideRepository,
    TeamMembershipRepository,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.datasources.adapters.tunnel_manager import SSHTunnelManager
from cockpit.runtime.pty_manager import PTYManager
from cockpit.runtime.task_supervisor import TaskSupervisor
from cockpit.ops.runtime.health_monitor import RuntimeHealthMonitor
from cockpit.ops.runtime.escalation_monitor import EscalationMonitor
from cockpit.ops.runtime.response_monitor import ResponseMonitor
from cockpit.plugins.services.plugin_service import PluginService


def wire_ops(
    store: SQLiteStore,
    event_bus: EventBus,
    command_dispatcher: CommandDispatcher,
    project_root: Path,
    pty_manager: PTYManager,
    tunnel_manager: SSHTunnelManager,
    task_supervisor: TaskSupervisor,
    plugin_service: PluginService,
    datasource_service: DataSourceService,
    notification_service: NotificationService,
    docker_adapter: DockerAdapter,
    database_adapter: DatabaseAdapter,
    http_adapter: HttpAdapter,
) -> dict[str, Any]:
    """Wire operations context components."""
    # Repositories
    component_health_repository = ComponentHealthRepository(store)
    incident_repository = IncidentRepository(store)
    recovery_attempt_repository = RecoveryAttemptRepository(store)
    guard_decision_repository = GuardDecisionRepository(store)
    operation_diagnostics_repository = OperationDiagnosticsRepository(store)
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
    runbook_catalog_repository = RunbookCatalogRepository(store)
    response_run_repository = ResponseRunRepository(store)
    response_step_run_repository = ResponseStepRunRepository(store)
    approval_request_repository = ApprovalRequestRepository(store)
    approval_decision_repository = ApprovalDecisionRepository(store)
    response_artifact_repository = ResponseArtifactRepository(store)
    compensation_run_repository = CompensationRunRepository(store)
    response_timeline_repository = ResponseTimelineRepository(store)
    postincident_review_repository = PostIncidentReviewRepository(store)
    review_finding_repository = ReviewFindingRepository(store)
    action_item_repository = ActionItemRepository(store)

    # Services
    recovery_policy_service = RecoveryPolicyService()
    guard_policy_service = GuardPolicyService(guard_decision_repository)
    escalation_policy_service = EscalationPolicyService(
        policy_repository=escalation_policy_repository,
        step_repository=escalation_step_repository,
    )

    component_watch_service = ComponentWatchService(
        event_bus=event_bus,
        repository=component_watch_repository,
        datasource_service=datasource_service,
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
    runbook_catalog_service = RunbookCatalogService(
        runbook_catalog_repository,
        project_root=project_root,
    )
    operations_diagnostics_service = OperationsDiagnosticsService(
        docker_adapter=docker_adapter,
        database_adapter=database_adapter,
        http_adapter=http_adapter,
        datasource_service=datasource_service,
        tunnel_manager=tunnel_manager,
        component_health_repository=component_health_repository,
        incident_repository=incident_repository,
        guard_decision_repository=guard_decision_repository,
        operation_diagnostics_repository=operation_diagnostics_repository,
    )
    approval_service = ApprovalService(
        event_bus=event_bus,
        request_repository=approval_request_repository,
        decision_repository=approval_decision_repository,
        notification_service=notification_service,
    )
    response_executor_service = ResponseExecutorService(
        guard_policy_service=guard_policy_service,
        operations_diagnostics_service=operations_diagnostics_service,
        http_adapter=http_adapter,
        docker_adapter=docker_adapter,
        database_adapter=database_adapter,
        datasource_service=datasource_service,
    )
    postincident_service = PostIncidentService(
        event_bus=event_bus,
        review_repository=postincident_review_repository,
        finding_repository=review_finding_repository,
        action_item_repository=action_item_repository,
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
    response_run_service = ResponseRunService(
        event_bus=event_bus,
        incident_repository=incident_repository,
        component_health_repository=component_health_repository,
        response_run_repository=response_run_repository,
        step_run_repository=response_step_run_repository,
        approval_request_repository=approval_request_repository,
        artifact_repository=response_artifact_repository,
        compensation_repository=compensation_run_repository,
        timeline_repository=response_timeline_repository,
        runbook_catalog_service=runbook_catalog_service,
        response_executor_service=response_executor_service,
        approval_service=approval_service,
        postincident_service=postincident_service,
    )

    # Monitors
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
    response_monitor = ResponseMonitor(
        response_run_service=response_run_service,
        task_supervisor=task_supervisor,
    )

    runbook_catalog_service.reload()

    # Handlers
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
    command_dispatcher.register(
        "response.start",
        StartResponseRunHandler(response_run_service),
    )
    command_dispatcher.register(
        "response.execute",
        ExecuteResponseStepHandler(response_run_service),
    )
    command_dispatcher.register(
        "response.retry",
        RetryResponseStepHandler(response_run_service),
    )
    command_dispatcher.register(
        "response.abort",
        AbortResponseRunHandler(response_run_service),
    )
    command_dispatcher.register(
        "response.compensate",
        CompensateResponseRunHandler(response_run_service),
    )

    return {
        "self_healing_service": self_healing_service,
        "incident_service": incident_service,
        "oncall_service": oncall_service,
        "oncall_resolution_service": oncall_resolution_service,
        "runbook_catalog_service": runbook_catalog_service,
        "operations_diagnostics_service": operations_diagnostics_service,
        "approval_service": approval_service,
        "postincident_service": postincident_service,
        "escalation_service": escalation_service,
        "response_run_service": response_run_service,
        "health_monitor": health_monitor,
        "escalation_monitor": escalation_monitor,
        "response_monitor": response_monitor,
        "component_watch_service": component_watch_service,
        "guard_policy_service": guard_policy_service,
        "escalation_policy_service": escalation_policy_service,
        "operation_diagnostics_repository": operation_diagnostics_repository,
    }
