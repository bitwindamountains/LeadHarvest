"""Logic behind the UI's All runs page (app/views/runs.py), testable without Streamlit."""

from __future__ import annotations

from datetime import UTC, tzinfo

from leadharvest.categories import Category
from leadharvest.models import Run
from leadharvest.ui_support import STATUS_LABELS, category_label, short_time


def filter_runs(
    runs: list[Run], query: str, statuses: list[str], categories: dict[str, Category]
) -> list[Run]:
    """Runs whose category, place or id contain every word of `query` (any case), and whose
    status is one of `statuses` (none picked: any status)."""
    words = query.casefold().split()

    def text(run: Run) -> str:
        parts = (category_label(run.category, categories), run.category, run.area_name or "",
                 run.location, run.id)  # fmt: skip
        return " ".join(parts).casefold()

    return [
        r for r in runs
        if (not statuses or r.status in statuses) and all(w in text(r) for w in words)
    ]  # fmt: skip


def run_rows(
    runs: list[Run], lead_counts: dict[str, int], categories: dict[str, Category],
    tz: tzinfo = UTC,
) -> list[dict[str, object]]:  # fmt: skip
    """One table row per run, in the order given."""
    return [
        {
            "Started": short_time(r.created_at, tz),
            "Search": f"{category_label(r.category, categories)} · {r.area_name or r.location}",
            "Status": STATUS_LABELS[r.status],
            "Leads": lead_counts.get(r.id, 0),
            "Run": r.id[:8],
        }
        for r in runs
    ]
