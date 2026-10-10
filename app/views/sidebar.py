"""Sidebar: logo, New search, run history and sign-out."""

from __future__ import annotations

import streamlit as st

from leadharvest.categories import Category
from leadharvest.storage.repository import Repository
from leadharvest.ui_support import ago, run_labels, status_markdown

from views.common import LOGO, MARK, select_run

HISTORY_SIZE = 15


def sidebar(repo: Repository, categories: dict[str, Category]) -> str | None:
    """Returns the id of the run to show, or None for the search page."""
    st.logo(LOGO, icon_image=MARK, size="large")
    with st.sidebar:
        if st.button("New search", icon=":material/add:", width="stretch", key="new_search"):
            select_run(None)
        runs = {run.id: run for run in repo.list_runs(HISTORY_SIZE)}
        # Only write the picker's state when it must change: rewriting a widget's state on
        # every rerun makes Streamlit ignore the user's next click on it.
        if "select_run" in st.session_state:
            st.session_state["run_picker"] = st.session_state.pop("select_run")
        picked = st.session_state.get("run_picker", "unset")
        if picked is not None and picked not in runs:  # first visit, or the run aged out
            st.session_state["run_picker"] = None
        st.header("Recent runs", anchor=False)
        choice = None
        if not runs:
            st.caption("Runs you start appear here, newest first.")
        else:
            labels = run_labels(list(runs.values()), categories)
            choice = st.radio(
                "Recent runs",
                list(runs),
                key="run_picker",
                label_visibility="collapsed",
                format_func=labels.__getitem__,
                captions=[
                    f"{status_markdown(r.status)} · {ago(r.created_at)} · "
                    f"{repo.count_run_leads(r.id)} leads"
                    for r in runs.values()
                ],
            )
        st.divider()
        if st.button("Sign out", icon=":material/logout:", type="tertiary"):
            st.session_state.clear()
            st.rerun()
    return choice
