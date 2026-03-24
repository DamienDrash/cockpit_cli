"""Docker response step executor."""

from __future__ import annotations

from cockpit.infrastructure.docker.docker_adapter import DockerAdapter
from cockpit.infrastructure.runbooks.executors.base import (
    ExecutorArtifact,
    ExecutorContext,
    ExecutorResult,
)
from cockpit.shared.enums import SessionTargetKind


class DockerStepExecutor:
    """Execute structured Docker operations through the existing adapter."""

    def __init__(self, docker_adapter: DockerAdapter) -> None:
        self._docker_adapter = docker_adapter

    def execute(self, context: ExecutorContext) -> ExecutorResult:
        operation = str(context.resolved_config.get("operation", "restart")).strip().lower()
        container_id = str(context.resolved_config.get("container_id", "")).strip()
        target_kind = SessionTargetKind(str(context.resolved_config.get("target_kind", "local")))
        target_ref = context.resolved_config.get("target_ref")
        if operation == "restart":
            result = self._docker_adapter.restart_container(
                container_id,
                target_kind=target_kind,
                target_ref=str(target_ref) if isinstance(target_ref, str) and target_ref else None,
            )
        elif operation == "stop":
            result = self._docker_adapter.stop_container(
                container_id,
                target_kind=target_kind,
                target_ref=str(target_ref) if isinstance(target_ref, str) and target_ref else None,
            )
        elif operation == "remove":
            result = self._docker_adapter.remove_container(
                container_id,
                target_kind=target_kind,
                target_ref=str(target_ref) if isinstance(target_ref, str) and target_ref else None,
            )
        else:
            return ExecutorResult(
                success=False,
                summary=f"Unsupported docker operation '{operation}'.",
                error_message=f"Unsupported docker operation '{operation}'.",
            )
        return ExecutorResult(
            success=result.success,
            summary=result.message,
            payload={
                "operation": operation,
                "container_id": container_id,
                "target_kind": target_kind.value,
                "target_ref": target_ref,
            },
            artifacts=(
                ExecutorArtifact(
                    kind="docker_action",
                    label=f"{operation} {container_id}",
                    summary=result.message,
                    payload={
                        "operation": operation,
                        "container_id": container_id,
                    },
                ),
            ),
            error_message=None if result.success else result.message,
        )

