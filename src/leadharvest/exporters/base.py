"""Exporter protocol, managed columns, and row building (blueprint sections 10.7, 10.7b)."""

from __future__ import annotations

import re
from typing import Protocol

from leadharvest.models import ExportResult, Lead, Run

OSM_ATTRIBUTION = (
    "Data © OpenStreetMap contributors, ODbL 1.0 — https://www.openstreetmap.org/copyright"
)
# Overture's per-source lines (docs.overturemaps.org/attribution), for every Places provider.
OVERTURE_ATTRIBUTION = (
    "Places data from Overture Maps Foundation (overturemaps.org): data from Meta, Microsoft, "
    "BrightQuery, PinMeTo, DAC, Krick and RenderSEO, available under CDLA Permissive 2.0; data "
    "from AllThePlaces, available under CC0 1.0; data from Foursquare, available under Apache "
    "2.0, Copyright 2024 Foursquare Labs, Inc., notice: "
    "https://opensource.foursquare.com/places-notice-txt/"
)


def attribution(run: Run, leads: list[Lead]) -> str:
    """Attribution for the sources behind these leads (earlier runs may have added some)."""
    used = set(run.sources) | {source for lead in leads for source in lead.sources}
    lines = [OVERTURE_ATTRIBUTION] if "overture" in used else []
    if "osm" in used or not lines:
        lines.insert(0, OSM_ATTRIBUTION)
    return "\n".join(lines)


MANAGED_COLUMNS: tuple[str, ...] = (
    "lead_id", "business_name", "category", "phone", "phones_extra", "email", "email_kind",
    "emails_extra", "website", "facebook", "instagram", "linkedin", "tiktok", "address", "city",
    "score", "flags", "tech", "opening_hours", "lat", "lon", "sources", "updated_at",
)  # fmt: skip
PHONE_COLUMNS = frozenset({"phone", "phones_extra"})
NUMERIC_COLUMNS = frozenset({"lat", "lon", "score"})


class ExportError(Exception):
    """An export target failed after retries. The run becomes `partial`."""


class Exporter(Protocol):
    name: str

    def export(self, leads: list[Lead], run: Run) -> ExportResult: ...


# Mailboxes that belong to a function, not a person.
_ROLE_MAILBOXES = frozenset({
    "info", "contact", "contactus", "hello", "hi", "admin", "sales", "support", "office",
    "inquiry", "inquiries", "enquiry", "enquiries", "appointment", "appointments", "booking",
    "bookings", "reservation", "reservations", "hr", "careers", "jobs", "billing", "accounts",
    "accounting", "marketing", "clinic", "frontdesk", "reception", "mail", "email", "team",
    "service", "services", "customerservice", "cs", "help", "general", "main", "management",
})  # fmt: skip
_PERSON_LIKE = re.compile(r"(?:dra?\.?)?([a-z]{2,})[._-]([a-z]{2,})(?:[._-][a-z]{1,})?\d*")
_DOCTOR = re.compile(r"dra?[._-]?[a-z]{3,}\d*")  # dr.reyes, drajose: a named doctor


def email_kind(email: str | None, name_key: str = "") -> str:
    """'business' (info@, or named after the business), 'personal' (looks like a person's
    name, e.g. maria.santos@: personal data under RA 10173), or 'unknown'. A heuristic label
    for clients to filter on, not a verdict."""
    if not email:
        return ""
    local = email.split("@", 1)[0].lower()
    words = {re.sub(r"\d+$", "", w) for w in re.split(r"[._+-]", local)}  # inquiries2 → inquiries
    business_words = {w for w in name_key.split() if len(w) >= 3}
    if words & _ROLE_MAILBOXES or any(w in local for w in business_words):
        return "business"
    match = _PERSON_LIKE.fullmatch(local)
    if match and not {match.group(1), match.group(2)} & _ROLE_MAILBOXES:
        return "personal"
    if _DOCTOR.fullmatch(local):
        return "personal"
    return "unknown"


def _share(count: int, total: int) -> str:
    return f"{count} ({count * 100 // total}%)" if total else "0"


def run_summary(run: Run, leads: list[Lead]) -> list[tuple[str, str]]:
    """What a client sees first: how complete the list is and what was filtered out."""
    clean = run.stats.get("clean", {})
    outcomes = run.stats.get("enrich", {}).get("outcomes", {})
    total = len(leads)
    return [
        ("Leads", str(total)),
        ("New this run", str(clean.get("new", "—"))),
        ("With email", _share(sum(1 for x in leads if x.email), total)),
        ("With phone", _share(sum(1 for x in leads if x.phone), total)),
        ("With website", _share(sum(1 for x in leads if x.website), total)),
        (
            "With Facebook or Instagram",
            _share(sum(1 for x in leads if x.facebook or x.instagram), total),
        ),
        (
            "Personal-name emails (email_kind)",
            str(sum(1 for x in leads if email_kind(x.email, x.name_key) == "personal")),
        ),
        ("Duplicates merged", str(clean.get("duplicates_merged", 0))),
        ("Removed on request (suppressed)", str(clean.get("suppressed", 0))),
        ("Websites not read (robots.txt)", str(outcomes.get("robots_blocked", 0))),
    ]


def lead_to_row(lead: Lead, category: str) -> dict[str, str | float | int | None]:
    return {
        "lead_id": lead.lead_id,
        "business_name": lead.business_name,
        "category": category,
        "phone": lead.phone,
        "phones_extra": ", ".join(lead.phones_extra),
        "email": lead.email,
        "email_kind": email_kind(lead.email, lead.name_key),
        "emails_extra": ", ".join(lead.emails_extra),
        "website": lead.website,
        "facebook": lead.facebook,
        "instagram": lead.instagram,
        "linkedin": lead.linkedin,
        "tiktok": lead.tiktok,
        "address": lead.address,
        "city": lead.city,
        "score": lead.score,
        "flags": ", ".join(lead.flags),
        "tech": ", ".join(lead.tech),
        "opening_hours": lead.opening_hours,
        "lat": lead.lat,
        "lon": lead.lon,
        "sources": ", ".join(lead.sources),
        "updated_at": lead.updated_at,
    }


def safe_filename(text: str, max_len: int = 60) -> str:
    cleaned = re.sub(r"[^\w\-]+", "-", text.strip().lower()).strip("-")
    return (cleaned or "export")[:max_len]


def export_basename(run: Run) -> str:
    area = run.area_name or run.location
    return f"{safe_filename(run.category)}-{safe_filename(area)}-{run.id[:8]}"
