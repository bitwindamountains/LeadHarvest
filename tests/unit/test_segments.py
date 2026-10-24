"""Named lead segments."""

from __future__ import annotations

from typing import Any

from leadharvest.models import Lead, utcnow_iso
from leadharvest.segments import SEGMENTS, apply_segment, reachable, segment_counts


def lead(name: str, **kw: Any) -> Lead:
    now = utcnow_iso()
    return Lead(business_name=name, name_key=name.lower(), first_seen_run_id="r",
                first_seen_at=now, last_seen_at=now, updated_at=now, **kw)  # fmt: skip


LEADS = [
    lead("Bare"),
    lead("Social", facebook="https://facebook.com/s", flags=["no_website", "social_only"]),
    lead("Old Site", website="https://old.ph", flags=["stale_site", "no_online_booking"]),
    lead("Good Site", website="https://good.ph", email="maria.santos@good.ph"),
    lead("Mail", website="https://mail.ph", email="info@mail.ph", flags=["no_https"]),
]


def names(segment: str) -> list[str]:
    return [x.business_name for x in apply_segment(segment, LEADS)]


def test_segments() -> None:
    assert names("no-website") == ["Bare", "Social"]
    assert names("facebook-only") == ["Social"]
    assert names("website-upgrade") == ["Old Site", "Mail"]
    assert names("no-booking") == ["Old Site"]
    assert names("business-email") == ["Mail"]  # maria.santos@ is a person's name
    assert all(s.label for s in SEGMENTS.values())


def test_segment_counts_match_the_segments() -> None:
    assert segment_counts(LEADS) == [(k, s.short, len(names(k))) for k, s in SEGMENTS.items()]
    assert all(n == 0 for _, _, n in segment_counts([]))


def test_reachable_needs_any_way_to_contact() -> None:
    assert [x.business_name for x in LEADS if not reachable(x)] == ["Bare"]
    for field in ("email", "phone", "website", "facebook", "instagram", "linkedin", "tiktok"):
        assert reachable(lead("One", **{field: "x"})), field
    assert not reachable(lead("Map pin only", address="1 Rizal St", lat=10.0, lon=123.0))
