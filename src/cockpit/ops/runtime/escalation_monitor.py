"""Periodic due-action runner for incident engagements."""

from __future__ import annotations

from dataclasses import dataclass
from time import sleep

from cockpit.ops.services.escalation_service import EscalationService
from cockpit.runtime.task_supervisor import SupervisedTaskContext, TaskSupervisor
from cockpit.core.enums import ComponentKind


@dataclass(slots=True)
class EscalationMonitor:
    """Run due escalation actions on a deterministic cadence."""

    escalation_service: EscalationService
    task_supervisor: TaskSupervisor
    interval_seconds: float = 2.0
    task_name: str = "escalation-monitor"

    def start(self) -> None:
        """Start the supervised escalation sweep loop."""

        self.task_supervisor.spawn_supervised(
            self.task_name,
            self._run,
            heartbeat_timeout_seconds=max(3.0, self.interval_seconds * 3),
            restartable=True,
            metadata={
                "component_id": f"task:{self.task_name}",
                "component_kind": ComponentKind.BACKGROUND_TASK.value,
                "display_name": "Escalation Monitor",
            },
        )

    def stop(self) -> None:
        """Stop the supervised escalation sweep loop."""

        self.task_supervisor.stop(self.task_name, timeout=1.0)

    def _run(self, context: SupervisedTaskContext) -> None:
        while not context.stop_event.is_set():
            context.heartbeat("sweep")
            self.escalation_service.run_due_actions()
            sleep(self.interval_seconds)
