"""LeadHarvest web UI (V1, F12): sign in → search → live progress → results and downloads.

Run locally:  uv sync --extra ui && uv run streamlit run app/streamlit_app.py
This file sets up the page and routes between views (app/views/). Design rules: docs/UI.md.
"""

from __future__ import annotations

import streamlit as st

from leadharvest.categories import load_categories
from leadharvest.config import ConfigError, load_settings
from leadharvest.exporters.base import OSM_ATTRIBUTION, attribution
from leadharvest.storage.db import connect
from leadharvest.storage.repository import Repository

from views.common import MARK, inject_theme
from views.run import show_run
from views.search import search_page
from views.sidebar import sidebar
from views.signin import sign_in

st.set_page_config(page_title="LeadHarvest", page_icon=MARK, layout="wide")


def main() -> None:
    inject_theme()
    try:
        settings = load_settings()
    except ConfigError as exc:
        st.error(str(exc))
        st.stop()
    if not st.session_state.get("authed"):
        sign_in(settings)

    categories = load_categories(settings.categories_file)
    # One connection per script run (Streamlit runs each session in its own thread).
    repo = Repository(connect(settings.db_path))
    try:
        run_id = sidebar(repo, categories)
        run = repo.get_run(run_id) if run_id else None
        if run is None:
            search_page(settings, repo, categories, first_time=not repo.list_runs(1))
        else:
            show_run(settings, repo, run, categories)
        st.divider()
        st.caption(attribution(run, []) if run is not None else OSM_ATTRIBUTION)
    finally:
        repo.conn.close()


main()
