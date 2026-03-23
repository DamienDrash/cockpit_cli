"""Structured adapter for local and SSH Docker inspection."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
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


@dataclass(slots=True, frozen=True)
class DockerActionResult:
    success: bool
    message: str


@dataclass(slots=True, frozen=True)
class DockerContainerDiagnosticsSnapshot:
    container_id: str
    name: str
    image: str
    state: str
    status: str
    ports: str
    health: str | None = None
    restart_policy: str | None = None
    exit_code: int | None = None
    restart_count: int | None = None
    last_error: str | None = None
    last_finished_at: str | None = None
    recent_logs: list[str] = field(default_factory=list)


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

    def restart_container(
        self,
        container_id: str,
        *,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
    ) -> DockerActionResult:
        if target_kind is SessionTargetKind.SSH:
            return self._restart_remote_container(container_id, target_ref)

        try:
            result = self._run_docker("restart", container_id)
        except FileNotFoundError:
            return DockerActionResult(
                success=False,
                message="The docker executable is not available in this environment.",
            )

        if result.returncode != 0:
            return DockerActionResult(
                success=False,
                message=result.stderr.strip() or f"Docker restart failed for {container_id}.",
            )
        return DockerActionResult(
            success=True,
            message=result.stdout.strip() or f"Restarted docker container {container_id}.",
        )

    def stop_container(
        self,
        container_id: str,
        *,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
    ) -> DockerActionResult:
        return self._run_container_action(
            "stop",
            container_id,
            target_kind=target_kind,
            target_ref=target_ref,
        )

    def remove_container(
        self,
        container_id: str,
        *,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
    ) -> DockerActionResult:
        return self._run_container_action(
            "rm",
            container_id,
            target_kind=target_kind,
            target_ref=target_ref,
        )

    def _restart_remote_container(
        self,
        container_id: str,
        target_ref: str | None,
    ) -> DockerActionResult:
        if not target_ref:
            return DockerActionResult(
                success=False,
                message="No SSH target is configured for this workspace.",
            )
        if self._ssh_command_runner is None:
            return DockerActionResult(
                success=False,
                message="SSH docker inspection is not configured.",
            )
        result = self._ssh_command_runner.run(
            target_ref,
            f"docker restart {shlex.quote(container_id)}",
        )
        if not result.is_available:
            return DockerActionResult(
                success=False,
                message=result.message or "SSH is unavailable.",
            )
        if result.returncode != 0:
            return DockerActionResult(
                success=False,
                message=result.stderr.strip() or f"Docker restart failed for {container_id}.",
            )
        return DockerActionResult(
            success=True,
            message=result.stdout.strip() or f"Restarted docker container {container_id}.",
        )

    def _run_container_action(
        self,
        action: str,
        container_id: str,
        *,
        target_kind: SessionTargetKind,
        target_ref: str | None,
    ) -> DockerActionResult:
        verb = {
            "stop": "Stopped",
            "rm": "Removed",
        }.get(action, action.title())
        if target_kind is SessionTargetKind.SSH:
            return self._run_remote_container_action(action, container_id, target_ref, verb=verb)

        try:
            result = self._run_docker(action, container_id)
        except FileNotFoundError:
            return DockerActionResult(
                success=False,
                message="The docker executable is not available in this environment.",
            )
        if result.returncode != 0:
            return DockerActionResult(
                success=False,
                message=result.stderr.strip() or f"Docker {action} failed for {container_id}.",
            )
        return DockerActionResult(
            success=True,
            message=result.stdout.strip() or f"{verb} docker container {container_id}.",
        )

    def collect_diagnostics(
        self,
        *,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
        log_tail: int = 20,
    ) -> list[DockerContainerDiagnosticsSnapshot]:
        snapshot = self.list_containers(target_kind=target_kind, target_ref=target_ref)
        diagnostics: list[DockerContainerDiagnosticsSnapshot] = []
        for container in snapshot.containers:
            detail = self._inspect_container(
                container.container_id,
                target_kind=target_kind,
                target_ref=target_ref,
                log_tail=log_tail,
            )
            diagnostics.append(
                DockerContainerDiagnosticsSnapshot(
                    container_id=container.container_id,
                    name=container.name,
                    image=container.image,
                    state=container.state,
                    status=container.status,
                    ports=container.ports,
                    health=detail.get("health"),
                    restart_policy=detail.get("restart_policy"),
                    exit_code=detail.get("exit_code"),
                    restart_count=detail.get("restart_count"),
                    last_error=detail.get("last_error"),
                    last_finished_at=detail.get("last_finished_at"),
                    recent_logs=detail.get("recent_logs", []),
                )
            )
        return diagnostics

    def _inspect_container(
        self,
        container_id: str,
        *,
        target_kind: SessionTargetKind,
        target_ref: str | None,
        log_tail: int,
    ) -> dict[str, object]:
        if target_kind is SessionTargetKind.SSH:
            return self._inspect_remote_container(container_id, target_ref, log_tail=log_tail)
        return self._inspect_local_container(container_id, log_tail=log_tail)

    def _inspect_local_container(
        self,
        container_id: str,
        *,
        log_tail: int,
    ) -> dict[str, object]:
        try:
            inspect_result = self._run_docker("inspect", container_id)
        except FileNotFoundError:
            return {"recent_logs": [], "last_error": "docker executable unavailable"}
        if inspect_result.returncode != 0:
            return {
                "recent_logs": [],
                "last_error": inspect_result.stderr.strip()
                or f"docker inspect failed for {container_id}",
            }
        logs_result = self._run_docker("logs", "--tail", str(max(1, log_tail)), container_id)
        return self._detail_from_inspect_payload(
            inspect_result.stdout,
            logs_output=(logs_result.stdout or logs_result.stderr),
        )

    def _inspect_remote_container(
        self,
        container_id: str,
        target_ref: str | None,
        *,
        log_tail: int,
    ) -> dict[str, object]:
        if not target_ref or self._ssh_command_runner is None:
            return {"recent_logs": [], "last_error": "SSH docker inspection is not configured."}
        inspect_result = self._ssh_command_runner.run(
            target_ref,
            f"docker inspect {shlex.quote(container_id)}",
        )
        if not inspect_result.is_available or inspect_result.returncode != 0:
            return {
                "recent_logs": [],
                "last_error": inspect_result.message
                or inspect_result.stderr.strip()
                or f"docker inspect failed for {container_id}",
            }
        logs_result = self._ssh_command_runner.run(
            target_ref,
            f"docker logs --tail {max(1, int(log_tail))} {shlex.quote(container_id)}",
        )
        logs_output = logs_result.stdout or logs_result.stderr or logs_result.message or ""
        return self._detail_from_inspect_payload(
            inspect_result.stdout,
            logs_output=logs_output,
        )

    @staticmethod
    def _detail_from_inspect_payload(raw_inspect: str, *, logs_output: str) -> dict[str, object]:
        try:
            payload = json.loads(raw_inspect)
        except json.JSONDecodeError:
            payload = []
        inspect_entry = payload[0] if isinstance(payload, list) and payload else {}
        if not isinstance(inspect_entry, dict):
            inspect_entry = {}
        state = inspect_entry.get("State", {})
        if not isinstance(state, dict):
            state = {}
        health = state.get("Health", {})
        if not isinstance(health, dict):
            health = {}
        host_config = inspect_entry.get("HostConfig", {})
        if not isinstance(host_config, dict):
            host_config = {}
        restart_policy = host_config.get("RestartPolicy", {})
        if not isinstance(restart_policy, dict):
            restart_policy = {}
        return {
            "health": health.get("Status") if health.get("Status") else None,
            "restart_policy": restart_policy.get("Name") or None,
            "exit_code": (
                int(state["ExitCode"])
                if isinstance(state.get("ExitCode"), int)
                else None
            ),
            "restart_count": (
                int(inspect_entry["RestartCount"])
                if isinstance(inspect_entry.get("RestartCount"), int)
                else None
            ),
            "last_error": state.get("Error") or None,
            "last_finished_at": state.get("FinishedAt") or None,
            "recent_logs": [
                line
                for line in logs_output.splitlines()[-max(1, min(50, len(logs_output.splitlines()) or 0)) :]
                if line.strip()
            ],
        }

    def _run_remote_container_action(
        self,
        action: str,
        container_id: str,
        target_ref: str | None,
        *,
        verb: str,
    ) -> DockerActionResult:
        if not target_ref:
            return DockerActionResult(
                success=False,
                message="No SSH target is configured for this workspace.",
            )
        if self._ssh_command_runner is None:
            return DockerActionResult(
                success=False,
                message="SSH docker inspection is not configured.",
            )
        result = self._ssh_command_runner.run(
            target_ref,
            f"docker {action} {shlex.quote(container_id)}",
        )
        if not result.is_available:
            return DockerActionResult(
                success=False,
                message=result.message or "SSH is unavailable.",
            )
        if result.returncode != 0:
            return DockerActionResult(
                success=False,
                message=result.stderr.strip() or f"Docker {action} failed for {container_id}.",
            )
        return DockerActionResult(
            success=True,
            message=result.stdout.strip() or f"{verb} docker container {container_id}.",
        )
