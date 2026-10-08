"""Batch mode and weekly monitoring (V2: F15, F16), offline."""

from __future__ import annotations

import asyncio
import csv
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from leadharvest.batch import BatchError, parse_jobs, read_jobs_csv, read_jobs_sheet, run_batch
from leadharvest.categories import load_categories
from leadharvest.cli import app, monitor_batch_name
from leadharvest.exporters.csv_export import CsvExporter
from leadharvest.exporters.sheets_export import NEW_TAB_COLUMNS, SheetsExporter
from leadharvest.models import RawBusiness, SearchQuery
from leadharvest.pipeline import Pipeline
from tests.conftest import TEST_UA, fake_resolver, read_fixture
from tests.unit.test_exporters import FakeWorksheet

CATS = load_categories()


# ---- jobs parsing -----------------------------------------------------------------------------


def test_parse_jobs_rules() -> None:
    jobs = parse_jobs([
        {"Category": "dentist", "Location": "Makati", "limit": "50", "sources": "osm; directory:x"},
        {"category": "", "location": ""},
        {"category": "# gym", "location": "Pasig"},
        {"category": "gym", "location": "Taguig"},
    ])  # fmt: skip
    assert [(j.row, j.category, j.limit, j.sources) for j in jobs] == [
        (1, "dentist", 50, ["osm", "directory:x"]),
        (4, "gym", None, None),
    ]
    with pytest.raises(BatchError, match="row 1"):
        parse_jobs([{"category": "dentist", "location": ""}])
    with pytest.raises(BatchError, match="limit"):
        parse_jobs([{"category": "dentist", "location": "Makati", "limit": "lots"}])
    with pytest.raises(BatchError, match="no jobs"):
        parse_jobs([])


def test_read_jobs_csv_and_sheet(tmp_path: Path) -> None:
    path = tmp_path / "jobs.csv"
    path.write_text("﻿category,location\ndentist,Makati\n", encoding="utf-8")
    assert read_jobs_csv(path)[0].location == "Makati"
    (tmp_path / "bad.csv").write_text("cat,loc\nx,y\n", encoding="utf-8")
    with pytest.raises(BatchError, match="header"):
        read_jobs_csv(tmp_path / "bad.csv")
    with pytest.raises(BatchError, match="not found"):
        read_jobs_csv(tmp_path / "missing.csv")

    class Tab:
        def get_all_records(self):
            return [{"category": "gym", "location": "Pasig", "limit": 20}]

    assert read_jobs_sheet(Tab())[0].limit == 20


REPO = Path(__file__).resolve().parents[2]


def test_example_jobs_file_and_workflows_parse() -> None:
    import yaml

    jobs = read_jobs_csv(REPO / "config" / "monitor.example.csv")
    assert [(j.category, j.location) for j in jobs][-1] == ("gym", "Pasig, Philippines")
    for name in ("ci.yml", "monitor.yml"):
        workflow = yaml.safe_load((REPO / ".github" / "workflows" / name).read_text("utf-8"))
        assert workflow["jobs"]
    monitor = yaml.safe_load((REPO / ".github" / "workflows" / "monitor.yml").read_text("utf-8"))
    steps = " ".join(str(s.get("run", "")) for s in monitor["jobs"]["monitor"]["steps"])
    assert "openssl enc -aes-256-cbc" in steps and "leads.db.enc" in steps  # never plaintext


def test_monitor_batch_name_is_per_iso_week() -> None:
    assert monitor_batch_name("weekly", date(2026, 10, 1)) == "weekly@2026-W40"
    assert monitor_batch_name("weekly", date(2026, 10, 4)) == "weekly@2026-W40"
    assert monitor_batch_name("weekly", date(2026, 10, 5)) == "weekly@2026-W41"


# ---- running batches --------------------------------------------------------------------------


