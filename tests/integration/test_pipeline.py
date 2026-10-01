"""End-to-end pipeline, offline: fixture source → temp SQLite → enrichment (respx) → CSV."""

from __future__ import annotations

import asyncio
import csv
from pathlib import Path

import httpx
import pytest
import respx

from leadharvest.categories import load_categories
from leadharvest.enrich.enricher import Enricher
from leadharvest.exporters.csv_export import CsvExporter
from leadharvest.geo.nominatim import LocationNotFound
from leadharvest.models import RawBusiness, SearchQuery
from leadharvest.pipeline import Pipeline
from tests.conftest import fake_resolver, read_fixture

HTML = {"content-type": "text/html; charset=utf-8"}
SITES = [f"clinic{i}.ph" for i in range(6)]


class FixtureSource:
    name = "fixture"

    def __init__(self) -> None:
        self.calls = 0

    async def search(self, query: SearchQuery) -> list[RawBusiness]:
        self.calls += 1
        records = [
            RawBusiness(
                source="osm",
                source_ref=f"node/{i}",
                name=f"Clinic {i}",
                website_raw=f"https://{site}",
                lat=14.55 + i / 100,
                lon=121.02,
            )
            for i, site in enumerate(SITES)
        ]
        records.append(
            RawBusiness(
                source="osm",
                source_ref="node/99",
                name="No Site Dental",
                phones_raw=["0917 000 1111"],
            )
        )
        # A duplicate of Clinic 0 from another OSM element (same website + city → rule 2).
        records.append(
            RawBusiness(
                source="osm",
                source_ref="way/500",
                name="Clinic 0 Branch",
                website_raw=f"https://www.{SITES[0]}/",
                lat=14.55,
                lon=121.02,
            )
        )
        return records


def mock_world() -> dict[str, respx.Route]:
    respx.get("https://nominatim.test/search").respond(
        200, text=read_fixture("nominatim", "makati.json")
    )
    routes = {}
    for i, site in enumerate(SITES):
        respx.get(f"https://{site}/robots.txt").respond(404)
        routes[site] = respx.get(f"https://{site}").respond(
            200,
            headers=HTML,
            html=f'<p>Email us: <a href="mailto:info@{site}">info@{site}</a> '
            f"or call 0917 123 45{i:02d}</p>",
        )
    respx.get("https://www.clinic0.ph/robots.txt").respond(404)
    return routes


async def _instant(_: float) -> None:
    return None


async def fake_mx(domain: str) -> bool | None:
    return not domain.startswith("dead")


def make_pipeline(settings, repo, source: FixtureSource) -> Pipeline:
    return Pipeline(
        settings, repo,
        exporter_factory=lambda name: CsvExporter(settings.export_dir),
        sources_factory=lambda client, run, fetcher: [source],
        mx_lookup=fake_mx,
        resolver=fake_resolver,
        sleep=_instant,
    )  # fmt: skip


@respx.mock
async def test_full_run_end_to_end(settings, repo) -> None:
    routes = mock_world()
    source = FixtureSource()
    pipeline = make_pipeline(settings, repo, source)
    cat = load_categories()["dentist"]
    run = pipeline.create_run(cat, "Makati, Philippines", limit=100, targets=["csv"])
    result = await pipeline.execute(run.id, cat)

    assert result.status == "completed" and result.current_step == "done"
    assert result.area_name == "Makati"
    clean = result.stats["clean"]
    assert clean["found"] == 8
    assert clean["leads"] == 7 and clean["new"] == 7 and clean["duplicates_merged"] == 1
    leads = repo.leads_for_run(run.id)
    assert {lead.enrich_status for lead in leads} == {"ok", "no_website"}
    assert all(lead.email == f"info@{lead.domain}" for lead in leads if lead.domain)
    assert all(routes[s].call_count == 1 for s in SITES)

    (export,) = result.stats["export_results"]
    text = Path(export["target"]).read_text(encoding="utf-8-sig")
    rows = list(csv.DictReader(text.splitlines()))
    assert len(rows) == 7
    assert {r["lead_id"] for r in rows} == {lead.lead_id for lead in leads}
    assert rows[0]["phone"].startswith("+63")

    score = result.stats["score"]
    assert score["scored"] == 7 and score["mx_checked"] is True
    assert all(lead.score is not None for lead in repo.leads_for_run(run.id))
    assert "no_website" in score["flags"]

    # A second run over the same area re-uses every lead: nothing new.
    run2 = pipeline.create_run(cat, "Makati, Philippines", limit=100, targets=["csv"])
    result2 = await pipeline.execute(run2.id, cat)
    assert result2.stats["clean"]["new"] == 0
    assert result2.stats["clean"]["existing"] == 7
    assert result2.stats["enrich"]["attempted"] == 0  # already enriched, not re-fetched


