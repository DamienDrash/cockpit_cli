"""Periodic due-action runner for response approvals and sweeps."""

from __future__ import annotations

from dataclasses import dataclass
from time import sleep

from cockpit.ops.services.response_run_service import ResponseRunService
from cockpit.runtime.task_supervisor import SupervisedTaskContext, TaskSupervisor
from cockpit.core.enums import ComponentKind


@dataclass(slots=True)
class ResponseMonitor:
    """Run due response sweeps on a deterministic cadence."""

    response_run_service: ResponseRunService
    task_supervisor: TaskSupervisor
    interval_seconds: float = 2.0
    task_name: str = "response-monitor"

    def start(self) -> None:
        """Start the supervised response sweep loop."""

        self.task_supervisor.spawn_supervised(
            self.task_name,
            self._run,
            heartbeat_timeout_seconds=max(3.0, self.interval_seconds * 3),
            restartable=True,
            metadata={
                "component_id": f"task:{self.task_name}",
                "component_kind": ComponentKind.BACKGROUND_TASK.value,
                "display_name": "Response Monitor",
            },
        )

    def stop(self) -> None:
        """Stop the supervised response sweep loop."""

        self.task_supervisor.stop(self.task_name, timeout=1.0)

    def _run(self, context: SupervisedTaskContext) -> None:
        while not context.stop_event.is_set():
            context.heartbeat("sweep")
            self.response_run_service.sweep_due()
            sleep(self.interval_seconds)
