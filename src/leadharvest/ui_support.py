"""Logic behind the Streamlit UI (app/streamlit_app.py), kept here so it is testable without it."""

from __future__ import annotations

import hmac
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import phonenumbers

from leadharvest.categories import Category
from leadharvest.config import ConfigError, Settings
from leadharvest.enrich.render import playwright_installed
from leadharvest.exporters.base import lead_to_row
from leadharvest.models import Lead, Run
from leadharvest.sources.overture import duckdb_installed
from leadharvest.storage.repository import Repository

MAX_UI_LIMIT = 1000


def password_ok(settings: Settings, attempt: str) -> bool:
    """Constant-time comparison. An empty configured password never matches."""
    expected = settings.ui_password
    if not expected or not attempt:
        return False
    return hmac.compare_digest(expected.encode("utf-8"), attempt.encode("utf-8"))


def setup_problems(settings: Settings) -> list[str]:
    """Reasons the UI cannot run scrapes; shown instead of the form."""
    problems = []
    if not settings.ui_password:
        problems.append(
            "Set LH_UI_PASSWORD in .env (or app secrets) so strangers can't run scrapes."
        )
    try:
        settings.require_network_identity()
    except ConfigError as exc:
        problems.append(str(exc))
    return problems


def export_choices(settings: Settings) -> list[str]:
    choices = ["csv", "xlsx"]
    if settings.google_sheet_id and settings.google_service_account_file.is_file():
        choices.append("sheets")
    if settings.hubspot_access_token:
        choices.append("hubspot")
    return choices


@dataclass
class RunRequest:
    category: Category
    location: str
    limit: int
    targets: list[str]
    js: bool = False
    mx: bool = True
    sources: list[str] = field(default_factory=lambda: ["osm"])
    errors: list[str] = field(default_factory=list)


def validate_request(
    categories: dict[str, Category],
    category_key: str,
    location: str,
    limit: int,
    targets: list[str],
    js: bool,
    mx: bool,
    sources: list[str] | None = None,
) -> RunRequest | list[str]:
    errors = []
    if category_key not in categories:
        errors.append("Choose a category.")
    location = " ".join(location.split())
    if len(location) < 3:
        errors.append('Enter a location, e.g. "Makati, Philippines".')
    if not 1 <= limit <= MAX_UI_LIMIT:
        errors.append(f"Limit must be between 1 and {MAX_UI_LIMIT}.")
    if not targets:
        errors.append("Choose at least one export.")
    if js and not playwright_installed():
        errors.append("JS rendering needs Playwright installed on the server.")
    sources = ["osm"] if sources is None else sources
    if not sources:
        errors.append("Choose at least one data source.")
    if "overture" in sources and not duckdb_installed():
        errors.append("Overture Maps needs DuckDB on the server (uv sync --extra overture).")
    if errors:
        return errors
    return RunRequest(categories[category_key], location, limit, targets, js, mx, sources)


def source_choices() -> list[str]:
    return ["osm", "overture"] if duckdb_installed() else ["osm"]


# ---- presentation -------------------------------------------------------------------------------

SOURCE_LABELS = {
    "osm": "OpenStreetMap",
    "overture": "Overture Maps (incl. Facebook pages)",
}
TARGET_LABELS = {
    "csv": "CSV",
    "xlsx": "Excel (XLSX)",
    "sheets": "Google Sheets",
    "hubspot": "HubSpot",
}
STEP_LABELS = {
    "search": "Searching for businesses",
    "clean": "Cleaning and removing duplicates",
    "enrich": "Visiting their websites",
    "score": "Scoring leads",
    "export": "Exporting",
}
STATUS_LABELS = {"completed": "Completed", "partial": "Paused", "failed": "Failed",
                 "running": "Running"}  # fmt: skip
