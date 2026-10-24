"""The UI's All runs page and the run id in the URL (`?run=`)."""

from __future__ import annotations

from datetime import UTC

from leadharvest.categories import load_categories
from leadharvest.storage.db import connect
from leadharvest.storage.repository import Repository
from leadharvest.ui_runs import filter_runs, run_rows
from tests.integration.test_ui import _run, _seed, _signed_in, ui_env  # noqa: F401 (fixture)


def test_filter_runs_by_words_and_status() -> None:
    cats = load_categories()
    runs = [
        _run("aaaa1111", status="completed"),
        _run("bbbb2222", category="gym", status="partial"),
        _run("cccc3333", area_name=None, location="Cebu City", status="failed"),
    ]
    ids = lambda found: [r.id for r in found]  # noqa: E731
    assert ids(filter_runs(runs, "", [], cats)) == ["aaaa1111", "bbbb2222", "cccc3333"]
    assert ids(filter_runs(runs, "  DENTAL  makati ", [], cats)) == ["aaaa1111"]  # label, place
    assert ids(filter_runs(runs, "cebu", [], cats)) == ["cccc3333"]  # typed place, unresolved
    assert ids(filter_runs(runs, "bbbb", [], cats)) == ["bbbb2222"]  # id prefix
    assert ids(filter_runs(runs, "", ["partial", "failed"], cats)) == ["bbbb2222", "cccc3333"]
    assert filter_runs(runs, "gym", ["completed"], cats) == []  # both must match


def test_run_rows() -> None:
    rows = run_rows([_run("aaaa1111bbbb", status="partial")], {"aaaa1111bbbb": 4},
                    load_categories(), UTC)  # fmt: skip
    assert rows == [{"Started": "Oct 8, 16:20 UTC", "Search": "Dental clinics · Makati",
                     "Status": "Paused", "Leads": 4, "Run": "aaaa1111"}]  # fmt: skip
    assert run_rows([_run("x")], {}, load_categories())[0]["Leads"] == 0  # no leads linked


def test_repository_lists_every_run_and_counts_leads(ui_env) -> None:  # noqa: F811
    for i in range(25):  # more than list_runs' default of 20
        _seed(ui_env / "leads.db", f"run-{i:02}", "completed", "done", leads=1 if i == 0 else 0)
    repo = Repository(connect(ui_env / "leads.db"))
    assert len(repo.list_runs()) == 20
    assert len(repo.list_runs(None)) == 25
    assert repo.run_lead_counts() == {"run-00": 1}
    repo.conn.close()


def test_ui_all_runs_page_lists_and_filters(ui_env) -> None:  # noqa: F811
    _seed(ui_env / "leads.db", "run-done", "completed", "done", leads=3)
    _seed(ui_env / "leads.db", "run-paused", "partial", "enrich")
    at = _signed_in()
    at.sidebar.button(key="all_runs_button").click().run()
    assert not at.exception
    assert at.title[0].value == "All runs"
    table = at.dataframe[0].value
    assert table["Run"].tolist() == ["run-paus", "run-done"]  # newest first
    assert table["Leads"].tolist() == [0, 3]
    assert at.sidebar.radio[0].value is None  # no search highlighted here
    assert not at.query_params.get("run")
    at.multiselect(key="runs-status").select("completed").run()
    assert at.dataframe[0].value["Run"].tolist() == ["run-done"]
    at.text_input(key="runs-filter").input("nothing like this").run()
    assert any("No runs match" in i.value for i in at.info)
    # Picking a search in the sidebar leaves the page.
    at.sidebar.radio[0].set_value("run-paused").run()
    assert at.title[0].value != "All runs"
    assert at.query_params["run"] == "run-paused"


def test_ui_opens_the_run_named_in_the_url(ui_env) -> None:  # noqa: F811
    _seed(ui_env / "leads.db", "run-done", "completed", "done", leads=3)
    _seed(ui_env / "leads.db", "run-paused", "partial", "enrich")
    from streamlit.testing.v1 import AppTest

    from tests.integration.test_ui import APP

    at = AppTest.from_file(str(APP), default_timeout=30)
    at.query_params["run"] = "run-d"  # a unique prefix
    at.session_state["authed"] = True
    at.run()
    assert not at.exception
    assert at.metric[0].value == "3"  # run-done's leads, an earlier run of the search
    assert at.query_params["run"] == "run-done"  # the full id, ready to bookmark
    at.sidebar.button(key="new_search").click().run()
    assert not at.query_params.get("run")


def test_ui_ignores_an_unknown_run_in_the_url(ui_env) -> None:  # noqa: F811
    _seed(ui_env / "leads.db", "run-done", "completed", "done")
    from streamlit.testing.v1 import AppTest

    from tests.integration.test_ui import APP

    at = AppTest.from_file(str(APP), default_timeout=30)
    at.query_params["run"] = "nope"
    at.session_state["authed"] = True
    at.run()
    assert not at.exception
    assert at.button(key="find")  # the search page
    assert not at.query_params.get("run")
