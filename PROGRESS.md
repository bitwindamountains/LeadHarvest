# PROGRESS

## Current task

**Status (2026-10-11):** 0.3.0 plus the audit fixes, the UI redesign and the review fixes are on `main` (review fixes committed locally, not pushed yet). 214 tests pass and lint is clean. Blueprint phases 0–6, 8 (except 8.6 Google Places) and 9 are built.

**What's left:** live verification by the owner (two "Definition of done" items are still open), Phase 7 packaging, and decisions D1/D2 before selling. See the Roadmap below.

## Done (newest first)

- 2026-10-11: "Night harvest" theme for the Streamlit UI (230 tests pass, lint clean). Checked at 1440 and 390 px; no horizontal scroll.
  - **Theme files:** `.streamlit/config.toml` switches to `base = "dark"` with a gold primary. `app/assets/theme.css` is injected by `views.common.inject_theme()`.
  - **What the CSS styles:** the dot-field background, glass cards (`stForm` and `st-key-lh-card*`), metric cards, gold buttons with dark text, sidebar selection via `:has(input:checked)`, dark text on multiselect chips, and entrance and hover motion behind `prefers-reduced-motion`.
  - **Design contract:** `docs/UI.md` is updated to match.
  - **Risk:** the CSS targets Streamlit `data-testid` hooks. After a Streamlit upgrade, check the screens again.

- 2026-10-11: Frontend engineering pass on the Streamlit UI (230 tests pass, lint clean). Checked in a browser at 320, 768, 1024 and 1440 px; 320 px has no horizontal scroll.
  - **Split:** `app/streamlit_app.py` (50 lines) now routes to `app/views/` (signin, sidebar, search, run, common), each under 200 lines. Ruff `known-local-folder = ["views"]`.
  - **Headings:** one H1 per page. `headingFontSizes` keeps H2 compact. The brand panel's headline is a styled `<p>`.
  - **Contract:** `docs/UI.md`, the design contract: screens, primary actions, required states, responsive rules, rejected patterns.
  - **Empty segment:** a segment with no leads gets an info note.
  - **Known Streamlit limits:**
    - Material icons are announced by screen readers by their ligature name ("login Sign in").
    - The sidebar opens over the page on phones after sign-in.
    - At 320 px the number cards mostly stack one per row.

- 2026-10-11: UI/UX redesign of the Streamlit app (230 tests pass, lint clean). Checked in a browser at 1366 px and 390 px against the seeded demo DB.
  - **Theme:** `.streamlit/config.toml`. Fonts load as Google Fonts through `font`, `headingFont` and `codeFont`, plus softened semantic colours, `[theme.sidebar]` dark colours, radii, and the dataframe header colour.
  - **Assets:** `app/assets/` holds `logo.svg` and `mark.svg` (`st.logo`, `page_icon`) and `brand_panel.html` for the sign-in panel. `st.html` strips svg and data images, so the panel is pure CSS.
  - **Navigation:** the main area shows the search page when no run is picked. The sidebar's New search button calls `select_run(None)` before the picker is built.
  - **Status icons:** `ui_support.STATUS_STYLE` and `status_markdown` replace the emoji `STATUS_ICONS`.
  - **Not done:**
    - On phones the sidebar opens over the page after sign-in. Streamlit decides this and the app can't control it.
    - Status icon colours in the sidebar captions come out muted.

- 2026-10-11: Value plan step D, segments (230 tests pass, lint clean, checked in a browser).
  - **Code:** `segments.py` (`SEGMENTS`, `apply_segment`) and `Pipeline.export_segment`. It writes CSV/XLSX with a `-<segment>` suffix and doesn't touch the run's recorded exports. CSV/XLSX `export()` take a `suffix`.
  - **CLI:** `export --segment`, csv/xlsx only.
  - **UI:** the **Show** selectbox and a "Download these N (CSV)" button (`ui_support.csv_download`, reusing `csv_export.write_rows`). The button sits on the left because Streamlit's own table toolbar appears top right on hover.
  - **Not done:** segment tabs in Google Sheets.

- 2026-10-11: Value plan step C (228 tests pass, lint clean, each rule mutation-checked).
  - **Website facts:** `enrich/signals.site_signals` records facts such as `copyright:2018`, `analytics:google`, `pixel:meta` and `booking:seriousmd`. They are stored in `leads.site_signals` (migration 004), which is NULL until the homepage was read. A separate nullable JSON path in the repository keeps NULL and `[]` distinct.
  - **Flags:** `scoring.site_flags` derives `stale_site` (3 years or more), `no_analytics`, and `no_online_booking` (only for `APPOINTMENT_CATEGORIES`).
  - **Email labels:** `exporters/base.email_kind` (role words, business-name words, first.last and dr-prefix patterns) fills the new `email_kind` managed column.
  - **Summary:** `run_summary` is written into the CSV about file and the XLSX About sheet. Sheets gets no summary; its header note holds the attribution only.
  - **Not done:**
    - Messenger, WhatsApp and Viber chat-link detection.
    - A `--no-personal-emails` export option; the `email_kind` column is enough to filter in the Sheet.
    - Leads enriched before migration 004 get the new flags only after re-enrichment (`enrich --refresh-days`).

