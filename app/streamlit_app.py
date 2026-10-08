"""LeadHarvest web UI (V1, F12): form → progress → results and downloads. Password-protected.

Run locally:  uv sync --extra ui && uv run streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import streamlit as st

from leadharvest.categories import Category, load_categories
from leadharvest.cli import exporter_factory
from leadharvest.config import ConfigError, Settings, load_settings
from leadharvest.exporters.base import OSM_ATTRIBUTION
from leadharvest.geo.nominatim import LocationNotFound
from leadharvest.logging_setup import attach_run_log, detach_run_log
from leadharvest.models import Run
from leadharvest.pipeline import Pipeline
from leadharvest.storage.db import connect
from leadharvest.storage.repository import Repository
from leadharvest.ui_support import (
    MAX_UI_LIMIT,
    STATUS_ICONS,
    STATUS_LABELS,
    STEP_LABELS,
    TABLE_COLUMNS,
    TARGET_LABELS,
    can_resume,
    duration_text,
    export_choices,
    mark_interrupted,
    password_ok,
    result_rows,
    run_labels,
    run_seconds,
    run_title,
    setup_problems,
    share,
    sheet_url,
    short_time,
    validate_request,
)

st.set_page_config(page_title="LeadHarvest", page_icon="🌾", layout="wide")

TAGLINE = "Find businesses, enrich them from their own websites, and export clean leads."


class StatusReporter:
    """Pipeline progress inside an st.status box: one line per step, a bar for websites."""

    def __init__(self, box: Any) -> None:
        self.box = box
        self.lines: dict[str, Any] = {}
        self.bar: Any = None

    def step_started(self, step: str, total: int | None = None) -> None:
        self.box.update(label=f"{STEP_LABELS[step]}…")
        self.lines[step] = self.box.empty()
        self.lines[step].markdown(f"⏳ {STEP_LABELS[step]}…")
        if step == "enrich":
            self.bar = self.box.progress(0.0)

    def step_progress(self, step: str, done: int, total: int) -> None:
        if self.bar is not None and total:
            self.bar.progress(min(done / total, 1.0), text=f"Visited {done} of {total} websites")

    def step_finished(self, step: str) -> None:
        if step in self.lines:
            self.lines[step].markdown(f"✓ {STEP_LABELS[step]}")


def open_repo(settings: Settings) -> Repository:
    """One connection per script run (Streamlit runs each session in its own thread)."""
    return Repository(connect(settings.db_path))


# ---- sign-in ------------------------------------------------------------------------------------


def sign_in(settings: Settings) -> None:
    _, middle, _ = st.columns([1, 1.2, 1])
    with middle:
        st.title("🌾 LeadHarvest")
        st.caption(TAGLINE)
        if not settings.ui_password:
            st.error("Set LH_UI_PASSWORD in .env (or app secrets) so strangers can't run scrapes.")
            st.stop()
        with st.form("sign_in"):
            attempt = st.text_input("Password", type="password")
            if st.form_submit_button("Sign in", type="primary", width="stretch"):
                if password_ok(settings, attempt):
                    st.session_state["authed"] = True
                    st.rerun()
                st.error("Wrong password.")
    st.stop()


# ---- sidebar: recent runs -----------------------------------------------------------------------


def select_run(run_id: str | None) -> None:
    """Open a run on the next rerun (the sidebar picker owns the current selection)."""
    st.session_state["select_run"] = run_id


def sidebar(repo: Repository, categories: dict[str, Category]) -> str | None:
    """Recent runs; returns the id of the run to show."""
    with st.sidebar:
        st.header("Recent runs")
        runs = {run.id: run for run in repo.list_runs(15)}
        # Only write the picker's state when it must change: rewriting a widget's state on
        # every rerun makes Streamlit ignore the user's next click on it.
        if "select_run" in st.session_state:
            st.session_state["run_picker"] = st.session_state.pop("select_run")
        picked = st.session_state.get("run_picker", "unset")
        if picked is not None and picked not in runs:  # first visit, or the run aged out
            st.session_state["run_picker"] = None
        choice = None
        if not runs:
            st.caption("Your runs will appear here.")
        else:
            labels = run_labels(list(runs.values()), categories)
            choice = st.radio(
                "Recent runs",
                list(runs),
                key="run_picker",
                label_visibility="collapsed",
                format_func=labels.__getitem__,
                captions=[
                    f"{STATUS_ICONS[r.status]} {STATUS_LABELS[r.status]} · "
                    f"{short_time(r.created_at)} · {repo.count_run_leads(r.id)} leads"
                    for r in runs.values()
                ],
            )
        st.divider()
        if st.button("Sign out", icon=":material/logout:", type="tertiary"):
            st.session_state.clear()
            st.rerun()
    return choice


# ---- new run form -------------------------------------------------------------------------------


def run_form(settings: Settings, repo: Repository, categories: dict[str, Category]) -> None:
    choices = export_choices(settings)
    with st.form("run", border=False):  # the "New search" expander already frames it
        # One st.columns row per pair, so phones stack the fields in reading order.
        left, right = st.columns(2)
        category_key = left.selectbox(
            "Category", list(categories), format_func=lambda k: categories[k].label
        )
        location = right.text_input(
            "Location",
            placeholder="Makati, Philippines",
            help="A city, municipality or barangay. Add the province if the name is common.",
        )
        left, right = st.columns(2)
        limit = left.number_input(
            "Max leads", 1, MAX_UI_LIMIT, 100, step=50,
            help="The run keeps the first businesses found, up to this number.",
        )  # fmt: skip
        targets = right.multiselect(
            "Export to", choices, default=["csv", "xlsx"], format_func=TARGET_LABELS.get
        )
        if len(choices) < len(TARGET_LABELS):
            right.caption("Google Sheets and HubSpot appear here once set up in .env.")
        with st.expander("Advanced options"):
            js = st.checkbox(
                "Render JavaScript-only websites",
                help="Opens near-empty sites in a headless browser to find their contacts. "
                "Slower, and needs Playwright on the server.",
            )
            mx = st.checkbox(
                "Drop emails whose domain can't receive mail",
                value=settings.mx_check,
                help="Checks each email domain's mail (MX) records before export.",
            )
        submitted = st.form_submit_button("Find leads", type="primary", key="find")
    st.caption(
        "Websites are visited politely, with a pause between requests, so 100 leads take a few "
        "minutes. Keep this tab open and don't click elsewhere in the app until the run "
        "finishes; if you do, the run pauses and you can resume it."
    )
    if not submitted:
        return
    request = validate_request(categories, category_key, location, int(limit), targets, js, mx)
    if isinstance(request, list):
        for error in request:
            st.error(error)
        return
    pipeline = Pipeline(settings, repo, exporter_factory=exporter_factory(settings))
    run = pipeline.create_run(
        request.category, request.location, limit=request.limit, targets=request.targets,
        options={"js": request.js, "mx": request.mx},
    )  # fmt: skip
    select_run(run.id)
    execute(settings, repo, run, request.category)


def execute(settings: Settings, repo: Repository, run: Run, category: Category) -> None:
    """Run (or resume) a run with live progress, then rerun the page to show the result."""
    box = st.status(run_title(run, {category.key: category}), expanded=True)
    pipeline = Pipeline(
        settings, repo, exporter_factory=exporter_factory(settings), reporter=StatusReporter(box)
    )
    handler = attach_run_log(settings.log_dir, run.id)
    try:
        asyncio.run(pipeline.execute(run.id, category))
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


# ---- run results --------------------------------------------------------------------------------


def show_run(
    settings: Settings, repo: Repository, run: Run, categories: dict[str, Category]
) -> None:
    st.divider()
    st.subheader(run_title(run, categories))
    meta = [f"Run {run.id[:8]}", f"started {short_time(run.created_at)}"]
    if run.status == "completed" and run_seconds(run) >= 1:
        meta.append(f"took {duration_text(run_seconds(run))}")
    st.caption(" · ".join(meta))
    status_banner(settings, repo, run, categories)

    leads = repo.leads_for_run(run.id)
    if not leads:
        if run.current_step == "done":
            st.info(
                "No businesses found. Try a broader area (the city rather than a barangay) or a "
                "related category."
            )
        return
    clean, score = run.stats.get("clean", {}), run.stats.get("score", {})
    total = len(leads)
    cols = st.columns(5)
    cols[0].metric("Leads", total)
    cols[1].metric("New this run", clean.get("new", "—"), help="Not seen in any earlier run.")
    cols[2].metric("With email", share(sum(1 for x in leads if x.email), total))
    cols[3].metric("With phone", share(sum(1 for x in leads if x.phone), total))
    cols[4].metric(
        "Average score",
        score.get("average_score", "—"),
        help="From 0 to 100: higher means more ways to reach the business.",
    )
    exports(settings, run)

    rows = result_rows(leads, run.category)
    if st.toggle("Only leads with an email", key=f"email-only-{run.id}"):
        rows = [r for r in rows if r["email"]]
    st.dataframe(
        rows,
        hide_index=True,
        width="stretch",
        placeholder="—",
        column_order=TABLE_COLUMNS,
        column_config={
            "business_name": "Business",
            "score": st.column_config.ProgressColumn(
                "Score", min_value=0, max_value=100, format="%d"
            ),
            "email": "Email",
            "phone": "Phone",
            "website": st.column_config.LinkColumn("Website"),
            "facebook": st.column_config.LinkColumn("Facebook", display_text="Open"),
            "instagram": st.column_config.LinkColumn("Instagram", display_text="Open"),
            "address": "Address",
            "city": "City",
            "flags": "Flags",
            "tech": "Site platform",
            "opening_hours": "Opening hours",
        },
    )
    dups = len(clean.get("possible_duplicates", [])) + len(
        run.stats.get("enrich", {}).get("possible_duplicates", [])
    )
    if dups:
        st.caption(f"{dups} possible duplicate(s) to review; the run log lists the lead ids.")


def status_banner(
    settings: Settings, repo: Repository, run: Run, categories: dict[str, Category]
) -> None:
    log_file = settings.log_dir / f"run-{run.id}.jsonl"
    if run.status == "failed":
        st.error(f"This run failed: {run.error or 'unknown error'}. Details: `{log_file}`")
        return
    if not can_resume(run):
        return
    step = STEP_LABELS.get(run.current_step, run.current_step).lower()
    if run.status == "running":
        st.warning(
            "This run is marked as running. If it isn't running in another tab (for example, "
            "the app restarted mid-run), resume it here."
        )
    else:
        reason = "The run was interrupted." if run.error == "interrupted" else f"{run.error}."
        st.warning(
            f"Paused while **{step}**. {reason}  \n"
            "Resuming continues where it stopped; finished work is kept."
        )
    category = categories.get(run.category)
    if category is None:
        st.caption(f"Category '{run.category}' is no longer configured, so it can't resume.")
    elif st.button("Resume run", type="primary", icon=":material/play_arrow:"):
        execute(settings, repo, run, category)


def exports(settings: Settings, run: Run) -> None:
    results = run.stats.get("export_results", [])
    if not results:
        return
    with st.container(horizontal=True):
        for i, result in enumerate(results):
            path = Path(result["target"])
            kind = TARGET_LABELS.get(result["exporter"], result["exporter"])
            if path.suffix in (".csv", ".xlsx") and path.is_file():
                newly = " (new since last run)" if path.stem.endswith("-new") else ""
                st.download_button(
                    f"Download {kind}{newly}", path.read_bytes(), file_name=path.name,
                    icon=":material/download:", key=f"download-{i}",
                )  # fmt: skip
            elif result["exporter"] == "sheets" and (url := sheet_url(settings)):
                st.link_button(f"Open {kind}", url, icon=":material/open_in_new:")
            else:
                st.caption(
                    f"{kind}: {result['rows_appended']} added, {result['rows_updated']} updated"
                )


# ---- page ---------------------------------------------------------------------------------------


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as exc:
        st.error(str(exc))
        st.stop()
    if not st.session_state.get("authed"):
        sign_in(settings)

    categories = load_categories(settings.categories_file)
    repo = open_repo(settings)
    try:
        run_id = sidebar(repo, categories)
        st.title("🌾 LeadHarvest")
        st.caption(TAGLINE)
        run = repo.get_run(run_id) if run_id else None
        problems = setup_problems(settings)
        for problem in problems:
            st.error(problem)
        if not problems:
            # Collapsed while a run is open, so its results are the first thing on the page.
            with st.expander("New search", expanded=run is None, icon=":material/search:"):
                run_form(settings, repo, categories)
        if run is not None:
            show_run(settings, repo, run, categories)
        st.caption(OSM_ATTRIBUTION)
    finally:
        repo.conn.close()


main()
