"""Manual response step executor."""

from __future__ import annotations

from cockpit.infrastructure.runbooks.executors.base import (
    ExecutorArtifact,
    ExecutorContext,
    ExecutorResult,
)


class ManualStepExecutor:
    """Record operator-confirmed completion for a manual step."""

    def execute(self, context: ExecutorContext) -> ExecutorResult:
        instructions = str(context.resolved_config.get("instructions", "")).strip()
        note = str(context.resolved_config.get("note", "")).strip()
        summary = note or instructions or f"Manual step '{context.step_definition.title}' completed."
        artifacts = (
            ExecutorArtifact(
                kind="manual_note",
                label=context.step_definition.title,
                summary=summary,
                payload={"actor": context.actor},
            ),
        )
        return ExecutorResult(
            success=True,
            summary=summary,
            payload={
                "instructions": instructions,
                "note": note,
                "actor": context.actor,
            },
            artifacts=artifacts,
        )

