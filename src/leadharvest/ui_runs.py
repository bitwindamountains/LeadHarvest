"""Logic behind the UI's run lists (app/views/runs.py: All runs and batch pages; the sidebar's
batch entries), testable without Streamlit."""

from __future__ import annotations

from datetime import UTC, tzinfo

from leadharvest.categories import Category
from leadharvest.models import Run
from leadharvest.ui_support import STATUS_LABELS, category_label, search_key, short_time


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


def batch_name(run: Run) -> str | None:
    """The batch a run belongs to (options.batch, see batch.py), if any."""
    batch = run.options.get("batch")
    return batch if isinstance(batch, str) else None


def entry_key(run: Run) -> tuple[str, str]:
    """Sidebar entries: a batch's runs share one entry, any other run its search's."""
    batch = batch_name(run)
    return ("batch", batch) if batch else search_key(run)


def batch_caption(runs: list[Run], lead_counts: dict[str, int]) -> str:
    """'3 of 4 completed · 25 leads' for a batch's runs."""
    done = sum(r.status == "completed" for r in runs)
    leads = sum(lead_counts.get(r.id, 0) for r in runs)
    return f"{done} of {len(runs)} completed · {leads} leads"
