# LeadHarvest — Blueprint Review and Build Plan

Review of `01_LeadHarvest_Blueprint.md` v1.0 · 2026-10-01

---

## 1. Verdict

The blueprint is well above average. Scope, non-goals, the politeness rules, the legal section, the test cases and the phase plan are all solid, and it is close to buildable. It is **not ready to build as written**, though: about a dozen spec gaps would produce duplicate or wrongly merged leads, a broken resume, Sheets exports that damage client columns, or compliance commands that can't run. Each fix is small. Apply them to the blueprint (making it v1.1) **before** Phase 0, because Claude Code treats the blueprint as the spec. If this plan and the blueprint disagree, the blueprint wins.

| Area | Rating | Note |
|---|---|---|
| Product definition, goals, non-goals | Strong | Clear B2B scope and honest limits |
| Architecture | Strong | A modular monolith with Source/Exporter protocols is the right size |
| Data model | Needs fixes | Missing source-ref identity, `first_seen_run_id`, suppression list; FK pragma |
| Dedupe and normalization | Needs fixes | False merges on shared phones, NULL keys, missing city |
| Enrichment and politeness | Good, with gaps | robots.txt keyed per domain instead of per origin; redirects; http-only sites; SSRF |
| Exports | Needs fixes | Positional Sheets columns; formula and phone mangling |
| Legal and compliance | Good, with gaps | `forget`/`purge` not in the roadmap; Places ToS and ODbL risks for paid lists |
| Roadmap and estimate | Optimistic | 3–4 days → realistically 7–9 focused days for the MVP |

---

## 2. Must fix before building

These are spec bugs. If they are built as written, the output will be wrong.