STATUS_ICONS = {"completed": "✅", "partial": "⏸️", "failed": "❌", "running": "⏳"}
FLAG_LABELS = {
    "no_website": "No website",
    "social_only": "Social media only",
    "no_https": "No HTTPS",
    "no_mobile_viewport": "Not mobile-friendly",
    "free_email_provider": "Free email address",
    "stale_site": "Old website",
    "no_analytics": "No analytics or ad pixel",
    "no_online_booking": "No online booking",
}
# Columns shown in the results table, in order; the rest stay in the downloads.
TABLE_COLUMNS = (
    "business_name", "score", "email", "email_kind", "phone", "website", "facebook", "instagram", "address",
    "city", "flags", "tech", "opening_hours",
)  # fmt: skip


def can_resume(run: Run) -> bool:
    """Paused runs, and runs left "running" when the app stopped mid-run."""
    return run.status in ("partial", "running") and run.current_step != "done"


def mark_interrupted(repo: Repository, run_id: str) -> None:
    """Any click in Streamlit while a run is in progress stops the script with a BaseException
    the pipeline doesn't record. Mark the run paused so it can be resumed."""
    run = repo.get_run(run_id)
    if run is not None and run.status == "running":
        repo.update_run(run_id, status="partial", error="interrupted")


def category_label(key: str, categories: dict[str, Category]) -> str:
    return categories[key].label if key in categories else key


def run_title(run: Run, categories: dict[str, Category]) -> str:
    return f"{category_label(run.category, categories)} in {run.area_name or run.location}"


def run_labels(runs: list[Run], categories: dict[str, Category]) -> dict[str, str]:
    """Picker labels by run id. Streamlit tells radio options apart by their label, so repeat
    runs of one search (e.g. a weekly monitor) get a short run id to stay distinct."""
    base = {r.id: f"{category_label(r.category, categories)} · {r.area_name or r.location}"
            for r in runs}  # fmt: skip
    counts = Counter(base.values())
    return {rid: f"{text} · #{rid[:6]}" if counts[text] > 1 else text for rid, text in base.items()}


def viewer_tz(name: str | None) -> tzinfo:
    """The browser's time zone (st.context.timezone), or UTC if unknown."""
    try:
        return ZoneInfo(name) if name else UTC
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


def short_time(iso: str, tz: tzinfo = UTC) -> str:
    """'2026-10-08T16:20:05+00:00' → 'Oct 9, 00:20' in Manila; 'Oct 8, 16:20 UTC' in UTC."""
    when = datetime.fromisoformat(iso).astimezone(tz)
    return f"{when:%b} {when.day}, {when:%H:%M}" + (" UTC" if tz is UTC else "")


def ago(iso: str, now: datetime | None = None) -> str:
    """'5 min ago', '3 h ago', '2 days ago': a run left "running" for hours stands out."""
    seconds = ((now or datetime.now(UTC)) - datetime.fromisoformat(iso)).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    days = int(seconds // 86400)
    return "yesterday" if days == 1 else f"{days} days ago"


def display_phone(phone: str | None) -> str | None:
    """'+639171234567' → '+63 917 123 4567' for reading; exports keep the E.164 form."""
    if not phone:
        return phone
    try:
        number = phonenumbers.parse(phone)
    except phonenumbers.NumberParseException:
        return phone
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)


def run_seconds(run: Run) -> float:
    return sum(
        float(step.get("seconds", 0)) for step in run.stats.values() if isinstance(step, dict)
    )


def duration_text(seconds: float) -> str:
    minutes, secs = divmod(round(seconds), 60)
    return f"{minutes} min {secs} s" if minutes else f"{secs} s"


def result_rows(leads: list[Lead], category: str) -> list[dict[str, object]]:
    """Table rows, best leads first, with readable flags."""
    rows = []
    for lead in sorted(leads, key=lambda x: -(x.score or 0)):  # stable: ties keep run order
        row = lead_to_row(lead, category)
        row["flags"] = ", ".join(FLAG_LABELS.get(f, f) for f in lead.flags)
        row["phone"] = display_phone(lead.phone)
        rows.append(row)
    return rows


def sheet_url(settings: Settings) -> str | None:
    if not settings.google_sheet_id:
        return None
    return f"https://docs.google.com/spreadsheets/d/{settings.google_sheet_id}"


def share(count: int, total: int) -> str:
    return f"{count} ({count * 100 // total}%)" if total else "0"
