"""Fetcher and enricher behavior with mocked HTTP (respx). Covers the Phase 4 gate."""

from __future__ import annotations

import httpx
import pytest
import respx

from leadharvest.enrich.enricher import Enricher
from leadharvest.enrich.fetcher import FetchError, PoliteFetcher
from leadharvest.http import make_client
from leadharvest.models import Lead, Run, new_lead_id, utcnow_iso
from tests.conftest import fake_resolver, read_fixture

HTML = {"content-type": "text/html; charset=utf-8"}
ALLOW_ALL = httpx.Response(404)


def fetcher_for(settings, repo, clock, client) -> PoliteFetcher:
    return PoliteFetcher(
        settings, client, repo=repo, resolver=fake_resolver, clock=clock, sleep=clock.sleep
    )


@pytest.fixture
async def client(settings):
    async with make_client(settings) as c:
        yield c


@respx.mock
async def test_robots_disallow_means_no_page_request(settings, repo, clock, client) -> None:
    respx.get("https://blocked.ph/robots.txt").respond(200, text="User-agent: *\nDisallow: /")
    page = respx.get("https://blocked.ph/").respond(200, html="<p>hi</p>", headers=HTML)
    fetcher = fetcher_for(settings, repo, clock, client)
    with pytest.raises(FetchError) as exc:
        await fetcher.get_page("https://blocked.ph/")
    assert exc.value.kind == "robots_blocked"
    assert page.call_count == 0


@respx.mock
async def test_robots_checked_on_redirect_target_origin(settings, repo, clock, client) -> None:
    respx.get("https://start.ph/robots.txt").mock(return_value=ALLOW_ALL)
    respx.get("https://start.ph/").respond(301, headers={"location": "https://www.target.ph/"})
    respx.get("https://www.target.ph/robots.txt").respond(200, text="User-agent: *\nDisallow: /")
    target = respx.get("https://www.target.ph/").respond(200, html="x", headers=HTML)
    fetcher = fetcher_for(settings, repo, clock, client)
    with pytest.raises(FetchError) as exc:
        await fetcher.get_page("https://start.ph/")
    assert exc.value.kind == "robots_blocked"
    assert target.call_count == 0


@respx.mock
async def test_robots_5xx_disallows_everything(settings, repo, clock, client) -> None:
    respx.get("https://down.ph/robots.txt").respond(503)
    page = respx.get("https://down.ph/").respond(200, html="x", headers=HTML)
    with pytest.raises(FetchError):
        await fetcher_for(settings, repo, clock, client).get_page("https://down.ph/")
    assert page.call_count == 0


@respx.mock
async def test_private_ip_never_fetched_directly_or_via_redirect(
    settings, repo, clock, client
) -> None:
    private = respx.get(host="private.test").respond(200, html="secret", headers=HTML)
    respx.get("https://evil-redirect.test/robots.txt").mock(return_value=ALLOW_ALL)
    respx.get("https://evil-redirect.test/").respond(
        302, headers={"location": "http://private.test/admin"}
    )
    fetcher = fetcher_for(settings, repo, clock, client)
    for url in ("http://private.test/", "https://evil-redirect.test/", "http://127.0.0.1/"):
        with pytest.raises(FetchError):
            await fetcher.get_page(url)
    assert private.call_count == 0


class PeerStream:
    """Stands in for httpx's network_stream extension: the address actually connected to."""

    def __init__(self, address: str) -> None:
        self.address = address

    def get_extra_info(self, info: str) -> object:
        return (self.address, 443) if info == "server_addr" else None


@respx.mock
async def test_dns_rebinding_response_is_never_read(settings, repo, clock, client) -> None:
    # Our resolver says public, but the connection landed on a private address.
    respx.get("https://rebind.ph/robots.txt").mock(return_value=ALLOW_ALL)
    respx.get("https://rebind.ph/").mock(return_value=httpx.Response(
        200, html="secret", headers=HTML, extensions={"network_stream": PeerStream("10.0.0.5")}
    ))  # fmt: skip
    fetcher = fetcher_for(settings, repo, clock, client)
    fetcher.via_proxy = False
    with pytest.raises(FetchError, match=r"non-public 10.0.0.5"):
        await fetcher.get_page("https://rebind.ph/")
    fetcher.via_proxy = True  # behind a proxy the peer is the proxy, so it can't be judged
    assert (await fetcher.get_page("https://rebind.ph/")).text == "secret"


