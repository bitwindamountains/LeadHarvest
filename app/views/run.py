"""Run page: status, the numbers, downloads, then the segment picker and the leads table."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from leadharvest.categories import Category
from leadharvest.config import Settings
from leadharvest.models import Lead, Run
from leadharvest.segments import segment_counts
from leadharvest.storage.repository import Repository
from leadharvest.ui_jobs import JOBS
from leadharvest.ui_support import (
    RUNS_SCANNED,
    SOURCE_LABELS,
    STATUS_LABELS,
    STATUS_STYLE,
    STEP_LABELS,
    TARGET_LABELS,
    ago,
    can_resume,
    coverage,
    duration_text,
    group_runs,
    percent,
    run_seconds,
    run_title,
    score_bands,
    sheet_url,
    short_time,
    viewer_tz,
)

from views.common import execute, eyebrow, live_progress
from views.leads import leads_table
from views.runs import batch_link


def show_run(
    settings: Settings, repo: Repository, run: Run, categories: dict[str, Category]
) -> None:
    run_header(run, categories)
    batch_link(run)
    run_history(repo, run)
    job = JOBS.get(run.id)
    if job is not None and job.running:
        live_progress(run.id, run_title(run, categories))
        return
    if job is not None and job.message:  # replaces the banner: it says what to do instead
        st.error(job.message)
    else:
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
    eyebrow(f"Run {run.id[:8]}")
    st.title(run_title(run, categories), anchor=False)
    started = short_time(run.created_at, viewer_tz(st.context.timezone))
    meta = [f"Started {started} ({ago(run.created_at)})"]
    if run.status == "completed" and run_seconds(run) >= 1:
        meta.append(f"took {duration_text(run_seconds(run))}")
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        icon, color = STATUS_STYLE[run.status]
        st.badge(STATUS_LABELS[run.status], icon=icon, color=color)
        st.caption(" · ".join(meta))


def run_history(repo: Repository, run: Run) -> None:
    """Earlier runs of the same search (the sidebar lists each search once, by its latest run)."""
    group = next(
        (g for g in group_runs(repo.list_runs(RUNS_SCANNED)) if any(r.id == run.id for r in g)),
        [run],
    )
    if len(group) < 2:
        return
    tz = viewer_tz(st.context.timezone)
    # Options are the labels themselves (with a short id, so two runs never share one); the
    # callback maps the picked label back to its run.
    by_label: dict[str, str] = {}
    for r in group:
        text = f"{short_time(r.created_at, tz)} · {STATUS_LABELS[r.status]}"
        text += f" · {repo.count_run_leads(r.id)} leads · #{r.id[:6]}"
        by_label[f"{text} · latest" if r is group[0] else text] = r.id
    labels = list(by_label)
    key = f"history-{run.id}"
    st.selectbox(
        f"Run history ({len(group)} runs of this search)",
        labels,
        index=list(by_label.values()).index(run.id),
        key=key,
        width=480,
        on_change=_open_run,
        args=(key, by_label),
    )


def _open_run(key: str, by_label: dict[str, str]) -> None:
    """Runs before the rerun, so the sidebar returns the picked run instead of the latest."""
    st.session_state["open_run"] = by_label[st.session_state[key]]


def numbers(run: Run, leads: list[Lead]) -> None:
    clean, score = run.stats.get("clean", {}), run.stats.get("score", {})
    total, new, average = len(leads), clean.get("new"), score.get("average_score")
    email = sum(1 for x in leads if x.email)
    phone = sum(1 for x in leads if x.phone)
    # theme.css draws each meter from its card's --lh-fill (0 to 1).
    fills = {
        "email": percent(email, total) / 100,
        "phone": percent(phone, total) / 100,
    }
    rules = "".join(f".st-key-lh-kpi-{k} {{ --lh-fill: {v:.3f}; }}" for k, v in fills.items())
    st.html(f"<style>{rules}</style>")
    # Not st.columns, which stacks one per line on phones and pushes the table a screen down.
    # theme.css lays "lh-numbers" out as a ledger bento: a tall Leads card beside the meters.
    quiet = {"delta_color": "off", "delta_arrow": "off", "border": True}
    with st.container(horizontal=True, gap="small", key="lh-numbers"):
        with st.container(key="lh-kpi-leads"):
            st.metric(
                "Leads",
                total,
                None if new is None else f"{new} new this run",
                help="Businesses in this run. New means not seen in any earlier run.",
                **(quiet | {"border": False}),  # the container is the card here
            )
            segment_ledger(run, leads)
        for name, label, count in (("email", "With email", email), ("phone", "With phone", phone)):
            with st.container(key=f"lh-kpi-{name}"):
                st.metric(label, count, coverage(count, total), **quiet)
        with st.container(key="lh-kpi-score"):
            st.metric(
                "Average score",
                "—" if average is None else round(average),
                None if average is None else "out of 100 · higher = easier to reach",
                help="From 0 to 100: higher means more ways to reach the business.",
                **(quiet | {"border": False}),  # the container is the card here
            )
            score_histogram(leads)


def score_histogram(leads: list[Lead]) -> None:
    """The score card's right half: leads per score band as bars scaled to the fullest band.
    No average marker: a mean drawn over a few, often bimodal, leads misleads. st.html strips
    <svg>, so it is plain elements."""
    bands = score_bands(leads)
    tallest = max((n for _, n in bands), default=0) or 1
    bars = "".join(
        f'<li class="{"is-zero" if n == 0 else ""}" style="--h: {n / tallest:.3f}">'
        f'<span class="lh-col"><b>{n}<span class="lh-sr"> scored</span></b>'
        f'<i aria-hidden="true"></i></span><small>{label}</small></li>'
        for label, n in bands
    )
    st.html(
        f'<figure class="lh-hist"><figcaption>Leads by score</figcaption>'
        f'<div class="lh-hist-plot"><ol>{bars}</ol></div></figure>'
    )


def segment_ledger(run: Run, leads: list[Lead]) -> None:
    """The Leads card's lower half: one row per segment, ruled like a ledger with dot leaders.
    A row filters the leads table to that segment (a check marks it); again shows all leads."""
    show_key = f"show-{run.id}"  # the table's Show selectbox
    current = st.session_state.get(show_key, "all")
    # Segments overlap (a lead with no website can also lack booking), so counts can sum past
    # the total; the heading says so.
    st.html('<p class="lh-ledger-head">Segments <span>· a lead can be in several</span></p>')
    with st.container(key="lh-ledger", gap=None):
        for key, label, count in segment_counts(leads):
            st.button(
                f"{label} **{count}**",
                key=f"lh-seg-{key}",
                type="tertiary",
                width="stretch",
                icon=":material/check:" if key == current else None,
                disabled=count == 0 and key != current,
                on_click=toggle_show,
                args=(show_key, key),
            )


def toggle_show(show_key: str, segment: str) -> None:
    """Runs before the rerun, so the selectbox below picks the new value up."""
    st.session_state[show_key] = "all" if st.session_state.get(show_key) == segment else segment


def status_banner(
    settings: Settings, repo: Repository, run: Run, categories: dict[str, Category]
) -> None:
    log_file = settings.log_dir / f"run-{run.id}.jsonl"
    if run.status == "failed":
        st.error(f"This run failed: {run.error or 'unknown error'}. Details: `{log_file}`")
        return
    for name, error in (run.stats.get("search", {}).get("source_errors") or {}).items():
        st.warning(
            f"**{SOURCE_LABELS.get(name, name)}** was skipped because it failed ({error}). "
            "These leads come from the other sources only; start a new run later to include it.",
            icon=":material/cloud_off:",
        )
    if not can_resume(run):
        return
    step = STEP_LABELS.get(run.current_step, run.current_step).lower()
    running = run.status == "running"
    if running:
        st.warning(
            f"This run is marked as running (**{step}**), but not by this app. It may still be "
            "running in the CLI; resuming it here too would visit every website twice. Take it "
            "over only if it stopped, for example because the app restarted mid-run."
        )
    else:
        reason = {
            "interrupted": "The run was interrupted.",
            "stopped": "You stopped it.",
            None: "",
        }.get(run.error, f"{run.error}.")
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
        execute(settings, run, category, force=running)


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
                if skipped := result.get("rows_skipped"):
                    st.caption(f"{skipped} rows you deleted from the Sheet were left out")
            else:
                st.caption(
                    f"{kind}: {result['rows_appended']} added, {result['rows_updated']} updated"
                )
