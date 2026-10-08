"""Streamlit UI: setup checks, password gate, form validation. Skipped without the `ui` extra."""

from __future__ import annotations

from pathlib import Path

import pytest

from leadharvest.categories import load_categories
from leadharvest.config import Settings
from leadharvest.geo.nominatim import LocationNotFound
from leadharvest.models import Lead, Run, new_lead_id, utcnow_iso
from leadharvest.storage.db import connect
from leadharvest.storage.repository import Repository
from leadharvest.ui_support import (
    can_resume,
    duration_text,
    export_choices,
    mark_interrupted,
    password_ok,
    result_rows,
    run_labels,
    setup_problems,
    share,
    short_time,
    validate_request,
)
from tests.conftest import TEST_UA

APP = Path(__file__).resolve().parents[2] / "app" / "streamlit_app.py"


def _settings(**kw: object) -> Settings:
    return Settings(_env_file=None, user_agent=TEST_UA, **kw)  # type: ignore[call-arg]


def test_password_ok_is_strict() -> None:
    assert password_ok(_settings(ui_password="s3cret"), "s3cret")
    assert not password_ok(_settings(ui_password="s3cret"), "S3cret")
    assert not password_ok(_settings(ui_password=""), "")
    assert not password_ok(_settings(ui_password="x"), "")


def test_setup_problems_and_choices(tmp_path) -> None:
    assert len(setup_problems(Settings(_env_file=None))) == 2  # type: ignore[call-arg]
    assert setup_problems(_settings(ui_password="p")) == []
    key = tmp_path / "sa.json"
    key.write_text("{}", encoding="utf-8")
    full = _settings(GOOGLE_SHEET_ID="abc", GOOGLE_SERVICE_ACCOUNT_FILE=key,
                     HUBSPOT_ACCESS_TOKEN="t")  # fmt: skip
    assert export_choices(full) == ["csv", "xlsx", "sheets", "hubspot"]
    assert export_choices(_settings()) == ["csv", "xlsx"]


def test_validate_request() -> None:
    cats = load_categories()
    ok = validate_request(cats, "dentist", "  Makati,   Philippines ", 50, ["csv"], False, True)
    assert not isinstance(ok, list)
    assert ok.location == "Makati, Philippines"
    errors = validate_request(cats, "nope", "x", 0, [], False, True)
    assert isinstance(errors, list) and len(errors) == 4


def _run(run_id: str = "r1", **kw: object) -> Run:
    data = {"id": run_id, "category": "dentist", "location": "Makati, Philippines",
            "area_name": "Makati", "created_at": "2026-10-08T16:20:05+00:00", **kw}  # fmt: skip
    return Run.model_validate(data)


def test_run_labels_stay_unique_for_repeat_searches() -> None:
    cats = load_categories()
    labels = run_labels([_run("aaaaaaaa"), _run("bbbbbbbb"), _run("c", category="gym")], cats)
    assert labels["aaaaaaaa"] == "Dental clinics · Makati · #aaaaaa"
    assert labels["bbbbbbbb"] == "Dental clinics · Makati · #bbbbbb"
    assert labels["c"].endswith("· Makati")  # unique already: no id suffix
    assert len(set(labels.values())) == 3


def test_presentation_helpers() -> None:
    assert short_time("2026-10-08T06:05:09+00:00") == "Oct 8, 06:05 UTC"
    assert duration_text(45.4) == "45 s" and duration_text(135) == "2 min 15 s"
    assert share(1, 3) == "1 (33%)" and share(0, 0) == "0"
    assert can_resume(_run(status="partial", current_step="enrich"))
    assert can_resume(_run(status="running", current_step="search"))
    assert not can_resume(_run(status="completed", current_step="done"))
    assert not can_resume(_run(status="failed", current_step="search"))
    now = utcnow_iso()
    leads = [
        Lead(lead_id=f"L{i}", business_name=f"B{i}", name_key=f"b{i}", score=s, flags=f,
             first_seen_at=now, last_seen_at=now, updated_at=now)
        for i, (s, f) in enumerate([(40, []), (90, ["no_https", "custom"]), (None, [])])
    ]  # fmt: skip
    rows = result_rows(leads, "dentist")
    assert [r["lead_id"] for r in rows] == ["L1", "L0", "L2"]  # best first, unscored last
    assert rows[0]["flags"] == "No HTTPS, custom"  # readable; unknown flags pass through


def test_mark_interrupted_only_touches_running_runs(tmp_path) -> None:
    repo = Repository(connect(tmp_path / "leads.db"))
    repo.create_run(_run("live", status="running"))
    repo.create_run(_run("done", status="completed", current_step="done"))
    mark_interrupted(repo, "live")
    mark_interrupted(repo, "done")
    mark_interrupted(repo, "missing")
    assert (repo.get_run("live").status, repo.get_run("live").error) == ("partial", "interrupted")
    assert repo.get_run("done").status == "completed"
    repo.conn.close()


streamlit = pytest.importorskip("streamlit")


@pytest.fixture
def ui_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.setenv("LH_USER_AGENT", TEST_UA)
    monkeypatch.setenv("LH_DB_PATH", str(tmp_path / "leads.db"))
    monkeypatch.setenv("LH_UI_PASSWORD", "correct horse")
    return tmp_path