@respx.mock
async def test_https_failure_falls_back_to_http(settings, repo, clock, client) -> None:
    respx.get("https://plain.ph/robots.txt").mock(side_effect=httpx.ConnectError("tls"))
    respx.get("https://plain.ph/").mock(side_effect=httpx.ConnectError("tls"))
    respx.get("http://plain.ph/robots.txt").mock(return_value=ALLOW_ALL)
    respx.get("http://plain.ph/").respond(200, html="<p>ok</p>", headers=HTML)
    page = await fetcher_for(settings, repo, clock, client).get_homepage("https://plain.ph/")
    assert page.final_url == "http://plain.ph/"


@respx.mock
async def test_per_host_delay_and_parallel_hosts(settings, repo, clock, client) -> None:
    for host in ("a.ph", "b.ph"):
        respx.get(f"https://{host}/robots.txt").mock(return_value=ALLOW_ALL)
        respx.get(url__regex=rf"https://{host}/p\d").respond(200, html="x", headers=HTML)
    fetcher = fetcher_for(settings, repo, clock, client)
    start = clock.now
    await fetcher.get_page("https://a.ph/p1")
    await fetcher.get_page("https://a.ph/p2")
    await fetcher.get_page("https://b.ph/p1")
    # a.ph: robots, p1, p2 → two waits of ≥ 2 s; b.ph has its own clock.
    assert clock.now - start >= 4.0
    assert all(s <= settings.per_domain_delay_seconds for s in clock.sleeps)


@respx.mock
async def test_circuit_breaker_after_three_403s(settings, repo, clock, client) -> None:
    respx.get("https://grumpy.ph/robots.txt").mock(return_value=ALLOW_ALL)
    route = respx.get(url__regex=r"https://grumpy.ph/p\d").respond(403)
    fetcher = fetcher_for(settings, repo, clock, client)
    for i in range(3):
        with pytest.raises(FetchError):
            await fetcher.get_page(f"https://grumpy.ph/p{i}")
    with pytest.raises(FetchError) as exc:
        await fetcher.get_page("https://grumpy.ph/p9")
    assert exc.value.kind == "blocked"
    assert route.call_count == 3
    assert "grumpy.ph" in fetcher.blocked_hosts


@respx.mock
async def test_429_retry_after_pushes_host_back(settings, repo, clock, client) -> None:
    respx.get("https://busy.ph/robots.txt").mock(return_value=ALLOW_ALL)
    respx.get("https://busy.ph/a").respond(429, headers={"Retry-After": "30"})
    respx.get("https://busy.ph/b").respond(200, html="x", headers=HTML)
    fetcher = fetcher_for(settings, repo, clock, client)
    with pytest.raises(FetchError):
        await fetcher.get_page("https://busy.ph/a")
    before = clock.now
    await fetcher.get_page("https://busy.ph/b")
    assert clock.now - before >= 29


@respx.mock
async def test_size_cap_and_non_html(settings, repo, clock, client) -> None:
    settings.max_response_bytes = 1000
    respx.get("https://big.ph/robots.txt").mock(return_value=ALLOW_ALL)
    respx.get("https://big.ph/").respond(200, html="<p>" + "a" * 5000 + "</p>", headers=HTML)
    respx.get("https://big.ph/file").respond(
        200, content=b"%PDF", headers={"content-type": "application/pdf"}
    )
    fetcher = fetcher_for(settings, repo, clock, client)
    page = await fetcher.get_page("https://big.ph/")
    assert page.truncated and len(page.text) <= 1000
    with pytest.raises(FetchError):
        await fetcher.get_page("https://big.ph/file")


def _lead(repo, website: str, **kw) -> Lead:
    run = Run(id="run-1", category="dentist", location="Makati", created_at=utcnow_iso())
    if repo.get_run("run-1") is None:
        repo.create_run(run)
    now = utcnow_iso()
    lead = Lead(
        lead_id=new_lead_id(),
        business_name="Smile",
        name_key="smile",
        website=website,
        first_seen_run_id="run-1",
        first_seen_at=now,
        last_seen_at=now,
        updated_at=now,
        **kw,
    )
    repo.insert_lead(lead)
    repo.link_run_lead("run-1", lead.lead_id, "dentist")
    return lead