| # | Issue | Why it matters | Fix (blueprint section) |
|---|---|---|---|
| R1 | **No source identity in dedupe.** An OSM node that has a name but no phone, domain or street matches nothing on re-run. | Every re-run creates a duplicate lead for each such record. Many PH OSM records only have a name. | Add table `lead_sources(source, source_ref, lead_id, PK(source, source_ref))`. New **rule 0**: same `(source, source_ref)` → same lead. (§9, §10.4) |
| R2 | **Phone-only match causes false merges.** Chain hotlines (e.g. a franchise 8-7000 number), building main lines and medical-tower switchboards are shared. | Different businesses collapse into one lead. A whole restaurant chain becomes one row. | Phone match counts only if `name_key` is similar (token overlap) **or** the coordinates are within ~250 m. Also treat a phone seen on 3+ different `name_key`s as "shared", the same way shared-host domains are handled. (§10.4) |
| R3 | **Empty keys and missing city.** The rules don't require non-empty values, rule 3 has no city, and `addr:city` is often missing in PH OSM data. | `NULL = NULL` style matches. "Smile Dental, Rizal St" merges across cities. Rule 2 (domain + city) rarely fires. | Every rule requires non-empty keys. Rule 3 becomes name_key + street_key + city. When `addr:city` is missing, fill city from the resolved run area and store `city_source = osm\|run_area`. (§10.2, §10.4) |
| R4 | **Conflicting matches.** A record can match lead A by phone and lead B by domain. | The behavior is undefined, so results are non-deterministic. | The first rule in order wins. Log the pair as a `possible_duplicate` in run stats for manual review. (§10.4) |
| R5 | **`is_new` is wrong after resume.** On resume, leads inserted before the crash look like existing leads. | The "New since last run" count is wrong, and so is the V2 monitoring tab. | Add `leads.first_seen_run_id`; `is_new = (first_seen_run_id == run_id)`; link with `INSERT OR IGNORE`. (§9) |
| R6 | **SQLite foreign keys are off by default**, and `run_leads.lead_id ON DELETE RESTRICT` blocks deleting leads. | CASCADE silently doesn't happen, and `purge`/`forget` fail. | Run `PRAGMA foreign_keys=ON` and `journal_mode=WAL` on every connection in `db.py`. Make `run_leads.lead_id` and `lead_sources.lead_id` `ON DELETE CASCADE`. (§9) |
| R7 | **`forget` and `purge` appear only in §9 and §13.** They are missing from the CLI list, the roadmap and the DoD. `forget` also has no suppression list. | The removal requests you promise under RA 10173 can't be honored, and the next run re-collects the business anyway. | Add a `suppressions(kind: domain\|phone\|email, value, reason, created_at)` table. The clean step drops suppressed records. Make `forget` and `purge` P0 in Phase 6 and add them to the DoD. (§8, §9, §18, §19) |
| R8 | **robots.txt is cached per registered domain.** robots.txt is per origin (scheme + host + port). Redirects can land on another host. | `www.`, the apex domain and `shop.` subdomains can have different rules. A homepage that redirects to a different host is fetched without checking that host's robots.txt. | Key `robots_cache` by origin. Follow redirects manually (≤ 5) and check robots.txt, SSRF rules and per-host delay at every hop. Add a test for robots.txt checked across a redirect. (§9, §10.5) |
| R9 | **robots.txt status handling is incomplete.** Only 404 is specified. | Behavior for 401/403/410 is undefined. | Follow RFC 9309: any 4xx → allowed; 5xx or unreachable → disallowed. If you'd rather be stricter about 401/403, write that down explicitly. (§10.6) |
| R10 | **"Add `https://` if no scheme"** breaks http-only sites and hides the `no_https` flag. | Lost enrichments, and the agency sales signal is always wrong. | Try https, then fall back to http. Store `final_url` and `https_ok` on the lead. (§9, §10.3, §10.8) |
| R11 | **Sheets managed columns are positional.** Adding a managed column later (tiktok, phones_extra) or a client reordering columns overwrites client data. | Breaks the core promise behind the demo: "client columns are never touched". | Map columns by **header name**. Read row 1, find each managed header, and append any missing managed header after the last used column. Never write to a column whose header isn't managed. (§10.7) |
| R12 | **Formula and number mangling in exports.** Scraped text starting with `=`, `+`, `-`, `@` can execute as a formula. Excel opens the CSV value `+639171234567` as `6.39E+11`. | A spreadsheet-injection risk, and phones look broken to clients. | Sheets: always `valueInputOption=RAW`. XLSX: write phones as text cells. CSV: UTF-8 with BOM, escape formula-leading cells in non-phone columns, and tell clients to use the XLSX in Excel. (§10.7, §5.1 task) |
| R13 | **`--limit` semantics.** Overpass `out … {limit}` runs before the no-name filter and dedupe, so "result count above limit → warn" can't be detected. | Runs return fewer than N leads with no explanation. | Run `out count;` first (it's cheap), fetch `limit × 1.5`, and truncate after clean. Record `truncated: true` in stats. (§5 W1, §10.2) |
| R14 | **Location resolution handles relations only.** Barangays, BGC, malls and business parks are often ways or nodes in OSM. | "Location not found" for valid, commonly requested areas. | Relation → `3600000000 + id`. Way → `2400000000 + id`. Otherwise use a bbox query from Nominatim's `boundingbox`. Pass `countrycodes=LH_DEFAULT_REGION`. (§10.2) |
| R15 | **SSRF guard is deferred to V2.** OSM `website` tags are untrusted input, and V1 already hosts the tool on Streamlit Cloud. | It can fetch `http://192.168.1.1` or cloud metadata endpoints. | Move the guard into the MVP fetcher. Resolve the host and reject private, loopback, link-local and reserved IPs, at every redirect hop. (§13, Phase 4.1) |

---

## 3. Should fix (quality, consistency)

