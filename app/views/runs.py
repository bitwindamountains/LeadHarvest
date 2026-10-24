"""All runs (every run, filterable) and batch pages (one batch's rows): picking a row in their
table opens the run."""

from __future__ import annotations

import streamlit as st

from leadharvest.categories import Category
from leadharvest.models import Run
from leadharvest.storage.repository import Repository
from leadharvest.ui_runs import batch_caption, batch_name, filter_runs, run_rows
from leadharvest.ui_support import STATUS_LABELS, viewer_tz

from views.common import eyebrow, select_run


def all_runs_page(repo: Repository, categories: dict[str, Category]) -> None:
    runs = repo.list_runs(None)
    eyebrow(f"{len(runs)} runs")
    st.title("All runs", anchor=False)
    if not runs:
        st.caption("Runs you start appear here, newest first.")
        return
    with st.container(horizontal=True):
        query = st.text_input(
            "Filter", placeholder="Category, place or run id", key="runs-filter", width=320
        )
        statuses = st.multiselect(
            "Status", list(STATUS_LABELS), format_func=STATUS_LABELS.__getitem__,
            key="runs-status", width=320,
        )  # fmt: skip
    shown = filter_runs(runs, query, statuses, categories)
    if not shown:
        st.info("No runs match this filter.", icon=":material/filter_alt_off:")
        return
    st.caption(f"Showing {len(shown)} of {len(runs)} runs. Pick a row to open it.")
    runs_table(repo, shown, categories, "runs-table")


def batch_page(repo: Repository, name: str, categories: dict[str, Category]) -> None:
    runs = repo.batch_runs(name)
    eyebrow(f"Batch · {len(runs)} searches")
    st.title(name, anchor=False)
    if not runs:
        st.caption("This batch has no runs.")
        return
    counts = repo.run_lead_counts()
    st.caption(f"{batch_caption(runs, counts)}. Pick a row to open its run.")
    runs_table(repo, runs, categories, f"batch-table-{name}", counts)


def batch_link(run: Run) -> None:
    """On a batch row's run page: back to its batch."""
    if name := batch_name(run):
        st.button(
            f"Batch {name}", icon=":material/arrow_back:", type="tertiary", key="batch_link",
            on_click=st.session_state.__setitem__, args=("open_batch", name),
        )  # fmt: skip


def runs_table(
    repo: Repository, runs: list[Run], categories: dict[str, Category], key: str,
    counts: dict[str, int] | None = None,
) -> None:  # fmt: skip
    st.dataframe(
        run_rows(
            runs,
            repo.run_lead_counts() if counts is None else counts,
            categories,
            viewer_tz(st.context.timezone),
        ),
        key=key,
        hide_index=True,
        selection_mode="single-row",
        # The callback runs before the next rerun, against the rows this run showed.
        on_select=lambda: _open_picked(key, runs),
    )


def _open_picked(key: str, shown: list[Run]) -> None:
    rows = st.session_state[key]["selection"]["rows"]
    if rows:
        select_run(shown[rows[0]].id)
