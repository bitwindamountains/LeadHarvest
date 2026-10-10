"""Run page: status, the numbers, downloads, then the segment picker and the leads table."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from leadharvest.categories import Category
from leadharvest.config import Settings
from leadharvest.exporters.base import export_basename
from leadharvest.models import Lead, Run
from leadharvest.storage.repository import Repository
from leadharvest.ui_support import (
    SHOW_OPTIONS,
    STATUS_LABELS,
    STATUS_STYLE,
    STEP_LABELS,
    TABLE_COLUMNS,
    TARGET_LABELS,
    ago,
    can_resume,
    csv_download,
    duration_text,
    result_rows,
    run_seconds,
    run_title,
    share,
    sheet_url,
    short_time,
    shown_leads,
    viewer_tz,
)

from views.common import execute

COLUMN_CONFIG = {
    "business_name": "Business",
    "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
    "email": "Email",
    "email_kind": st.column_config.TextColumn(
        "Email type", help="business, personal (a person's name) or unknown"
    ),
    "phone": "Phone",
    # Show the domain; the link keeps the full URL.
    "website": st.column_config.LinkColumn("Website", display_text=r"https?://(?:www\.)?([^/]+)"),
    "facebook": st.column_config.LinkColumn("Facebook", display_text="Open"),
    "instagram": st.column_config.LinkColumn("Instagram", display_text="Open"),
    "address": "Address",
    "city": "City",
    "flags": "Flags",
    "tech": "Site platform",
    "opening_hours": "Opening hours",
}


def show_run(
    settings: Settings, repo: Repository, run: Run, categories: dict[str, Category]
) -> None:
    run_header(run, categories)
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
    numbers(run, leads)
    exports(settings, run)
    leads_table(run, leads)


def run_header(run: Run, categories: dict[str, Category]) -> None:
    st.title(run_title(run, categories), anchor=False)
    started = short_time(run.created_at, viewer_tz(st.context.timezone))
    meta = [f"Run {run.id[:8]}", f"started {started} ({ago(run.created_at)})"]
    if run.status == "completed" and run_seconds(run) >= 1:
        meta.append(f"took {duration_text(run_seconds(run))}")
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        icon, color = STATUS_STYLE[run.status]
        st.badge(STATUS_LABELS[run.status], icon=icon, color=color)
        st.caption(" · ".join(meta))


def numbers(run: Run, leads: list[Lead]) -> None:
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


def leads_table(run: Run, leads: list[Lead]) -> None:
    st.header("Leads", anchor=False)
    pick, action = st.columns([1.1, 2], vertical_alignment="bottom")
    show = pick.selectbox(
        "Show", list(SHOW_OPTIONS), format_func=SHOW_OPTIONS.__getitem__, key=f"show-{run.id}",
        help="Segments agencies buy, e.g. businesses with no website. Each can be downloaded.",
    )  # fmt: skip
    shown = shown_leads(leads, show)
    if show != "all":
        # Left of the table's own toolbar, which appears top right on hover.
        with action.container(horizontal=True, vertical_alignment="center"):
            st.download_button(
                f"Download these {len(shown)} (CSV)", csv_download(shown, run.category),
                file_name=f"{export_basename(run)}-{show}.csv", icon=":material/download:",
                disabled=not shown, key=f"download-shown-{run.id}",
            )  # fmt: skip
            st.caption(f"{len(shown)} of {len(leads)} leads, all columns")
    if not shown:
        st.info("No leads in this segment for this run.", icon=":material/filter_alt_off:")
        return
    st.dataframe(
        result_rows(shown, run.category), hide_index=True, width="stretch", placeholder="—",
        column_order=TABLE_COLUMNS, column_config=COLUMN_CONFIG,
    )  # fmt: skip
    clean, enrich = run.stats.get("clean", {}), run.stats.get("enrich", {})
    dups = len(clean.get("possible_duplicates", [])) + len(enrich.get("possible_duplicates", []))
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
