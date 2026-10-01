# Changelog

## 0.1.0 — 2026-10-01

First MVP release (blueprint v1.1, Phases 0–6).

- OpenStreetMap search via Nominatim + Overpass, with relation/way/bbox location resolution, `out count` pre-query, retries, and fallback endpoints.
- Normalization (E.164 phones incl. PH shorthands, URLs, registered domains, name/street/city keys) and dedupe rules 0–3 with the phone-match guard and shared-phone list.
- Polite enrichment: robots.txt per origin (RFC 9309) at every redirect hop, SSRF guard, per-host delays, https→http fallback, a 403/429 circuit breaker, JSON-LD extraction, and contact-page discovery.
- Exports: CSV (BOM, formula escaping), XLSX (text phones, About sheet with ODbL attribution), and a Google Sheets upsert with header-mapped columns and RAW writes.
- Resumable pipeline (`run`, `resume`, Ctrl+C → partial), `search`, `enrich`, `export`, `runs`, `categories`.
- Privacy: `forget` with a suppression list, and `purge` for retention.
- Offline test suite (network blocked in tests) and CI on Ubuntu and Windows.
