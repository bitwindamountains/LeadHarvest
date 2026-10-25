# PROGRESS

## Current task

**Status (end of 2026-10-11):** everything through `83a323b` is on `main` and pushed (239 tests, lint clean): the run-page redesign and data-honesty fixes, Overture as the default source (D6), dedupe rule 4 plus `leadharvest dedupe`, and multi-source runs that survive one failed source. Blueprint phases 0–6, 8 (except 8.6 Google Places) and 9 are built.

**Also pushed (2026-10-24, `f8e14d2`):** run history grouped by search (direction A, step 1), 240 tests. Deployment check the same day: tests and lint pass, no secrets tracked. Pillow CVEs fixed the same day: the `ui` extra now needs `streamlit>=1.66.1` (the first release to allow Pillow 13), and the lock has Streamlit 1.66.1 and Pillow 13.0.0. pip-audit is clean, 240 tests pass, and the app boots. The Weekly monitor workflow is disabled on GitHub (it failed weekly without its repo secrets and `config/monitor.csv`); add those, then `gh workflow enable "Weekly monitor"`.

**Also pushed (2026-10-24):** the All runs page and the run id in the URL (direction A, step 2). 246 tests pass, lint clean, checked in the browser.

**Also pushed (2026-10-24):** batches collapsed into one sidebar entry with a batch page (direction A, step 3, which finishes direction A). 249 tests pass, lint clean, checked in the browser.

**Also pushed (2026-10-24):** reachable leads, slice 1 (hide leads with no way to contact; email and phone links). 250 tests pass, lint clean, checked in the browser.

**Also pushed (2026-10-24):** reachable leads, slice 2 (the `why_contact` export column). 251 tests pass, lint clean.

**Also pushed (2026-10-24):** reachable leads, slice 3 (export summary with reachable and opening counts; a Sheets summary tab). 252 tests pass, lint clean.

