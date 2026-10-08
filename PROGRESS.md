# PROGRESS

## Current task

All code on the roadmap except Google Places is built and committed. What's left is the owner's live verification (Next steps 2–4) and Phase 7.

## Done (newest first)

- 2026-10-09: Audit fixes 5–9 (204 tests pass, lint clean):
  - **HubSpot:** an export remembers the companies it created (keyed by domain, or by name when there is no domain), so the search index lag can't cause duplicates.
  - **SQLite:** `Repository.transaction` uses `BEGIN IMMEDIATE`. The test fails with a plain `BEGIN`.
  - **robots.txt:** a 429 now means disallow everything.
  - **MX:** the score step looks up every email domain in the run in one concurrent pass.
  - **Removed:** `upsert_lead` and `PlaywrightRenderer.rendered`. Also typed the `_record_status` limiter and fixed the `_social_url` docstring.
- 2026-10-09: Full repo audit, then fixes 1–4 (200 tests pass, lint clean):
  - **SSRF:** `render.py` re-checks the final URL, robots.txt and server address after `goto`. Verified that without it, Chromium follows a redirect to a private host and the page gets read. `PoliteFetcher.check_peer` rejects responses from non-public peers (DNS rebinding). It is skipped behind a proxy, and the GET is still sent (`ponytail:` note).
  - **Privacy:** `forget --domain` matches email domains too. `forget` and `purge` delete `raw_records`. Stats keep only a count of dropped emails.
  - **Batch:** an edited row (category or location) gets a new run instead of being skipped or resumed.

- 2026-10-01: Review of 0.3.0. Fixed `monitor`: "new since last run" compared against any earlier completed run of the same category and area. That included one-off `run`s and other monitors, so a client could get a wrong "new" list. Now it compares only against the same monitor (`Repository.previous_run`), and there is a regression test for it.
- 2026-10-01: Session workflow (this file plus a CLAUDE.md update).
- 2026-10-01: 0.3.0 (`6dc4508`). 195 tests pass, lint is clean, coverage is 89%.
  - **Tech signals:** `enrich/signals.py` and migration 003. Adds the `tech` export column and the `no_mobile_viewport` flag.
  - **Batch mode:** `batch.py` and the `batch` CLI command (CSV file or `--from-sheet`). It resumes on re-run, and one bad row doesn't stop the rest.
  - **Weekly monitor:** the `monitor` command. Exports "new since last run" to `-new` CSV/XLSX files and a `<tab> - new` Sheets tab.
  - **Workflow:** `.github/workflows/monitor.yml` runs weekly and carries the DB between runs as an AES-256-encrypted artifact. The openssl round trip was verified locally.
- 2026-10-01: 0.2.0 (`b909fb0`): scoring and flags, MX check, Playwright `--js`, YAML directory adapters, HubSpot export, Streamlit UI.
- 2026-10-01: 0.1.0 MVP (`6c30c8a`): OSM search, clean and dedupe, polite enrichment, CSV/XLSX/Sheets export, resume.
- 2026-10-01: Blueprint review and v1.1 fixes (`docs/planning/02_*`; the spec is `docs/BLUEPRINT.md`). Production plan in `docs/planning/03_*`.

## Next steps

1. Done: 0.3.0 is committed.
2. Owner: put a real contact email in `LH_USER_AGENT` in `.env`, then:
   - run `uv run pytest -m live`;
   - do a live `run --limit 20` for Makati;
   - test a real Sheets export, and HubSpot if it's used.
3. Owner: check Ctrl+C by hand on Windows. This is the last open Definition of Done item.
4. To use the monitor workflow:
   - push the repo;
   - add the `LH_USER_AGENT`, `LH_DB_PASSPHRASE`, `GOOGLE_SHEET_ID` and `GOOGLE_SERVICE_ACCOUNT_JSON` secrets;
   - commit `config/monitor.csv`.
5. Phase 7: record the demo and publish the repo.
6. Google Places source: blocked on decision D1.

## Notes / decisions

- **Open decisions:** D1 (Google Places storage terms) and D2 (ODbL obligations) are in blueprint section 23. Decide them before selling.
- **Build order:** V1 and V2 were built ahead of the live Definition of Done run, at the owner's request. The blueprint had said to build V2 only once a client pays for it.
- **Owner's email:** it identifies the owner only. Never send it in live requests from this environment.
- **Never commit:** `.env`, `secrets/` and `data/`. These are gitignored.
- **No logs artifact:** the monitor workflow uploads no logs, because artifacts on a public repo are readable by any signed-in user.
- **Refreshes:** a refresh overwrites a lead's fields only when it is that lead's sole source. This stops two sources from flip-flopping a website between runs.
