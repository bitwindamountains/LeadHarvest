"""Streamlit UI: setup checks, password gate, form validation. Skipped without the `ui` extra."""

from __future__ import annotations

from pathlib import Path

import pytest

from leadharvest.categories import load_categories
from leadharvest.config import Settings
from leadharvest.ui_support import export_choices, password_ok, setup_problems, validate_request
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
    at.text_input[0].input("wrong").run()
    at.button[0].click().run()
    assert any("Wrong password" in e.value for e in at.error)
    at.text_input[0].input("correct horse").run()
    at.button[0].click().run()
    assert not at.exception
    assert at.selectbox[0].value == "dentist"
    assert at.multiselect[0].value == ["csv", "xlsx"]


def test_ui_form_validation_blocks_bad_input(ui_env) -> None:
    at = _app()
    at.session_state["authed"] = True
    at.run()
    at.text_input[0].input("x")
    at.button[0].click().run()  # the form's submit button
    assert any("Enter a location" in e.value for e in at.error)
