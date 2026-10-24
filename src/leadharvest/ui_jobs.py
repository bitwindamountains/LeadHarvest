"""The UI's pipeline runs, each on a background thread, so a run survives clicks, page changes
and reloads (a Streamlit rerun stops whatever the page itself is doing). One registry per
server process, shared by every browser tab; the run page reads progress from it."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field


class Progress:
    """A pipeline Reporter that the run page reads from another thread. Each update is a plain
    assignment, which the GIL keeps whole."""

    def __init__(self) -> None:
        self.steps: dict[str, bool] = {}  # step → finished, in the order they started
        self.done = 0  # websites visited
        self.total = 0

    def step_started(self, step: str, total: int | None = None) -> None:
        self.steps[step] = False

    def step_progress(self, step: str, done: int, total: int) -> None:
        self.done, self.total = done, total

    def step_finished(self, step: str) -> None:
        self.steps[step] = True


@dataclass
class Job:
    progress: Progress = field(default_factory=Progress)
    thread: threading.Thread | None = None
    message: str | None = None  # why it stopped early, in words for the person who started it

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()


class Jobs:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, run_id: str, work: Callable[[Job], None]) -> Job:
        """Run `work(job)` on a new thread, unless this run is already running here (a second
        tab clicking Resume gets the running job). Daemon threads: stopping the server doesn't
        wait for a run, which stays marked running, and its page offers to take it over."""
        with self._lock:
            job = self._jobs.get(run_id)
            if job is not None and job.running:
                return job
            job = Job()
            job.thread = threading.Thread(
                target=work, args=(job,), name=f"run-{run_id[:8]}", daemon=True
            )
            self._jobs[run_id] = job
            job.thread.start()
            return job

    def get(self, run_id: str) -> Job | None:
        return self._jobs.get(run_id)

    def wait(self, timeout: float = 10) -> None:
        """Until every job has finished (tests)."""
        for job in list(self._jobs.values()):
            if job.thread is not None:
                job.thread.join(timeout)


JOBS = Jobs()