| # | Issue | Fix |
|---|---|---|
| S1 | F3 directory adapter is P0 in §4 but P1 in Phase 7 and missing from the DoD | Make it V1 everywhere. The MVP is OSM only. |
| S2 | Nominatim and Overpass clients (`geo/`, `sources/`) have no shared HTTP rules, so UA, retries and `Retry-After` could get duplicated | Add `http.py` in Phase 0 as a shared httpx client factory (UA, timeouts, tenacity, 429/`Retry-After`). The fetcher and source clients build on it. Update the §7 rule. |
| S3 | Enrich scope is unclear. "Leads with `pending`" could mean every lead in the DB. | Enrich only leads linked to the current run. Set `no_website` during the clean step. Add `--refresh-days N` to re-enrich stale `ok` leads (V2 retainers need it). |
| S4 | "Existing non-empty values win" means data never refreshes, e.g. after a clinic changes its phone | Fields from the same `source_ref` get refreshed by that source. Enrichment fields are overwritten on re-enrichment. Cross-source conflicts still keep the existing value. |
| S5 | Extractors ignore schema.org JSON-LD, which is the highest-yield source on SME sites | Parse `LocalBusiness`/`Organization` JSON-LD: `telephone`, `email`, `address`, `sameAs` (socials). It's a pure function and easy to test. |
| S6 | No dedupe after enrichment, even though enrichment adds phones and domains that reveal duplicates | Re-run matching for enriched leads and report candidates. Don't auto-merge in the MVP. |
| S7 | `leads.category` is a single value, so a clinic found by both the `dentist` and `salon` runs shows the wrong category in the salon tab | Store `categories` as a JSON list. Exports show the run's category. |
| S8 | Ctrl+C on Windows: `loop.add_signal_handler` isn't supported on Windows | Wrap `asyncio.run` in `try/except KeyboardInterrupt`, cancel the tasks, and set `partial` in `finally`. Test it on Windows, since that's your machine. |
| S9 | Async code writes to SQLite, and Streamlit (V1) runs scripts in threads | Use one connection with writes on the event-loop thread. Streamlit gets a connection per session or thread. |
| S10 | `.env.example` has a placeholder UA with `you@example.com` | `config.py` refuses to run when the UA contains `example.com` or has no contact. |
| S11 | Common PH phone shorthands aren't covered | Add test cases for `(02) 8123-4567/68` (consecutive lines) and `8123-4567` with no area code after a split (carry the area code from the previous number). |
| S12 | Export column gaps: `tiktok`, `phones_extra`, `emails_extra` aren't exported, and the format of `flags` in the Sheet is undefined | Add them as managed columns (safe once R11 is in). Render lists comma-separated. |
| S13 | A client deletes a row in the Sheet, and the next export re-appends it | Decide (see D4). The simplest option is to document it. |
| S14 | §13 covers only CAN-SPAM, but persona "Mark" may be in AU, where the Spam Act 2003 is stricter | Name the AU and PH rules in your service terms. Keep the "we don't send email" line. |
| S15 | Roadmap estimate: 3–4 days for Phases 0–6 is optimistic for polite async fetching, resume, header-mapped Sheets upsert and tests | Plan for 7–9 focused days for the MVP plus 1 day of packaging (below). |

---

## 4. Decisions you need to make

| # | Decision | Recommendation |
|---|---|---|
| D1 | **Google Places (F14).** Maps Platform terms restrict storing Places content: place IDs may be stored indefinitely, lat/lng only for a limited time, and most other fields can't be cached. A lead DB plus a delivered Sheet conflicts with that. | Keep F14 out until you've read the current terms yourself. If they still restrict storage, drop it. Don't sell "Places leads". |
| D2 | **ODbL.** Delivering an OSM-derived lead list to a paying client may count as conveying a derivative database, which carries share-alike obligations for the OSM-derived part. | Read the OSMF licence FAQ on this specific case before setting prices. Add an ODbL notice to every deliverable regardless. |
| D3 | **Cloudflare-obfuscated emails** (`/cdn-cgi/l/email-protection`) are common on SME sites, and the blueprint deliberately decodes only bracketed forms | Keep respecting them: the site owner opted out of harvesting. Count them as a "protected" stat so your quoted hit rate stays honest. |
| D4 | **Rows deleted from the Sheet by a client** | MVP: re-append and document it. V2: track a `client_removed` set if a client asks. |
| D5 | **Phone-match radius and shared-phone threshold** (R2) | Start with 250 m and 3 names. Tune them on the first real Makati run. |

---

## 5. Build plan

Do **Step 0** first. Each task below is about one Claude Code prompt. Run `/clear` between phases, and check that the gate passes before you move on.