class AreaSource:
    """Two clinics everywhere; `extra` adds a third (a business that opened since last week)."""

    name = "fixture"

    def __init__(self) -> None:
        self.extra = False

    async def search(self, query: SearchQuery) -> list[RawBusiness]:
        names = ["Alpha Dental", "Beta Dental"] + (["Gamma Dental"] if self.extra else [])
        return [RawBusiness(source="osm", source_ref=f"node/{query.location}/{i}", name=n)
                for i, n in enumerate(names)]  # fmt: skip


async def _instant(_: float) -> None:
    return None


async def _mx(domain: str) -> bool:
    return True


def make_pipeline(settings, repo, source: AreaSource) -> Pipeline:
    return Pipeline(
        settings, repo, exporter_factory=lambda n: CsvExporter(settings.export_dir),
        sources_factory=lambda client, run, fetcher: [source], mx_lookup=_mx,
        resolver=fake_resolver, sleep=_instant,
    )  # fmt: skip


def mock_nominatim() -> None:
    makati = read_fixture("nominatim", "makati.json")

    def answer(request: httpx.Request) -> httpx.Response:
        if "Atlantis" in str(request.url):
            return httpx.Response(200, json=[])
        return httpx.Response(200, text=makati)

    respx.get("https://nominatim.test/search").mock(side_effect=answer)


def batch_kwargs(settings, repo, pipeline, **kw):
    def execute(run, category):
        return asyncio.run(pipeline.execute(run.id, category))

    base = dict(
        repo=repo,
        pipeline=pipeline,
        categories=CATS,
        execute=execute,
        default_limit=50,
        targets=["csv"],
        default_sources=["osm"],
        options={},
    )
    base.update(kw)
    return base


@respx.mock
def test_batch_runs_all_rows_and_skips_on_rerun(settings, repo) -> None:
    mock_nominatim()
    pipeline = make_pipeline(settings, repo, AreaSource())
    jobs = parse_jobs([
        {"category": "dentist", "location": "Makati"},
        {"category": "dentst", "location": "Makati"},
        {"category": "dentist", "location": "Atlantis"},
        {"category": "gym", "location": "Taguig", "limit": "1"},
    ])  # fmt: skip
    results = run_batch("jobs", jobs, **batch_kwargs(settings, repo, pipeline))
    assert [r.status for r in results] == ["completed", "error", "failed", "completed"]
    assert results[0].leads == 2 and results[3].leads == 1
    assert "location not found" in results[2].message

    again = run_batch("jobs", jobs, **batch_kwargs(settings, repo, pipeline))
    assert [r.status for r in again] == ["skipped", "error", "failed", "skipped"]
    assert again[0].run_id == results[0].run_id
    rerun = run_batch("jobs", jobs[:1], **batch_kwargs(settings, repo, pipeline, rerun=True))
    assert rerun[0].status == "completed" and rerun[0].run_id != results[0].run_id


@respx.mock
def test_batch_interrupt_then_resume(settings, repo) -> None:
    mock_nominatim()
    pipeline = make_pipeline(settings, repo, AreaSource())
    jobs = parse_jobs([{"category": "dentist", "location": "Makati"},
                       {"category": "gym", "location": "Makati"}])  # fmt: skip
    calls = {"n": 0}

    def flaky(run, category):
        calls["n"] += 1
        if calls["n"] == 2:
            repo.update_run(run.id, status="partial", error="interrupted")
            raise KeyboardInterrupt
        return asyncio.run(pipeline.execute(run.id, category))

    with pytest.raises(KeyboardInterrupt):
        run_batch("b", jobs, **batch_kwargs(settings, repo, pipeline, execute=flaky))
    interrupted = repo.find_batch_run("b", 2)
    assert interrupted is not None and interrupted.status == "partial"

    results = run_batch("b", jobs, **batch_kwargs(settings, repo, pipeline))
    assert [r.status for r in results] == ["skipped", "completed"]
    assert results[1].run_id == interrupted.id  # resumed, not restarted


