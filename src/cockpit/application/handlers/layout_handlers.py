"""Layout-related handlers."""

from __future__ import annotations

import copy

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


class ToggleActiveLayoutOrientationHandler:
    """Toggle the root split orientation for the active tab."""

    def __call__(self, command: Command) -> DispatchResult:
        tabs, active_tab = _tabs_context(command)
        active_split = _active_root_split(tabs, active_tab)
        current = str(active_split.get("orientation", "vertical"))
        active_split["orientation"] = "horizontal" if current == "vertical" else "vertical"
        return DispatchResult(
            success=True,
            message=f"Toggled {active_tab} layout to {active_split['orientation']}.",
            data={"tabs": tabs, "active_tab_id": active_tab},
        )


class AdjustActiveLayoutRatioHandler:
    """Grow or shrink the root split ratio for the active tab."""

    def __init__(self, *, delta: float) -> None:
        self._delta = delta

    def __call__(self, command: Command) -> DispatchResult:
        tabs, active_tab = _tabs_context(command)
        active_split = _active_root_split(tabs, active_tab)
        current_ratio = active_split.get("ratio", 0.5)
        try:
            current = float(current_ratio)
        except (TypeError, ValueError):
            current = 0.5
        next_ratio = max(0.2, min(0.8, round(current + self._delta, 2)))
        active_split["ratio"] = next_ratio
        return DispatchResult(
            success=True,
            message=f"Adjusted {active_tab} split ratio to {next_ratio:.2f}.",
            data={"tabs": tabs, "active_tab_id": active_tab},
        )


class FocusNextPanelHandler:
    """Cycle focus across visible panels in the active tab."""

    def __call__(self, command: Command) -> DispatchResult:
        visible_panel_ids = command.context.get("visible_panel_ids")
        if not isinstance(visible_panel_ids, list):
            raise CommandContextError("No visible panels are available.")
        ordered_ids = [panel_id for panel_id in visible_panel_ids if isinstance(panel_id, str)]
        if not ordered_ids:
            raise CommandContextError("No visible panels are available.")
        focused_panel_id = command.context.get("focused_panel_id")
        if focused_panel_id in ordered_ids:
            next_index = (ordered_ids.index(focused_panel_id) + 1) % len(ordered_ids)
        else:
            next_index = 0
        next_panel_id = ordered_ids[next_index]
        return DispatchResult(
            success=True,
            message=f"Focused panel {next_panel_id}.",
            data={"focus_panel_id": next_panel_id},
        )


def _tabs_context(command: Command) -> tuple[list[dict[str, object]], str]:
    raw_tabs = command.context.get("tabs")
    active_tab = command.context.get("active_tab_id")
    if not isinstance(raw_tabs, list):
        raise CommandContextError("No active layout is available to edit.")
    if not isinstance(active_tab, str) or not active_tab:
        raise CommandContextError("No active tab is available to edit.")
    tabs = copy.deepcopy([tab for tab in raw_tabs if isinstance(tab, dict)])
    if not tabs:
        raise CommandContextError("No active layout is available to edit.")
    return tabs, active_tab


def _active_root_split(tabs: list[dict[str, object]], active_tab: str) -> dict[str, object]:
    for tab in tabs:
        if tab.get("id") != active_tab:
            continue
        root_split = tab.get("root_split")
        if isinstance(root_split, dict):
            return root_split
        raise CommandContextError("The active tab does not expose a root split.")
    raise CommandContextError(f"The active tab '{active_tab}' could not be found.")
