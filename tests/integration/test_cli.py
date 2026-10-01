"""CLI behavior that doesn't need the network: config errors, listing, privacy commands, export."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from leadharvest.cli import app
from leadharvest.models import Lead, Run, new_lead_id, utcnow_iso
from leadharvest.storage.db import connect
from leadharvest.storage.repository import Repository
from tests.conftest import TEST_UA

runner = CliRunner()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.setenv("LH_USER_AGENT", TEST_UA)
    monkeypatch.setenv("LH_DB_PATH", str(tmp_path / "leads.db"))
    monkeypatch.setenv("LH_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("LH_LOG_DIR", str(tmp_path / "logs"))
    return tmp_path


def seed(db_path) -> tuple[str, str]:
    conn = connect(db_path)
    repo = Repository(conn)
    run = Run(
        id="12345678-aaaa",
        category="dentist",
        location="Makati",
        area_name="Makati",
        current_step="done",
        status="completed",
        created_at=utcnow_iso(),
    )
    repo.create_run(run)
    now = utcnow_iso()
    lead = Lead(
        lead_id=new_lead_id(),
        business_name="Smile",
        name_key="smile",
        domain="smile.ph",
        website="https://smile.ph",
        phone="+639171234567",
        first_seen_run_id=run.id,
        first_seen_at=now,
        last_seen_at=now,
        updated_at=now,
    )
    repo.insert_lead(lead)
    repo.link_run_lead(run.id, lead.lead_id, "dentist")
    conn.close()
    return run.id, lead.lead_id


def test_help_and_categories(env) -> None:
    assert runner.invoke(app, ["--help"]).exit_code == 0
    result = runner.invoke(app, ["categories"])
    assert result.exit_code == 0
    assert "dentist" in result.output


def test_run_refuses_placeholder_user_agent(env, monkeypatch) -> None:
    monkeypatch.setenv("LH_USER_AGENT", "LeadHarvest/0.1 (+mailto:you@example.com)")
    result = runner.invoke(app, ["run", "--category", "dentist", "--location", "Makati"])
    assert result.exit_code == 2
    assert "placeholder" in result.output


def test_run_unknown_category_and_bad_targets(env) -> None:
    result = runner.invoke(app, ["run", "--category", "dentst", "--location", "Makati"])
    assert result.exit_code == 2
    assert "dentist" in result.output
    result = runner.invoke(app, ["run", "--category", "dentist", "--location", "X", "--to", "pdf"])
    assert result.exit_code == 2
    result = runner.invoke(
        app, ["run", "--category", "dentist", "--location", "X", "--to", "sheets"]
    )
    assert result.exit_code == 2
    assert "GOOGLE_SHEET_ID" in result.output


def test_runs_export_forget_purge(env) -> None:
    run_id, lead_id = seed(env / "leads.db")
    result = runner.invoke(app, ["runs"])
    assert result.exit_code == 0 and run_id[:8] in result.output

    result = runner.invoke(app, ["export", "--run", run_id[:8], "--to", "csv,xlsx"])
    assert result.exit_code == 0, result.output
    assert len(list((env / "exports").glob("*.xlsx"))) == 1

    result = runner.invoke(app, ["forget", "--domain", "https://www.smile.ph/contact"])
    assert result.exit_code == 0
    assert "Deleted 1" in result.output
    repo = Repository(connect(env / "leads.db"))
    assert repo.get_lead(lead_id) is None
    assert repo.is_suppressed("domain", "smile.ph")
    repo.conn.close()

    assert runner.invoke(app, ["forget", "--domain", "x.wixsite.com"]).exit_code == 2
    assert runner.invoke(app, ["forget"]).exit_code == 2
    assert runner.invoke(app, ["purge", "--not-seen-days", "30", "--yes"]).exit_code == 0


def test_resume_unknown_run(env) -> None:
    result = runner.invoke(app, ["resume", "--run", "nope"])
    assert result.exit_code == 2
