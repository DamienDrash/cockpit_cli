"""Layout-related handlers."""

from __future__ import annotations

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.handlers.base import CommandContextError, DispatchResult
from cockpit.domain.commands.command import Command
from cockpit.domain.events.domain_events import LayoutApplied


class ApplyDefaultLayoutHandler:
    """Reset focus to the default tab order of the active layout."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    def __call__(self, command: Command) -> DispatchResult:
        available_tab_ids = command.context.get("available_tab_ids")
        if not isinstance(available_tab_ids, list):
            raise CommandContextError("No active layout is available to apply.")
        ordered_tab_ids = [
            tab_id for tab_id in available_tab_ids if isinstance(tab_id, str) and tab_id
        ]
        if not ordered_tab_ids:
            raise CommandContextError("The active layout does not expose any tabs.")
        active_tab_id = ordered_tab_ids[0]
        session_id = command.context.get("session_id")
        layout_id = command.context.get("layout_id")
        self._event_bus.publish(
            LayoutApplied(
                layout_id=layout_id if isinstance(layout_id, str) and layout_id else "default",
                session_id=session_id if isinstance(session_id, str) else None,
            )
        )
        return DispatchResult(
            success=True,
            message=f"Applied default layout: {active_tab_id}",
            data={"active_tab_id": active_tab_id},
        )
