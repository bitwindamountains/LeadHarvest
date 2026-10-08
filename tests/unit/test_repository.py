import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from leadharvest.models import Lead, RawBusiness, Run, new_lead_id, utcnow_iso
from leadharvest.storage.db import MIGRATIONS, _split_sql, connect, current_version
from leadharvest.storage.repository import Repository


def make_run(repo: Repository, run_id: str = "run-1", **kw: object) -> Run:
    run = Run(id=run_id, category="dentist", location="Makati", created_at=utcnow_iso(), **kw)
    repo.create_run(run)
    return run


def make_lead(run_id: str = "run-1", **kw: object) -> Lead:
    now = utcnow_iso()
    data = {
        "lead_id": new_lead_id(), "business_name": "Smile Dental", "name_key": "smile dental",
        "categories": ["dentist"], "first_seen_run_id": run_id, "first_seen_at": now,
        "last_seen_at": now, "updated_at": now,
    }  # fmt: skip
    data.update(kw)
    return Lead.model_validate(data)


def test_migrations_and_pragmas(settings) -> None:
    latest = MIGRATIONS[-1][0]
    conn = connect(settings.db_path)
    assert current_version(conn) == latest
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    conn.close()
    conn = connect(settings.db_path)  # re-open: migrations are not re-applied
    assert current_version(conn) == latest


def test_transaction_takes_the_write_lock_up_front(settings, repo: Repository) -> None:
    other = connect(settings.db_path)  # e.g. the UI while the CLI runs
    other.execute("PRAGMA busy_timeout = 0")
    try:
        with repo.transaction():
            repo.suppressions()  # read first, as find_match does before writing
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("INSERT INTO geo_cache VALUES ('k', '[]', 'now')")
            repo.add_suppression("phone", "+639171234567")  # would fail with a plain BEGIN
    finally:
        other.close()
    assert repo.is_suppressed("phone", "+639171234567")


def test_v1_database_upgrades_and_keeps_data(tmp_path) -> None:
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path, isolation_level=None)
    raw.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    for statement in _split_sql(MIGRATIONS[0][1]):
        raw.execute(statement)
    raw.execute("INSERT INTO schema_version VALUES (1)")
    raw.execute(
        "INSERT INTO runs (id, category, location, sources, status, current_step, created_at) "
        "VALUES ('old', 'dentist', 'Makati', '[\"osm\"]', 'completed', 'done', '2026-01-01')"
    )
    raw.close()
    repo = Repository(connect(path))
    assert current_version(repo.conn) == MIGRATIONS[-1][0]
    old = repo.get_run("old")
    assert old is not None and old.options == {}
    repo.mx_cache_put("clinic.ph", True)
    assert repo.mx_cache_get("clinic.ph") is True


def test_run_roundtrip_and_resolve(repo: Repository) -> None:
    run = make_run(repo, export_targets=["csv"], bbox=(14.5, 121.0, 14.6, 121.1))
    loaded = repo.get_run(run.id)
    assert loaded is not None
    assert loaded.export_targets == ["csv"]
    assert loaded.bbox == (14.5, 121.0, 14.6, 121.1)
    assert repo.resolve_run_id("latest") == run.id
    assert repo.resolve_run_id("run-") == run.id
    assert repo.resolve_run_id("nope") is None
    repo.update_run_step(run.id, "clean")
    stats = repo.merge_run_stats(run.id, {"search": {"n": 3}})
    assert stats == {"search": {"n": 3}}
    assert repo.get_run(run.id).current_step == "clean"


def test_raw_records_are_unique_per_run(repo: Repository) -> None:
    make_run(repo)
    raw = RawBusiness(source="osm", source_ref="node/1", name="A")
    assert repo.save_raw("run-1", raw) is True
    assert repo.save_raw("run-1", raw) is False
    assert [r.source_ref for r in repo.raw_for_run("run-1")] == ["node/1"]


def test_lead_roundtrip_with_json_and_bool(repo: Repository) -> None:
    make_run(repo)
    lead = make_lead(phones_extra=["+639171234567"], https_ok=False, flags=["no_https"])
    repo.insert_lead(lead)
    loaded = repo.get_lead(lead.lead_id)
    assert loaded.phones_extra == ["+639171234567"]
    assert loaded.https_ok is False
    assert loaded.flags == ["no_https"]


def test_link_run_lead_is_idempotent_and_is_new_survives_resume(repo: Repository) -> None:
    make_run(repo, "run-1")
    make_run(repo, "run-2")
    old = make_lead("run-1")
    repo.insert_lead(old)
    assert repo.link_run_lead("run-1", old.lead_id, "dentist") is True
    new = make_lead("run-2", business_name="B", name_key="b")
    repo.insert_lead(new)
    repo.link_run_lead("run-2", old.lead_id, "dentist")
    repo.link_run_lead("run-2", new.lead_id, "dentist")
    assert repo.count_new_leads("run-2") == 1
    # Simulated resume: linking again changes nothing.
    assert repo.link_run_lead("run-2", new.lead_id, "dentist") is False
    assert repo.count_new_leads("run-2") == 1
    assert [lead.lead_id for lead in repo.leads_for_run("run-2")] == [old.lead_id, new.lead_id]


