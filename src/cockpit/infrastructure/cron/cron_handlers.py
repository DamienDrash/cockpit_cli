"""Cron-related command handlers."""

from __future__ import annotations

from cockpit.core.dispatch.handler_base import (
    CommandContextError,
    ConfirmationRequiredError,
    DispatchResult,
)
from cockpit.core.command import Command
from cockpit.infrastructure.cron.cron_adapter import CronAdapter
from cockpit.core.enums import SessionTargetKind
from cockpit.core.risk import classify_target_risk, risk_presentation


class SetCronJobEnabledHandler:
    """Enable or disable the selected cron job with an explicit confirmation step."""

    def __init__(self, cron_adapter: CronAdapter, *, enabled: bool) -> None:
        self._cron_adapter = cron_adapter
        self._enabled = enabled

    def __call__(self, command: Command) -> DispatchResult:
        selected_command = self._resolve_command(command)
        target_kind = self._target_kind(command.context.get("target_kind"))
        target_ref = self._optional_str(command.context.get("target_ref"))
        workspace_root = self._optional_str(command.context.get("workspace_root")) or ""
        workspace_name = (
            self._optional_str(command.context.get("workspace_name")) or "workspace"
        )
        action_label = "enable" if self._enabled else "disable"
        verb_label = "Enable" if self._enabled else "Disable"

        if not self._is_confirmed(command):
            risk_level = classify_target_risk(
                target_kind=target_kind,
                target_ref=target_ref,
                workspace_name=workspace_name,
                workspace_root=workspace_root,
            )
            risk_label = risk_presentation(risk_level).label
            raise ConfirmationRequiredError(
                f"Confirm cron {action_label} on {risk_label}.",
                payload={
                    "pending_command_name": command.name,
                    "pending_args": dict(command.args),
                    "pending_context": dict(command.context),
                    "confirmation_message": (
                        f"{verb_label} cron job '{selected_command}'? "
                        "Press Enter/Y to confirm or Esc/N to cancel."
                    ),
                },
            )

        result = self._cron_adapter.set_job_enabled(
            selected_command,
            enabled=self._enabled,
            target_kind=target_kind,
            target_ref=target_ref,
        )
        return DispatchResult(
            success=result.success,
            message=result.message,
            data={"refresh_panel_id": "cron-panel"},
        )

    def _resolve_command(self, command: Command) -> str:
        argv = command.args.get("argv", [])
        if isinstance(argv, list) and argv and isinstance(argv[0], str) and argv[0]:
            return argv[0]
        selected = command.context.get("selected_cron_command")
        if isinstance(selected, str) and selected:
            return selected
        raise CommandContextError("No cron job is selected.")

    @staticmethod
    def _is_confirmed(command: Command) -> bool:
        confirmed = command.args.get("confirmed")
        return bool(confirmed is True or confirmed == "true")

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return value if isinstance(value, str) else None

    @staticmethod
    def _target_kind(value: object) -> SessionTargetKind:
        if isinstance(value, SessionTargetKind):
            return value
        if isinstance(value, str):
            try:
                return SessionTargetKind(value)
            except ValueError:
                return SessionTargetKind.LOCAL
        return SessionTargetKind.LOCAL
