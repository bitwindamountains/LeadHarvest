# PROGRESS

## Current task

**Status (end of 2026-10-11):** everything through `83a323b` is on `main` and pushed (239 tests, lint clean): the run-page redesign and data-honesty fixes, Overture as the default source (D6), dedupe rule 4 plus `leadharvest dedupe`, and multi-source runs that survive one failed source. Blueprint phases 0–6, 8 (except 8.6 Google Places) and 9 are built.

**Also pushed (2026-10-24, `f8e14d2`):** run history grouped by search (direction A, step 1), 240 tests. Deployment check the same day: tests and lint pass, no secrets tracked. Pillow CVEs fixed the same day: the `ui` extra now needs `streamlit>=1.66.1` (the first release to allow Pillow 13), and the lock has Streamlit 1.66.1 and Pillow 13.0.0. pip-audit is clean, 240 tests pass, and the app boots. The Weekly monitor workflow is disabled on GitHub (it failed weekly without its repo secrets and `config/monitor.csv`); add those, then `gh workflow enable "Weekly monitor"`.

**Next session, in order:**
1. Direction A, step 2: an "All runs" page (a table of every run, filterable, click to open) with the run id in the URL (`st.query_params`, `?run=<id>`). Today searches past the newest 15, and runs past the 500 scanned, can't be opened from the UI.
2. Direction A, step 3: collapse each batch (`options.batch`) into one sidebar entry that opens a batch summary.

**Also left:** live verification by the owner (two "Definition of done" items are still open), Phase 7 packaging, and decisions D1 (and D2 only if OSM is added to a client list). See the Roadmap below.

## Done (newest first)

- 2026-10-24: Pillow 12.3.0 → 13.0.0 (11 CVEs) by raising the Streamlit floor to 1.66.1. pip-audit clean, 240 tests pass, app boots.

- 2026-10-11: Run history grouped by search (direction A, step 1 of 3; 240 tests pass, lint clean).
  - **Sidebar:** one entry per search (category plus place, from `ui_support.search_key`/`group_runs` over the newest `RUNS_SCANNED` = 500 runs), up to 15 searches. Each radio option's value is the search's latest run id, so `select_run()` works unchanged; captions add "· N runs" when a search repeats.
  - **Run page:** a "Run history (N runs of this search)" picker under the header lists each run (time, status, leads, short id, "latest"). Picking one sets `open_run`, which the sidebar returns while that search stays selected; choosing a search in the sidebar opens its latest run again. Options are the labels themselves, as AppTest can't map values through `format_func` (CLAUDE.md: options need unique labels).
  - **Checked live:** Hotels · Argao (3 runs) and Restaurants · Argao (2 runs) each show once, and picking the oldest hotel run opens 57ad2d96 with the sidebar entry kept.
  - **Next (direction A):** an "All runs" page (searches older than the newest 15, or runs past the 500 scanned, are unreachable from the UI) with the run id in the URL; then collapse batches into one entry.

- 2026-10-11: A failing source no longer stops a multi-source run (239 tests pass, lint clean).
  - `Pipeline.search` catches `SourceError` per source. With two or more sources, it logs a warning, records the source in `stats["search"]["source_errors"]` and keeps the others' results. If every source fails it raises a combined error, so the run pauses at search as before. A single-source run is unchanged.
  - Shown as a "Skipped source" row in the CLI summary and a warning on the run page that names the source and suggests a new run later. Resume doesn't retry a skipped source, because search is already done.
  - Tests: one source down means the run completes with the other's leads; all down means it pauses with both errors; an AppTest checks the UI warning.
  - Live: resuming hotel run 496710d9 (OSM + Overture) completed. The first Overpass endpoint returned 504 and the fallback answered, so nothing was skipped this time. The run also showed rule 4 live: 22 raw records became 18 leads, 4 duplicates merged, 0 new.

