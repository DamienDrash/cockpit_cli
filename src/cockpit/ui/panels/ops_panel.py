"""Compact operator summary panel for operator runtime state."""

from __future__ import annotations

from threading import get_ident

from textual import events
from textual.widgets import Static

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.services.component_watch_service import ComponentWatchService
from cockpit.application.services.escalation_service import EscalationService
from cockpit.application.services.incident_service import IncidentService
from cockpit.application.services.notification_service import NotificationService
from cockpit.application.services.self_healing_service import SelfHealingService
from cockpit.domain.events.base import BaseEvent
from cockpit.domain.events.escalation_events import (
    EngagementAcknowledged,
    EngagementEscalated,
    EngagementExhausted,
    EngagementHandedOff,
    EngagementPaged,
    EngagementStatusChanged,
    IncidentEngagementCreated,
)
from cockpit.domain.events.health_events import (
    ComponentHealthChanged,
    ComponentQuarantined,
    ComponentWatchObserved,
    IncidentOpened,
    IncidentStatusChanged,
)
from cockpit.domain.events.notification_events import (
    NotificationDelivered,
    NotificationDeliveryFailed,
    NotificationQueued,
    NotificationStatusChanged,
        NotificationSuppressed,
    )
from cockpit.domain.events.runtime_events import PanelMounted, PanelStateChanged
from cockpit.domain.models.panel_state import PanelState
from cockpit.shared.enums import IncidentStatus