@respx.mock
def test_edited_row_is_a_new_job(settings, repo) -> None:
    mock_nominatim()
    pipeline = make_pipeline(settings, repo, AreaSource())
    first = run_batch("e", parse_jobs([{"category": "dentist", "location": "Makati"}]),
                      **batch_kwargs(settings, repo, pipeline))  # fmt: skip
    edited = parse_jobs([{"category": "dentist", "location": "Taguig"}])
    results = run_batch("e", edited, **batch_kwargs(settings, repo, pipeline))
    assert results[0].status == "completed" and results[0].run_id != first[0].run_id
    assert repo.get_run(results[0].run_id).location == "Taguig"

    # An unfinished run for the old row is not resumed for the edited one either.
    repo.update_run(results[0].run_id, status="partial")
    makati = parse_jobs([{"category": "dentist", "location": "Makati"}])
    again = run_batch("e", makati, **batch_kwargs(settings, repo, pipeline))
    assert again[0].run_id not in (first[0].run_id, results[0].run_id)


@respx.mock
def test_monitor_exports_new_since_last_run(settings, repo) -> None:
    mock_nominatim()
    source = AreaSource()
    pipeline = make_pipeline(settings, repo, source)
    jobs = parse_jobs([{"category": "dentist", "location": "Makati"}])
    week1 = run_batch(
        "watch@2026-W40", jobs, **batch_kwargs(settings, repo, pipeline, options={"monitor": True})
    )
    first = repo.get_run(week1[0].run_id)
    assert first.stats["monitor"] == {"new_since_last_run": 2, "previous_run": None}
    # Later runs over the same area that are not this monitor never count as "last run".
    run_batch("other@2026-W40", jobs,
              **batch_kwargs(settings, repo, pipeline, options={"monitor": True}))  # fmt: skip
    run_batch("one-off", jobs, **batch_kwargs(settings, repo, pipeline))

    source.extra = True  # a clinic opened during the week
    week2 = run_batch(
        "watch@2026-W41", jobs, **batch_kwargs(settings, repo, pipeline, options={"monitor": True})
    )
    second = repo.get_run(week2[0].run_id)
    assert second.stats["monitor"] == {"new_since_last_run": 1, "previous_run": first.id}
    new_file = next(Path(r["target"]) for r in second.stats["export_results"]
                    if r["target"].endswith("-new.csv"))  # fmt: skip
    rows = list(csv.DictReader(new_file.read_text(encoding="utf-8-sig").splitlines()))
    assert [r["business_name"] for r in rows] == ["Gamma Dental"]


def test_sheets_new_tab_keeps_history_and_found_on(settings, repo) -> None:
    from tests.unit.test_exporters import lead, run

    ws = FakeWorksheet()
    titles: list[str] = []

    def opener(title: str, n: int) -> FakeWorksheet:
        titles.append(title)
        return ws

    exporter = SheetsExporter(opener, sleep=lambda s: None)
    week1 = run().model_copy(update={"created_at": "2026-09-28T01:00:00+00:00"})
    exporter.export_new([lead("L-1")], week1)
    week2 = run().model_copy(update={"created_at": "2026-10-05T01:00:00+00:00"})
    exporter.export_new([lead("L-2", "Gamma")], week2)
    assert titles == ["dentist - Makati - new", "dentist - Makati - new"]
    assert [str(h) for h in ws.grid[0]] == list(NEW_TAB_COLUMNS)
    assert ws.column("lead_id") == ["L-1", "L-2"]
    assert ws.column("found_on") == ["2026-09-28", "2026-10-05"]


# ---- CLI ---------------------------------------------------------------------------------------


def test_batch_cli_input_errors(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LH_USER_AGENT", TEST_UA)
    monkeypatch.setenv("LH_DB_PATH", str(tmp_path / "leads.db"))
    runner = CliRunner()
    result = runner.invoke(app, ["batch"])
    assert result.exit_code == 2 and "one of them" in result.output
    result = runner.invoke(app, ["batch", "missing.csv"])
    assert result.exit_code == 2 and "not found" in result.output
    (tmp_path / "jobs.csv").write_text("category,location,sources\ndentist,Makati,yelp\n",
                                       encoding="utf-8")  # fmt: skip
    result = runner.invoke(app, ["monitor", "jobs.csv"])
    assert result.exit_code == 2 and "Unknown source" in result.output
