"""Logic behind the Streamlit UI (app/streamlit_app.py), kept here so it is testable without it."""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field

from leadharvest.categories import Category
from leadharvest.config import ConfigError, Settings
from leadharvest.enrich.render import playwright_installed

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
    errors: list[str] = field(default_factory=list)


def validate_request(
    categories: dict[str, Category],
    category_key: str,
    location: str,
    limit: int,
    targets: list[str],
    js: bool,
    mx: bool,
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
    if errors:
        return errors
    return RunRequest(categories[category_key], location, limit, targets, js, mx)
