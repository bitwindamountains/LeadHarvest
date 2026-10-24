"""Named lead segments: the lists agencies buy ("dental clinics with no website", "Facebook only").

Each is a filter over a run's scored leads; `leadharvest export --segment NAME` writes it as its
own CSV/XLSX next to the full list.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from leadharvest.exporters.base import email_kind
from leadharvest.models import Lead

_UPGRADE_FLAGS = frozenset({"no_https", "no_mobile_viewport", "stale_site"})


@dataclass(frozen=True)
class Segment:
    label: str
    keep: Callable[[Lead], bool]
    short: str  # for tight spots, like the run page's ledger


SEGMENTS: dict[str, Segment] = {
    "no-website": Segment("No website", lambda x: not x.website, "No website"),
    "facebook-only": Segment(
        "Social media only (no website)", lambda x: "social_only" in x.flags, "Social only"
    ),
    "website-upgrade": Segment(
        "Website needs work (no HTTPS, not mobile-friendly or old)",
        lambda x: bool(x.website) and bool(_UPGRADE_FLAGS.intersection(x.flags)),
        "Site needs work",
    ),
    "no-booking": Segment(
        "No online booking", lambda x: "no_online_booking" in x.flags, "No online booking"
    ),
    "business-email": Segment(
        "Has a business email (not a person's name)",
        lambda x: bool(x.email) and email_kind(x.email, x.name_key) != "personal",
        "Business email",
    ),
}


def reachable(lead: Lead) -> bool:
    """Any way to contact the business: an email, phone, website or social page."""
    return any((lead.email, lead.phone, lead.website, lead.facebook, lead.instagram,
                lead.linkedin, lead.tiktok))  # fmt: skip


def segment_counts(leads: list[Lead]) -> list[tuple[str, str, int]]:
    """Each segment's name, short label and how many of these leads it holds, in SEGMENTS order."""
    return [(k, s.short, sum(1 for x in leads if s.keep(x))) for k, s in SEGMENTS.items()]


def apply_segment(name: str, leads: list[Lead]) -> list[Lead]:
    return [lead for lead in leads if SEGMENTS[name].keep(lead)]