def test_deleting_run_cascades_but_keeps_leads(repo: Repository) -> None:
    make_run(repo)
    lead = make_lead()
    repo.insert_lead(lead)
    repo.link_run_lead("run-1", lead.lead_id, "dentist")
    repo.save_raw("run-1", RawBusiness(source="osm", source_ref="node/1", name="A"))
    repo.conn.execute("DELETE FROM runs WHERE id = 'run-1'")
    assert repo.count_raw("run-1") == 0
    assert repo.count_run_leads("run-1") == 0
    assert repo.get_lead(lead.lead_id) is not None


def test_forget_deletes_cascades_and_suppresses(repo: Repository) -> None:
    make_run(repo)
    lead = make_lead(domain="smile.ph", emails_extra=["drjose@gmail.com"])
    repo.insert_lead(lead)
    repo.add_lead_source("osm", "node/1", lead.lead_id)
    repo.link_run_lead("run-1", lead.lead_id, "dentist")
    repo.save_raw("run-1", RawBusiness(source="osm", source_ref="node/1", name="Smile"))
    repo.save_raw("run-1", RawBusiness(source="osm", source_ref="node/2", name="Other"))
    assert repo.forget("domain", "smile.ph", "request") == 1
    assert repo.get_lead(lead.lead_id) is None
    assert repo.lead_by_source_ref("osm", "node/1") is None
    assert repo.count_run_leads("run-1") == 0
    assert [r.source_ref for r in repo.raw_for_run("run-1")] == ["node/2"]  # raw data gone too
    assert repo.is_suppressed("domain", "smile.ph")


def test_forget_domain_matches_email_domain(repo: Repository) -> None:
    make_run(repo)
    no_site = make_lead(email="info@clinic.com.ph")
    extra = make_lead(business_name="B", name_key="b", emails_extra=["dr@clinic.com.ph"])
    other = make_lead(business_name="C", name_key="c", email="info@otherclinic.com.ph")
    for lead in (no_site, extra, other):
        repo.insert_lead(lead)
    assert repo.forget("domain", "clinic.com.ph") == 2
    assert repo.get_lead(other.lead_id) is not None


def test_forget_by_extra_email_and_phone(repo: Repository) -> None:
    make_run(repo)
    a = make_lead(emails_extra=["drjose@gmail.com"])
    b = make_lead(business_name="B", name_key="b", phones_extra=["+639171234567"])
    repo.insert_lead(a)
    repo.insert_lead(b)
    assert repo.forget("email", "drjose@gmail.com") == 1
    assert repo.forget("phone", "+639171234567") == 1
    assert repo.suppressions()["phone"] == {"+639171234567"}


def test_purge_by_last_seen(repo: Repository) -> None:
    make_run(repo)
    stale = (datetime.now(UTC) - timedelta(days=200)).isoformat(timespec="seconds")
    repo.insert_lead(make_lead(last_seen_at=stale))
    fresh = make_lead(business_name="B", name_key="b")
    repo.insert_lead(fresh)
    repo.save_raw("run-1", RawBusiness(source="osm", source_ref="node/old", name="A"))
    repo.save_raw("run-1", RawBusiness(source="osm", source_ref="node/new", name="B"))
    repo.conn.execute(
        "UPDATE raw_records SET fetched_at = ? WHERE source_ref = ?", (stale, "node/old")
    )
    assert repo.purge(180) == 1
    assert repo.get_lead(fresh.lead_id) is not None
    assert [r.source_ref for r in repo.raw_for_run("run-1")] == ["node/new"]


def test_leads_to_enrich_scopes_to_run_and_statuses(repo: Repository) -> None:
    make_run(repo, "run-1")
    make_run(repo, "run-2")
    mine = make_lead(website="https://a.ph")
    failed = make_lead(
        business_name="F", name_key="f", website="https://f.ph", enrich_status="timeout"
    )
    other_run = make_lead("run-2", business_name="O", name_key="o", website="https://o.ph")
    no_site = make_lead(business_name="N", name_key="n")
    for lead in (mine, failed, other_run, no_site):
        repo.insert_lead(lead)
    for lead in (mine, failed, no_site):
        repo.link_run_lead("run-1", lead.lead_id, "dentist")
    repo.link_run_lead("run-2", other_run.lead_id, "dentist")
    assert repo.mark_no_website("run-1") == 1
    assert [x.lead_id for x in repo.leads_to_enrich("run-1")] == [mine.lead_id]
    retry = repo.leads_to_enrich("run-1", retry_failed=True)
    assert {x.lead_id for x in retry} == {mine.lead_id, failed.lead_id}


def test_caches(repo: Repository) -> None:
    repo.geo_cache_put("k", [{"a": 1}])
    assert repo.geo_cache_get("k") == [{"a": 1}]
    repo.robots_cache_put("https://a.ph:443", "User-agent: *", 200)
    assert repo.robots_cache_get("https://a.ph:443") == ("User-agent: *", 200)
    old = (datetime.now(UTC) - timedelta(hours=30)).isoformat(timespec="seconds")
    repo.conn.execute("UPDATE robots_cache SET fetched_at = ?", (old,))
    assert repo.robots_cache_get("https://a.ph:443") is None
    assert json.loads(json.dumps(repo.suppressions()["domain"], default=list)) == []
