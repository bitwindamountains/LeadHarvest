# LeadHarvest
Python 3.12 CLI that finds businesses, enriches them from their own websites, and exports leads.
Full spec: docs/BLUEPRINT.md. Read the relevant section before changing code.

## Commands
(On this machine uv isn't on PATH: use `python -m uv ...`.)
- Install: `uv sync` (`uv sync --all-extras` for Playwright `js` and Streamlit `ui`; then `uv run playwright install chromium`)
- Run: `uv run leadharvest --help`; UI: `uv run streamlit run app/streamlit_app.py`
- Test: `uv run pytest -q`; one test: `uv run pytest tests/unit/test_dedupe.py -k <name>`; live (network, needs real `LH_USER_AGENT`): `uv run pytest -m live`
- Lint/format: `uv run ruff check . --fix && uv run ruff format .`

## Architecture
- Pipeline (`pipeline.py`): `search → clean → enrich → score → export → done`, each step idempotent; `resume` restarts at `runs.current_step`. SQLite (`data/leads.db`) is the only state.
- `cli.py` (Typer) → `pipeline.py`; `batch.py` runs many jobs as ordinary runs tagged `options={"batch","row"}`; `monitor` = batch named `<name>@YYYY-Www` plus "new since last run" exports.
- Sources: `sources/osm_overpass.py`, YAML directory adapters (`config/directories/`); area resolution in `geo/nominatim.py`.
- Schema changes: add `storage/migrations/NNN_*.sql` (applied in order by `storage/db.py`).
- Exporters (`exporters/`) share `MANAGED_COLUMNS` in `base.py`; Sheets only touches managed columns.

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
