"""Shared by the views: asset paths, opening a run, and running a pipeline in the background
with live progress."""

from __future__ import annotations

import asyncio
import html
from pathlib import Path

import streamlit as st

from leadharvest.categories import Category
from leadharvest.cli import exporter_factory
from leadharvest.config import Settings
from leadharvest.geo.nominatim import LocationNotFound
from leadharvest.logging_setup import attach_run_log, detach_run_log
from leadharvest.models import Run
from leadharvest.pipeline import Pipeline, RunInProgress
from leadharvest.storage.db import connect
from leadharvest.storage.repository import Repository
from leadharvest.ui_jobs import JOBS, Job
from leadharvest.ui_support import STEP_LABELS

ASSETS = Path(__file__).resolve().parent.parent / "assets"
LOGO, MARK = str(ASSETS / "logo.svg"), str(ASSETS / "mark.svg")


def eyebrow(text: str) -> None:
    """A small pill above a page title, for real context (region, run id), never decoration."""
    st.html(f'<span class="lh-eyebrow">{html.escape(text)}</span>')


def inject_theme() -> None:
    """The night-harvest stylesheet (app/assets/theme.css), on top of .streamlit/config.toml."""
    st.html(f"<style>{(ASSETS / 'theme.css').read_text(encoding='utf-8')}</style>")


def select_run(run_id: str | None) -> None:
    """Open a run (or, with None, the search page) on the next rerun. The sidebar picker owns
    the current selection. Leaves the All runs and batch pages."""
    st.session_state["select_run"] = run_id
    st.session_state.pop("all_runs", None)
    st.session_state.pop("open_batch", None)


def execute(settings: Settings, run: Run, category: Category, *, force: bool = False) -> None:
    """Start (or resume) a run on a background thread and open its page, which shows the
    progress. The run keeps going whatever the person clicks, or if they close the tab."""
    JOBS.start(run.id, lambda job: _work(settings, run.id, category, force, job))
    select_run(run.id)
    st.rerun()


def _work(settings: Settings, run_id: str, category: Category, force: bool, job: Job) -> None:
    repo = Repository(connect(settings.db_path))  # SQLite connections stay in their thread
    pipeline = Pipeline(
        settings, repo, exporter_factory=exporter_factory(settings), reporter=job.progress
    )
    handler = attach_run_log(settings.log_dir, run_id)
    try:
        asyncio.run(pipeline.execute(run_id, category, force=force))
    except RunInProgress:
        job.message = "This run was started somewhere else (the CLI or another server) just now."
    except LocationNotFound as exc:
        hint = "".join(f"\n- {s}" for s in exc.suggestions)
        job.message = (
            f"Couldn't find **{exc.location}**. Start a new search with a more specific name, "
            "e.g. add the province." + (f"\n\nClosest matches:{hint}" if hint else "")
        )
    except Exception:  # the pipeline recorded it on the run; the run page shows it
        pass
    finally:
        detach_run_log(handler)
        repo.conn.close()


@st.fragment(run_every=1)
def live_progress(run_id: str, title: str) -> None:
    """A running run's steps and website count, redrawn every second; the whole page reruns
    to show the results once the run stops."""
    job = JOBS.get(run_id)
    if job is None or not job.running:
        st.rerun()
        return
    steps = dict(job.progress.steps)
    current = next((s for s, finished in reversed(steps.items()) if not finished), None)
    # Not `with st.status(...)`: leaving the block would mark the box complete.
    box = st.status(f"{STEP_LABELS[current]}…" if current else title, expanded=True)
    for step, finished in steps.items():
        icon = ":green[:material/check:]" if finished else ":blue[:material/progress_activity:]"
        box.markdown(f"{icon} {STEP_LABELS[step]}" + ("" if finished else "…"))
    done, total = job.progress.done, job.progress.total
    if "enrich" in steps and total:
        box.progress(min(done / total, 1.0), text=f"Visited {done} of {total} websites")
    st.caption(
        "The run continues if you open another page or close this tab; come back here to see it."
    )