### Step 0 — Amend the blueprint (≈1 hour)
- [ ] Apply R1–R15 and S1–S15 to `01_LeadHarvest_Blueprint.md`, bump it to v1.1, and record decisions D1–D5.
- [ ] Update the §20 CLAUDE.md starter: add the rules "phones are text, never numbers", "Sheets writes use RAW and header mapping", and "every fetch goes through the SSRF and robots.txt check at each redirect hop".

### Phase 0 — Setup (0.5 day)
- [ ] 0.1 uv project, `src/` layout, Python 3.12, ruff, pytest, respx, pytest-asyncio; `leadharvest --help` works
- [ ] 0.2 `config.py` + `.env.example`, with the UA guard (S10) and per-command required-value checks
- [ ] 0.3 `logging_setup.py`: Rich console + JSON-lines file, with a secret-redaction filter
- [ ] 0.4 `http.py` shared client factory (S2)
- [ ] 0.5 CLAUDE.md, README skeleton, `.gitignore` (`data/`, `secrets/`, `.env`)

**Gate:** `uv run pytest` and `uv run ruff check .` both pass.

### Phase 1 — Models and storage (1 day, blocks everything below)
- [ ] 1.1 Pydantic models: `SearchQuery`, `RawBusiness`, `Lead` (with `categories`, `final_url`, `https_ok`, `city_source`), `Run`, `ExportResult`
- [ ] 1.2 `schema.sql`: v1.0 tables plus `lead_sources`, `suppressions`, `leads.first_seen_run_id`, FK cascades. `db.py`: `schema_version` migrations, `foreign_keys=ON`, WAL (R1, R5, R6, R7)
- [ ] 1.3 Repository: `create_run`, `update_run_step`, `save_raw`, `find_match` (rules 0–3 with non-empty guards), `upsert_lead`, `link_run_lead` (INSERT OR IGNORE), `leads_for_run`, `add_suppression`, `is_suppressed`, `forget`, `purge`
- [ ] 1.4 Repository tests on a temp DB, including: cascade on run delete, `forget` removes a lead and blocks re-insert, `is_new` survives a simulated resume

**Gate:** all repository tests pass.

### Phase 2 — Location and OSM source (1 day; can run in parallel with 3.1, 4.3 and 5)
- [ ] 2.1 Nominatim client: 1 req/s, `geo_cache`, relation/way/bbox resolution, `countrycodes`, top-3 "did you mean" suggestions (R14)
- [ ] 2.2 `categories.yaml` + loader + `leadharvest categories`, with close-match suggestions for unknown categories
- [ ] 2.3 Overpass query builder (area or bbox) + `out count` pre-check + client with retry and fallback URLs (R13)
- [ ] 2.4 Overpass parser → `RawBusiness`, with city fallback from the run area (R3); fixture tests
- [ ] 2.5 `leadharvest search` saves raw records

**Gate:** a live smoke search for `dentist` in Makati (`-m live`) returns records. A barangay-level location resolves.

### Phase 3 — Clean (1 day)
- [ ] 3.1 `normalize.py`: phone (plus the S11 cases), URL (no forced scheme; R10), domain, name_key, street_key, social-URL routing. Tests for every blueprint §14 case
- [ ] 3.2 `dedupe.py`: rules 0–3, phone guard with name similarity or 250 m plus the shared-phone list (R2), conflict logging (R4), merge rules with per-source refresh (S4)
- [ ] 3.3 Wire the clean step into the pipeline: drop suppressed records, set `no_website`, truncate to the limit

**Gate:** chain-hotline, NULL-street and cross-city fixtures don't merge. Re-running the same raw data twice creates 0 new leads.

### Phase 4 — Enrichment (2 days)
- [ ] 4.1 Polite fetcher: per-host delay, global semaphore, manual redirects (≤ 5) with an SSRF check and robots.txt check at each hop (R8, R15), https→http fallback (R10), 2 MB / `text/html` caps, 403/429 circuit breaker, `Retry-After`
- [ ] 4.2 robots.txt checker: per-origin cache, 24 h TTL, RFC 9309 status handling (R9)
- [ ] 4.3 Extractors (pure functions): mailto, bracket deobfuscation, JSON-LD (S5), phones, socials, junk filters, email ranking; HTML fixture tests
- [ ] 4.4 Contact-page discovery (≤ 2 same-site pages, contact pages first)
- [ ] 4.5 Enricher orchestrator scoped to the run's leads, plus `leadharvest enrich [--retry-failed] [--refresh-days N]` (S3); post-enrich duplicate candidates reported (S6)
- [ ] 4.6 (P1, optional) Playwright fallback behind `--js`