- 2026-10-11: Value plan step B, the Overture Maps source (223 tests pass, lint clean, filters mutation-checked).
  - **Live data check** (anonymous read of Overture's public bucket): about 40 s for a Makati-sized bounding box. It had 868 dental places in the box (which also covers parts of Pasay, Taguig and Manila): 90% with a phone, 53% with an email, almost all with a Facebook page, and 28% with a website. Meta supplies about 95% of the records.
  - **Code:** `sources/overture.py`.
    - **Query:** DuckDB `read_parquet` over the latest release (from the STAC catalog), filtered by bbox, by `list_has_any(taxonomy.hierarchy, ...)`, by confidence ≥ 0.5 and by not being permanently closed.
    - **Boundary:** `NominatimClient.boundary`, a cached `/lookup?osm_ids=R…&polygon_geojson=1`, with ray-casting point-in-polygon filtering (holes respected).
    - **Ordering:** most confident first, cut to `fetch_n`.
    - **Addresses:** a leading house number is split off the freeform address, so street keys match OSM's for dedupe.
  - **Categories:** `overture:` taxonomy lists in `categories.yaml` for all 12 categories, checked against the real taxonomy.
  - **Attribution:** `exporters/base.attribution(run, leads)` lists only the sources used. The Sheets export puts it in a note on A1; before this, it had none.
  - **UI:** a "Data sources" multiselect in Advanced options. The default stays `osm`.
  - **Not done:**
    - I didn't run the live end-to-end Overture test (`tests/test_live.py`); it needs the owner's contact UA for Nominatim.
    - The D6 default source is still open (blueprint section 23).
    - `MIN_CONFIDENCE` is untuned.

- 2026-10-11: UI polish after a browser review: a seeded throwaway DB in the scratchpad, with runs in every state, viewed at 1366 px and 390 px. 214 tests pass, lint clean.
  - **Header:** signed in, it is a `**🌾 LeadHarvest**` brand line. The sign-in page keeps the title and tagline. The divider above a run is gone.
  - **Metrics:** in `st.container(horizontal=True)` with `width="content"`. `st.columns` stacks one per line on phones.
  - **`ui_support` helpers:** `viewer_tz` (`st.context.timezone`, falling back to UTC), `short_time(iso, tz)`, `ago`, and `display_phone` (table only; exports keep E.164). The website `LinkColumn` shows the domain through a `display_text` regex.
  - **Gotcha:** Streamlit reloads the app script on save but not `leadharvest.ui_support`. Restart the server after changing it.
  - **Not done:** on a phone, choosing a run leaves the sidebar open over the results. Streamlit can't close it from code.

- 2026-10-11: Five-axis review of `879d552` and `8db28b6`, then fixes (214 tests pass, lint clean; each fix mutation-checked against its test):
  - **One copy of a run at a time:** `Repository.claim_run` sets a run running with one conditional UPDATE, and `Pipeline.execute` raises `RunInProgress` if it is already running. `create_run` now stores new runs as `partial`. `force=True` takes over a run left "running" by a crash: in the UI the button is **Take over and resume**, in the CLI it is `resume --force`. A batch row whose run is still running fails, and the rest of the batch goes on.
  - **purge** keeps the raw records of `partial` and `running` runs.
  - **HubSpot:** companies that were found or patched during an export are cached with their updated properties, so a third lead with the same domain can't overwrite fields.
  - **Suppression:** a suppressed domain also matches email subdomains, in `forget` (SQL: `'.'||host LIKE '%.'||domain`), in the clean step and in the enricher (`registered_domain` of the email host).
  - **Sign-in:** a wrong password waits one second.
  - **render.py:** a `ponytail:` note says the redirect GET to a private host is still sent; blocking it would need a proxy.
  - **Not done:** stale-run detection (a heartbeat column) instead of a manual take-over. Add it if crashed runs turn out to be common.

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

### Value plan (2026-10-11)
`docs/planning/04_LeadHarvest_Value_Plan.md` ranks the next features after research. Its top pick is an **Overture Maps places source**: permissive licence, no OSM data, and websites, phones, emails and socials. It fixes coverage and decision D2 together and fits Facebook-first PH SMEs. Next come zero-request website signals, email type labels and a per-run quality report. Its order is: live run first (below), then Overture, then signals, then the demo.

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