@respx.mock
async def test_crash_during_enrich_then_resume(settings, repo, monkeypatch) -> None:
    routes = mock_world()
    source = FixtureSource()
    pipeline = make_pipeline(settings, repo, source)
    cat = load_categories()["dentist"]
    run = pipeline.create_run(cat, "Makati", limit=100, targets=["csv"])

    original = Enricher.enrich_lead
    calls = {"n": 0}

    async def crash_on_fourth(self, lead):
        calls["n"] += 1
        if calls["n"] == 4:
            # Ctrl+C reaches the running pipeline as task cancellation (asyncio.run).
            raise asyncio.CancelledError
        return await original(self, lead)

    settings.concurrency = 1
    monkeypatch.setattr(Enricher, "enrich_lead", crash_on_fourth)
    with pytest.raises((KeyboardInterrupt, asyncio.CancelledError)):
        await pipeline.execute(run.id, cat)
    partial = repo.get_run(run.id)
    assert partial.status == "partial" and partial.current_step == "enrich"
    fetched_before = {s: routes[s].call_count for s in SITES}
    done_before = repo.enrich_status_counts(run.id).get("ok", 0)
    assert 1 <= done_before < 6

    monkeypatch.setattr(Enricher, "enrich_lead", original)
    resumed = await make_pipeline(settings, repo, source).execute(run.id, cat)
    assert resumed.status == "completed"
    assert source.calls == 1  # search was not repeated
    assert repo.enrich_status_counts(run.id) == {"ok": 6, "no_website": 1}
    for site in SITES:  # finished leads were not fetched again
        assert routes[site].call_count == 1, (site, fetched_before[site])
    assert resumed.stats["clean"]["new"] == 7  # is_new survives the resume


@respx.mock
async def test_directory_source_through_default_factory(settings, repo, monkeypatch, tmp_path):
    folder = tmp_path / "config" / "directories"
    folder.mkdir(parents=True)
    folder.joinpath("testdir.yaml").write_text(
        read_fixture("directories", "testdir.yaml"), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    respx.get("https://nominatim.test/search").respond(
        200, text=read_fixture("nominatim", "makati.json")
    )
    respx.get("https://directory.test/robots.txt").respond(404)
    respx.get(url__regex=r"^https://directory\.test/search\?q=[^&]+&where=Makati$").respond(
        200, html=read_fixture("html", "directory_page1.html"), headers=HTML
    )
    respx.get(url__regex=r"^https://directory\.test/search\?.*page=2$").respond(
        200, html=read_fixture("html", "directory_page2.html"), headers=HTML
    )
    pipeline = Pipeline(
        settings,
        repo,
        exporter_factory=lambda n: CsvExporter(settings.export_dir),
        mx_lookup=fake_mx,
        resolver=fake_resolver,
        sleep=_instant,
    )
    cat = load_categories()["dentist"]
    run = pipeline.create_run(
        cat, "Makati", limit=10, targets=["csv"], sources=["directory:testdir"]
    )
    result = await pipeline.execute(run.id, cat, stop_after="clean")
    assert result.stats["search"]["directory:testdir_records"] == 3
    assert result.stats["clean"]["leads"] == 3
    leads = repo.leads_for_run(run.id)
    assert {lead.sources[0] for lead in leads} == {"directory:testdir"}
    assert any(lead.website == "https://www.smileclinic.com.ph/?ref=dir" for lead in leads)


@respx.mock
async def test_location_not_found_fails_run(settings, repo) -> None:
    respx.get("https://nominatim.test/search").respond(200, json=[])
    pipeline = make_pipeline(settings, repo, FixtureSource())
    cat = load_categories()["dentist"]
    run = pipeline.create_run(cat, "Atlantis", limit=10, targets=["csv"])
    with pytest.raises(LocationNotFound):
        await pipeline.execute(run.id, cat)
    assert repo.get_run(run.id).status == "failed"


@respx.mock
async def test_source_error_marks_partial_and_resume_finishes(settings, repo) -> None:
    respx.get("https://nominatim.test/search").respond(
        200, text=read_fixture("nominatim", "makati.json")
    )
    respx.post(url__regex=r"https://overpass2?\.test/.*").mock(
        side_effect=httpx.ConnectError("down")
    )
    pipeline = Pipeline(
        settings,
        repo,
        exporter_factory=lambda n: CsvExporter(settings.export_dir),
        resolver=fake_resolver,
        sleep=_instant,
    )
    cat = load_categories()["dentist"]
    run = pipeline.create_run(cat, "Makati", limit=10, targets=["csv"])
    result = await pipeline.execute(run.id, cat)
    assert result.status == "partial" and result.current_step == "search"
    assert "Overpass" in (result.error or "")
