"""Real pipelines on the UI's background threads, each with its own connection to one database."""

from __future__ import annotations

import asyncio
import threading

import respx

from leadharvest.categories import load_categories
from leadharvest.enrich.enricher import Enricher
from leadharvest.storage.db import connect
from leadharvest.storage.repository import Repository
from leadharvest.ui_jobs import Job, Jobs
from tests.integration.test_pipeline import SITES, FixtureSource, make_pipeline, mock_world

CAT = load_categories()["dentist"]


def _work(settings, run_id: str, source: FixtureSource, job: Job) -> None:
    """Like the UI's views.common._work: own connection, "stopped" recorded after a Stop."""
    repo = Repository(connect(settings.db_path))
    try:
        job.run(make_pipeline(settings, repo, source).execute(run_id, CAT))
    except asyncio.CancelledError:
        repo.update_run(run_id, error="stopped")
    finally:
        repo.conn.close()


@respx.mock
def test_stop_from_another_thread_pauses_a_real_run_for_resume(settings, repo, monkeypatch):
    routes, source = mock_world(), FixtureSource()
    run = make_pipeline(settings, repo, source).create_run(
        CAT, "Makati", limit=100, targets=["csv"]
    )
    original, reached, calls = Enricher.enrich_lead, threading.Event(), {"n": 0}

    async def hang_on_third(self, lead):
        calls["n"] += 1
        if calls["n"] == 3:
            reached.set()
            await asyncio.sleep(30)  # the Stop button cancels it here
        return await original(self, lead)

    settings.concurrency = 1
    monkeypatch.setattr(Enricher, "enrich_lead", hang_on_third)
    jobs = Jobs()
    job = jobs.start(run.id, lambda j: _work(settings, run.id, source, j))
    assert reached.wait(10)
    job.stop()  # from the test's thread, as Streamlit's on_click does
    jobs.wait()
    paused = repo.get_run(run.id)
    assert (paused.status, paused.current_step, paused.error) == ("partial", "enrich", "stopped")

    monkeypatch.setattr(Enricher, "enrich_lead", original)
    resumed = asyncio.run(make_pipeline(settings, repo, source).execute(run.id, CAT))
    assert resumed.status == "completed" and source.calls == 1
    assert all(routes[site].call_count == 1 for site in SITES)  # nothing fetched twice


@respx.mock
def test_two_runs_write_to_one_database_at_once(settings, repo):
    mock_world()
    pipeline, jobs = make_pipeline(settings, repo, FixtureSource()), Jobs()
    runs = [pipeline.create_run(CAT, "Makati", limit=100, targets=["csv"]) for _ in range(2)]
    for run in runs:
        jobs.start(run.id, lambda j, rid=run.id: _work(settings, rid, FixtureSource(), j))
    jobs.wait()
    assert [repo.get_run(r.id).status for r in runs] == ["completed", "completed"]
    assert len({lead.lead_id for r in runs for lead in repo.leads_for_run(r.id)}) == 7
