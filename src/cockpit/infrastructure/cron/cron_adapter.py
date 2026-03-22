"""Structured adapter for local and SSH crontab inspection."""

from __future__ import annotations

from dataclasses import dataclass, field
import shlex
import subprocess

from cockpit.infrastructure.ssh.command_runner import SSHCommandRunner
from cockpit.shared.enums import SessionTargetKind


@dataclass(slots=True, frozen=True)
class CronJob:
    schedule: str
    command: str
    enabled: bool = True
    comment: str | None = None


@dataclass(slots=True, frozen=True)
class CronSnapshot:
    jobs: list[CronJob] = field(default_factory=list)
    is_available: bool = True
    message: str | None = None


class CronAdapter:
    """Read crontab entries from local or SSH-backed targets."""

    def __init__(self, ssh_command_runner: SSHCommandRunner | None = None) -> None:
        self._ssh_command_runner = ssh_command_runner

    def list_jobs(
        self,
        *,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
    ) -> CronSnapshot:
        if target_kind is SessionTargetKind.SSH:
            return self._list_remote_jobs(target_ref)

        try:
            result = subprocess.run(
                ("crontab", "-l"),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except FileNotFoundError:
            return CronSnapshot(
                is_available=False,
                message="The crontab executable is not available in this environment.",
            )
        return self._snapshot_from_result(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            is_available=True,
        )

    def _list_remote_jobs(self, target_ref: str | None) -> CronSnapshot:
        if not target_ref:
            return CronSnapshot(
                is_available=False,
                message="No SSH target is configured for this workspace.",
            )
        if self._ssh_command_runner is None:
            return CronSnapshot(
                is_available=False,
                message="SSH crontab inspection is not configured.",
            )
        result = self._ssh_command_runner.run(target_ref, "crontab -l")
        if not result.is_available:
            return CronSnapshot(
                is_available=False,
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
    ) -> CronSnapshot:
        if returncode != 0:
            message = stderr.strip() or "crontab -l failed."
            if "no crontab" in message.lower():
                return CronSnapshot(
                    jobs=[],
                    is_available=is_available,
                    message="No crontab configured.",
                )
            return CronSnapshot(
                jobs=[],
                is_available=is_available,
                message=message,
            )
        jobs = self._parse_crontab(stdout)
        return CronSnapshot(
            jobs=jobs,
            is_available=is_available,
            message=None if jobs else "No crontab configured.",
        )

    def _parse_crontab(self, raw_output: str) -> list[CronJob]:
        jobs: list[CronJob] = []
        pending_comments: list[str] = []
        for raw_line in raw_output.splitlines():
            line = raw_line.strip()
            if not line:
                pending_comments.clear()
                continue
            enabled = True
            if line.startswith("#"):
                candidate = line[1:].strip()
                if not self._looks_like_job(candidate):
                    if candidate:
                        pending_comments.append(candidate)
                    continue
                line = candidate
                enabled = False

            comment = " ".join(pending_comments) if pending_comments else None
            pending_comments.clear()
            job = self._parse_job_line(line, enabled=enabled, comment=comment)
            if job is not None:
                jobs.append(job)
        return jobs

    def _parse_job_line(
        self,
        line: str,
        *,
        enabled: bool,
        comment: str | None,
    ) -> CronJob | None:
        if not line:
            return None
        if line.startswith("@"):
            parts = shlex.split(line)
            if len(parts) < 2:
                return None
            return CronJob(
                schedule=parts[0],
                command=" ".join(parts[1:]),
                enabled=enabled,
                comment=comment,
            )

        fields = line.split(maxsplit=5)
        if len(fields) >= 6:
            return CronJob(
                schedule=" ".join(fields[:5]),
                command=fields[5],
                enabled=enabled,
                comment=comment,
            )

        first_token = line.split(maxsplit=1)[0]
        if "=" in first_token and not first_token.startswith("@"):
            return CronJob(
                schedule="env",
                command=line,
                enabled=False,
                comment=comment or "Environment variable",
            )
        return CronJob(
            schedule="invalid",
            command=line,
            enabled=False,
            comment=comment or "Could not parse crontab line.",
        )

    def _looks_like_job(self, line: str) -> bool:
        if not line:
            return False
        if line.startswith("@"):
            return True
        fields = line.split(maxsplit=5)
        if len(fields) >= 6:
            return True
        first_token = line.split(maxsplit=1)[0]
        return "=" in first_token
