"""Website facts and the sales flags derived from them; email labels; the export summary."""

from __future__ import annotations

from typing import Any

from leadharvest.enrich.signals import site_signals
from leadharvest.exporters.base import email_kind, run_summary
from leadharvest.models import Lead, Run, utcnow_iso
from leadharvest.scoring import score_lead, site_flags
from leadharvest.storage.repository import Repository

GA = '<script async src="https://www.googletagmanager.com/gtag/js?id=G-X1"></script>'
PIXEL = "<script>!function(f){}(window);fbq('init', '123');</script>"
SERIOUSMD = '<a href="https://seriousmd.com/doctor/dr-reyes">Book a visit</a>'


def lead(**kw: Any) -> Lead:
    now = utcnow_iso()
    data: dict[str, Any] = {
        "business_name": "Smile Dental", "name_key": "smile dental", "categories": ["dentist"],
        "first_seen_run_id": "r", "first_seen_at": now, "last_seen_at": now, "updated_at": now,
    }  # fmt: skip
    data.update(kw)
    return Lead(**data)


def test_site_signals_reads_year_analytics_and_booking() -> None:
    html = f"<footer>&copy; 2012 &ndash; 2018 Smile Dental. Copyright 2016</footer>{GA}{PIXEL}"
    assert site_signals(html, 2026) == ["copyright:2018", "analytics:google", "pixel:meta"]
    assert site_signals("<p>© 2031 future</p><p>Book now!</p>", 2026) == []  # no platform link
    assert site_signals(SERIOUSMD, 2026) == ["booking:seriousmd"]
    assert site_signals("<p>Copyright 2015-2024</p>", 2026) == ["copyright:2024"]


def test_site_flags_only_for_read_sites_and_appointment_categories() -> None:
    assert site_flags(lead(site_signals=None), 2026) == []  # not read: no guesses
    stale = lead(site_signals=["copyright:2023"])
    assert site_flags(stale, 2026) == ["stale_site", "no_analytics", "no_online_booking"]
    fresh = lead(site_signals=["copyright:2024", "pixel:meta", "booking:calendly"])
    assert site_flags(fresh, 2026) == []
    cafe = lead(categories=["cafe"], site_signals=["analytics:google"])
    assert site_flags(cafe, 2026) == []  # cafes don't need online booking
    _, flags = score_lead(lead(website="https://smile.ph", site_signals=[]), year=2026)
    assert flags == ["no_analytics", "no_online_booking"]


def test_site_signals_none_and_empty_survive_storage(repo: Repository) -> None:
    repo.create_run(Run(id="r", category="dentist", location="Makati", created_at=utcnow_iso()))
    unread, empty, facts = (lead(site_signals=None), lead(name_key="b", site_signals=[]),
                            lead(name_key="c", site_signals=["booking:fresha"]))  # fmt: skip
    for x in (unread, empty, facts):
        repo.insert_lead(x.model_copy(update={"lead_id": x.name_key.replace(" ", "-")}))
    assert repo.get_lead("smile-dental").site_signals is None
    assert repo.get_lead("b").site_signals == []
    assert repo.get_lead("c").site_signals == ["booking:fresha"]


def test_email_kind_labels() -> None:
    assert email_kind("info@smile.ph") == "business"
    assert email_kind("inquiries2@smile.ph") == "business"
    assert email_kind("smile.dental.makati@gmail.com", "smile dental") == "business"
    assert email_kind("maria.santos@smile.ph") == "personal"
    assert email_kind("juan_dela.cruz@gmail.com") == "personal"
    assert email_kind("dr.reyes@gmail.com") == "personal"
    assert email_kind("drajose@gmail.com") == "personal"  # no separator: the doctor rule
    assert email_kind("contact.us@smile.ph") == "business"
    assert email_kind("xk7731@yahoo.com") == "unknown"
    assert email_kind(None) == ""


def test_run_summary_counts() -> None:
    run = Run(id="r", category="dentist", location="Makati", created_at=utcnow_iso(),
              stats={"clean": {"new": 2, "duplicates_merged": 1, "suppressed": 3},
                     "enrich": {"outcomes": {"ok": 1, "robots_blocked": 4}}})  # fmt: skip
    leads = [
        lead(email="maria.santos@smile.ph", phone="+639171234567", facebook="https://fb.com/x"),
        lead(website="https://b.ph"),
    ]
    summary = dict(run_summary(run, leads))
    assert summary["Leads"] == "2" and summary["New this run"] == "2"
    assert summary["With email"] == "1 (50%)" and summary["With website"] == "1 (50%)"
    assert summary["With Facebook or Instagram"] == "1 (50%)"
    assert summary["Personal-name emails (email_kind)"] == "1"
    assert summary["Duplicates merged"] == "1"
    assert summary["Removed on request (suppressed)"] == "3"
    assert summary["Websites not read (robots.txt)"] == "4"