@respx.mock
async def test_enricher_homepage_plus_contact_page(settings, repo, clock, client) -> None:
    site = "https://www.smileclinic.com.ph"
    home = """<html><body><a href="/about-us">About</a><a href="/contact-us">Contact</a>
      <p>Call 0917 123 4567</p><a href="https://www.facebook.com/SmileClinicPH/">fb</a>
      </body></html>"""  # a phone but no email → contact pages are discovered
    respx.get(f"{site}/robots.txt").respond(200, text="User-agent: *\nDisallow: /about-us")
    respx.get(f"{site}/").respond(200, html=home, headers=HTML)
    respx.get(f"{site}/contact-us").respond(
        200, html=read_fixture("html", "clinic_contact.html"), headers=HTML
    )
    about = respx.get(f"{site}/about-us").respond(200, html="x", headers=HTML)
    lead = _lead(repo, site + "/", domain="smileclinic.com.ph", phone="+639171234567")
    repo.add_suppression("email", "drsantos@gmail.com")
    enricher = Enricher(settings, repo, fetcher_for(settings, repo, clock, client))
    stats = await enricher.enrich_run("run-1")
    assert stats["outcomes"] == {"ok": 1}
    updated = repo.get_lead(lead.lead_id)
    assert updated.enrich_status == "ok"
    assert updated.email == "appointments@smileclinic.com.ph"
    assert updated.emails_extra == []  # drsantos@gmail.com is suppressed
    assert updated.phone == "+639171234567"
    assert "+639187654321" in updated.phones_extra
    assert updated.facebook == "https://www.facebook.com/SmileClinicPH"
    assert updated.https_ok is True
    assert updated.mobile_viewport is False  # the homepage has no viewport meta
    assert updated.tech == []
    assert about.call_count == 0  # robots-disallowed extra page was skipped


@respx.mock
async def test_enricher_records_failures_without_stopping(settings, repo, clock, client) -> None:
    respx.get("https://slow.ph/robots.txt").mock(return_value=ALLOW_ALL)
    respx.get("https://slow.ph/").mock(side_effect=httpx.ReadTimeout("slow"))
    respx.get("http://slow.ph/robots.txt").mock(return_value=ALLOW_ALL)
    respx.get("http://slow.ph/").mock(side_effect=httpx.ReadTimeout("slow"))
    respx.get("https://nope.ph/robots.txt").respond(200, text="User-agent: *\nDisallow: /")
    respx.get("https://gone.ph/robots.txt").mock(return_value=ALLOW_ALL)
    respx.get("https://gone.ph/").respond(500)
    respx.get("https://plain.ph/robots.txt").mock(side_effect=httpx.ConnectError("x"))
    respx.get("https://plain.ph/").mock(side_effect=httpx.ConnectError("x"))
    respx.get("http://plain.ph/robots.txt").mock(return_value=ALLOW_ALL)
    respx.get("http://plain.ph/").respond(
        200,
        html='<link href="/wp-content/x.css"><meta name="viewport" content="width=device-width">'
        "<p>Call 0917 123 4567</p>",
        headers=HTML,
    )
    leads = {
        name: _lead(repo, f"https://{name}/")
        for name in ("slow.ph", "nope.ph", "gone.ph", "plain.ph")
    }
    enricher = Enricher(settings, repo, fetcher_for(settings, repo, clock, client))
    stats = await enricher.enrich_run("run-1")
    status = {n: repo.get_lead(lead.lead_id).enrich_status for n, lead in leads.items()}
    assert status == {
        "slow.ph": "timeout",
        "nope.ph": "robots_blocked",
        "gone.ph": "http_error",
        "plain.ph": "ok",
    }
    plain = repo.get_lead(leads["plain.ph"].lead_id)
    assert plain.https_ok is False
    assert plain.phone == "+639171234567"
    assert plain.tech == ["wordpress"] and plain.mobile_viewport is True
    assert stats["attempted"] == 4
    # Nothing left pending → re-running enriches nothing (resume never re-fetches finished work)
    assert (await enricher.enrich_run("run-1"))["attempted"] == 0
