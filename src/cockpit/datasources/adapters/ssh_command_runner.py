"""SSH command execution helpers for remote workspace inspection."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess


@dataclass(slots=True, frozen=True)
class SSHCommandResult:
    target_ref: str
    command: str
    returncode: int
    stdout: str
    stderr: str
    is_available: bool = True
    message: str | None = None


class SSHCommandRunner:
    """Run structured non-interactive commands over SSH."""

    def run(
        self,
        target_ref: str,
        command: str,
        *,
        timeout_seconds: int = 5,
        input_text: str | None = None,
    ) -> SSHCommandResult:
        try:
            completed = subprocess.run(
                (
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    f"ConnectTimeout={timeout_seconds}",
                    target_ref,
                    "sh",
                    "-lc",
                    command,
                ),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                input=input_text,
                check=False,
                timeout=max(1, timeout_seconds),
            )
        except FileNotFoundError:
            return SSHCommandResult(
                target_ref=target_ref,
                command=command,
                returncode=127,
                stdout="",
                stderr="",
                is_available=False,
                message="The ssh executable is not available in this environment.",
            )
        except subprocess.TimeoutExpired:
            return SSHCommandResult(
                target_ref=target_ref,
                command=command,
                returncode=124,
                stdout="",
                stderr="",
                is_available=True,
                message=f"SSH command timed out after {timeout_seconds} seconds.",
            )

        return SSHCommandResult(
            target_ref=target_ref,
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            is_available=True,
        )
