"""UI context wiring."""

from __future__ import annotations

from typing import Any

from cockpit.ui.panels.curl_panel import CurlPanel
from cockpit.ui.panels.db_panel import DBPanel
from cockpit.ui.panels.git_panel import GitPanel
from cockpit.ui.panels.docker_panel import DockerPanel
from cockpit.ui.panels.cron_panel import CronPanel
from cockpit.ui.panels.logs_panel import LogsPanel
from cockpit.ui.panels.ops_panel import OpsPanel
from cockpit.ui.panels.response_panel import ResponsePanel
from cockpit.ui.panels.registry import PanelRegistry, PanelSpec
from cockpit.ui.panels.work_panel import WorkPanel


def wire_ui(container: Any) -> dict[str, Any]:
    """Wire UI component registry."""
    panel_registry = PanelRegistry()

    panel_registry.register(
        PanelSpec(
            panel_type=WorkPanel.PANEL_TYPE,
            panel_id=WorkPanel.PANEL_ID,
            display_name="Work",
            factory=lambda c: WorkPanel(
                event_bus=c.event_bus,
                pty_manager=c.pty_manager,
                stream_router=c.stream_router,
                remote_filesystem_adapter=c.remote_filesystem_adapter,
                clipboard_service=c.clipboard_service,
            ),
        )
    )
    panel_registry.register(
        PanelSpec(
            panel_type=GitPanel.PANEL_TYPE,
            panel_id=GitPanel.PANEL_ID,
            display_name="Git",
            factory=lambda c: GitPanel(
                event_bus=c.event_bus,
                git_adapter=c.git_adapter,
            ),
        )
    )
    panel_registry.register(
        PanelSpec(
            panel_type=DockerPanel.PANEL_TYPE,
            panel_id=DockerPanel.PANEL_ID,
            display_name="Docker",
            factory=lambda c: DockerPanel(
                event_bus=c.event_bus,
                docker_adapter=c.docker_adapter,
            ),
        )
    )
    panel_registry.register(
        PanelSpec(
            panel_type=CronPanel.PANEL_TYPE,
            panel_id=CronPanel.PANEL_ID,
            display_name="Cron",
            factory=lambda c: CronPanel(
                event_bus=c.event_bus,
                cron_adapter=c.cron_adapter,
            ),
        )
    )
    panel_registry.register(
        PanelSpec(
            panel_type=DBPanel.PANEL_TYPE,
            panel_id=DBPanel.PANEL_ID,
            display_name="DB",
            factory=lambda c: DBPanel(
                event_bus=c.event_bus,
                database_adapter=c.database_adapter,
                datasource_service=c.data_source_service,
            ),
        )
    )
    panel_registry.register(
        PanelSpec(
            panel_type=CurlPanel.PANEL_TYPE,
            panel_id=CurlPanel.PANEL_ID,
            display_name="Curl",
            factory=lambda c: CurlPanel(
                event_bus=c.event_bus,
            ),
        )
    )
    panel_registry.register(
        PanelSpec(
            panel_type=LogsPanel.PANEL_TYPE,
            panel_id=LogsPanel.PANEL_ID,
            display_name="Logs",
            factory=lambda c: LogsPanel(
                event_bus=c.event_bus,
                activity_log_service=c.activity_log_service,
            ),
        )
    )
    panel_registry.register(
        PanelSpec(
            panel_type=OpsPanel.PANEL_TYPE,
            panel_id=OpsPanel.PANEL_ID,
            display_name="Ops",
            factory=lambda c: OpsPanel(
                event_bus=c.event_bus,
                self_healing_service=c.self_healing_service,
                incident_service=c.incident_service,
                notification_service=c.notification_service,
                component_watch_service=c.component_watch_service,
                escalation_service=c.escalation_service,
            ),
        )
    )
    panel_registry.register(
        PanelSpec(
            panel_type=ResponsePanel.PANEL_TYPE,
            panel_id=ResponsePanel.PANEL_ID,
            display_name="Response",
            factory=lambda c: ResponsePanel(
                event_bus=c.event_bus,
                response_run_service=c.response_run_service,
                postincident_service=c.postincident_service,
            ),
        )
    )

    return {
        "panel_registry": panel_registry,
    }
