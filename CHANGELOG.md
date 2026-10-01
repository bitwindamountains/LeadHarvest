# Changelog

## 0.2.0 — 2026-10-01

V1 features (blueprint Phase 4.6 and Phase 8, except Google Places, which is on hold per decision D1).

- Lead scoring (0–100) and flags: `no_website`, `social_only`, `no_https`, `free_email_provider`.
- MX check: emails on domains that cannot receive mail are dropped (cached 30 days; `--no-mx`).
- `--js`: Playwright rendering for near-empty JavaScript pages, under the same robots.txt, rate-limit and SSRF rules (sub-requests are SSRF-checked; images, media and fonts are skipped).
- Directory adapters: YAML-configured scrapers with an enforced scraping checklist, plus the `adapters` and `test-adapter` commands and `--sources osm,directory:NAME`.
- HubSpot export: match by domain or name, create or fill only the empty properties.
- Streamlit UI (`app/streamlit_app.py`) with a password gate.
- Schema v2: `runs.options` (kept across `resume`) and `mx_cache`. Existing databases upgrade automatically.
- Fix: the same-site checks for adapter start URLs and pagination no longer pass for hosts without a known public suffix.

## 0.1.0 — 2026-10-01

First MVP release (blueprint v1.1, Phases 0–6).

- OpenStreetMap search via Nominatim + Overpass, with relation/way/bbox location resolution, `out count` pre-query, retries, and fallback endpoints.
- Normalization (E.164 phones incl. PH shorthands, URLs, registered domains, name/street/city keys) and dedupe rules 0–3 with the phone-match guard and shared-phone list.
- Polite enrichment: robots.txt per origin (RFC 9309) at every redirect hop, SSRF guard, per-host delays, https→http fallback, a 403/429 circuit breaker, JSON-LD extraction, and contact-page discovery.
- Exports: CSV (BOM, formula escaping), XLSX (text phones, About sheet with ODbL attribution), and a Google Sheets upsert with header-mapped columns and RAW writes.
- Resumable pipeline (`run`, `resume`, Ctrl+C → partial), `search`, `enrich`, `export`, `runs`, `categories`.
- Privacy: `forget` with a suppression list, and `purge` for retention.
- Offline test suite (network blocked in tests) and CI on Ubuntu and Windows.
