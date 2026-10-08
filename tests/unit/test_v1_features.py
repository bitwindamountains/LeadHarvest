"""V1 features: scoring + flags, MX check, JS render fallback, directory adapter, HubSpot."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from leadharvest.enrich.enricher import Enricher
from leadharvest.enrich.fetcher import FetchError, PoliteFetcher
from leadharvest.enrich.mx import MxChecker, dns_mx_lookup
from leadharvest.enrich.render import PlaywrightRenderer, RenderUnavailable
from leadharvest.exporters.base import ExportError
from leadharvest.exporters.hubspot_export import HubSpotExporter, lead_properties
from leadharvest.http import make_client
from leadharvest.models import Lead, ResolvedArea, Run, SearchQuery, new_lead_id, utcnow_iso
from leadharvest.scoring import run_score_step, score_lead
from leadharvest.sources.base import SourceError
from leadharvest.sources.directory import (
    DirectoryConfigError,
    DirectorySource,
    load_directory_config,
    parse_listing,
)
from tests.conftest import FIXTURES, fake_resolver, read_fixture

HTML = {"content-type": "text/html; charset=utf-8"}
DIRS = FIXTURES / "directories"


def lead(**kw: Any) -> Lead:
    now = utcnow_iso()
    data = {"lead_id": new_lead_id(), "business_name": "Smile", "name_key": "smile",
            "first_seen_run_id": "run-1", "first_seen_at": now, "last_seen_at": now,
            "updated_at": now}  # fmt: skip
    data.update(kw)
    return Lead.model_validate(data)


def stored_run(repo, **kw: Any) -> Run:
    run = Run(
        id="run-1",
        category="dentist",
        location="Makati",
        area_name="Makati",
        created_at=utcnow_iso(),
        **kw,
    )
    repo.create_run(run)
    return run


def store(repo, item: Lead) -> Lead:
    repo.insert_lead(item)
    repo.link_run_lead("run-1", item.lead_id, "dentist")
    return item


# ---- scoring ----------------------------------------------------------------------------------


def test_score_full_house_is_capped_at_100() -> None:
    full = lead(email="info@smile.ph", domain="smile.ph", phone="+639171234567",
                website="https://smile.ph", facebook="https://facebook.com/smile",
                street_key="ayala avenue", opening_hours="Mo-Fr", https_ok=True)  # fmt: skip
    assert score_lead(full) == (100, [])


def test_score_points_and_flags() -> None:
    assert score_lead(lead()) == (0, ["no_website"])
    social = lead(facebook="https://facebook.com/smile", phone="+639171234567")
    assert score_lead(social) == (30, ["no_website", "social_only"])
    free = lead(email="smile@gmail.com", website="http://smile.ph", domain="smile.ph",
                https_ok=False)  # fmt: skip
    assert score_lead(free) == (45, ["no_https", "free_email_provider"])
    shared = lead(email="a@smile.wixsite.com", website="https://smile.wixsite.com",
                  domain="wixsite.com")  # fmt: skip
    assert score_lead(shared)[0] == 45  # no own-domain bonus on shared hosting


# ---- MX ---------------------------------------------------------------------------------------


async def test_mx_checker_caches_and_skips_free_providers(repo) -> None:
    calls: list[str] = []

    async def lookup(domain: str) -> bool | None:
        calls.append(domain)
        return {"dead.ph": False, "flaky.ph": None}.get(domain, True)

    mx = MxChecker(repo, lookup)
    emails = ["a@dead.ph", "b@ok.ph", "c@gmail.com", "d@flaky.ph", "e@dead.ph"]
    assert await mx.dead_emails(emails) == ["a@dead.ph", "e@dead.ph"]
    assert sorted(calls) == ["dead.ph", "flaky.ph", "ok.ph"]  # gmail never looked up
    assert await MxChecker(repo, lookup).has_mail("dead.ph") is False  # from SQLite cache
    assert repo.mx_cache_get("flaky.ph") is None  # unknown results are not cached
    assert len(calls) == 3


async def test_score_step_drops_dead_emails_and_reranks(repo) -> None:
    run = stored_run(repo)
    item = store(repo, lead(email="info@old-domain.ph", emails_extra=["owner@gmail.com"],
                            website="https://smile.ph", domain="smile.ph"))  # fmt: skip

    async def lookup(domain: str) -> bool | None:
        return domain != "old-domain.ph"

    stats = await run_score_step(repo, run, MxChecker(repo, lookup))
    updated = repo.get_lead(item.lead_id)
    assert updated.email == "owner@gmail.com" and updated.emails_extra == []
    assert stats["emails_dropped_dead_domain"] == 1  # a count, never the address
    assert updated.score == 45 and "free_email_provider" in updated.flags


async def test_score_step_looks_up_all_leads_domains_concurrently(repo) -> None:
    run = stored_run(repo)
    store(repo, lead(email="info@a.ph"))
    store(repo, lead(business_name="B", name_key="b", email="info@b.ph"))
    in_flight, peak = 0, 0

    async def lookup(domain: str) -> bool | None:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0)
        in_flight -= 1
        return True

    await run_score_step(repo, run, MxChecker(repo, lookup))
    assert peak == 2  # both leads' domains at once, not lead by lead


async def test_score_step_without_mx(repo) -> None:
    run = stored_run(repo)
    store(repo, lead(email="info@whatever.ph"))
    stats = await run_score_step(repo, run, None)
    assert stats["mx_checked"] is False and stats["scored"] == 1


class _Rec:
    def __init__(self, exchange: str) -> None:
        self.exchange = exchange


async def test_dns_mx_lookup_outcomes(monkeypatch) -> None:
    import dns.asyncresolver
    import dns.exception
    import dns.resolver

    behaviour: dict[tuple[str, str], Any] = {
        ("mail.ph", "MX"): [_Rec("mx1.mail.ph.")],
        ("nullmx.ph", "MX"): [_Rec(".")],
        ("gone.ph", "MX"): dns.resolver.NXDOMAIN(),
        ("aonly.ph", "MX"): dns.resolver.NoAnswer(),
        ("aonly.ph", "A"): ["1.2.3.4"],
        ("nothing.ph", "MX"): dns.resolver.NoAnswer(),
        ("nothing.ph", "A"): dns.resolver.NoAnswer(),
        ("nothing.ph", "AAAA"): dns.resolver.NoAnswer(),
        ("slow.ph", "MX"): dns.exception.Timeout(),
    }

    async def fake_resolve(self, domain: str, rtype: str):
        result = behaviour[(domain, rtype)]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(dns.asyncresolver.Resolver, "resolve", fake_resolve)
    monkeypatch.setattr(dns.asyncresolver.Resolver, "__init__", lambda self, *a, **k: None)
    expected = {"mail.ph": True, "nullmx.ph": False, "gone.ph": False, "aonly.ph": True,
                "nothing.ph": False, "slow.ph": None}  # fmt: skip
    for domain, answer in expected.items():
        assert await dns_mx_lookup(domain) is answer, domain


# ---- JS render fallback -----------------------------------------------------------------------


class FakeRenderer:
    def __init__(self, html: str | Exception) -> None:
        self.html = html
        self.urls: list[str] = []

    async def render(self, url: str) -> str:
        self.urls.append(url)
        if isinstance(self.html, Exception):
            raise self.html
        return self.html


def _fetcher(settings, repo, clock, client) -> PoliteFetcher:
    return PoliteFetcher(settings, client, repo=repo, resolver=fake_resolver, clock=clock,
                         sleep=clock.sleep)  # fmt: skip


@respx.mock
async def test_js_fallback_only_for_near_empty_pages(settings, repo, clock) -> None:
    stored_run(repo)
    respx.get("https://spa.ph/robots.txt").respond(404)
    respx.get("https://spa.ph/").respond(200, html='<div id="root"></div>', headers=HTML)
    respx.get("https://text.ph/robots.txt").respond(404)
    respx.get("https://text.ph/").respond(200, html="<p>" + "words " * 200 + "</p>", headers=HTML)
    spa = store(repo, lead(website="https://spa.ph/", domain="spa.ph"))
    text = store(repo, lead(business_name="T", name_key="t", website="https://text.ph/"))
    renderer = FakeRenderer('<a href="mailto:hello@spa.ph">mail</a> Call 0917 123 4567')
    async with make_client(settings) as client:
        enricher = Enricher(settings, repo, _fetcher(settings, repo, clock, client), renderer)
        stats = await enricher.enrich_run("run-1")
    assert renderer.urls == ["https://spa.ph/"]
    assert stats["js_rendered"] == 1
    assert repo.get_lead(spa.lead_id).email == "hello@spa.ph"
    assert repo.get_lead(text.lead_id).email is None


@respx.mock
async def test_js_render_failure_does_not_fail_lead(settings, repo, clock) -> None:
    stored_run(repo)
    respx.get("https://spa.ph/robots.txt").respond(404)
    respx.get("https://spa.ph/").respond(200, html="<div></div>", headers=HTML)
    item = store(repo, lead(website="https://spa.ph/"))
    async with make_client(settings) as client:
        for error in (RuntimeError("browser crashed"), FetchError("robots_blocked", "no")):
            enricher = Enricher(settings, repo, _fetcher(settings, repo, clock, client),
                                FakeRenderer(error))  # fmt: skip
            await enricher.enrich_lead(repo.get_lead(item.lead_id))
            assert enricher.rendered == 0


@respx.mock
async def test_fetcher_admit_applies_politeness(settings, repo, clock) -> None:
    respx.get("https://closed.ph/robots.txt").respond(200, text="User-agent: *\nDisallow: /")
    respx.get("https://open.ph/robots.txt").respond(404)
    async with make_client(settings) as client:
        fetcher = _fetcher(settings, repo, clock, client)
        with pytest.raises(FetchError) as exc:
            await fetcher.admit("https://closed.ph/")
        assert exc.value.kind == "robots_blocked"
        with pytest.raises(FetchError):
            await fetcher.admit("http://private.test/")
        before = clock.now
        await fetcher.admit("https://open.ph/a")
        await fetcher.admit("https://open.ph/b")
        assert clock.now - before >= settings.per_domain_delay_seconds


class FakeRoute:
    def __init__(self, url: str, resource_type: str = "document", nav: bool = False) -> None:
        self.request = self
        self.url = url
        self.resource_type = resource_type
        self._nav = nav
        self.frame = self
        self.parent_frame = None
        self.result: str | None = None

    def is_navigation_request(self) -> bool:
        return self._nav

    async def abort(self) -> None:
        self.result = "abort"

    async def continue_(self) -> None:
        self.result = "continue"


@respx.mock
async def test_render_guard_blocks_private_media_and_disallowed_navigation(
    settings, repo, clock
) -> None:
    respx.get("https://site.ph/robots.txt").respond(200, text="User-agent: *\nDisallow: /secret")
    async with make_client(settings) as client:
        renderer = PlaywrightRenderer(settings, _fetcher(settings, repo, clock, client))
        cases = [
            (FakeRoute("https://site.ph/app.js", "script"), "continue"),
            (FakeRoute("https://cdn.site.ph/logo.png", "image"), "abort"),
            (FakeRoute("http://metadata.test/latest", "xhr"), "abort"),
            (FakeRoute("https://site.ph/secret", nav=True), "abort"),
            (FakeRoute("https://site.ph/", nav=True), "continue"),
        ]
        for route, expected in cases:
            await renderer._guard(route, "https://site.ph/")
            assert route.result == expected, route.url


async def test_renderer_reports_missing_playwright(settings, repo, monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def no_playwright(name, *args, **kwargs):
        if name.startswith("playwright"):
            raise ImportError("no playwright")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_playwright)
    with pytest.raises(RenderUnavailable):
        async with PlaywrightRenderer(settings, None):  # type: ignore[arg-type]
            pass


# ---- directory adapter ------------------------------------------------------------------------


def test_directory_config_validation(tmp_path: Path) -> None:
    config = load_directory_config("testdir", DIRS)
    assert config.fields["name"].selector == ".listing-title"
    assert config.next_page is not None and config.next_page.attr == "href"
    text = (DIRS / "testdir.yaml").read_text(encoding="utf-8")
    cases = {
        "nochecklist": text.replace("tos_allows: true", "tos_allows: false"),
        "badfield": text.replace('city: ".listing-city"', 'ssn: ".x"'),
        "offsite": text.replace("https://directory.test/search", "https://elsewhere.test/search"),
    }
    for name, body in cases.items():
        (tmp_path / f"{name}.yaml").write_text(body, encoding="utf-8")
        with pytest.raises(DirectoryConfigError):
            load_directory_config(name, tmp_path)
    with pytest.raises(DirectoryConfigError):
        load_directory_config("missing", tmp_path)
    with pytest.raises(DirectoryConfigError):
        load_directory_config("_template", Path("config/directories"))


def test_parse_listing() -> None:
    config = load_directory_config("testdir", DIRS)
    records = parse_listing(read_fixture("html", "directory_page1.html"), config,
                            "https://directory.test/search?q=x")  # fmt: skip
    assert [r.name for r in records] == ["Smile Dental Clinic", "Ngiti Dental Care"]
    first = records[0]
    assert first.source == "directory:testdir"
    assert first.source_ref == "https://directory.test/biz/smile-dental-123"
    assert first.phones_raw == ["0917 123 4567"]
    assert first.website_raw == "https://www.smileclinic.com.ph/?ref=dir"
    assert first.city == "Makati City" and first.street == "12 Ayala Ave."


def _query() -> SearchQuery:
    return SearchQuery(category="dentist", osm_tags=["amenity=dentist"], location="Makati",
                       area=ResolvedArea(kind="bbox", bbox=(0, 0, 0, 0), name="Makati"),
                       limit=50)  # fmt: skip


@respx.mock
async def test_directory_source_paginates_politely(settings, repo, clock) -> None:
    respx.get("https://directory.test/robots.txt").respond(404)
    first = respx.get(url__regex=r"^https://directory\.test/search\?q=[^&]+&where=Makati$").respond(
        200, html=read_fixture("html", "directory_page1.html"), headers=HTML
    )
    second = respx.get(url__regex=r"^https://directory\.test/search\?.*page=2$").respond(
        200, html=read_fixture("html", "directory_page2.html"), headers=HTML
    )
    async with make_client(settings) as client:
        source = DirectorySource(load_directory_config("testdir", DIRS),
                                 _fetcher(settings, repo, clock, client))  # fmt: skip
        records = await source.search(_query())
    assert [r.name for r in records] == ["Smile Dental Clinic", "Ngiti Dental Care", "Bright Smile"]
    assert first.calls[0].request.url.params["q"] == "dental-clinics"
    assert first.calls[0].request.url.params["where"] == "Makati"
    assert second.call_count == 1
    assert clock.sleeps  # per-host delay applied between pages


@respx.mock
async def test_directory_source_respects_robots(settings, repo, clock) -> None:
    respx.get("https://directory.test/robots.txt").respond(200, text="User-agent: *\nDisallow: /")
    page = respx.get("https://directory.test/search").respond(200, html="x", headers=HTML)
    async with make_client(settings) as client:
        source = DirectorySource(load_directory_config("testdir", DIRS),
                                 _fetcher(settings, repo, clock, client))  # fmt: skip
        with pytest.raises(SourceError):
            await source.search(_query())
    assert page.call_count == 0


# ---- HubSpot ----------------------------------------------------------------------------------


def _hub(**kw: Any) -> HubSpotExporter:
    return HubSpotExporter("pat-secret-token", client=httpx.Client(), sleep=lambda s: None, **kw)


def _run() -> Run:
    return Run(id="r", category="dentist", location="Makati", created_at=utcnow_iso())


@respx.mock
def test_hubspot_creates_and_fills_only_empty_properties() -> None:
    search = respx.post("https://api.hubapi.com/crm/v3/objects/companies/search").mock(
        side_effect=[
            httpx.Response(200, json={"results": []}),
            httpx.Response(200, json={"results": [{"id": "77", "properties": {
                "name": "Bright Smile (edited in CRM)", "phone": "", "domain": "bright.ph"}}]}),
        ]
    )  # fmt: skip
    create = respx.post("https://api.hubapi.com/crm/v3/objects/companies").respond(
        201, json={"id": "90"}
    )
    patch = respx.patch("https://api.hubapi.com/crm/v3/objects/companies/77").respond(200, json={})
    leads = [
        lead(business_name="Smile", domain="smile.ph", phone="+639171234567"),
        lead(business_name="Bright Smile", domain="bright.ph", phone="+639187654321",
             website="https://bright.ph"),
    ]  # fmt: skip
    result = _hub().export(leads, _run())
    assert (result.rows_appended, result.rows_updated) == (1, 1)
    sent = patch.calls[0].request.read().decode()
    assert '"phone":"+639187654321"' in sent.replace(" ", "")
    assert "edited in CRM" not in sent and '"name"' not in sent  # CRM edits are kept
    assert search.calls[0].request.headers["Authorization"] == "Bearer pat-secret-token"
    assert create.call_count == 1


@respx.mock
def test_hubspot_searches_by_name_without_domain_and_retries_429() -> None:
    search = respx.post("https://api.hubapi.com/crm/v3/objects/companies/search").mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "1"}),
                     httpx.Response(200, json={"results": [{"id": "5", "properties": {
                         "name": "Smile", "phone": "+639171234567"}}]})]
    )  # fmt: skip
    patch = respx.patch("https://api.hubapi.com/crm/v3/objects/companies/5").respond(200, json={})
    _hub().export([lead(business_name="Smile", domain="wixsite.com", phone="+639171234567")],
                  _run())  # fmt: skip
    body = search.calls[1].request.read().decode()
    assert '"propertyName":"name"' in body.replace(" ", "")
    assert (
        patch.calls[0].request.read().decode().replace(" ", "") == '{"properties":{"country":"PH"}}'
    )


@respx.mock
def test_hubspot_same_domain_twice_creates_one_company() -> None:
    # Search never shows the company created a moment ago (HubSpot's index lags).
    search = respx.post("https://api.hubapi.com/crm/v3/objects/companies/search").respond(
        200, json={"results": []}
    )
    create = respx.post("https://api.hubapi.com/crm/v3/objects/companies").respond(
        201, json={"id": "90"}
    )
    patch = respx.patch("https://api.hubapi.com/crm/v3/objects/companies/90").respond(200, json={})
    leads = [
        lead(business_name="Smile Makati", domain="smile.ph"),
        lead(business_name="Smile Taguig", domain="smile.ph", phone="+639171234567"),
    ]
    result = _hub().export(leads, _run())
    assert (result.rows_appended, result.rows_updated) == (1, 1)
    assert (search.call_count, create.call_count) == (1, 1)
    assert patch.calls[0].request.read().decode().replace(" ", "") == (
        '{"properties":{"phone":"+639171234567"}}'  # only what the first create left empty
    )


@respx.mock
def test_hubspot_errors_never_leak_token() -> None:
    respx.post("https://api.hubapi.com/crm/v3/objects/companies/search").respond(
        401, json={"message": "bad token"}
    )
    with pytest.raises(ExportError) as exc:
        _hub().export([lead(domain="smile.ph")], _run())
    assert "pat-secret-token" not in str(exc.value)
    with pytest.raises(ExportError):
        HubSpotExporter("")


def test_lead_properties_skip_empty_and_shared_domains() -> None:
    props = lead_properties(lead(domain="blogspot.com", city="Makati"))
    assert props == {"name": "Smile", "city": "Makati", "country": "PH"}
