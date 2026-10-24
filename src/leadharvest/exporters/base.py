"""Exporter protocol, managed columns, and row building (blueprint sections 10.7, 10.7b)."""

from __future__ import annotations

import re
from typing import Protocol

from leadharvest.models import ExportResult, Lead, Run, utcnow_iso

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
    "score", "flags", "why_contact", "tech", "opening_hours", "lat", "lon", "sources",
    "updated_at",
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


# Flags as sales openings in plain words, in the order a pitch would lead with them.
_REASONS = {
    "social_only": "only on social media, no website",
    "no_website": "no website",
    "no_https": "website isn't secure (no HTTPS)",
    "no_mobile_viewport": "website isn't mobile-friendly",
    "stale_site": "website looks out of date",
    "no_online_booking": "no online booking",
    "free_email_provider": "uses a free email address",
    "no_analytics": "no analytics or ad tracking",
}
MAX_REASONS = 2  # one short line; the flags column has them all


def why_contact(flags: list[str]) -> str:
    """'Only on social media, no website; uses a free email address': the lead's top sales
    openings, or '' when it has none."""
    skip = {"no_website"} if "social_only" in flags else set()  # already said
    reasons = [text for flag, text in _REASONS.items() if flag in flags and flag not in skip]
    line = "; ".join(reasons[:MAX_REASONS])
    return line[:1].upper() + line[1:]


def reachable(lead: Lead) -> bool:
    """Any way to contact the business: an email, phone, website or social page."""
    return any((lead.email, lead.phone, lead.website, lead.facebook, lead.instagram,
                lead.linkedin, lead.tiktok))  # fmt: skip


def _share(count: int, total: int) -> str:
    return f"{count} ({count * 100 // total}%)" if total else "0"


def run_summary(run: Run, leads: list[Lead]) -> list[tuple[str, str]]:
    """What a client sees first: how complete the list is, how many leads have each sales
    opening (worded as in why_contact) and what was filtered out."""
    clean = run.stats.get("clean", {})
    outcomes = run.stats.get("enrich", {}).get("outcomes", {})
    total = len(leads)
    return [
        ("Leads", str(total)),
        ("New this run", str(clean.get("new", "—"))),
        ("Reachable (email, phone, website or social)", _share(sum(map(reachable, leads)), total)),
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
        *(
            (f"Opening: {text}", _share(sum(1 for x in leads if flag in x.flags), total))
            for flag, text in _REASONS.items()
        ),
        ("Duplicates merged", str(clean.get("duplicates_merged", 0))),
        ("Removed on request (suppressed)", str(clean.get("suppressed", 0))),
        ("Websites not read (robots.txt)", str(outcomes.get("robots_blocked", 0))),
    ]


def about_rows(run: Run, leads: list[Lead]) -> list[tuple[str, str]]:
    """The summary every export carries (XLSX "About" sheet, CSV .about.txt, Sheets summary
    tab): attribution, what was searched, then run_summary."""
    return [
        ("Attribution", attribution(run, leads)),
        ("Category", run.category),
        ("Location", run.location),
        ("Run ID", run.id),
        ("Exported at (UTC)", utcnow_iso()),
        *run_summary(run, leads),
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
        "why_contact": why_contact(lead.flags),
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
