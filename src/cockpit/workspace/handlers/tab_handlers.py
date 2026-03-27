"""Tab-related handlers."""

from __future__ import annotations

from cockpit.core.dispatch.handler_base import CommandContextError, DispatchResult
from cockpit.core.command import Command


class FocusTabHandler:
    """Switch the active application tab through the shared dispatcher."""

    VALID_TABS = {"work"}

    def __call__(self, command: Command) -> DispatchResult:
        argv = command.args.get("argv", [])
        tab_id = argv[0] if isinstance(argv, list) and argv else command.args.get("tab")
        if not isinstance(tab_id, str) or not tab_id:
            raise CommandContextError("A target tab id is required.")
        valid_tabs = self._valid_tabs(command.context)
        if tab_id not in valid_tabs:
            raise CommandContextError(f"Tab '{tab_id}' is not available.")
        return DispatchResult(
            success=True,
            message=f"Focused tab: {tab_id}",
            data={"active_tab_id": tab_id},
        )

    def _valid_tabs(self, context: dict[str, object]) -> set[str]:
        available_tab_ids = context.get("available_tab_ids")
        if not isinstance(available_tab_ids, list):
            return set(self.VALID_TABS)
        tab_ids = {
            tab_id for tab_id in available_tab_ids if isinstance(tab_id, str) and tab_id
        }
        return tab_ids or set(self.VALID_TABS)
