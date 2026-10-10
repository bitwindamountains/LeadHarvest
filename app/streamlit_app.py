"""LeadHarvest web UI (V1, F12): sign in → search → live progress → results and downloads.

Run locally:  uv sync --extra ui && uv run streamlit run app/streamlit_app.py
Look and feel: .streamlit/config.toml (theme, fonts) and app/assets/. Logic: ui_support.py.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import streamlit as st

from leadharvest.categories import Category, load_categories
from leadharvest.cli import exporter_factory
from leadharvest.config import ConfigError, Settings, load_settings
from leadharvest.exporters.base import OSM_ATTRIBUTION, attribution, export_basename
from leadharvest.geo.nominatim import LocationNotFound
from leadharvest.logging_setup import attach_run_log, detach_run_log
from leadharvest.models import Run
from leadharvest.pipeline import Pipeline, RunInProgress
from leadharvest.storage.db import connect
from leadharvest.storage.repository import Repository
from leadharvest.ui_support import (
    MAX_UI_LIMIT,
    SHOW_OPTIONS,
    SOURCE_LABELS,
    STATUS_LABELS,
    STATUS_STYLE,
    STEP_LABELS,
    TABLE_COLUMNS,
    TARGET_LABELS,
    ago,
    can_resume,
    csv_download,
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
    shown_leads,
    source_choices,
    status_markdown,
    validate_request,
    viewer_tz,
)

ASSETS = Path(__file__).parent / "assets"
LOGO, MARK = str(ASSETS / "logo.svg"), str(ASSETS / "mark.svg")

st.set_page_config(page_title="LeadHarvest", page_icon=MARK, layout="wide")


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


def open_repo(settings: Settings) -> Repository:
    """One connection per script run (Streamlit runs each session in its own thread)."""
    return Repository(connect(settings.db_path))


# ---- sign-in ------------------------------------------------------------------------------------


def brand_panel() -> str:
    """The panel beside the sign-in form (markup and CSS in app/assets/brand_panel.html)."""
    return (ASSETS / "brand_panel.html").read_text(encoding="utf-8")


def sign_in(settings: Settings) -> None:
    brand, form = st.columns([1.15, 1], gap="large", vertical_alignment="center")
    with brand:
        st.html(brand_panel())
    with form:
        st.image(MARK, width=34)
        st.header("Sign in", anchor=False)
        if not settings.ui_password:
            st.error("Set LH_UI_PASSWORD in .env (or app secrets) so strangers can't run scrapes.")
            st.stop()
        st.caption("Enter the workspace password. It's set as LH_UI_PASSWORD in `.env`.")
        with st.form("sign_in"):
            attempt = st.text_input("Password", type="password", placeholder="Workspace password")
            if st.form_submit_button(
                "Sign in", type="primary", width="stretch", icon=":material/login:"
            ):
                if password_ok(settings, attempt):
                    st.session_state["authed"] = True
                    st.rerun()
                # Slows guessing; a new session per guess gets the same delay.
                time.sleep(1)
                st.error("Wrong password. Check LH_UI_PASSWORD in `.env`.")
    st.stop()


# ---- sidebar: new search and recent runs -------------------------------------------------------


def select_run(run_id: str | None) -> None:
    """Open a run (or, with None, the search page) on the next rerun. The sidebar picker owns
    the current selection."""
    st.session_state["select_run"] = run_id


def sidebar(repo: Repository, categories: dict[str, Category]) -> str | None:
    """New search, recent runs and sign-out; returns the id of the run to show."""
    st.logo(LOGO, icon_image=MARK, size="large")
    with st.sidebar:
        if st.button("New search", icon=":material/add:", width="stretch", key="new_search"):
            select_run(None)
        runs = {run.id: run for run in repo.list_runs(15)}
        # Only write the picker's state when it must change: rewriting a widget's state on
        # every rerun makes Streamlit ignore the user's next click on it.
        if "select_run" in st.session_state:
            st.session_state["run_picker"] = st.session_state.pop("select_run")
        picked = st.session_state.get("run_picker", "unset")
        if picked is not None and picked not in runs:  # first visit, or the run aged out
            st.session_state["run_picker"] = None
        st.markdown("###### Recent runs")
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


# ---- new search ---------------------------------------------------------------------------------


def search_page(
    settings: Settings, repo: Repository, categories: dict[str, Category], first_time: bool
) -> None:
    st.header("New search", anchor=False)
    st.caption(
        "Choose a category and a place. LeadHarvest finds the businesses, visits their "
        "websites and builds the list."
    )
    problems = setup_problems(settings)
    for problem in problems:
        st.error(problem, icon=":material/settings:")
    if problems:
        return
    form_col, help_col = st.columns([1.75, 1], gap="large")
    with help_col:
        what_happens_next(first_time)
    with form_col:
        run_form(settings, repo, categories)


def what_happens_next(first_time: bool) -> None:
    with st.container(border=True):
        st.markdown("##### What happens next")
        st.markdown(
            ":material/travel_explore: **Search** the place for businesses in the category  \n"
            ":material/cleaning_services: **Clean** names and phones, and merge duplicates  \n"
            ":material/language: **Visit** each website for emails, phones and social pages  \n"
            ":material/insights: **Score** each lead and flag sales openings  \n"
            ":material/ios_share: **Export** to the files and tools you picked"
        )
        st.caption(
            "Websites are visited politely, with a pause between requests, so 100 leads take a "
            "few minutes. Keep this tab open until the run finishes. If you click elsewhere in "
            "the app, the run pauses and you can resume it from its page."
        )
    if first_time:
        st.caption(":material/history: Finished runs appear in the sidebar, newest first.")


def run_form(settings: Settings, repo: Repository, categories: dict[str, Category]) -> None:
    choices = export_choices(settings)
    with st.form("run"):
        st.markdown("##### What and where")
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
        st.markdown("##### Size and delivery")
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
        with st.expander("Advanced options", icon=":material/tune:"):
            sources = st.multiselect(
                "Data sources", source_choices(), default=["osm"],
                format_func=SOURCE_LABELS.get,
                help="Overture Maps has far more businesses, many with a phone, email or "
                "Facebook page, and its licence has no share-alike. A list that mixes in "
                "OpenStreetMap data falls under the ODbL.",
            )  # fmt: skip
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
        submitted = st.form_submit_button(
            "Find leads", type="primary", key="find", icon=":material/search:"
        )
    if not submitted:
        return
    request = validate_request(
        categories, category_key, location, int(limit), targets, js, mx, sources
    )
    if isinstance(request, list):
        for error in request:
            st.error(error)
        return
    pipeline = Pipeline(settings, repo, exporter_factory=exporter_factory(settings))
    run = pipeline.create_run(
        request.category, request.location, limit=request.limit, targets=request.targets,
        sources=request.sources, options={"js": request.js, "mx": request.mx},
    )  # fmt: skip
    select_run(run.id)
    execute(settings, repo, run, request.category)


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


# ---- run results --------------------------------------------------------------------------------


def show_run(
    settings: Settings, repo: Repository, run: Run, categories: dict[str, Category]
) -> None:
    st.subheader(run_title(run, categories), anchor=False)
    started = short_time(run.created_at, viewer_tz(st.context.timezone))
    meta = [f"Run {run.id[:8]}", f"started {started} ({ago(run.created_at)})"]
    if run.status == "completed" and run_seconds(run) >= 1:
        meta.append(f"took {duration_text(run_seconds(run))}")
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        icon, color = STATUS_STYLE[run.status]
        st.badge(STATUS_LABELS[run.status], icon=icon, color=color)
        st.caption(" · ".join(meta))
    status_banner(settings, repo, run, categories)

    leads = repo.leads_for_run(run.id)
    if not leads:
        if run.current_step == "done":
            st.info(
                "No businesses found. Try a broader area (the city rather than a barangay), a "
                "related category, or add Overture Maps under Advanced options.",
                icon=":material/search_off:",
            )
        return
    clean, score = run.stats.get("clean", {}), run.stats.get("score", {})
    total = len(leads)
    # A wrapping row, not st.columns: columns stack one per line on phones, which pushes the
    # table a full screen down.
    with st.container(horizontal=True, gap="small"):
        st.metric("Leads", total, width="content", border=True)
        st.metric("New this run", clean.get("new", "—"), help="Not seen in any earlier run.",
                  width="content", border=True)  # fmt: skip
        st.metric("With email", share(sum(1 for x in leads if x.email), total),
                  width="content", border=True)  # fmt: skip
        st.metric("With phone", share(sum(1 for x in leads if x.phone), total),
                  width="content", border=True)  # fmt: skip
        st.metric(
            "Average score",
            score.get("average_score", "—"),
            help="From 0 to 100: higher means more ways to reach the business.",
            width="content",
            border=True,
        )
    exports(settings, run)

    st.markdown("##### Leads")
    pick, action = st.columns([1.1, 2], vertical_alignment="bottom")
    show = pick.selectbox(
        "Show", list(SHOW_OPTIONS), format_func=SHOW_OPTIONS.__getitem__, key=f"show-{run.id}",
        help="Segments agencies buy, e.g. businesses with no website. Each can be downloaded.",
    )  # fmt: skip
    shown = shown_leads(leads, show)
    rows = result_rows(shown, run.category)
    if show != "all":
        # Left of the table's own toolbar, which appears top right on hover.
        with action.container(horizontal=True, vertical_alignment="center"):
            st.download_button(
                f"Download these {len(shown)} (CSV)", csv_download(shown, run.category),
                file_name=f"{export_basename(run)}-{show}.csv", icon=":material/download:",
                disabled=not shown, key=f"download-shown-{run.id}",
            )  # fmt: skip
            st.caption(f"{len(shown)} of {len(leads)} leads, all columns")
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
            "email_kind": st.column_config.TextColumn(
                "Email type", help="business, personal (a person's name) or unknown"
            ),
            "phone": "Phone",
            # Show the domain; the link keeps the full URL.
            "website": st.column_config.LinkColumn(
                "Website", display_text=r"https?://(?:www\.)?([^/]+)"
            ),
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
    running = run.status == "running"
    if running:
        st.warning(
            f"This run is marked as running (**{step}**). It may still be running in another "
            "tab or in the CLI; resuming it here too would visit every website twice. Take it "
            "over only if it stopped, for example because the app restarted mid-run."
        )
    else:
        reason = {"interrupted": "The run was interrupted.", None: ""}.get(
            run.error, f"{run.error}."
        )
        st.warning(
            f"Paused while **{step}**. {reason}  \n"
            "Resuming continues where it stopped; finished work is kept."
        )
    category = categories.get(run.category)
    label = "Take over and resume" if running else "Resume run"
    if category is None:
        st.caption(f"Category '{run.category}' is no longer configured, so it can't resume.")
    elif st.button(label, type="secondary" if running else "primary",
                   icon=":material/play_arrow:"):  # fmt: skip
        execute(settings, repo, run, category, force=running)


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
