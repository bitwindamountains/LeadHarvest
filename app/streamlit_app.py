"""LeadHarvest web UI (V1, F12): form → progress → table → downloads. Password-protected.

Run locally:  uv sync --extra ui && uv run streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import streamlit as st

from leadharvest.categories import load_categories
from leadharvest.cli import exporter_factory
from leadharvest.config import ConfigError, load_settings
from leadharvest.exporters.base import OSM_ATTRIBUTION, lead_to_row
from leadharvest.geo.nominatim import LocationNotFound
from leadharvest.pipeline import Pipeline
from leadharvest.storage.db import connect
from leadharvest.storage.repository import Repository
from leadharvest.ui_support import (
    MAX_UI_LIMIT,
    export_choices,
    password_ok,
    setup_problems,
    validate_request,
)

st.set_page_config(page_title="LeadHarvest", page_icon="🌾", layout="wide")


class StreamlitReporter:
    def __init__(self) -> None:
        self.status = st.empty()
        self.bar = st.progress(0.0)

    def step_started(self, step: str, total: int | None = None) -> None:
        self.status.write(f"**{step.capitalize()}**…")

    def step_progress(self, step: str, done: int, total: int) -> None:
        if total:
            self.bar.progress(min(done / total, 1.0), text=f"{step}: {done}/{total}")

    def step_finished(self, step: str) -> None:
        self.bar.progress(1.0, text=f"{step}: done")


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as exc:
        st.error(str(exc))
        st.stop()

    st.title("LeadHarvest")
    problems = setup_problems(settings)
    if problems:
        for problem in problems:
            st.error(problem)
        st.stop()

    if not st.session_state.get("authed"):
        attempt = st.text_input("Password", type="password")
        if st.button("Sign in"):
            if password_ok(settings, attempt):
                st.session_state["authed"] = True
                st.rerun()
            st.error("Wrong password.")
        st.stop()

    categories = load_categories(settings.categories_file)
    with st.form("run"):
        left, right = st.columns(2)
        category_key = left.selectbox(
            "Category", list(categories), format_func=lambda k: categories[k].label
        )
        location = right.text_input("Location", placeholder="Makati, Philippines")
        limit = left.number_input("Max leads", 1, MAX_UI_LIMIT, 100)
        choices = export_choices(settings)
        targets = right.multiselect("Export to", choices, default=["csv", "xlsx"])
        js = left.checkbox("Render JavaScript-only sites (slower)")
        mx = right.checkbox("Drop emails on dead domains", value=settings.mx_check)
        submitted = st.form_submit_button("Find leads", type="primary")

    if submitted:
        request = validate_request(categories, category_key, location, int(limit), targets, js, mx)
        if isinstance(request, list):
            for error in request:
                st.error(error)
            st.stop()
        conn = connect(settings.db_path)  # one connection per script run (Streamlit threads)
        try:
            repo = Repository(conn)
            pipeline = Pipeline(
                settings,
                repo,
                exporter_factory=exporter_factory(settings),
                reporter=StreamlitReporter(),
            )
            run = pipeline.create_run(
                request.category,
                request.location,
                limit=request.limit,
                targets=request.targets,
                options={"js": request.js, "mx": request.mx},
            )
            try:
                result = asyncio.run(pipeline.execute(run.id, request.category))
            except LocationNotFound as exc:
                st.error(f"Location not found: {exc.location}. Try a more specific name.")
                if exc.suggestions:
                    st.write("Closest matches:", exc.suggestions)
                st.stop()
            st.session_state["last_run"] = result.id
        finally:
            conn.close()

    run_id = st.session_state.get("last_run")
    if run_id:
        show_run(settings, run_id)
    st.caption(OSM_ATTRIBUTION)


def show_run(settings, run_id: str) -> None:
    conn = connect(settings.db_path)
    try:
        repo = Repository(conn)
        run = repo.get_run(run_id)
        if run is None:
            return
        leads = repo.leads_for_run(run.id)
        clean = run.stats.get("clean", {})
        a, b, c, d = st.columns(4)
        a.metric("Leads", len(leads))
        b.metric("New", clean.get("new", 0))
        c.metric("With email", sum(1 for x in leads if x.email))
        d.metric("Avg score", run.stats.get("score", {}).get("average_score", "-"))
        if run.status != "completed":
            st.warning(
                f"Run is {run.status}: {run.error or ''} — resume it from the CLI with "
                f"`leadharvest resume --run {run.id[:8]}`."
            )
        st.dataframe(
            [lead_to_row(x, run.category) for x in leads], use_container_width=True, hide_index=True
        )
        for result in run.stats.get("export_results", []):
            path = Path(result["target"])
            if path.suffix in (".csv", ".xlsx") and path.is_file():
                st.download_button(
                    f"Download {path.suffix[1:].upper()}", path.read_bytes(), file_name=path.name
                )
            else:
                st.write(f"Exported to {result['target']}")
    finally:
        conn.close()


main()
