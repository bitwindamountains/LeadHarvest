"""Search page: the run form beside a "What happens next" guide."""

from __future__ import annotations

import streamlit as st

from leadharvest.categories import Category
from leadharvest.cli import exporter_factory
from leadharvest.config import Settings
from leadharvest.pipeline import Pipeline
from leadharvest.sources.overture import default_source_names
from leadharvest.storage.repository import Repository
from leadharvest.ui_support import (
    MAX_UI_LIMIT,
    SOURCE_LABELS,
    TARGET_LABELS,
    export_choices,
    setup_problems,
    source_choices,
    validate_request,
)

from views.common import execute, eyebrow, select_run

REGION_NAMES = {"PH": "Philippines"}


def search_page(
    settings: Settings, repo: Repository, categories: dict[str, Category], first_time: bool
) -> None:
    eyebrow(f"Lead search · {REGION_NAMES.get(settings.default_region, settings.default_region)}")
    st.title("New search", anchor=False)
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
    with st.container(border=True, key="lh-card-guide"):
        st.header("What happens next", anchor=False)
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
        st.header("What and where", anchor=False)
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
        st.header("Size and delivery", anchor=False)
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
                "Data sources", source_choices(), default=default_source_names(),
                format_func=SOURCE_LABELS.get,
                help="Overture Maps is the default: far more businesses, many with a phone, "
                "email or Facebook page, and its licence has no share-alike. Adding "
                "OpenStreetMap can find a few more, but the list then falls under the ODbL.",
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
