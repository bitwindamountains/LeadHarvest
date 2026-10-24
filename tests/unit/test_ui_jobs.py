"""The UI's background run registry."""

from __future__ import annotations

import threading

from leadharvest.ui_jobs import Job, Jobs


def test_one_thread_per_run_and_progress_is_readable() -> None:
    jobs, release, calls = Jobs(), threading.Event(), []

    def work(job: Job) -> None:
        calls.append(job)
        job.progress.step_started("search")
        job.progress.step_finished("search")
        job.progress.step_started("enrich")
        job.progress.step_progress("enrich", 2, 5)
        release.wait(5)
        job.message = "done"

    first = jobs.start("run-1", work)
    assert jobs.start("run-1", work) is first  # a second Resume joins the running job
    assert first.running and jobs.get("run-2") is None
    release.set()
    jobs.wait()
    assert len(calls) == 1 and not first.running and first.message == "done"
    assert first.progress.steps == {"search": True, "enrich": False}
    assert (first.progress.done, first.progress.total) == (2, 5)
    again = jobs.start("run-1", work)  # finished: a later resume starts afresh
    jobs.wait()
    assert again is not first and len(calls) == 2
