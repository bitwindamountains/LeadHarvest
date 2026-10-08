# PROGRESS

## Current task

**Status (2026-10-09):** 0.3.0 plus the audit fixes and the UI redesign are on `main` and pushed (`8db28b6`). 211 tests pass and lint is clean. Blueprint phases 0–6, 8 (except 8.6 Google Places) and 9 are built.

**What's left:** live verification by the owner (two "Definition of done" items are still open), Phase 7 packaging, and decisions D1/D2 before selling. See the Roadmap below.

## Done (newest first)

- 2026-10-09: UI/UX review and redesign of the Streamlit app (211 tests pass, lint clean). Reviewed in a real browser at desktop and phone widths, against a seeded throwaway DB with no network.
  - **Problems found:**
    - results lived only in session state, so a reload lost them and there was no history;
    - paused runs could only be resumed from the CLI;
    - any click mid-run killed the run and left it stuck as "running";
    - Enter didn't sign in;
    - progress bar was misleading;
    - raw export ids sat in red chips;
    - wide table full of "None";
    - phone layout put the fields out of order.
  - **Built:** `app/streamlit_app.py` rewritten: sign-in form; sidebar run history (`st.radio` with captions); a collapsible "New search" form; `st.status` progress; results with metrics, downloads, a Sheets link and a column-configured table; a Resume button.
  - **Shared logic:** testable logic lives in `ui_support.py` (`run_labels`, `result_rows`, `mark_interrupted`, `can_resume`, formatting).
  - **Config:** theme and toolbar settings live in `.streamlit/config.toml`.
  - **Gotchas found:**
    - Streamlit (1.64) tells radio options apart by their label, so `run_labels` adds `#<id>` when labels repeat.
    - Streamlit's rerun and stop exceptions are `BaseException`s that the pipeline doesn't catch, hence `mark_interrupted`.
  - **Not done:** running pipelines in a background thread, so a run would survive clicks and reloads. It's the bigger fix if interruptions turn out to be common.
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

## Roadmap

Blueprint section 18 has the phase list; section 19 has the Definition of Done (DoD).

### Now: live verification (owner; needs a real contact email in `LH_USER_AGENT` in `.env`)
1. **CI:** check that GitHub Actions passed for `879d552` (audit fixes) and `8db28b6` (UI). This is the first CI run of the new real-browser tests on Ubuntu and Windows.
2. **Live tests:** run `uv run pytest -m live`.
3. **DoD item 1:** a live `leadharvest run --category dentist --location "Makati, Philippines" --limit 100`. It is also the first real-world test of the SSRF checks, the MX batching and HubSpot (if used). Afterwards, tune decision D5 (phone radius and shared-phone threshold) from what it finds.
4. **DoD item 8:** press Ctrl+C mid-run on Windows, then `resume`. Completed work must not be fetched again.
5. **Real exports:** check a Google Sheet export (client columns kept, re-export updates rows) and HubSpot if a client uses it.
6. **UI:** do one live run in the Streamlit UI, including Resume after a deliberate interruption.

### Next: Phase 7, portfolio packaging
7. **README (7.1):** add screenshots or a GIF (the UI, the Sheet), redacted sample output, and an honest email/phone hit rate taken from the live Makati run.
8. **Demo (7.2):** record the 90-second demo (blueprint section 21). Blur emails and phones.
9. **Publish (7.3):** the repo is on GitHub (`bitwindamountains/LeadHarvest`). Confirm its visibility is what you want, and that it contains no secrets or real lead data.

### Before selling
10. **Decide D1** (Google Places storage terms) and **D2** (ODbL share-alike for client lists). Both are in blueprint section 23.
11. **Weekly monitor for a client:**
    - add the secrets `LH_USER_AGENT`, `LH_DB_PASSPHRASE`, `GOOGLE_SHEET_ID` and `GOOGLE_SERVICE_ACCOUNT_JSON`;
    - commit `config/monitor.csv`;
    - trigger `monitor.yml` once by hand.
12. **Go to market:** follow blueprint section 22 (platforms, pricing, honesty rule).

### Backlog (build only when needed)
- **Streamlit version floor:** `pyproject.toml` says `streamlit>=1.36`, but the UI uses newer APIs (tested on 1.64). Raise the floor and run `uv lock`.
- **Background runs in the UI:** a run would then survive clicks and page reloads. Today a click pauses the run, and Resume recovers it.
- **SSRF:** block the connection itself, not just the reading of the response (a custom httpcore network backend; see the `ponytail:` note in `enrich/fetcher.py`).
- **F14, Google Places source (8.6):** blocked on D1.
- **F18, more directory adapters:** build per client request.
- **D4:** remember rows a client deletes from the Sheet, so they are not appended again.

## Notes / decisions

- **Open decisions:** D1 (Google Places storage terms) and D2 (ODbL obligations) are in blueprint section 23. Decide them before selling.
- **Build order:** V1 and V2 were built ahead of the live Definition of Done run, at the owner's request. The blueprint had said to build V2 only once a client pays for it.
- **Owner's email:** it identifies the owner only. Never send it in live requests from this environment.
- **Never commit:** `.env`, `secrets/` and `data/`. These are gitignored.
- **No logs artifact:** the monitor workflow uploads no logs, because artifacts on a public repo are readable by any signed-in user.
- **Refreshes:** a refresh overwrites a lead's fields only when it is that lead's sole source. This stops two sources from flip-flopping a website between runs.
