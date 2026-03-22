"""Background task supervision for runtime workers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Event, Lock, Thread

TaskTarget = Callable[[Event], None]


@dataclass(slots=True)
class BackgroundTask:
    name: str
    thread: Thread
    stop_event: Event


class TaskSupervisor:
    """Tracks and stops background threads started by the runtime layer."""

    def __init__(self) -> None:
        self._tasks: dict[str, BackgroundTask] = {}
        self._lock = Lock()

    def spawn(self, name: str, target: TaskTarget) -> BackgroundTask:
        stop_event = Event()
        thread = Thread(
            target=target,
            args=(stop_event,),
            name=name,
            daemon=True,
        )
        task = BackgroundTask(name=name, thread=thread, stop_event=stop_event)
        with self._lock:
            if name in self._tasks:
                raise ValueError(f"Task '{name}' is already running.")
            self._tasks[name] = task
        thread.start()
        return task

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
