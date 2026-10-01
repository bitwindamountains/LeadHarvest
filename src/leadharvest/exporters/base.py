"""Exporter protocol, managed columns, and row building (blueprint sections 10.7, 10.7b)."""

from __future__ import annotations

import re
from typing import Protocol

from leadharvest.models import ExportResult, Lead, Run

OSM_ATTRIBUTION = (
    "Data © OpenStreetMap contributors, ODbL 1.0 — https://www.openstreetmap.org/copyright"
)

MANAGED_COLUMNS: tuple[str, ...] = (
    "lead_id", "business_name", "category", "phone", "phones_extra", "email", "emails_extra",
    "website", "facebook", "instagram", "linkedin", "tiktok", "address", "city", "score",
    "flags", "tech", "opening_hours", "lat", "lon", "sources", "updated_at",
)  # fmt: skip
PHONE_COLUMNS = frozenset({"phone", "phones_extra"})
NUMERIC_COLUMNS = frozenset({"lat", "lon", "score"})


class ExportError(Exception):
    """An export target failed after retries. The run becomes `partial`."""


class Exporter(Protocol):
    name: str

    def export(self, leads: list[Lead], run: Run) -> ExportResult: ...


def lead_to_row(lead: Lead, category: str) -> dict[str, str | float | int | None]:
    return {
        "lead_id": lead.lead_id,
        "business_name": lead.business_name,
        "category": category,
        "phone": lead.phone,
        "phones_extra": ", ".join(lead.phones_extra),
        "email": lead.email,
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
