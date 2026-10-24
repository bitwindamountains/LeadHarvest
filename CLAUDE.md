# LeadHarvest
Python 3.12 CLI that finds businesses, enriches them from their own websites, and exports leads.
Full spec: docs/BLUEPRINT.md. Read the relevant section before changing code.

## Commands
(On this machine uv isn't on PATH: use `python -m uv ...`.)
- Install: `uv sync` (`uv sync --all-extras` for Playwright `js`, Streamlit `ui` and DuckDB `overture`; then `uv run playwright install chromium`)
- Run: `uv run leadharvest --help`; UI: `uv run streamlit run app/streamlit_app.py`
- Test: `uv run pytest -q`; one test: `uv run pytest tests/unit/test_dedupe.py -k <name>`; live (network, needs real `LH_USER_AGENT`): `uv run pytest -m live`
- Lint/format: `uv run ruff check . --fix && uv run ruff format .`

## Architecture
- Pipeline (`pipeline.py`): `search → clean → enrich → score → export → done`, each step idempotent; `resume` restarts at `runs.current_step`. SQLite (`data/leads.db`) is the only state.
- `cli.py` (Typer) → `pipeline.py`; `batch.py` runs many jobs as ordinary runs tagged `options={"batch","row"}`; `monitor` = batch named `<name>@YYYY-Www` plus "new since last run" exports.
- Sources (default `sources.overture.default_source_names()`: Overture when DuckDB is installed, else OSM; decision D6): `sources/osm_overpass.py`, `sources/overture.py` (DuckDB over the latest Overture places GeoParquet, filtered to the Nominatim boundary; tests build a synthetic parquet), YAML directory adapters (`config/directories/`); area resolution and boundaries in `geo/nominatim.py`. Export attribution follows the sources (`exporters/base.attribution`).
- Schema changes: add `storage/migrations/NNN_*.sql` (applied in order by `storage/db.py`).
- Exporters (`exporters/`) share `MANAGED_COLUMNS` in `base.py`; Sheets only touches managed columns.
- UI: `app/streamlit_app.py` routes between `app/views/` (one module per screen: `signin`, `sidebar`, `search`, `run`, plus `common`). The sidebar lists one entry per search (`ui_support.group_runs`); its option values are each search's latest run id, and `open_run` in session state holds an earlier run picked on the run page. Design rules and the states each screen must show are in `docs/UI.md`. Put logic in `ui_support.py` (tested in `tests/integration/test_ui.py` with AppTest and a fake `Pipeline.execute`). Theme lives in `.streamlit/config.toml` (fonts, colours, sidebar), so launch from the repo root. Logo, mark and the sign-in brand panel live in `app/assets/`. `st.html` strips `<svg>` and `data:` images, so the panel is pure CSS. Use Material icons (`:material/...:`), never emojis. Radio and select options need unique labels.

## Status and roadmap
Details, history and the full roadmap are in PROGRESS.md; keep this summary in sync with it.
- **Built:** blueprint phases 0–6, 8 (except 8.6 Google Places) and 9, plus the 2026-10-09 audit fixes and UI redesign. On `main` and pushed through `f8e14d2` (240 tests): Overture is the default source (D6), dedupe rule 4 plus `leadharvest dedupe` merge one place from two sources, and a failed source no longer stops a multi-source run.
- Also pushed: run history grouped by search (sidebar shows each search once; the run page has a "Run history" picker).
- **Next (direction A, run history):** an "All runs" page with the run id in the URL, then collapse batches into one sidebar entry.
- **Now (owner, live):**
  - CI green on GitHub;
  - `pytest -m live`;
  - a live Makati `run --limit 100` (DoD item 1), then tune D5;
  - Ctrl+C then `resume` on Windows (DoD item 8);
  - a real Sheets/HubSpot export, and one live UI run.
- **Then:** Phase 7, meaning README screenshots and real hit rate (first Argao numbers are in PROGRESS), the 90-second demo, and confirming the GitHub repo has no secrets or real data.
- **Before selling:** decide D1, and D2 only if OSM goes into client lists (blueprint section 23), set up the monitor workflow secrets and `config/monitor.csv`, then `gh workflow enable "Weekly monitor"` (disabled 2026-10-24).
- **Backlog:**
  - background runs in the UI;
  - block SSRF at connect time;
  - Google Places (blocked on D1);
  - more directory adapters;
  - D4 (rows a client deletes).

## Rules
- Work only on the task I name. Stop and summarize when done.
- Don't add dependencies without asking.
- Never weaken politeness rules (robots.txt, delays, User-Agent) or add CAPTCHA/proxy evasion.
- Read env vars only in config.py. Never print or log secrets.
- All SQL goes in storage/repository.py. All HTTP clients come from http.py; website fetches go through enrich/fetcher.py.
- Every website fetch passes the SSRF guard and robots.txt check at each redirect hop.
- Phones are text (E.164), never numbers. Sheets writes use RAW and header-mapped columns.
- Tests must not hit the network: use respx and tests/fixtures. Inject fake resolver/clock/sleep (see tests/conftest.py).
- Add or update tests for every behavior change and run them before finishing.
- Keep functions small and typed; split files over ~300 lines.

## Session workflow
- At the start of each session, read PROGRESS.md to see current status and next steps.
- After any major or relevant change (new feature, architecture change, important decision, bug fix, new commands), update PROGRESS.md with what was done and what's next.
- If the change affects lasting project knowledge (structure, setup, commands, conventions), also update CLAUDE.md.
- Keep CLAUDE.md concise; put task-specific details in PROGRESS.md.
- Before the user runs /clear or /compact, make sure both files are up to date.
