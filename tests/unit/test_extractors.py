from leadharvest.enrich.discovery import discover_contact_pages
from leadharvest.enrich.extractors import (
    deobfuscate,
    extract_all,
    extract_jsonld,
    make_soup,
    rank_emails,
)
from tests.conftest import read_fixture

BASE = "https://www.smileclinic.com.ph"


def test_homepage_extraction() -> None:
    found = extract_all(read_fixture("html", "clinic_home.html"), BASE)
    # mailto first, then JSON-LD, then visible text; junk and image matches dropped
    assert found.emails == ["info@smileclinic.com.ph", "frontdesk@smileclinic.com.ph"]
    assert "+639171234567" in found.phones
    assert "+63281234567" in found.phones
    assert found.socials == {
        "facebook": "https://www.facebook.com/SmileClinicPH",
        "tiktok": "https://www.tiktok.com/@smileclinicph",
        "instagram": "https://www.instagram.com/smileclinicph",
    }
    assert found.protected_emails == 0


def test_junk_and_script_emails_ignored() -> None:
    found = extract_all(read_fixture("html", "clinic_home.html"), BASE)
    for junk in ("user@example.com", "noreply@sentry.io", "hidden@style.com"):
        assert junk not in found.emails
    assert not any(e.endswith(".png") for e in found.emails)


def test_bracketed_obfuscation_only() -> None:
    assert deobfuscate("info [at] clinic [dot] ph") == ["info@clinic.ph"]
    assert deobfuscate("name(at)domain(dot)com") == ["name@domain.com"]
    assert deobfuscate("info at clinic dot ph") == []
    found = extract_all(read_fixture("html", "clinic_contact.html"), BASE + "/contact-us")
    assert found.emails == ["appointments@smileclinic.com.ph", "drsantos@gmail.com"]
    assert found.phones == ["+639187654321"]


def test_cloudflare_protected_emails_counted_not_decoded() -> None:
    found = extract_all(read_fixture("html", "cloudflare_protected.html"), BASE)
    assert found.emails == []
    assert found.protected_emails == 2


def test_jsonld_extraction() -> None:
    soup = make_soup(read_fixture("html", "clinic_home.html"))
    found = extract_jsonld(soup)
    assert found.emails == ["frontdesk@smileclinic.com.ph"]
    assert found.phones == ["+63281234567"]
    assert found.socials == {"instagram": "https://www.instagram.com/smileclinicph"}


def test_rank_emails_same_domain_then_free_then_other() -> None:
    emails = [
        "owner@otherbiz.com",
        "drsantos@gmail.com",
        "billing@smileclinic.com.ph",
        "info@smileclinic.com.ph",
    ]
    assert rank_emails(emails, "smileclinic.com.ph") == [
        "info@smileclinic.com.ph", "billing@smileclinic.com.ph", "drsantos@gmail.com",
        "owner@otherbiz.com",
    ]  # fmt: skip


def test_discovery_same_site_contact_first() -> None:
    html = read_fixture("html", "clinic_home.html")
    assert discover_contact_pages(html, BASE, limit=2) == [
        "https://www.smileclinic.com.ph/contact-us",
        "https://www.smileclinic.com.ph/about-us",
    ]
    assert discover_contact_pages(html, BASE, limit=0) == []