- 2026-10-11: Dedupe rule 4, same place from two sources (235 tests pass, lint clean).
  - **Cause:** rules 1–3 need a shared phone, domain, or name + street. OSM records often have no phone or street, and Overture spells names differently, so "Kafe Marco", "BJ's Seaside"/"BJs Seaside", "Maayo stay Argao"/"Maayo Argao" and others stayed as two leads.
  - **Rule 4 (`clean/dedupe.py`):** both records have coordinates within 100 m, and the names are equal ignoring spaces or share at least 60% of tokens (`names_match_closely`, stricter than rule 1's similarity). It runs last, so earlier rules keep priority and conflicts are still reported. `Repository.leads_near` does a lat/lon box lookup; migration `005_leads_location_index.sql` adds the index.
  - **Proof:** across all 52 real leads with coordinates, the rule pairs exactly the 5 known duplicates (10–88 m apart) and nothing else. New tests use those pairs plus near-misses ("Ai's Restaurant" vs "Max's Restaurant SM" 60 m apart, the same name 220 m apart, no coordinates). `test_shared_phone_never_used_for_matching` now puts its probe far away, so it still tests only the shared-phone guard.
  - **Stored duplicates:** `leadharvest dedupe` lists stored pairs that rule 4 would have merged; `--apply` merges each into the older lead (`dedupe.merge_location_duplicates`). The merge keeps the older `lead_id` so earlier exports stay valid, applies the normal merge rules, carries over the duplicate's website results when its website is the one kept (no re-visit), and rescores. `Repository.merge_lead_into` moves `lead_sources` and `run_leads` onto the kept lead and deletes the duplicate in one transaction; raw records stay. Applied 2026-10-11 to `data/leads.db`: 52 leads became 47, with no orphaned source rows or run links, and a second run finds none. Rows for merged-away leads stay in files already delivered.

- 2026-10-11: Overture is the default source (decision D6: Overture-only), 232 tests pass, lint clean.
  - `sources.overture.default_source_names()` returns `["overture"]` when DuckDB is installed, else `["osm"]`. It's the one default for the CLI (`run`, `search`, `batch`, `monitor`: `--sources` now defaults to None), `Pipeline.create_run`, `ui_support.validate_request`/`RunRequest` and the search form.
  - Why: the Argao comparison (entry below). Overture is free (public S3/Azure, no key) and its places licences (CDLA-Permissive-2.0, Apache-2.0, CC0) have no share-alike.
  - The monitor workflow installs without extras, so it stays on OSM and its weekly "new since last run" series doesn't jump. Add `--extra overture` there deliberately, expecting one week where everything reads as new.
  - Tests: a fallback test (no DuckDB means OSM); the pipeline source-error test now names `sources=["osm"]`.

- 2026-10-11: Live OSM vs OSM + Overture comparison, Argao, Cebu (first real hit-rate data for Phase 7).
  - **Restaurants:** OSM alone gave 4 leads, none reachable (no email, phone or social). OSM + Overture (run 1fb0356f) gave 30 leads, 26 reachable: email 9 (all free providers), phone 18, Facebook 26. Every reachable lead came from Overture; the 4 OSM-only leads still had nothing.
  - **Hotels:** run 496710d9 (OSM + Overture) stopped twice at search because both Overpass endpoints returned 504/500. A fresh Overture-only run (8b6160d0, the new default) finished in about 45 s: 17 leads, all 17 reachable (email 9, phone 15, Facebook 17, website 6), against OSM's 5 leads with 2 reachable. 4 of OSM's 5 hotels are also in Overture, under slightly different names ("Maayo stay Argao" / "Maayo Argao", "BJ's Seaside" / "BJs Seaside"). The only one missing, Sea Breeze Hotel & Spa, had no contact details anyway. Those 4 weren't matched to the existing leads ("17 new, 0 seen before"): the same name-variant dedupe gap as Kafe Marco. Run 496710d9 is still resumable. Finding: when Overpass is down the whole multi-source run stops, even though Overture alone would have worked.
  - **Dedupe gap:** "Kafe Marco" came from both sources about 10 m apart and wasn't merged (the OSM record has no street, so name + street + city can't match). Candidate rule: same name key within ~50 m.
  - **Facebook links:** all 26 are numeric page URLs (facebook.com/<id>). Whether m.me/<id> opens Messenger for them is unverified.
  - **Implication:** Overture is the main source of reachable leads here; it's off by default today. Next decision: make Overture the default when the `overture` extra is installed (see D2 for licence).