**Gate:** respx tests prove that a robots.txt disallow (including after a redirect) causes zero page requests, a private IP is never fetched, and an http-only site enriches with `https_ok=false`.

### Phase 5 — Export (1 day; depends only on Phase 1)
- [ ] 5.1 CSV (BOM, formula escaping) and XLSX (text phone cells, bold header, widths, ODbL attribution) (R12)
- [ ] 5.2 Sheets exporter: header-mapped columns, RAW writes, one batch update + one append, 429 backoff, bold/frozen/filtered header (R11, R12)
- [ ] 5.3 `leadharvest export --run <id|latest> --to csv,xlsx,sheets`

**Gate:** fake-worksheet tests pass for: client "Notes" column untouched; client reorders columns → still correct; new managed column added → appended after the client columns; a value like `=HYPERLINK(...)` is stored as text.

### Phase 6 — Pipeline and compliance (1–1.5 days; depends on Phases 2–5)
- [ ] 6.1 `leadharvest run` chains the steps with progress bars
- [ ] 6.2 `resume` from `current_step`; Windows-safe Ctrl+C → `partial` (S8)
- [ ] 6.3 Run summary table + `leadharvest runs`
- [ ] 6.4 `leadharvest forget --domain|--phone|--email` and `leadharvest purge --not-seen-days N` (R7)
- [ ] 6.5 Offline end-to-end integration test with a fixture source, including crash-during-enrich → resume

**Gate:** the full MVP Definition of Done (below) passes.

### Phase 7 — Portfolio packaging (1 day)
- [ ] 7.1 README: problem, features, setup in under 10 steps, redacted sample output, OSM attribution, an honest hit-rate note
- [ ] 7.2 Record the 90-second demo (blueprint §21), blurring emails and phone numbers
- [ ] 7.3 Public GitHub: run a secret scan, no `data/`, no real leads

### Phase 8 — V1 (only after Phase 7)
- [ ] 8.1 (P1) Directory adapter + `_template.yaml` + `test-adapter` + fixture tests (moved from the old Phase 7, S1)
- [ ] 8.2 (P1) Scoring + flags (uses `https_ok` from R10)
- [ ] 8.3 (P1) MX check
- [ ] 8.4 (P1) Streamlit UI with password and thread-safe DB access (S9)
- [ ] 8.5 (P2) HubSpot exporter
- [ ] 8.6 (P2) Google Places, **only if D1 clears**

### Phase 9 — V2 (only when a client pays for it)
Unchanged from blueprint §18 Phase 10. It also relies on `--refresh-days` and the `is_new` fix.

### Timeline

| Milestone | Phases | Focused days | Cumulative |
|---|---|---|---|
| Spec v1.1 | Step 0 | 0.1 | 0.1 |
| Foundation | 0–1 | 1.5 | 1.6 |
| Data in | 2–3 | 2 | 3.6 |
| Enrich + export | 4–5 | 3 | 6.6 |
| MVP done | 6 | 1.5 | ~8 |
| Demo-ready | 7 | 1 | ~9 |

---

## 6. Additions to the Definition of Done (blueprint §19)

- [ ] Re-running the same search creates 0 new leads (R1)
- [ ] Two branches sharing a chain hotline stay separate leads (R2)
- [ ] `forget --domain x.com` removes the lead, and the next run does not re-add it (R7)
- [ ] robots.txt is honored across redirects, and private IPs are never fetched (R8, R15)
- [ ] Reordering columns in the Sheet and then re-exporting leaves client data intact (R11)
- [ ] Phones show as `+63…` text in Sheets and XLSX (R12)
- [ ] Ctrl+C → `resume` works on Windows (S8)
