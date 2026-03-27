"""Background task supervision for runtime workers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from threading import Event, Lock, Thread

from cockpit.core.utils import utc_now

TaskTarget = Callable[[Event], None]
SupervisedTaskTarget = Callable[["SupervisedTaskContext"], None]


@dataclass(slots=True)
class BackgroundTask:
    """Runtime worker task tracked by the supervisor."""

    name: str
    thread: Thread
    stop_event: Event
    target: SupervisedTaskTarget
    heartbeat_timeout_seconds: float
    restartable: bool
    metadata: dict[str, object] = field(default_factory=dict)
    started_at: datetime = field(default_factory=utc_now)
    last_heartbeat_at: datetime | None = None
    last_progress_message: str | None = None
    finished_at: datetime | None = None
    last_error: str | None = None
    restart_count: int = 0


@dataclass(slots=True, frozen=True)
class TaskSnapshot:
    """Read-only task status used by watchdog logic."""

    name: str
    alive: bool
    restartable: bool
    started_at: datetime
    last_heartbeat_at: datetime | None
    last_progress_message: str | None
    heartbeat_timeout_seconds: float
    stale: bool
    age_seconds: float
    finished_at: datetime | None
    last_error: str | None
    restart_count: int
    metadata: dict[str, object]


class SupervisedTaskContext:
    """Mutable control surface exposed to supervised task workers."""

    def __init__(
        self, supervisor: "TaskSupervisor", task_name: str, stop_event: Event
    ) -> None:
        self._supervisor = supervisor
        self._task_name = task_name
        self.stop_event = stop_event

    def heartbeat(self, message: str | None = None) -> None:
        """Publish a heartbeat for stale-task detection."""

        self._supervisor.heartbeat(self._task_name, message=message)


class TaskSupervisor:
    """Tracks, snapshots, and restarts background threads started by the runtime layer."""

    def __init__(self) -> None:
        self._tasks: dict[str, BackgroundTask] = {}
        self._lock = Lock()

    def spawn(self, name: str, target: TaskTarget) -> BackgroundTask:
        """Spawn a legacy stop-event based worker.

        Notes
        -----
        This compatibility path wraps the target in a supervised context and issues
        an initial heartbeat on startup.
        """

        def wrapped(context: SupervisedTaskContext) -> None:
            context.heartbeat("started")
            target(context.stop_event)

        return self.spawn_supervised(
            name,
            wrapped,
            heartbeat_timeout_seconds=30.0,
            restartable=False,
        )

    def spawn_supervised(
        self,
        name: str,
        target: SupervisedTaskTarget,
        *,
        heartbeat_timeout_seconds: float = 30.0,
        restartable: bool = False,
        metadata: dict[str, object] | None = None,
        restart_count: int = 0,
    ) -> BackgroundTask:
        """Spawn a supervised worker with heartbeat and restart metadata."""

        stop_event = Event()
        task = BackgroundTask(
            name=name,
            thread=Thread(),
            stop_event=stop_event,
            target=target,
            heartbeat_timeout_seconds=max(1.0, float(heartbeat_timeout_seconds)),
            restartable=restartable,
            metadata=dict(metadata or {}),
            restart_count=restart_count,
        )
        thread = Thread(
            target=self._run_task,
            args=(task,),
            name=name,
            daemon=True,
        )
        task.thread = thread
        with self._lock:
            if name in self._tasks:
                raise ValueError(f"Task '{name}' is already running.")
            self._tasks[name] = task
        thread.start()
        return task

    def heartbeat(self, name: str, *, message: str | None = None) -> None:
        with self._lock:
            task = self._tasks.get(name)
            if task is None:
                return
            task.last_heartbeat_at = utc_now()
            if message:
                task.last_progress_message = message

    def get_snapshot(self, name: str) -> TaskSnapshot | None:
        with self._lock:
            task = self._tasks.get(name)
            if task is None:
                return None
            return self._snapshot_for_task(task)

    def list_snapshots(self) -> list[TaskSnapshot]:
        with self._lock:
            return [self._snapshot_for_task(task) for task in self._tasks.values()]

    def list_stale(self) -> list[TaskSnapshot]:
        return [snapshot for snapshot in self.list_snapshots() if snapshot.stale]

    def restart(self, name: str) -> BackgroundTask:
        """Restart a previously spawned restartable task."""

        with self._lock:
            current = self._tasks.get(name)
            if current is None:
                raise LookupError(f"Task '{name}' is not running.")
            if not current.restartable:
                raise ValueError(f"Task '{name}' is not restartable.")
            target = current.target
            heartbeat_timeout_seconds = current.heartbeat_timeout_seconds
            metadata = dict(current.metadata)
            restart_count = current.restart_count + 1
        self.stop(name, timeout=1.0)
        return self.spawn_supervised(
            name,
            target,
            heartbeat_timeout_seconds=heartbeat_timeout_seconds,
            restartable=True,
            metadata=metadata,
            restart_count=restart_count,
        )

    def stop(self, name: str, timeout: float = 1.0) -> None:
        with self._lock:
            task = self._tasks.pop(name, None)
        if task is None:
            return
        task.stop_event.set()
        task.thread.join(timeout)

    def stop_all(self, timeout: float = 1.0) -> None:
        with self._lock:
            names = list(self._tasks.keys())
        for name in names:
            self.stop(name, timeout)

    def _run_task(self, task: BackgroundTask) -> None:
        context = SupervisedTaskContext(self, task.name, task.stop_event)
        try:
            task.target(context)
        except (
            Exception
        ) as exc:  # pragma: no cover - intentionally captured for diagnostics
            with self._lock:
                active = self._tasks.get(task.name)
                if active is not None:
                    active.last_error = str(exc)
        finally:
            with self._lock:
                active = self._tasks.get(task.name)
                if active is not None:
                    active.finished_at = utc_now()

    def _snapshot_for_task(self, task: BackgroundTask) -> TaskSnapshot:
        effective_now = utc_now()
        reference_time = task.last_heartbeat_at or task.started_at
        age_seconds = max(0.0, (effective_now - reference_time).total_seconds())
        stale = task.thread.is_alive() and age_seconds > task.heartbeat_timeout_seconds
        return TaskSnapshot(
            name=task.name,
            alive=task.thread.is_alive(),
            restartable=task.restartable,
            started_at=task.started_at,
            last_heartbeat_at=task.last_heartbeat_at,
            last_progress_message=task.last_progress_message,
            heartbeat_timeout_seconds=task.heartbeat_timeout_seconds,
            stale=stale,
            age_seconds=age_seconds,
            finished_at=task.finished_at,
            last_error=task.last_error,
            restart_count=task.restart_count,
            metadata=dict(task.metadata),
        )
