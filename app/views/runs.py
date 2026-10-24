"""All runs: every run in one filterable table; picking a row opens it."""

from __future__ import annotations

import streamlit as st

from leadharvest.categories import Category
from leadharvest.models import Run
from leadharvest.storage.repository import Repository
from leadharvest.ui_runs import filter_runs, run_rows
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
    st.dataframe(
        run_rows(shown, repo.run_lead_counts(), categories, viewer_tz(st.context.timezone)),
        key="runs-table",
        hide_index=True,
        selection_mode="single-row",
        # The callback runs before the next rerun, against the rows this run showed.
        on_select=lambda: _open_picked(shown),
    )


def _open_picked(shown: list[Run]) -> None:
    rows = st.session_state["runs-table"]["selection"]["rows"]
    if rows:
        select_run(shown[rows[0]].id)