- 2026-10-11: Data-honesty fixes on the run page numbers, from a design review (231 tests pass, lint clean).
  - Email and phone lead with the count ("2", "of 5 leads"). The percentage appears only from 20 leads (`ui_support.coverage`, `PERCENT_MIN_LEADS`), since "40%" of 5 overstates precision.
  - The average score is a whole number and says its direction: "out of 100 · higher = easier to reach". The score measures reachability (email, phone, website…), so higher is better; the review had guessed the reverse.
  - The histogram's average marker is gone (a mean drawn over a few, often bimodal, leads misleads), and so are the meters' quarter ticks.
  - The segment heading says "a lead can be in several", because segment counts can add up to more than the lead total.
  - Not done from the review (owner's call): table above the fold, contrast and focus pass, run ID in the URL. Decided against: grouping run history, streaming leads during a run (backlog: background runs), font preloading.

- 2026-10-11: Run page number cards reworked into a ledger bento (230 tests pass, lint clean). Checked at 1280 and 390 px.
  - **Layout (`theme.css`):** a tall Leads hero card with an ochre-lit core, the figure anchored low, and "N new this run" as a pill. Email and phone cards sit beside it, with a wide score card under them. On phones: Leads, then the pair, then score. The gap is 1.25rem, wider than two 7 px bezel rings, so trays no longer touch. Grid items are Streamlit's `stLayoutWrapper`s, so placement uses `:has(> .st-key-lh-kpi-*)`.
  - **Meters:** email and phone show a plain track (the quarter ticks were dropped: they encoded nothing) and an ochre fill set by `transform: scaleX(var(--lh-fill))`. The fill animates in after its card lands and respects `prefers-reduced-motion`.
  - **Leads card ledger:** the empty middle of the tall card now lists every segment's count ("No website ···· 4") under a "Segments" heading, with zeros muted. The keyed container is the card; the metric inside has no border. `Segment` gained a `short` label and `segments.segment_counts()` (unit-tested).
  - **Clickable ledger:** each segment row is a tertiary `st.button` (key `lh-seg-<segment>`). Its `on_click` sets the table's `show-<run id>` state before the rerun; clicking the active row again goes back to all leads. The active row is tinted and has a check icon, so state isn't shown by colour alone. Empty segments are disabled. The AppTest covers filter, clear and the disabled row.
  - **Score histogram:** the score card is now its container (like the Leads card): the average on the left and leads per 20-point band on the right (`ui_support.score_bands`, which leaves unscored leads out and puts 100 in the top band). Counts sit on their bars, empty bands are muted, and bars grow in on load unless reduced motion is on. The score meter is gone.
  - **Table scrollbar:** 16 px with a rounded 10 px thumb (was Streamlit's 10 px "thin" bar). Streamlit's `scrollbar-width`/`scrollbar-color` are reset on `.dvn-scroller` because Chrome ignores `::-webkit-scrollbar` while they are set. `table_height()` reserves 18 px so the last row isn't clipped.
  - **Values (`run.py`, `ui_support.py`):** "New this run" folds into the Leads card. Email and phone read "40%" with "2 of 5 leads" under them, and the score reads "out of 100". `share()` is replaced by `percent()`, which rounds down so 199 of 200 shows 99%.

- 2026-10-11: Run page cards, type and results table (230 tests pass, lint clean). Checked at 320, 390, 768, 1034, 1280 and 1440 px, plus 1440 px with the sidebar collapsed.
  - **Number cards (`theme.css`, `run.py`):** the `lh-numbers` container is a grid of equal-width, equal-height cards that switches on the content width (a container query): 5 across from 940 px, 3 + 2 below that, and 2 + 2 with a full-width last card below 540 px. Figures shrink at 320 px. Labels wrap between words. No card sits alone on a row at its own size.
  - **Type:** the run-id tag, card labels and the sidebar "Recent runs" heading are now 12 px, up from 10.5–11 px. Fraunces and Geist are kept as intentional; the impeccable detector ignores them via `.impeccable/config.json`.
  - **Leads table (`run.py`, `ui_support.py`):** Business is pinned. Flags move to the third column as "Openings" chips (`result_rows` now returns a list). Columns get fitted widths. The social links read "Facebook" and "Instagram" instead of "Open". The last row was clipped because Windows draws a 10 px horizontal scrollbar inside the grid; `table_height()` now sets an explicit height (header plus up to 10 rows, plus 14 px).

- 2026-10-11: Colour theme changed to "harvest ledger" (230 tests pass, lint clean). Checked at 1440 px: sign-in, search and run pages, plus the sidebar.
  - **Config (`.streamlit/config.toml`):** `base = "light"`, `primaryColor` `#8f5e0e`, Fraunces as `headingFont`, and an olive `[theme.sidebar]`.
  - **CSS (`theme.css`):** rebuilt on tokens. Ledger rules replace the dot grid, warm shadows replace black ones, ochre buttons take light text, sidebar buttons stay light-on-dark, and the sidebar run captions are lightened (`#aeb19f`) to stay readable on olive.
  - **Sign-in (`brand_panel.html`):** recoloured olive and ochre, with a Fraunces headline.
  - **Not changed:** the landing page keeps its dark green and gold look.

- 2026-10-11: High-end visual pass on the Streamlit UI (230 tests pass, lint clean). Checked at 1440 and 390 px; no horizontal scroll, and all five number cards sit on one row at 1440.
  - **CSS (`theme.css`):**
    - Double-bezel cards come from stacked box-shadow rings, so Streamlit's markup is unchanged.
    - Button icon circles target `button > div > span > span:has(stIconMaterial)`.
    - Icons use Material Symbols `font-variation-settings` `wght` 300.
    - Film grain is a percent-encoded SVG in a fixed `::after`.
  - **Config:** `buttonRadius = "full"`, plus a deeper canvas.
  - **Context pills:** `views.common.eyebrow` adds them on sign-in ("Private workspace"), search ("Lead search · Philippines") and run pages (the run id, moved out of the caption).

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
`docs/planning/04_LeadHarvest_Value_Plan.md` ranks the next features after research. Its top pick is an **Overture Maps places source**: permissive licence, no OSM data, and websites, phones, emails and socials. It fixes coverage and decision D2 together and fits Facebook-first PH SMEs. Next come zero-request website signals, email type labels and a per-run quality report. Its order is: live run first (below), then Overture, then signals, then the demo. **Update 2026-10-11:** Overture is built and is now the default (D6). In live Argao runs it gave 26 of 30 restaurants and 17 of 17 hotels a way to contact them, against 0 of 4 and 2 of 5 from OSM. Website signals are built too.

### In progress: run history (direction A, from the 2026-10-11 idea session)
The sidebar stacks one entry per run, so repeated searches, weekly monitors and batches crowd it, and older runs fall off the newest 15.
- **Step 1, done (`f8e14d2`):** group by search (category plus place). The sidebar shows each search once, and the run page has a "Run history" picker.
- **Step 2:** an "All runs" page with the run id in the URL.
- **Step 3:** collapse batches into one entry.
- **Not doing:** pins and tags, folders, searching leads from the sidebar, deleting runs automatically. Direction B, a "Leads library" (every lead, filtered by category and place, with runs as history), is the long-term model; build it only on demand.

### Other ideas from 2026-10-11 (not started)
- **Reachable leads:** hide unreachable leads by default ("7 hidden: no way to contact"); a "Contact via" column with one-tap phone, email and Messenger links (unverified: whether `m.me/<numeric id>` works for Overture's numeric Facebook page links); a one-line "why contact" reason from the flags; a summary tab in exports (extend `exporters/base.run_summary`).
- **Design review leftovers:** the leads table above the fold, a contrast and focus pass, the run id in the URL (folded into step 2 above).
- **Overture tuning:** `MIN_CONFIDENCE` (0.5) on a live Makati run (D6 note).

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
