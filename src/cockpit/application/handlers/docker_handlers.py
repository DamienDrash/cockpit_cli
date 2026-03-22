"""Docker-related command handlers."""

from __future__ import annotations

from dataclasses import dataclass

from cockpit.application.handlers.base import (
    CommandContextError,
    ConfirmationRequiredError,
    DispatchResult,
)
from cockpit.domain.commands.command import Command
from cockpit.infrastructure.docker.docker_adapter import DockerActionResult, DockerAdapter
from cockpit.shared.enums import SessionTargetKind
from cockpit.shared.risk import classify_target_risk, risk_presentation


@dataclass(slots=True, frozen=True)
class DockerActionSpec:
    command_name: str
    action_name: str
    confirmation_verb: str
    success_key: str
    success_message: str


class DockerContainerActionHandler:
    """Run a guarded mutating action for the selected docker container."""

    def __init__(self, docker_adapter: DockerAdapter, spec: DockerActionSpec) -> None:
        self._docker_adapter = docker_adapter
        self._spec = spec

    def __call__(self, command: Command) -> DispatchResult:
        container_id = self._resolve_container_id(command)
        target_kind = self._target_kind(command.context.get("target_kind"))
        target_ref = self._optional_str(command.context.get("target_ref"))
        workspace_root = self._optional_str(command.context.get("workspace_root")) or ""
        workspace_name = self._optional_str(command.context.get("workspace_name")) or "workspace"
        container_name = self._optional_str(command.context.get("selected_container_name"))
        display_name = container_name or container_id

        if not self._is_confirmed(command):
            risk_level = classify_target_risk(
                target_kind=target_kind,
                target_ref=target_ref,
                workspace_name=workspace_name,
                workspace_root=workspace_root,
            )
            risk_label = risk_presentation(risk_level).label
            raise ConfirmationRequiredError(
                f"Confirm docker {self._spec.action_name} for {display_name} on {risk_label}.",
                payload={
                    "pending_command_name": command.name,
                    "pending_args": dict(command.args),
                    "pending_context": dict(command.context),
                    "confirmation_message": (
                        f"{self._spec.confirmation_verb} container {display_name}? "
                        "Press Enter/Y to confirm or Esc/N to cancel."
                    ),
                },
            )

        result = self._run_action(
            container_id,
            target_kind=target_kind,
            target_ref=target_ref,
        )
        return DispatchResult(
            success=result.success,
            message=result.message,
            data={
                "refresh_panel_id": "docker-panel",
                self._spec.success_key: container_id,
            },
        )

    def _run_action(
        self,
        container_id: str,
        *,
        target_kind: SessionTargetKind,
        target_ref: str | None,
    ) -> DockerActionResult:
        if self._spec.action_name == "restart":
            return self._docker_adapter.restart_container(
                container_id,
                target_kind=target_kind,
                target_ref=target_ref,
            )
        if self._spec.action_name == "stop":
            return self._docker_adapter.stop_container(
                container_id,
                target_kind=target_kind,
                target_ref=target_ref,
            )
        if self._spec.action_name == "remove":
            return self._docker_adapter.remove_container(
                container_id,
                target_kind=target_kind,
                target_ref=target_ref,
            )
        raise CommandContextError(f"Unsupported docker action '{self._spec.action_name}'.")

    def _resolve_container_id(self, command: Command) -> str:
        argv = command.args.get("argv", [])
        if isinstance(argv, list) and argv and isinstance(argv[0], str) and argv[0]:
            return argv[0]
        selected = command.context.get("selected_container_id")
        if isinstance(selected, str) and selected:
            return selected
        raise CommandContextError("No docker container is selected.")

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


class RestartDockerContainerHandler(DockerContainerActionHandler):
    def __init__(self, docker_adapter: DockerAdapter) -> None:
        super().__init__(
            docker_adapter,
            DockerActionSpec(
                command_name="docker.restart",
                action_name="restart",
                confirmation_verb="Restart",
                success_key="restarted_container_id",
                success_message="Restarted",
            ),
        )


class StopDockerContainerHandler(DockerContainerActionHandler):
    def __init__(self, docker_adapter: DockerAdapter) -> None:
        super().__init__(
            docker_adapter,
            DockerActionSpec(
                command_name="docker.stop",
                action_name="stop",
                confirmation_verb="Stop",
                success_key="stopped_container_id",
                success_message="Stopped",
            ),
        )


class RemoveDockerContainerHandler(DockerContainerActionHandler):
    def __init__(self, docker_adapter: DockerAdapter) -> None:
        super().__init__(
            docker_adapter,
            DockerActionSpec(
                command_name="docker.remove",
                action_name="remove",
                confirmation_verb="Remove",
                success_key="removed_container_id",
                success_message="Removed",
            ),
        )
