"""Logic behind the Streamlit UI (app/streamlit_app.py), kept here so it is testable without it."""

from __future__ import annotations

import hmac
import io
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import phonenumbers

from leadharvest.categories import Category
from leadharvest.clean.normalize import messenger_link
from leadharvest.config import ConfigError, Settings
from leadharvest.enrich.render import playwright_installed
from leadharvest.exporters.base import lead_to_row
from leadharvest.exporters.csv_export import write_rows
from leadharvest.models import Lead, Run
from leadharvest.segments import SEGMENTS, apply_segment
from leadharvest.sources.overture import default_source_names, duckdb_installed

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
    sources: list[str] = field(default_factory=default_source_names)
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
    sources = default_source_names() if sources is None else sources
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
# Status as (Material icon, Streamlit colour): badges in the run header, coloured icons in lists.
STATUS_STYLE = {
    "completed": (":material/check_circle:", "green"),
    "partial": (":material/pause_circle:", "orange"),
    "failed": (":material/error:", "red"),
    "running": (":material/progress_activity:", "blue"),
}


def status_markdown(status: str) -> str:
    """':green[:material/check_circle:] Completed' for captions and other markdown."""
    icon, color = STATUS_STYLE[status]
    return f":{color}[{icon}] {STATUS_LABELS[status]}"


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
# Columns shown in the results table, in order: who, how good, the sales openings, how to reach
# them, then where. The rest stay in the downloads.
TABLE_COLUMNS = (
    "business_name", "score", "flags", "email", "email_kind", "phone", "messenger", "website",
    "facebook", "instagram", "address", "city", "tech", "opening_hours",
)  # fmt: skip


def can_resume(run: Run) -> bool:
    """Paused runs, and runs left "running" when the app stopped mid-run."""
    return run.status in ("partial", "running") and run.current_step != "done"


def category_label(key: str, categories: dict[str, Category]) -> str:
    return categories[key].label if key in categories else key


def run_title(run: Run, categories: dict[str, Category]) -> str:
    return f"{category_label(run.category, categories)} in {run.area_name or run.location}"


RUNS_SCANNED = 500  # recent runs the sidebar groups; older searches drop off its list


def search_key(run: Run) -> tuple[str, str]:
    """Runs of one search share a category and place (the resolved area name, else the text
    typed), compared without case or extra spaces."""
    return run.category, " ".join((run.area_name or run.location).casefold().split())


def group_runs(
    runs: list[Run], key: Callable[[Run], tuple[str, str]] = search_key
) -> list[list[Run]]:
    """Runs grouped by `key` (by default the search), in the input order: newest runs in,
    newest group first and each group's newest run first."""
    groups: dict[tuple[str, str], list[Run]] = {}
    for run in runs:
        groups.setdefault(key(run), []).append(run)
    return list(groups.values())


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


# "Show" picker over the results table: everything, anything with an email, or a segment.
SHOW_OPTIONS = {
    "all": "All leads",
    "has-email": "Has an email",
    **{key: segment.label for key, segment in SEGMENTS.items()},
}


def shown_leads(leads: list[Lead], show: str) -> list[Lead]:
    if show == "all":
        return leads
    if show == "has-email":
        return [lead for lead in leads if lead.email]
    return apply_segment(show, leads)


def csv_download(leads: list[Lead], category: str) -> bytes:
    """The same CSV as an export (escaped cells, UTF-8 with BOM for Excel), in memory."""
    buffer = io.StringIO()
    write_rows(buffer, leads, category)
    return buffer.getvalue().encode("utf-8-sig")


def result_rows(leads: list[Lead], category: str) -> list[dict[str, object]]:
    """Table rows, best leads first, with flags as readable labels (shown as chips) and email
    and phone as links that open the mail app or dialler."""
    rows = []
    for lead in sorted(leads, key=lambda x: -(x.score or 0)):  # stable: ties keep run order
        row = lead_to_row(lead, category)
        row["flags"] = [FLAG_LABELS.get(f, f) for f in lead.flags]
        row["email"] = f"mailto:{lead.email}" if lead.email else None
        row["phone"] = _tel_link(lead.phone) if lead.phone else None
        row["messenger"] = messenger_link(lead.facebook)
        rows.append(row)
    return rows


def _tel_link(phone: str) -> str:
    """'+639171234567' → 'tel:%2B63-917-123-4567'. Hyphens are tel: URIs' visual separators
    (RFC 3966; spaces aren't allowed), and the table decodes a bare '+' in link text to a space."""
    return "tel:" + str(display_phone(phone)).replace(" ", "-").replace("+", "%2B")


def sheet_url(settings: Settings) -> str | None:
    if not settings.google_sheet_id:
        return None
    return f"https://docs.google.com/spreadsheets/d/{settings.google_sheet_id}"


TABLE_ROW_PX = 35  # st.dataframe's default row height, set explicitly so the maths holds


def table_height(rows: int) -> int:
    """Header plus up to 10 rows, plus room for the horizontal scrollbar: theme.css draws it
    16 px tall inside the grid, which st.dataframe's "auto" height ignores (clipping a row)."""
    return TABLE_ROW_PX * (min(rows, 10) + 1) + 2 + 18


SCORE_BANDS = ("0–19", "20–39", "40–59", "60–79", "80–100")  # noqa: RUF001 (display en dashes)


def score_bands(leads: list[Lead]) -> list[tuple[str, int]]:
    """Leads per 20-point score band (100 falls in the top one). Unscored leads are left out."""
    counts = [0] * len(SCORE_BANDS)
    for lead in leads:
        if lead.score is not None:
            counts[min(max(lead.score, 0) // 20, len(SCORE_BANDS) - 1)] += 1
    return list(zip(SCORE_BANDS, counts, strict=True))


def percent(count: int, total: int) -> int:
    """Whole-number share, rounded down so 99.6% never reads as a complete 100%."""
    return count * 100 // total if total else 0


PERCENT_MIN_LEADS = 20  # below this, a percentage claims more precision than the count has


def coverage(count: int, total: int) -> str:
    """The line under a count ("of 5 leads"), with the share only once there are enough leads."""
    share = f" · {percent(count, total)}%" if total >= PERCENT_MIN_LEADS else ""
    return f"of {total} leads{share}"
