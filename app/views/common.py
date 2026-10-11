"""Shared by the views: asset paths, opening a run, and running a pipeline with live progress."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import streamlit as st

from leadharvest.categories import Category
from leadharvest.cli import exporter_factory
from leadharvest.config import Settings
from leadharvest.geo.nominatim import LocationNotFound
from leadharvest.logging_setup import attach_run_log, detach_run_log
from leadharvest.models import Run
from leadharvest.pipeline import Pipeline, RunInProgress
from leadharvest.storage.repository import Repository
from leadharvest.ui_support import STEP_LABELS, mark_interrupted, run_title

ASSETS = Path(__file__).resolve().parent.parent / "assets"
LOGO, MARK = str(ASSETS / "logo.svg"), str(ASSETS / "mark.svg")


def inject_theme() -> None:
    """The night-harvest stylesheet (app/assets/theme.css), on top of .streamlit/config.toml."""
    st.html(f"<style>{(ASSETS / 'theme.css').read_text(encoding='utf-8')}</style>")


def select_run(run_id: str | None) -> None:
    """Open a run (or, with None, the search page) on the next rerun. The sidebar picker owns
    the current selection."""
    st.session_state["select_run"] = run_id


class StatusReporter:
    """Pipeline progress inside an st.status box: one line per step, a bar for websites."""

    def __init__(self, box: Any) -> None:
        self.box = box
        self.lines: dict[str, Any] = {}
        self.bar: Any = None

    def step_started(self, step: str, total: int | None = None) -> None:
        self.box.update(label=f"{STEP_LABELS[step]}…")
        self.lines[step] = self.box.empty()
        self.lines[step].markdown(f":blue[:material/progress_activity:] {STEP_LABELS[step]}…")
        if step == "enrich":
            self.bar = self.box.progress(0.0)

    def step_progress(self, step: str, done: int, total: int) -> None:
        if self.bar is not None and total:
            self.bar.progress(min(done / total, 1.0), text=f"Visited {done} of {total} websites")

    def step_finished(self, step: str) -> None:
        if step in self.lines:
            self.lines[step].markdown(f":green[:material/check:] {STEP_LABELS[step]}")


def execute(
    settings: Settings, repo: Repository, run: Run, category: Category, *, force: bool = False
) -> None:
    """Run (or resume) a run with live progress, then rerun the page to show the result."""
    box = st.status(run_title(run, {category.key: category}), expanded=True)
    pipeline = Pipeline(
        settings, repo, exporter_factory=exporter_factory(settings), reporter=StatusReporter(box)
    )
    handler = attach_run_log(settings.log_dir, run.id)
    try:
        asyncio.run(pipeline.execute(run.id, category, force=force))
    except RunInProgress:
        box.update(label="Already running", state="error", expanded=False)
        st.error("This run was started somewhere else (another tab or the CLI) just now.")
        return
    except LocationNotFound as exc:
        box.update(label="Location not found", state="error", expanded=False)
        select_run(None)  # nothing to show for this run
        hint = "".join(f"\n- {s}" for s in exc.suggestions)
        st.error(
            f"Couldn't find **{exc.location}**. Try a more specific name, e.g. add the province."
            + (f"\n\nClosest matches:{hint}" if hint else "")
        )
        return
    except Exception:  # the pipeline recorded it on the run; the run view shows it
        pass
    except BaseException:
        mark_interrupted(repo, run.id)
        raise
    finally:
        detach_run_log(handler)
    st.rerun()
