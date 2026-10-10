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


SEGMENTS: dict[str, Segment] = {
    "no-website": Segment("No website", lambda x: not x.website),
    "facebook-only": Segment("Social media only (no website)", lambda x: "social_only" in x.flags),
    "website-upgrade": Segment(
        "Website needs work (no HTTPS, not mobile-friendly or old)",
        lambda x: bool(x.website) and bool(_UPGRADE_FLAGS.intersection(x.flags)),
    ),
    "no-booking": Segment("No online booking", lambda x: "no_online_booking" in x.flags),
    "business-email": Segment(
        "Has a business email (not a person's name)",
        lambda x: bool(x.email) and email_kind(x.email, x.name_key) != "personal",
    ),
}


def apply_segment(name: str, leads: list[Lead]) -> list[Lead]:
    return [lead for lead in leads if SEGMENTS[name].keep(lead)]
