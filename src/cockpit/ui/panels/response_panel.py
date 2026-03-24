"""Live response runtime panel for Stage 4 incident response."""

from __future__ import annotations

from threading import get_ident

from textual import events
from textual.widgets import Static

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.services.postincident_service import PostIncidentService
from cockpit.application.services.response_run_service import ResponseRunService
from cockpit.domain.events.health_events import IncidentStatusChanged
from cockpit.domain.events.response_events import (
    ActionItemStatusChanged,
    ApprovalRequested,
    ApprovalResolved,
    CompensationStatusChanged,
    PostIncidentReviewStatusChanged,
    ResponseRunCreated,
    ResponseRunStatusChanged,
    ResponseStepStatusChanged,
)
from cockpit.domain.models.panel_state import PanelState
from cockpit.domain.events.runtime_events import PanelMounted, PanelStateChanged


class ResponsePanel(Static):
    """Render active response runs, approvals, and review summaries."""

    PANEL_ID = "response-panel"
    PANEL_TYPE = "response"
    can_focus = True

    _REFRESH_EVENTS = (
        ResponseRunCreated,
        ResponseRunStatusChanged,
        ResponseStepStatusChanged,
        ApprovalRequested,
        ApprovalResolved,
        CompensationStatusChanged,
        PostIncidentReviewStatusChanged,
        ActionItemStatusChanged,
        IncidentStatusChanged,
    )

    def __init__(
        self,
        *,
        event_bus: EventBus,
        response_run_service: ResponseRunService,
        postincident_service: PostIncidentService,
    ) -> None:
        super().__init__("", id=self.PANEL_ID, markup=False)
        self._event_bus = event_bus
        self._response_run_service = response_run_service
        self._postincident_service = postincident_service
        self._main_thread_id = get_ident()
        self._subscriptions_registered = False
        self._workspace_root = ""
        self._workspace_id: str | None = None
        self._session_id: str | None = None
        self._runs: list[dict[str, object]] = []
        self._selected_run_id: str | None = None
        self._selected_run_index = 0
        self._selected_approval_request_id: str | None = None
        self._selected_review_id: str | None = None

    def on_mount(self) -> None:
        self._main_thread_id = get_ident()
        if not self._subscriptions_registered:
            for event_type in self._REFRESH_EVENTS:
                self._event_bus.subscribe(event_type, self._on_refresh_event)
            self._subscriptions_registered = True
        self._event_bus.publish(
            PanelMounted(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE)
        )
        self.refresh_state()

    def initialize(self, context: dict[str, object]) -> None:
        self._workspace_root = str(context.get("workspace_root", ""))
        self._workspace_id = _optional_str(context.get("workspace_id"))
        self._session_id = _optional_str(context.get("session_id"))
        self._selected_run_id = _optional_str(context.get("selected_response_run_id"))
        self.refresh_state()

    def restore_state(self, snapshot: dict[str, object]) -> None:
        self._selected_run_id = _optional_str(snapshot.get("selected_response_run_id"))

    def snapshot_state(self) -> PanelState:
        return PanelState(
            panel_id=self.PANEL_ID,
            panel_type=self.PANEL_TYPE,
            snapshot={"selected_response_run_id": self._selected_run_id},
        )

    def suspend(self) -> None:
        """No runtime resources need suspension."""

    def resume(self) -> None:
        self.refresh_state()

    def dispose(self) -> None:
        """No runtime resources need disposal."""

    def command_context(self) -> dict[str, object]:
        selected = self._selected_run()
        detail = self._selected_run_detail()
        selected_step = None
        if detail is not None and detail.step_runs:
            selected_step = detail.step_runs[min(selected.current_step_index, len(detail.step_runs) - 1)] if selected is not None else None
        return {
            "panel_id": self.PANEL_ID,
            "workspace_id": self._workspace_id,
            "session_id": self._session_id,
            "workspace_root": self._workspace_root,
            "selected_response_run_id": self._selected_run_id,
            "selected_response_step_run_id": selected_step.id if selected_step is not None else None,
            "selected_approval_request_id": self._selected_approval_request_id,
            "selected_review_id": self._selected_review_id,
            "selected_incident_id": selected.incident_id if selected is not None else None,
        }

    def on_key(self, event: events.Key) -> None:
        if event.key == "r":
            self.refresh_state()
            event.stop()
            return
        if event.key in {"down", "j"}:
            self._move_selection(1)
            event.stop()
            return
        if event.key in {"up", "k"}:
            self._move_selection(-1)
            event.stop()

    def refresh_state(self) -> None:
        runs = self._response_run_service.list_active_runs(limit=8)
        previous_selected = self._selected_run_id
        self._runs = [item.to_dict() for item in runs]
        self._sync_selection(previous_selected)
        self._render_state()
        self._publish_panel_state()

    def _render_state(self) -> None:
        self.update(self._render_text())

    def _render_text(self) -> str:
        lines = [
            f"Workspace root: {self._workspace_root or '(none)'}",
            "",
            "Active response runs:",
        ]
        if not self._runs:
            lines.append("None.")
            return "\n".join(lines)
        for index, item in enumerate(self._runs):
            prefix = ">" if index == self._selected_run_index else " "
            lines.append(
                (
                    f"{prefix} {item.get('status', '')} "
                    f"{item.get('id', '')} "
                    f"incident={item.get('incident_id', '')} "
                    f"runbook={item.get('runbook_id', '')}:{item.get('runbook_version', '')}"
                )
            )
        detail = self._selected_run_detail()
        if detail is None:
            return "\n".join(lines)
        lines.extend(
            [
                "",
                f"Selected run: {detail.response_run.id}",
                f"Current step index: {detail.response_run.current_step_index}",
                f"Status: {detail.response_run.status.value}",
                f"Summary: {detail.response_run.summary or '(none)'}",
                "",
                "Pending approvals:",
            ]
        )
        pending_requests = [
            item["request"]
            for item in detail.approvals
            if isinstance(item, dict)
            and isinstance(item.get("request"), dict)
            and item["request"].get("status") == "pending"
        ]
        if not pending_requests:
            lines.append("None.")
        else:
            for item in pending_requests:
                marker = ">" if item.get("id") == self._selected_approval_request_id else " "
                lines.append(
                    f"{marker} {item.get('id', '')} approvers={item.get('required_approver_count', 0)} reason={item.get('reason', '')}"
                )
        lines.extend(["", "Step runs:"])
        for step_run in detail.step_runs:
            lines.append(
                f"- {step_run.step_key} status={step_run.status.value} attempts={step_run.attempt_count} summary={step_run.output_summary or ''}"
            )
        review = detail.review
        lines.extend(["", "Post-incident review:"])
        if review is None:
            lines.append("None.")
        else:
            self._selected_review_id = review.id
            lines.append(
                f"- {review.id} status={review.status.value} closure={review.closure_quality.value} summary={review.summary or ''}"
            )
        return "\n".join(lines)

    def _sync_selection(self, previous_selected: str | None) -> None:
        if not self._runs:
            self._selected_run_index = 0
            self._selected_run_id = None
            self._selected_approval_request_id = None
            self._selected_review_id = None
            return
        if previous_selected:
            for index, item in enumerate(self._runs):
                if item.get("id") == previous_selected:
                    self._selected_run_index = index
                    self._selected_run_id = previous_selected
                    break
            else:
                self._selected_run_index = 0
                self._selected_run_id = str(self._runs[0].get("id", ""))
        else:
            self._selected_run_index = min(self._selected_run_index, len(self._runs) - 1)
            self._selected_run_id = str(self._runs[self._selected_run_index].get("id", ""))
        detail = self._selected_run_detail()
        if detail is None:
            self._selected_approval_request_id = None
            self._selected_review_id = None
            return
        pending_requests = [
            item["request"]
            for item in detail.approvals
            if isinstance(item, dict)
            and isinstance(item.get("request"), dict)
            and item["request"].get("status") == "pending"
        ]
        self._selected_approval_request_id = (
            str(pending_requests[0].get("id", "")) if pending_requests else None
        )
        self._selected_review_id = detail.review.id if detail.review is not None else None

    def _move_selection(self, delta: int) -> None:
        if not self._runs:
            return
        self._selected_run_index = max(0, min(len(self._runs) - 1, self._selected_run_index + delta))
        self._selected_run_id = str(self._runs[self._selected_run_index].get("id", ""))
        self.refresh_state()

    def _selected_run(self):
        for item in self._response_run_service.list_active_runs(limit=8):
            if item.id == self._selected_run_id:
                return item
        return None

    def _selected_run_detail(self):
        if not self._selected_run_id:
            return None
        return self._response_run_service.get_response_detail(self._selected_run_id)

    def _on_refresh_event(self, _event: object) -> None:
        if not self.is_mounted:
            return
        if get_ident() == self._main_thread_id:
            self.refresh_state()
            return
        self.call_from_thread(self.refresh_state)

    def _publish_panel_state(self) -> None:
        self._event_bus.publish(
            PanelStateChanged(
                panel_id=self.PANEL_ID,
                panel_type=self.PANEL_TYPE,
                snapshot=self.snapshot_state().snapshot,
                config=self.snapshot_state().config,
            )
        )


def _optional_str(raw_value: object) -> str | None:
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    return value or None