**Also pushed (2026-10-24):** reachable leads, Messenger links. The leads table has a Messenger column ("Message", after Phone) linking to `m.me/<page>` (`clean.normalize.messenger_link`, used by `ui_support.result_rows`). Checked first in a real browser: `m.me/<numeric id>` (Overture's facebook.com/<id> links; 141 of 143 Facebook links in the DB) goes to `messenger.com/t/<id>` like a username does (`m.me/facebook`), through Messenger's sign-in when logged out. Group, `/pages/...` and `profile.php` links get no Messenger link. UI only: exports keep the Facebook column. 264 tests pass, lint clean.

**Also pushed (2026-10-24):** Phase 7, slice 1 (7.1 README and 7.3 repo check).
- **README:** two UI screenshots (`docs/images/run-page.png`, `leads-table.png`), taken from a copy of the DB with every email and phone masked and `raw_records` emptied, then reduced to 256 colours (~840 KB together). A "Real results" section with hit rates (Makati dentists 5e5e7edb, Argao hotels 8b6160d0) and five redacted sample rows; the web UI paragraph brought up to date (All runs, batch pages, links, hiding); `why_contact` and the Sheets summary tab documented.
- **7.3, checked:** the repo is public; no `.env`, `secrets/`, `data/` or `.db` file is tracked or was ever in history; no key-like strings beyond a fake test PEM; fixtures are synthetic. The owner's email appears only as the git commit author (GitHub shows it on commits; switch to the GitHub noreply address if that matters).
- **Also:** the Messenger column is 100 px wide; "small" clipped its header (seen in the browser).
- 264 tests pass, lint clean.

**Also pushed (2026-10-24):** background runs in the UI. A run started or resumed in the UI now runs on a daemon thread (`ui_jobs.JOBS`, one registry per server process, each run with its own SQLite connection) instead of inside the page's script, so clicks, other pages, reloads and closed tabs no longer pause it.
- **Run page:** while its run is running here, it shows live progress (`views.common.live_progress`, an `st.fragment(run_every=1)`: steps, then "Visited N of M websites") and reruns the page when the run stops. A run marked running with no thread here (the CLI, or the app restarted mid-run) still gets "Take over and resume"; its wording no longer mentions other tabs, which share the registry. Location not found shows its suggestions on the run page (the search page used to show them).
- **Removed:** `mark_interrupted` and `StatusReporter`: nothing interrupts a UI run any more. The search page's "keep this tab open" note now says the run continues in the background.
- **Limits:** stopping the server kills the thread; the run stays "running" and is taken over as before. Two runs at once each write the other's log lines too (one root logger), as two tabs already could.
- **Tests:** `tests/unit/test_ui_jobs.py` (one thread per run, readable progress) and `test_ui_run_keeps_going_while_the_person_clicks_around` (live progress, leaving and returning mid-run, results after). 265 tests pass (the suite ran 3 times in a row), lint clean.
- **Checked live** on a scratch DB, 5-lead runs in Makati and Taguig: progress went searching → "Visited 0/4/5 of 5 websites" → scoring, survived New search and a full page reload mid-run, and the page showed the completed results on its own. Found and fixed in the browser: the status box showed a check mark while running (`with st.status` marks it complete on exit).

**Also pushed (2026-10-24):** a **Stop run** button on a running run's page. It cancels the run's asyncio task from the page (`ui_jobs.Job.stop`, via `call_soon_threadsafe`), the same path as Ctrl+C in the CLI: the pipeline saves the run as paused, and the UI then records `error="stopped"`, shown as "Paused while … You stopped it." with Resume. A stop clicked before the thread's event loop starts still cancels it. Work already on a worker thread (the Overture query) finishes first; the button shows "Stopping…" meanwhile. Tests: two in `test_ui_jobs.py` (stop mid-run, stop before start) and `test_ui_stop_pauses_the_run_for_resume`. 268 tests pass (suite run twice), lint clean.
- **Fixed, found live (a bug in the background-runs commit):** when a run ended, the progress fragment's `st.rerun()` left the sidebar picker unchecked in the browser, so the next click (Resume, a segment, anything) sent "nothing picked" and opened the search page. `live_progress` now calls `select_run(run_id)` before that rerun, which writes the picker's value and re-syncs the browser. AppTest can't see browser widget state, so this is checked live only.
- **Checked live** (scratch DB, 3–8 lead runs in Pasig, Mandaluyong, San Juan and Marikina): Stop during search paused the run in 2.9 s, or after the Overture query finished (over 90 s once), as "Paused while searching for businesses. You stopped it."; the picker stayed selected; Resume continued and completed the run; a segment click on the finished page stayed there. Not seen live: a stop during website visits (search was slow each time); tests cover it and it is the CLI's Ctrl+C path.

**Also pushed (2026-10-24):** the SSRF guard now also blocks at connect time. Every client from `http.make_client` connects through `netguard.PublicOnlyBackend`, an httpcore network backend that resolves the host, refuses any non-public address (`BlockedAddress`, unix sockets too), then connects to the very IP it checked, trying each in DNS order. So DNS rebinding between the fetcher's own check and the connection can no longer send even a request to a private address; before, the fetcher only refused to read the response (`check_peer`, now used by the JS renderer only). TLS still verifies the certificate against the URL's host name.
- **How it plugs in:** httpx has no backend option, so `public_only_transport` swaps the backend on the transport's httpcore pool (`transport._pool._network_backend`, httpx 0.28 / httpcore 1.0); a test asserts it, so an upgrade that moves it fails loudly. Requests through an environment proxy use httpx's proxy transport and keep relying on the host check, as before.
- **Tests:** backend refuses private addresses before connecting, connects to checked IPs in order, DNS failure is a connect error, an httpx request to a name resolving to loopback is refused with no network, and the fetcher reports a connect-time block as a failed fetch. 272 tests pass, the 2 live tests pass, lint clean.
- **Checked live:** https://www.python.org/ fetched normally (certificate checked); localhost, 127.0.0.1, `localtest.me` (public DNS → 127.0.0.1) and 169.254.169.254 refused before connecting.

**Also pushed (2026-10-24):** the JS renderer's SSRF gap is closed. Chromium now reaches the network only through `enrich/render_proxy.GuardProxy`, a local forward proxy started with the renderer: it resolves each host, refuses non-public addresses (a 403 with `X-LeadHarvest-Blocked`, which the renderer turns into the usual `FetchError`) and connects to the very address it checked. https goes through CONNECT tunnels; plain http is forwarded one request per connection (`Connection: close`) so a reused connection can't switch hosts. Redirect hops, which bypass the route handler, and DNS rebinding can no longer even send a request to a private address. Playwright sends loopback traffic through the proxy too (tested). `PoliteFetcher.check_peer` and `via_proxy` are gone: behind the proxy the browser's peer is always the proxy.
- **Tests:** `tests/unit/test_render_proxy.py` (origin-form forwarding to the checked IP, refusals before connecting, CONNECT tunnel) and the real-browser tests now go through the proxy: redirect to metadata.test, redirect to a 127.0.0.1 literal, and rebinding each leave only the first request on the server. 276 tests pass, lint clean.
- **Checked live:** https://www.python.org/ rendered through the proxy (59 KB, real DNS and certificates).

**Also pushed (2026-10-24):** D4: rows a client deletes from a Google Sheet tab stay deleted. Migration `006_sheet_rows.sql` adds `sheet_rows (sheet_id, tab, lead_id, written_at)` (FK to leads, so `forget`/`purge` clean it); `SheetsExporter` gets it through `exporter_factory(settings, repo)` (every caller passes its repo now) and `plan_upsert(..., sent_before)` leaves out a lead that was written to the tab before but is no longer there. Recorded only after the batch write succeeds. Covers the monitor's `- new` tabs too. `ExportResult.rows_skipped` counts them; the CLI summary and the run page say "N you deleted from the Sheet left out".
- **Limits:** tabs exported before this change have no memory yet, so a row deleted before it can come back once (then it's remembered). A deleted lead can't be brought back from LeadHarvest; paste the row back, or delete its `sheet_rows` entry. Renaming a tab starts a fresh memory (the key is the tab name).
- **Tests:** deleted rows stay deleted (skipped count, memory updated), no memory = old behaviour, a failed write remembers nothing, repository per sheet and tab with cleanup on delete. 280 tests pass, lint clean. Not checked against a real Sheet (no `GOOGLE_SHEET_ID` here).

**2026-10-25: deployment review (`/ship`: code review, security audit, test coverage) and its three blockers fixed.** Live first: the Makati run (5e5e7edb) exported to a real Google Sheet, 100 rows, phones as `+63…` text, attribution note and summary tab present; the client-edit check passed the same day: a client column (`my notes`, typed by the owner) survived two re-exports with its values; then 2 rows deleted and the `category` column moved to A (through the API) gave "0 appended, 98 updated, 2 you deleted from the Sheet left out": no deleted row came back, no duplicates, `category` stayed in A with its values updated, and `my notes` kept.
- **Fixed:** a real Sheet ID had been typed into `.env.example` (reverted, never committed); Stop clicked as a run ends no longer raises `Event loop is closed` (`Job.stop`); a tab the client recreates, or whose `lead_id` header is renamed, gets every lead again instead of staying empty (`plan_upsert` ignores the deleted-rows memory when the tab holds none of our rows). New limit: a client who deletes every row gets them all back on the next export. 282 tests pass, lint clean.
- **Recommended fixes, done the same day:** certifi 2026.10.23 and filelock 4.2.4 (pip-audit clean); the UI serves on `127.0.0.1` only (`.streamlit/config.toml`; the password throttle is per session, so sharing it on a network needs a proxy with its own sign-in, noted in the README); Chromium starts with `--force-webrtc-ip-handling-policy=disable_non_proxied_udp` (`render.NO_DIRECT_UDP`), so page scripts can't send WebRTC UDP around the guard proxy; `make_client` sets `trust_env=False`, so an `HTTP(S)_PROXY` in the environment can't skip the connect-time guard (a machine that needs a proxy to reach the internet can't run LeadHarvest now). New tests: a real pipeline stopped from another thread pauses at enrich with `error="stopped"` and resumes without re-fetching, two runs on two threads write to one database at once (`tests/integration/test_background_runs.py`), `exporter_factory` hands the Sheets exporter the repository and sheet id, and a v5 database with leads gains `sheet_rows`. 286 tests pass, lint clean, the 10 real-browser tests pass with the new flag.
- **Not done (low, from the review):** the guard proxy has no idle timeout or connection cap and forwards to any port; `is_public_ip` and NAT64 (64:ff9b::/96) per the code review, though the security audit found it refused; Actions pinned by tag, secrets on the whole monitor job; `Jobs._jobs` is never pruned; a Sheets export blocks Stop until it ends; `repository.py` and `ui_support.py` over ~300 lines.

**Next session, in order:**
1. **Demo (7.2):** the owner records the 90-second demo (blueprint section 21). It shows the Google Sheet, so it needs the live Sheets export first.
2. The owner's other live checks (below).

**Also left:** the demo (7.2, the owner records it), D1 to confirm (researched 2026-10-25, recommendation: drop Google Places), and the weekly monitor for a client. Every Definition of done item is ticked and D2 is decided. See the Roadmap below.

## Done (newest first)

- 2026-10-24: DoD item 1, the live Makati run: `leadharvest run --category dentist --location "Makati, Philippines" --limit 100` (run 5e5e7edb; Overture, CSV + XLSX; database backed up first). Completed in about 2 min (search 65 s, enrich 39 s).
  - 150 raw records, 5 duplicates merged, 100 leads kept (truncated at the limit), all new. Clean and enrich found 0 possible duplicates, so D5 (phone radius, shared-phone threshold) stays as it is.
  - **Hit rate (for the README):** email 76%, phone 98%, website 46%, Facebook 100%; every lead reachable. Emails by kind: 60 business, 13 unknown, 3 personal; 10 protected (Cloudflare) emails not decoded; MX dropped 1 email on a dead domain. Average score 70.9.
  - **Enrichment:** 46 websites tried with 173 requests: 30 read, 4 blocked by robots.txt, 12 failed (6 DNS failures on lapsed domains, 3 HTTP 404 including 2 shut-down `business.site` pages, 3 HTTP 403). No SSRF blocks and no host skipped. The 12 dead sites are real data, not bugs; "website is down" could become a sales opening flag.
  - **why_contact:** 33 "Only on social media, no website; uses a free email address", 21 "Only on social media, no website", 9 "No online booking", 9 "Uses a free email address", 7 "No online booking; uses a free email address", 7 empty.
  - **Bug found:** `leadharvest run --help` crashes with `UnicodeEncodeError` ('→', a "→" in the help text) when output goes to a non-UTF-8 pipe or console code page (cp1252); fine with `PYTHONIOENCODING=utf-8` or a UTF-8 terminal. Fixed the same day: the `leadharvest` script now starts at `cli.cli()`, which switches stdout and stderr to UTF-8 before running the Typer app (any non-cp1252 character, such as a business name in another script, could crash a piped run the same way). Test: `test_help_survives_a_non_utf8_pipe` forces `PYTHONIOENCODING=cp1252` in a subprocess, so it reproduces on Linux CI too; the old entry point fails it. Needs `uv sync` once to regenerate the script (254 tests pass, pushed).

- 2026-10-24: Live tests (`pytest -m live`) pass, both of them: Overture in Makati stays inside the city, and a Makati search + clean (limit 10) finds leads. The first try of the second test paused at search with `Could not find the latest Overture release: [Errno 11001] getaddrinfo failed`, a one-off DNS failure (the host resolved and answered 200 straight after, and the other test reached Overture in the same session); the re-run passed. Finding: one DNS blip on the Overture catalog lookup pauses a single-source run at search (it can be resumed). Fixed the same day: the lookup now goes through `http.request_with_retry` (3 tries, 1 s then 2 s apart; DNS and connection errors, 429 and 5xx), like Nominatim and Overpass. Tested with a respx DNS failure then success, and three failures giving the usual `SourceError` (253 tests pass).

- 2026-10-24: Reachable leads, slice 3: the export summary (252 tests pass, lint clean).
  - **One summary for every export:** `exporters/base.about_rows` (attribution, category, location, run id, export time, then `run_summary`). The XLSX `About` sheet, the CSV `.about.txt` (now "Label: value" lines, attribution included) and the new Sheets tab all use it.
  - **New rows in `run_summary`:** "Reachable (email, phone, website or social)" and one "Opening: …" row per flag, worded as in `why_contact`, always listed (even at 0) so the rows stay stable between exports. `reachable()` moved from `segments.py` to `exporters/base.py`, as base can't import segments (segments imports base).
  - **Sheets:** `export` also writes `<tab> - summary` (clear, one RAW `batch_update` of A:B, bold labels); a failure there is an `ExportError` like the leads tab. Monitor "new" tabs get no summary. Tests use a separate fake worksheet per tab (`export_to(..., tabs)`), and check a stale row is cleared.
  - Restaurants · Argao: 29 leads, 26 reachable (89%), 21 "only on social media, no website", 24 "no website", 9 "uses a free email address".

- 2026-10-24: Reachable leads, slice 2: the `why_contact` export column (251 tests pass, lint clean).
  - `exporters/base.why_contact` puts a lead's top two flags in plain words, in pitch order ("Only on social media, no website; uses a free email address"); no flags (or only unknown ones) give an empty cell. It's a managed column right after `flags`, so CSV, XLSX, "Download these N" and Sheets get it; an existing Sheet gets the new header after its last used column (the usual header-mapped rule), and client columns stay untouched. HubSpot is unchanged (a new property would have to exist in the portal first).
  - Not in the run page's table: its "Openings" chips already show every flag in words.
  - On the 73 stored leads: 33 "Only on social media, no website", 13 add "uses a free email address", 8 "Uses a free email address", 8 "No website", 3 "Website looks out of date; …", 2 "…; no analytics or ad tracking", 6 empty.
  - Blueprint section 10.7's column list was out of date (no `email_kind`, `tech`); it now matches `MANAGED_COLUMNS`.

- 2026-10-24: Reachable leads, slice 1 (250 tests pass, lint clean).
  - **Reachable (`segments.reachable`):** a lead with an email, phone, website or any social page. Only leads with none of these count as unreachable, so nothing a person could still contact is hidden.
  - **Leads table:** a "Hide leads with no way to contact" switch, on by default, with "N hidden" beside it. It applies on top of the Show picker, and to "Download these N", but not to the number cards or the full exports. Its label is fixed and it's always drawn (disabled when nothing would be hidden), because Streamlit drops a widget's state when it's relabelled or not drawn, which turned hiding back on after a segment switch (caught by the AppTest).
  - **Links:** email cells are `mailto:` links and phone cells `tel:` links (`ui_support.result_rows`), shown as the address and the formatted number. The `+` is sent as `%2B`: the table decodes a bare `+` in link text to a space, which dropped it ("63-966-…"), found in the browser. Messenger links followed (see the 2026-10-24 Messenger note above).
  - **Layout:** the table moved from `views/run.py` (320 lines) to `views/leads.py`.
  - **Checked live** on a copy of `data/leads.db`: Restaurants · Argao hides 3 of 29 leads; turning the switch off shows them; links render with the `+`.

- 2026-10-24: Each batch is one sidebar entry with a batch page (direction A, step 3 of 3; 249 tests pass, lint clean).
  - **Sidebar:** runs group by `ui_runs.entry_key`: a run with `options.batch` joins its batch's entry ("Batch · name", caption "N of M completed · L leads · age"), any other run its search's. Batch rows no longer count towards a search's duplicate label, so a search isn't given a run id suffix because a batch ran the same search. Lead counts for captions come from one `run_lead_counts()` query instead of one per entry.
  - **Batch page (`views/runs.batch_page`):** each row's latest run (`Repository.batch_runs`) in row order, in the same table as All runs; picking a row opens its run. A batch row's run page has a "Batch name" back link. `open_batch` in session state shows the page; `select_run` clears it. The run page's "Run history" still groups by search, so a batch row lists the same search's other runs.
  - **Not done:** monitor batches are named per ISO week (`name@YYYY-Www`), so each week is its own entry; folding weeks of one monitor into one entry is left until monitors are in use. The batch page has no URL of its own.
  - **Checked live** on a copy of `data/leads.db` with two runs tagged as a batch: one entry, the page lists both, a row opens its run, the back link returns, and another entry leaves the batch.

- 2026-10-24: All runs page and the run id in the URL (direction A, step 2 of 3; 246 tests pass, lint clean).
  - **Page (`app/views/runs.py`, logic in `ui_runs.py`):** an "All runs" link in the sidebar opens a table of every run, newest first (Started, Search, Status, Leads, Run), with a word filter (category, place, run id) and a status filter. Picking a row opens the run through the usual `select_run`, which also works for runs the sidebar doesn't list (the picker clears, `open_run` holds the run). `Repository.list_runs(None)` lists every run and `run_lead_counts()` counts leads per run in one query.
  - **URL:** the open run's id is kept in `?run=`. On a session's first page after sign-in, `?run=` (full id, unique prefix or `latest`) opens that run; an unknown one opens the search page and clears it. The All runs page and the search page have no URL of their own.
  - **Tests:** `tests/integration/test_ui_runs.py` (filter, rows, repository, AppTest for the page and the URL). AppTest can't click a dataframe row, so picking a row was checked in a real browser on a copy of `data/leads.db`: a row opens its run, the URL updates, returning to All runs stays there, and a reloaded run link reopens the run after sign-in.

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
  - **Facebook links:** all 26 are numeric page URLs (facebook.com/<id>). m.me/<id> opens Messenger for them (checked in a browser 2026-10-24).
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
- **Step 2, done:** an "All runs" page with the run id in the URL.
- **Step 3, done:** collapse batches into one entry with a batch page.
- **Not doing:** pins and tags, folders, searching leads from the sidebar, deleting runs automatically. Direction B, a "Leads library" (every lead, filtered by category and place, with runs as history), is the long-term model; build it only on demand.

### Other ideas from 2026-10-11 (not started)
- **Reachable leads (done 2026-10-24: slices 1–3 and Messenger links):** hide unreachable leads by default ("7 hidden: no way to contact"); a "Contact via" column with one-tap phone, email and Messenger links (`m.me/<numeric id>` verified in a browser); a one-line "why contact" reason from the flags; a summary tab in exports (extend `exporters/base.run_summary`).
- **Design review leftovers:** the leads table above the fold, a contrast and focus pass, the run id in the URL (folded into step 2 above).
- **Overture tuning:** `MIN_CONFIDENCE` (0.5) on a live Makati run (D6 note).

### Now: live verification (owner; needs a real contact email in `LH_USER_AGENT` in `.env`)
1. **CI:** done 2026-10-25, green on GitHub for every push through `4c48dcb` (real-browser tests on Ubuntu and Windows included).
2. **Live tests:** done 2026-10-24, both pass (see Done).
3. **DoD item 1:** done 2026-10-24 (run 5e5e7edb, see Done). D5 needs no change: no possible duplicates or phone conflicts came up. HubSpot is still untested live.
4. **DoD item 8:** done 2026-10-25, checked by the owner: Ctrl+C mid-run on Windows paused the run, and `resume` finished it without fetching completed work again.
5. **Real exports:** Google Sheets done 2026-10-25 (client column kept, moved column, deleted rows stay deleted; see Current task). HubSpot only if a client uses it.
6. **UI:** done 2026-10-25 (run e28d12cf, dentist, Pasig, limit 20, driven in a browser with a temporary password): search took ~106 s, the run kept going while All runs was open, Stop during website visits paused it as "Paused while visiting their websites. You stopped it." (partial, enrich, error stopped; 4 of 5 sites done), Resume visited only the 1 site left and completed (20 leads, 90% email, 100% phone, average score 71, CSV and XLSX). No browser console errors. Found: the search form's caption says "Google Sheets and HubSpot appear here once set up" even when Sheets is set up (Sheets is in the Export to list; only HubSpot is missing), and the footer of the search page shows the OpenStreetMap credit although Overture is the default source. Both fixed the same day: the caption names only the targets not set up (`ui_support.setup_hint`), and with no run open the footer credits the default sources (`exporters.base.sources_attribution`); checked in the browser. 286 tests pass.

### Next: Phase 7, portfolio packaging
7. **README (7.1), done 2026-10-24:** UI screenshots, redacted sample output and real hit rates. A Sheet screenshot can follow the owner's first live Sheets export.
8. **Demo (7.2):** record the 90-second demo (blueprint section 21). Blur emails and phones.
9. **Publish (7.3), done 2026-10-24:** the repo is public on GitHub (`bitwindamountains/LeadHarvest`), with no secrets or real lead data in its files or history.

### Before selling
10. **D1 and D2** (blueprint section 23). **D2 decided 2026-10-25:** OSM stays out of client lists (Overture only, D6). **D1 researched 2026-10-25, owner to confirm:** Google's Maps Platform terms forbid scraping or exporting Maps content for use outside Google's services, and the Places API policies forbid storing Places content beyond place IDs (lat/lng for 30 days) and require a Google map or logo wherever it's shown. A lead database and client Sheets can't comply, so the recommendation is to drop F14 and never sell "Google Maps leads". Sources: the Places API policies page (developers.google.com/maps/documentation/places/web-service/policies, updated 2026-10-23) and the Service Specific Terms; the main Terms page didn't load in the fetch tool, so the 3.2.3 wording is from third-party copies.
11. **Weekly monitor for a client:**
    - add the secrets `LH_USER_AGENT`, `LH_DB_PASSPHRASE`, `GOOGLE_SHEET_ID` and `GOOGLE_SERVICE_ACCOUNT_JSON`;
    - commit `config/monitor.csv`;
    - trigger `monitor.yml` once by hand.
12. **Go to market:** follow blueprint section 22 (platforms, pricing, honesty rule).

### Backlog (build only when needed)
- **F14, Google Places source (8.6):** blocked on D1; the 2026-10-25 research recommends dropping it.
- **F18, more directory adapters:** build per client request. **Researched 2026-10-24, none usable** (checked against the `_template.yaml` checklist):
  - BusinessList.ph: robots.txt allows listing pages, but its terms of use allow automated access for search engines only, content "for your own use only", and no reproducing without written permission (they take requests via their Contact Us page).
  - Kompass PH and Cybo: answer plain requests with 403 (bot protection); using them would need evasion, which is ruled out.
  - Infobel: robots.txt blocks AI and data bots. Yellow Pages PH, PhilippineCompanies and ph-yp: unreachable or offline.
  - So an adapter needs a directory whose owner allows it: written permission (e.g. BusinessList.ph), or a source a client brings with the rights to it (a member list, an association directory).

## Notes / decisions

- **Open decisions:** D1 (Google Places) awaits the owner's confirmation; the research recommends dropping it. D2 is decided: OSM stays out of client lists. Both are in blueprint section 23.
- **Build order:** V1 and V2 were built ahead of the live Definition of Done run, at the owner's request. The blueprint had said to build V2 only once a client pays for it.
- **Owner's email:** it identifies the owner only. Never send it in live requests from this environment.
- **Never commit:** `.env`, `secrets/` and `data/`. These are gitignored.
- **No logs artifact:** the monitor workflow uploads no logs, because artifacts on a public repo are readable by any signed-in user.
- **Refreshes:** a refresh overwrites a lead's fields only when it is that lead's sole source. This stops two sources from flip-flopping a website between runs.
