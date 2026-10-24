"""Sidebar: logo, New search, run history (one entry per search or batch), All runs and
sign-out."""

from __future__ import annotations

import streamlit as st

from leadharvest.categories import Category
from leadharvest.models import Run
from leadharvest.storage.repository import Repository
from leadharvest.ui_runs import batch_caption, batch_name, entry_key
from leadharvest.ui_support import RUNS_SCANNED, ago, group_runs, run_labels, status_markdown

from views.common import LOGO, MARK, select_run

HISTORY_SIZE = 15  # entries listed; a search's earlier runs are on the run page's history picker


def sidebar(repo: Repository, categories: dict[str, Category]) -> str | None:
    """Returns the id of the run to show, or None for the search page. Session state's
    `all_runs` and `open_batch` (set here, cleared by `select_run`) take precedence."""
    st.logo(LOGO, icon_image=MARK, size="large")
    with st.sidebar:
        if st.button("New search", icon=":material/add:", width="stretch", key="new_search"):
            select_run(None)
        groups = group_runs(repo.list_runs(RUNS_SCANNED), key=entry_key)[:HISTORY_SIZE]
        # The picker's options are each search's latest run; `owner` maps any run to them.
        latest = {group[0].id: group for group in groups}
        owner = {run.id: group[0].id for group in groups for run in group}
        batches = {rid: name for rid in latest if (name := batch_name(latest[rid][0]))}
        # Only write the picker's state when it must change: rewriting a widget's state on
        # every rerun makes Streamlit ignore the user's next click on it.
        if "select_run" in st.session_state:
            wanted = st.session_state.pop("select_run")
            st.session_state["run_picker"] = owner.get(wanted)
            st.session_state["open_run"] = wanted
        picked = st.session_state.get("run_picker", "unset")
        if picked is not None and picked not in latest:
            # First visit, a newer run of the search took its place, or the search aged out.
            st.session_state["run_picker"] = owner.get(picked)
        st.header("Recent runs", anchor=False)
        choice = None
        if not groups:
            st.caption("Runs you start appear here, newest first.")
        else:
            searches = [group[0] for group in groups if group[0].id not in batches]
            labels = run_labels(searches, categories)
            labels |= {rid: f"Batch · {name}" for rid, name in batches.items()}
            counts = repo.run_lead_counts()
            choice = st.radio(
                "Recent runs",
                list(latest),
                key="run_picker",
                label_visibility="collapsed",
                format_func=labels.__getitem__,
                captions=[_caption(repo, group, counts) for group in groups],
                on_change=_open_entry,
                args=(batches,),
            )
        st.button(
            "All runs", icon=":material/history:", type="tertiary", key="all_runs_button",
            on_click=_show_all_runs,
        )  # fmt: skip
        st.divider()
        if st.button("Sign out", icon=":material/logout:", type="tertiary"):
            st.session_state.clear()
            st.rerun()
    if choice is None:
        return None
    opened = st.session_state.get("open_run")  # an earlier run picked on the run page
    return opened if opened is not None and owner.get(opened) == choice else choice


def _open_entry(batches: dict[str, str]) -> None:
    """Picking a batch opens its page; picking a search opens its latest run, not an earlier
    one picked before."""
    st.session_state.pop("open_run", None)
    st.session_state.pop("all_runs", None)
    st.session_state["open_batch"] = batches.get(st.session_state["run_picker"])


def _show_all_runs() -> None:
    select_run(None)  # clears the picker, so any search can be picked from the page again
    st.session_state["all_runs"] = True


def _caption(repo: Repository, group: list[Run], counts: dict[str, int]) -> str:
    """A batch's progress and age, or a search's latest run status, age and leads, plus how
    many runs the search has had."""
    run = group[0]
    if name := batch_name(run):
        return f"{batch_caption(repo.batch_runs(name), counts)} · {ago(run.created_at)}"
    leads = counts.get(run.id, 0)
    text = f"{status_markdown(run.status)} · {ago(run.created_at)} · {leads} leads"
    return f"{text} · {len(group)} runs" if len(group) > 1 else text
