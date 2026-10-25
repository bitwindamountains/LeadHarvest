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
- Exporters (`exporters/`) share `MANAGED_COLUMNS` and the summary (`about_rows`) in `base.py`; Sheets only touches managed columns, plus its own `<tab> - summary` tab.
- UI: `app/streamlit_app.py` routes between `app/views/` (one module per screen: `signin`, `sidebar`, `search`, `run` with its leads table in `leads`, `runs`, plus `common`). The sidebar lists one entry per search, or per batch (`ui_support.group_runs` with `ui_runs.entry_key`; a batch opens a batch page, `open_batch` in session state); its option values are each search's latest run id, and `open_run` in session state holds an earlier run picked on the run page or on the All runs page (`views/runs.py`, logic in `ui_runs.py`; `all_runs` in session state shows it). The open run's id is mirrored in the URL (`?run=<id>`). UI runs run on background threads (`ui_jobs.JOBS`, one per server process; `views.common.execute` starts one, `live_progress` polls it), so a UI test that starts a run calls `JOBS.wait()` before `at.run()`. Design rules and the states each screen must show are in `docs/UI.md`. Put logic in `ui_support.py` (tested in `tests/integration/test_ui.py` with AppTest and a fake `Pipeline.execute`). Theme lives in `.streamlit/config.toml` (fonts, colours, sidebar), so launch from the repo root. Logo, mark and the sign-in brand panel live in `app/assets/`. `st.html` strips `<svg>` and `data:` images, so the panel is pure CSS. Use Material icons (`:material/...:`), never emojis. Radio and select options need unique labels.

## Status and roadmap
Details, history and the full roadmap are in PROGRESS.md; keep this summary in sync with it.
- **Built:** blueprint phases 0–6, 8 (8.6 Google Places dropped, D1) and 9, plus the 2026-10-09 audit fixes and UI redesign. On `main` and pushed through `f8e14d2` (240 tests): Overture is the default source (D6), dedupe rule 4 plus `leadharvest dedupe` merge one place from two sources, and a failed source no longer stops a multi-source run.
- Also pushed: run history grouped by search (sidebar shows each search once; the run page has a "Run history" picker).
- Also pushed: the All runs page (every run, filterable, pick a row to open) and the run id in the URL (246 tests).
- Also pushed: each batch is one sidebar entry that opens a batch page (direction A done, 249 tests).
- Also pushed: reachable leads, slice 1: the leads table hides leads with no way to contact (switch, on by default) and email/phone are one-click links (250 tests).
- Also pushed: reachable leads, slice 2: a `why_contact` export column (top two flags in plain words; 251 tests).
- Also pushed: reachable leads, slice 3: one export summary (`about_rows`) with reachable and per-opening counts, now also a Sheets summary tab (252 tests).
- Also pushed: reachable leads, Messenger links: a Messenger column in the leads table (`m.me/<page>`, `clean.normalize.messenger_link`; verified in a browser; 264 tests). Reachable leads is done.
- **Now (owner, live):**
  - none left: the live Sheets export and a live UI run with Stop and Resume passed 2026-10-25 (HubSpot only if a client uses it).
- 2026-10-25 deployment review: blockers and recommended fixes done (286 tests). The UI now serves on 127.0.0.1 only, and HTTP clients ignore environment proxies (`trust_env=False`).
- Also pushed: Phase 7 slice 1: README screenshots (`docs/images/`, contacts masked), real hit rates and redacted sample rows; repo checked clean of secrets and real data (7.1, 7.3 done).
- **Then:** the 90-second demo (7.2), recorded by the owner after a live Sheets export.
- **Before selling:** D1 and D2 are decided (2026-10-25: no Google Places, no OSM in client lists; blueprint section 23); set up the monitor workflow secrets and `config/monitor.csv`, then `gh workflow enable "Weekly monitor"` (disabled 2026-10-24).
- Also pushed: background runs in the UI (`ui_jobs.JOBS` threads; the run page shows live progress and survives clicks and reloads; 265 tests).
- Also pushed: a Stop run button (`Job.stop` cancels the run's asyncio task; paused as "stopped", resumable; 268 tests).
- Also pushed: the SSRF guard also runs at connect time (`netguard.PublicOnlyBackend` in every `make_client` client; 272 tests).
- Also pushed: the JS renderer's Chromium connects only through a local SSRF guard proxy (`enrich/render_proxy.py`); redirect hops can't reach private addresses (276 tests).
- Also pushed: D4, rows a client deletes from a Sheet stay deleted (`sheet_rows`, migration 006; `exporter_factory(settings, repo)`; 280 tests).
- **Backlog:**
  - more directory adapters (none usable yet; see PROGRESS).

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
