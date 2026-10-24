"""The run page's leads table: the Show picker, hiding leads with no way to contact them, a
download of what's shown, and the table itself."""

from __future__ import annotations

import streamlit as st

from leadharvest.exporters.base import export_basename, reachable
from leadharvest.models import Lead, Run
from leadharvest.ui_support import (
    SHOW_OPTIONS,
    TABLE_COLUMNS,
    TABLE_ROW_PX,
    csv_download,
    result_rows,
    shown_leads,
    table_height,
)

_col = st.column_config
# Business stays pinned while the table scrolls sideways. Pixel widths fit typical content: a
# 180 px pin still leaves room on phones, 240 px fits most emails, 280 px fits two openings.
COLUMN_CONFIG = {
    "business_name": _col.TextColumn("Business", width=180, pinned=True),
    "score": _col.ProgressColumn(
        "Score",
        min_value=0,
        max_value=100,
        format="%d",
        width="small",
        help="From 0 to 100: higher means more ways to reach the business.",
    ),
    "flags": _col.ListColumn(
        "Openings", width=280, help="Sales openings, e.g. no website or no HTTPS."
    ),
    # Email and phone are mailto:/tel: links (one click to write or call); show the address.
    "email": _col.LinkColumn("Email", width=240, display_text=r"mailto:(.*)"),
    "email_kind": _col.TextColumn(
        "Email type", width="small", help="business, personal (a person's name) or unknown"
    ),
    "phone": _col.LinkColumn("Phone", width=160, display_text=r"tel:(.*)"),
    "messenger": _col.LinkColumn(
        "Messenger",
        width=100,  # "small" clips the header
        display_text="Message",
        help="Opens a chat with the business's Facebook page.",
    ),
    # Show the domain; the link keeps the full URL.
    "website": _col.LinkColumn(
        "Website", width="medium", display_text=r"https?://(?:www\.)?([^/]+)"
    ),
    "facebook": _col.LinkColumn("Facebook", width="small", display_text="Facebook"),
    "instagram": _col.LinkColumn("Instagram", width="small", display_text="Instagram"),
    "address": _col.TextColumn("Address", width="large"),
    "city": _col.TextColumn("City", width="small"),
    "tech": _col.TextColumn("Site platform", width="small"),
    "opening_hours": _col.TextColumn("Opening hours", width="medium"),
}


def leads_table(run: Run, leads: list[Lead]) -> None:
    st.header("Leads", anchor=False)
    pick, action = st.columns([1.1, 2], vertical_alignment="bottom")
    show = pick.selectbox(
        "Show", list(SHOW_OPTIONS), format_func=SHOW_OPTIONS.__getitem__, key=f"show-{run.id}",
        help="Segments agencies buy, e.g. businesses with no website. Each can be downloaded.",
    )  # fmt: skip
    shown = shown_leads(leads, show)
    hidden = sum(1 for x in shown if not reachable(x))
    # Always drawn, with a fixed label: a widget that disappears or is relabelled loses its
    # state, so switching segments would turn hiding back on.
    with st.container(horizontal=True, vertical_alignment="center"):
        hide = st.toggle(
            "Hide leads with no way to contact", value=True, key=f"hide-unreachable-{run.id}",
            disabled=not hidden, help="No email, phone, website or social page was found.",
        )  # fmt: skip
        if hide and hidden:
            shown = [x for x in shown if reachable(x)]
            st.caption(f"{hidden} hidden")
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
        st.info(
            "None of these leads has a way to contact them; turn off the switch to see them."
            if hidden else "No leads in this segment for this run.",
            icon=":material/filter_alt_off:",
        )  # fmt: skip
        return
    st.dataframe(
        result_rows(shown, run.category), hide_index=True, width="stretch", placeholder="—",
        column_order=TABLE_COLUMNS, column_config=COLUMN_CONFIG,
        row_height=TABLE_ROW_PX, height=table_height(len(shown)),
    )  # fmt: skip
    clean, enrich = run.stats.get("clean", {}), run.stats.get("enrich", {})
    dups = len(clean.get("possible_duplicates", [])) + len(enrich.get("possible_duplicates", []))
    if dups:
        st.caption(f"{dups} possible duplicate(s) to review; the run log lists the lead ids.")