class OpsPanel(Static):
    """Render a concise operator-native summary for incidents and delivery state."""

    PANEL_ID = "ops-panel"
    PANEL_TYPE = "ops"
    can_focus = True

    _REFRESH_EVENTS = (
        ComponentHealthChanged,
        ComponentQuarantined,
        ComponentWatchObserved,
        IncidentOpened,
        IncidentStatusChanged,
        NotificationQueued,
        NotificationSuppressed,
        NotificationDelivered,
        NotificationDeliveryFailed,
        NotificationStatusChanged,
        IncidentEngagementCreated,
        EngagementStatusChanged,
        EngagementPaged,
        EngagementAcknowledged,
        EngagementHandedOff,
        EngagementEscalated,
        EngagementExhausted,
    )

    def __init__(
        self,
        *,
        event_bus: EventBus,
        self_healing_service: SelfHealingService,
        incident_service: IncidentService,
        notification_service: NotificationService,
        component_watch_service: ComponentWatchService,
        escalation_service: EscalationService,
    ) -> None:
        super().__init__("", id=self.PANEL_ID, markup=False)
        self._event_bus = event_bus
        self._self_healing_service = self_healing_service
        self._incident_service = incident_service
        self._notification_service = notification_service
        self._component_watch_service = component_watch_service
        self._escalation_service = escalation_service
        self._main_thread_id = get_ident()
        self._subscriptions_registered = False
        self._workspace_name = "No workspace"
        self._workspace_root = ""
        self._workspace_id: str | None = None
        self._session_id: str | None = None
        self._health: dict[str, int] = {}
        self._incidents: list[dict[str, object]] = []
        self._quarantined: list[dict[str, object]] = []
        self._engagements: list[dict[str, object]] = []
        self._notification_summary: dict[str, object] = {}
        self._unhealthy_watches: list[dict[str, object]] = []
        self._selected_engagement_id: str | None = None
        self._selected_engagement_index = 0

    def on_mount(self) -> None:
        self._main_thread_id = get_ident()
        if not self._subscriptions_registered:
            for event_type in self._REFRESH_EVENTS:
                self._event_bus.subscribe(event_type, self._on_refresh_event)
            self._subscriptions_registered = True
        self._event_bus.publish(
            PanelMounted(
                panel_id=self.PANEL_ID,
                panel_type=self.PANEL_TYPE,
            )
        )
        self.refresh_summary()

    def initialize(self, context: dict[str, object]) -> None:
        self._workspace_name = str(context.get("workspace_name", "Workspace"))
        self._workspace_root = str(context.get("workspace_root", ""))
        self._workspace_id = self._optional_str(context.get("workspace_id"))
        self._session_id = self._optional_str(context.get("session_id"))
        self._selected_engagement_id = self._optional_str(context.get("selected_engagement_id"))
        self.refresh_summary()

    def restore_state(self, snapshot: dict[str, object]) -> None:
        self._selected_engagement_id = self._optional_str(snapshot.get("selected_engagement_id"))

    def snapshot_state(self) -> PanelState:
        return PanelState(
            panel_id=self.PANEL_ID,
            panel_type=self.PANEL_TYPE,
            snapshot={
                "selected_engagement_id": self._selected_engagement_id,
            },
        )

    def suspend(self) -> None:
        """No runtime resources need suspension."""

    def resume(self) -> None:
        self.refresh_summary()

    def dispose(self) -> None:
        """No runtime resources need disposal."""

    def command_context(self) -> dict[str, object]:
        selected = self._selected_engagement()
        return {
            "panel_id": self.PANEL_ID,
            "workspace_id": self._workspace_id,
            "session_id": self._session_id,
            "workspace_root": self._workspace_root,
            "selected_engagement_id": self._selected_engagement_id,
            "selected_incident_id": selected.get("incident_id") if isinstance(selected, dict) else None,
            "selected_engagement_status": selected.get("status") if isinstance(selected, dict) else None,
        }

    def on_key(self, event: events.Key) -> None:
        if event.key == "r":
            self.refresh_summary()
            event.stop()
            return
        if event.key in {"down", "j"}:
            self._move_selection(1)
            event.stop()
            return
        if event.key in {"up", "k"}:
            self._move_selection(-1)
            event.stop()

    def refresh_summary(self) -> None:
        self._health = self._self_healing_service.health_summary().to_dict()
        self._incidents = [
            incident.to_dict()
            for incident in self._incident_service.list_incidents(
                limit=6,
                statuses=(
                    IncidentStatus.OPEN,
                    IncidentStatus.ACKNOWLEDGED,
                    IncidentStatus.RECOVERING,
                    IncidentStatus.QUARANTINED,
                ),
            )
        ]
        self._quarantined = [
            state.to_dict()
            for state in self._self_healing_service.list_quarantined()[:6]
        ]
        previous_selected = self._selected_engagement_id
        self._engagements = [
            engagement.to_dict()
            for engagement in self._escalation_service.list_active_engagements(limit=8)
        ]
        self._sync_engagement_selection(previous_selected)
        self._notification_summary = self._notification_service.summary()
        self._unhealthy_watches = [
            state.to_dict()
            for state in self._component_watch_service.list_states()
            if state.last_outcome.value != "success"
        ][:6]
        self._render_state()
        self._publish_panel_state()

    def _render_state(self) -> None:
        self.update(self._render_text())

    def _render_text(self) -> str:
        counts = self._notification_summary.get("counts", {})
        failed_deliveries = self._notification_summary.get("recent_failures", [])
        recent_notifications = self._notification_summary.get("recent", [])
        lines = [
            f"Workspace: {self._workspace_name}",
            f"Root: {self._workspace_root or '(none)'}",
            "",
            "Health:",
            (
                "healthy={healthy} degraded={degraded} recovering={recovering} "
                "failed={failed} quarantined={quarantined}"
            ).format(
                healthy=self._health.get("healthy", 0),
                degraded=self._health.get("degraded", 0),
                recovering=self._health.get("recovering", 0),
                failed=self._health.get("failed", 0),
                quarantined=self._health.get("quarantined", 0),
            ),
            "",
            "Active incidents:",
        ]
        if not self._incidents:
            lines.append("No active incidents.")
        else:
            for incident in self._incidents:
                lines.append(
                    f"- {incident.get('severity', 'info')} {incident.get('component_id', '')}: "
                    f"{incident.get('summary', '')}"
                )
        lines.extend(["", "Quarantined components:"])
        if not self._quarantined:
            lines.append("None.")
        else:
            for item in self._quarantined:
                lines.append(
                    f"- {item.get('component_id', '')}: {item.get('quarantine_reason') or item.get('status', '')}"
                )
        lines.extend(["", "Active engagements:"])
        if not self._engagements:
            lines.append("None.")
        else:
            for index, engagement in enumerate(self._engagements):
                prefix = ">" if index == self._selected_engagement_index else " "
                lines.append(
                    (
                        f"{prefix} {engagement.get('status', '')} "
                        f"{engagement.get('id', '')} "
                        f"incident={engagement.get('incident_id', '')} "
                        f"step={engagement.get('current_step_index', 0)} "
                        f"target={engagement.get('current_target_ref', '')}"
                    )
                )
                next_action = engagement.get("next_action_at") or engagement.get("ack_deadline_at")
                if next_action:
                    lines.append(f"  next={next_action}")
        lines.extend(
            [
                "",
                "Notifications:",
                "queued={queued} delivering={delivering} delivered={delivered} "
                "suppressed={suppressed} failed={failed}".format(
                    queued=counts.get("queued", 0),
                    delivering=counts.get("delivering", 0),
                    delivered=counts.get("delivered", 0),
                    suppressed=counts.get("suppressed", 0),
                    failed=counts.get("failed", 0),
                ),
                "",
                "Failed deliveries:",
            ]
        )
        if not failed_deliveries:
            lines.append("None.")
        else:
            for item in failed_deliveries[:5]:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"- {item.get('channel_id', '')} attempt={item.get('attempt_number', '')}: "
                    f"{item.get('error_message') or item.get('status', '')}"
                )
        lines.extend(["", "Unhealthy watches:"])
        if not self._unhealthy_watches:
            lines.append("None.")
        else:
            for watch in self._unhealthy_watches:
                lines.append(
                    f"- {watch.get('component_id', '')}: {watch.get('last_status', '')}"
                )
        lines.extend(["", "Recent notifications:"])
        if not recent_notifications:
            lines.append("No notifications recorded.")
        else:
            for item in recent_notifications[:5]:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"- {item.get('status', '')} {item.get('title', '')}: {item.get('summary', '')}"
                )
        lines.extend(
            [
                "",
                "Keys: r refresh, j/down next engagement, k/up previous engagement.",
            ]
        )
        return "\n".join(lines)

    def _publish_panel_state(self) -> None:
        state = self.snapshot_state()
        self._event_bus.publish(
            PanelStateChanged(
                panel_id=self.PANEL_ID,
                panel_type=self.PANEL_TYPE,
                snapshot=state.snapshot,
                config=state.config,
            )
        )

    def _on_refresh_event(self, _event: BaseEvent) -> None:
        if not self.is_attached or not self.is_mounted:
            return
        if get_ident() != self._main_thread_id:
            self.app.call_from_thread(self.refresh_summary)
            return
        self.refresh_summary()

    def _move_selection(self, delta: int) -> None:
        if not self._engagements:
            return
        self._selected_engagement_index = (self._selected_engagement_index + delta) % len(
            self._engagements
        )
        self._selected_engagement_id = self._optional_str(
            self._engagements[self._selected_engagement_index].get("id")
        )
        self._render_state()
        self._publish_panel_state()

    def _sync_engagement_selection(self, previous_selected: str | None) -> None:
        if not self._engagements:
            self._selected_engagement_id = None
            self._selected_engagement_index = 0
            return
        selected_id = previous_selected or self._selected_engagement_id
        if isinstance(selected_id, str):
            for index, engagement in enumerate(self._engagements):
                if engagement.get("id") == selected_id:
                    self._selected_engagement_index = index
                    self._selected_engagement_id = selected_id
                    return
        self._selected_engagement_index = 0
        self._selected_engagement_id = self._optional_str(self._engagements[0].get("id"))

    def _selected_engagement(self) -> dict[str, object] | None:
        if not self._engagements:
            return None
        if 0 <= self._selected_engagement_index < len(self._engagements):
            return self._engagements[self._selected_engagement_index]
        return None

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return value if isinstance(value, str) else None
