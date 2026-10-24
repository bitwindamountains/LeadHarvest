"""The UI's All runs page and the run id in the URL (`?run=`)."""

from __future__ import annotations

from datetime import UTC

from leadharvest.categories import load_categories
from leadharvest.storage.db import connect
from leadharvest.storage.repository import Repository
from leadharvest.ui_runs import batch_caption, batch_name, entry_key, filter_runs, run_rows
from leadharvest.ui_support import group_runs
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


# ---- batches: one sidebar entry, a batch page, and back ------------------------------------------


def _seed_batch(path, name: str, rows: dict[int, tuple[str, str]], leads_row: int = 1) -> None:
    """rows: {row: (run id, status)}; the run on `leads_row` gets 2 leads."""
    for row, (run_id, status) in rows.items():
        _seed(path, run_id, status, "done", leads=2 if row == leads_row else 0)
    repo = Repository(connect(path))
    for row, (run_id, _) in rows.items():
        repo.conn.execute(
            "UPDATE runs SET options = json_object('batch', ?, 'row', ?) WHERE id = ?",
            (name, row, run_id),
        )
    repo.conn.commit()
    repo.conn.close()


def test_batch_helpers() -> None:
    plain, in_batch = _run("a"), _run("b", options={"batch": "clinics", "row": 1})
    assert (batch_name(plain), batch_name(in_batch)) == (None, "clinics")
    assert entry_key(in_batch) == ("batch", "clinics")
    other = _run("c", category="gym", options={"batch": "clinics", "row": 2})
    groups = group_runs([in_batch, plain, other], key=entry_key)
    assert [[r.id for r in g] for g in groups] == [["b", "c"], ["a"]]  # one entry per batch
    assert [[r.id for r in g] for g in group_runs([in_batch, plain, other])] == [
        ["b", "a"],
        ["c"],
    ]  # by search (the run page's history) a batch row joins its search
    assert batch_caption([in_batch, _run("d", status="completed")], {"b": 3, "d": 2}) == (
        "1 of 2 completed · 5 leads")  # fmt: skip


def test_repository_batch_runs_keeps_each_rows_latest(ui_env) -> None:  # noqa: F811
    _seed_batch(
        ui_env / "leads.db", "clinics", {2: ("row2", "completed"), 1: ("row1-old", "failed")}
    )
    _seed_batch(ui_env / "leads.db", "clinics", {1: ("row1-new", "completed")})
    _seed_batch(ui_env / "leads.db", "other", {1: ("elsewhere", "completed")})
    repo = Repository(connect(ui_env / "leads.db"))
    assert [r.id for r in repo.batch_runs("clinics")] == ["row1-new", "row2"]
    assert repo.batch_runs("nope") == []
    repo.conn.close()


def test_ui_batch_is_one_sidebar_entry_with_its_own_page(ui_env) -> None:  # noqa: F811
    _seed(ui_env / "leads.db", "solo", "completed", "done")
    _seed_batch(ui_env / "leads.db", "clinics", {1: ("row1", "completed"), 2: ("row2", "partial")})
    at = _signed_in()
    picker = at.sidebar.radio[0]
    # The batch's rows are dentist searches in Makati too, yet "solo" needs no run id suffix.
    assert picker.options == ["Batch · clinics", "Dental clinics · Makati"]
    at.sidebar.radio[0].set_value("row2").run()  # the batch's entry (its newest run)
    assert not at.exception
    assert at.title[0].value == "clinics"
    assert at.dataframe[0].value["Run"].tolist() == ["row1", "row2"]  # row order
    assert any("1 of 2 completed · 2 leads" in c.value for c in at.caption)
    assert not at.query_params.get("run")
    # A row opens its run (what picking a table row does), which links back to the batch.
    at.session_state["select_run"] = "row1"
    at.session_state["open_batch"] = None  # select_run clears it
    at.run()
    assert at.title[0].value != "clinics"
    assert at.query_params["run"] == "row1"
    assert at.sidebar.radio[0].value == "row2"  # the batch's entry stays selected
    at.button(key="batch_link").click().run()
    assert at.title[0].value == "clinics"
    # Another entry leaves the batch.
    at.sidebar.radio[0].set_value("solo").run()
    assert at.title[0].value != "clinics" and at.query_params["run"] == "solo"
