"""Structured adapter for local and SSH Docker inspection."""

from __future__ import annotations

from dataclasses import dataclass, field
import shlex
import subprocess

from cockpit.infrastructure.ssh.command_runner import SSHCommandRunner
from cockpit.shared.enums import SessionTargetKind


@dataclass(slots=True, frozen=True)
class DockerContainerSummary:
    container_id: str
    name: str
    image: str
    state: str
    status: str
    ports: str


@dataclass(slots=True, frozen=True)
class DockerRuntimeSnapshot:
    containers: list[DockerContainerSummary] = field(default_factory=list)
    is_available: bool = True
    daemon_reachable: bool = True
    message: str | None = None


class DockerAdapter:
    """Load structured container status from Docker or SSH targets."""

    _FORMAT = "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.State}}\t{{.Status}}\t{{.Ports}}"

    def __init__(self, ssh_command_runner: SSHCommandRunner | None = None) -> None:
        self._ssh_command_runner = ssh_command_runner

    def list_containers(
        self,
        *,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
    ) -> DockerRuntimeSnapshot:
        if target_kind is SessionTargetKind.SSH:
            return self._list_remote_containers(target_ref)

        try:
            result = self._run_docker("ps", "-a", "--format", self._FORMAT)
        except FileNotFoundError:
            return DockerRuntimeSnapshot(
                is_available=False,
                daemon_reachable=False,
                message="The docker executable is not available in this environment.",
            )

        return self._snapshot_from_result(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            is_available=True,
        )

    def _list_remote_containers(self, target_ref: str | None) -> DockerRuntimeSnapshot:
        if not target_ref:
            return DockerRuntimeSnapshot(
                is_available=False,
                daemon_reachable=False,
                message="No SSH target is configured for this workspace.",
            )
        if self._ssh_command_runner is None:
            return DockerRuntimeSnapshot(
                is_available=False,
                daemon_reachable=False,
                message="SSH docker inspection is not configured.",
            )

        result = self._ssh_command_runner.run(
            target_ref,
            f"docker ps -a --format {shlex.quote(self._FORMAT)}",
        )
        if not result.is_available:
            return DockerRuntimeSnapshot(
                is_available=False,
                daemon_reachable=False,
                message=result.message or "SSH is unavailable.",
            )

        return self._snapshot_from_result(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr or result.message or "",
            is_available=True,
        )

    def _snapshot_from_result(
        self,
        *,
        returncode: int,
        stdout: str,
        stderr: str,
        is_available: bool,
    ) -> DockerRuntimeSnapshot:
        if returncode != 0:
            message = stderr.strip() or "docker ps failed."
            lowered = message.lower()
            daemon_reachable = "daemon" not in lowered and "cannot connect" not in lowered
            return DockerRuntimeSnapshot(
                is_available=is_available,
                daemon_reachable=daemon_reachable,
                message=message,
            )

        containers: list[DockerContainerSummary] = []
        for line in stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 6:
                continue
            container_id, name, image, state, status, ports = parts[:6]
            containers.append(
                DockerContainerSummary(
                    container_id=container_id,
                    name=name,
                    image=image,
                    state=state,
                    status=status,
                    ports=ports,
                )
            )
        return DockerRuntimeSnapshot(
            containers=containers,
            is_available=is_available,
            daemon_reachable=True,
            message=None if containers else "No containers found.",
        )

    def _run_docker(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ("docker", *args),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