def _app():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(APP), default_timeout=30)


def test_ui_requires_password_configuration(ui_env, monkeypatch) -> None:
    monkeypatch.delenv("LH_UI_PASSWORD")
    at = _app().run()
    assert any("LH_UI_PASSWORD" in e.value for e in at.error)
    assert len(at.text_input) == 0


def test_ui_password_gate_then_form(ui_env) -> None:
    at = _app().run()
    assert len(at.selectbox) == 0  # form hidden until signed in
    at.text_input[0].input("wrong")
    at.button[0].click().run()  # the sign-in form's submit button (Enter does the same)
    assert any("Wrong password" in e.value for e in at.error)
    at.text_input[0].input("correct horse")
    at.button[0].click().run()
    assert not at.exception
    assert at.selectbox[0].value == "dentist"
    assert at.multiselect[0].value == ["csv", "xlsx"]
    assert at.multiselect[0].options == ["CSV", "Excel (XLSX)"]  # readable names, not ids


def _signed_in():
    at = _app()
    at.session_state["authed"] = True
    return at.run()


def test_ui_form_validation_blocks_bad_input(ui_env) -> None:
    at = _signed_in()
    at.text_input[0].input("x")
    at.button(key="find").click().run()
    assert any("Enter a location" in e.value for e in at.error)


# ---- runs: history, results, resume, new runs ---------------------------------------------------


def _seed(path, run_id: str, status: str, step: str, leads: int = 0, error: str | None = None):
    repo = Repository(connect(path))
    repo.create_run(Run(
        id=run_id, category="dentist", location="Makati", area_name="Makati", status=status,
        current_step=step, error=error, created_at=utcnow_iso(),
    ))  # fmt: skip
    for i in range(leads):
        now = utcnow_iso()
        lead = Lead(
            lead_id=new_lead_id(), business_name=f"Clinic {i}", name_key=f"clinic {i}",
            email="info@clinic.ph" if i == 0 else None, score=10 * i, flags=["no_website"],
            first_seen_run_id=run_id, first_seen_at=now, last_seen_at=now, updated_at=now,
        )  # fmt: skip
        repo.insert_lead(lead)
        repo.link_run_lead(run_id, lead.lead_id, "dentist")
    repo.conn.close()


def _finish(run_status: str = "completed"):
    """A stand-in for Pipeline.execute that finishes the run without any network."""

    async def execute(self, run_id, category, **kwargs):
        self.repo.update_run(run_id, status=run_status, current_step="done")
        return self.repo.get_run(run_id)

    return execute


def test_ui_history_switches_between_runs(ui_env) -> None:
    _seed(ui_env / "leads.db", "run-done", "completed", "done", leads=3)
    _seed(ui_env / "leads.db", "run-paused", "partial", "enrich", error="Overpass timeout")
    at = _signed_in()
    picker = at.sidebar.radio[0]
    assert picker.value is None  # nothing open until picked
    # Same search twice: labels get a short run id so Streamlit can tell them apart.
    assert len(set(picker.options)) == 2
    for run_id in ("run-done", "run-paused", "run-done"):
        at.sidebar.radio[0].set_value(run_id).run()
        assert not at.exception
        resumable = any(b.label == "Resume run" for b in at.button)
        assert resumable is (run_id == "run-paused")
    assert at.metric[0].value == "3"  # leads
    assert at.metric[2].value == "1 (33%)"  # with email
    assert at.dataframe[0].value["business_name"].tolist()[0] == "Clinic 2"  # best score first


def test_ui_resume_finishes_a_paused_run(ui_env, monkeypatch) -> None:
    monkeypatch.setattr("leadharvest.pipeline.Pipeline.execute", _finish())
    _seed(ui_env / "leads.db", "run-paused", "partial", "enrich", error="interrupted")
    at = _signed_in()
    at.sidebar.radio[0].set_value("run-paused").run()
    assert any("interrupted" in w.value for w in at.warning)
    next(b for b in at.button if b.label == "Resume run").click().run()
    assert not at.exception
    assert not any(b.label == "Resume run" for b in at.button)
    assert any("No businesses found" in i.value for i in at.info)


def test_ui_new_run_opens_its_results(ui_env, monkeypatch) -> None:
    monkeypatch.setattr("leadharvest.pipeline.Pipeline.execute", _finish())
    at = _signed_in()
    at.text_input[0].input("Makati, Philippines")
    at.button(key="find").click().run()
    assert not at.exception
    run_id = at.sidebar.radio[0].value
    assert run_id is not None  # the new run is selected in the history
    assert at.subheader[0].value == "Dental clinics in Makati, Philippines"


def test_ui_location_not_found_suggests_names(ui_env, monkeypatch) -> None:
    async def not_found(self, run_id, category, **kwargs):
        raise LocationNotFound("Atlantis", ["Atlanta, Georgia"])

    monkeypatch.setattr("leadharvest.pipeline.Pipeline.execute", not_found)
    at = _signed_in()
    at.text_input[0].input("Atlantis")
    at.button(key="find").click().run()
    assert any("Atlanta, Georgia" in e.value for e in at.error)
    at.run()  # next interaction: the failed run is listed, but not opened
    assert len(at.sidebar.radio[0].options) == 1
    assert at.sidebar.radio[0].value is None
