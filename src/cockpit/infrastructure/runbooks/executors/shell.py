"""Local shell response step executor."""

from __future__ import annotations

import subprocess

from cockpit.infrastructure.runbooks.executors.base import (
    ExecutorArtifact,
    ExecutorContext,
    ExecutorResult,
)


class ShellStepExecutor:
    """Execute a bounded local shell command through ``bash -lc``."""

    def execute(self, context: ExecutorContext) -> ExecutorResult:
        command = str(context.resolved_config.get("command", "")).strip()
        cwd = str(context.resolved_config.get("cwd", "")).strip() or None
        timeout_seconds = int(context.resolved_config.get("timeout_seconds", 30) or 30)
        result = subprocess.run(
            ["bash", "-lc", command],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=max(1, timeout_seconds),
        )
        stdout = result.stdout[-4000:]
        stderr = result.stderr[-4000:]
        success = result.returncode == 0
        summary = f"Shell step '{context.step_definition.title}' exited with {result.returncode}."
        return ExecutorResult(
            success=success,
            summary=summary,
            payload={
                "command": command,
                "cwd": cwd,
                "returncode": result.returncode,
                "stdout": stdout,
                "stderr": stderr,
            },
            artifacts=(
                ExecutorArtifact(
                    kind="shell_output",
                    label=context.step_definition.title,
                    summary=summary,
                    payload={"stdout": stdout, "stderr": stderr},
                ),
            ),
            error_message=None if success else (stderr or summary),
        )
