# LeadHarvest

Type "dental clinics in Makati" and get a clean, deduplicated, enriched lead list in CSV, Excel, or Google Sheets in minutes, collected politely and legally.

LeadHarvest is a Python command-line tool that:

1. **Finds businesses** by category and location from OpenStreetMap (free, open data).
2. **Enriches** each one from its *own* website: emails, extra phone numbers, and social profiles, including schema.org data. It obeys robots.txt and rate limits.
3. **Cleans** the data: E.164 phone numbers, normalized URLs, and deduplication that won't merge a chain's branches just because they share a hotline.
4. **Exports** to CSV, XLSX, or a Google Sheet. Re-exporting updates existing rows and never touches the client's own columns ("Status", "Notes", ...).

It is not a cold-email tool, never logs in anywhere, and never evades blocks.

## Quick start

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env            # then set LH_USER_AGENT to your real contact email
uv run leadharvest categories
uv run leadharvest run --category dentist --location "Makati, Philippines" --limit 100 --to csv,xlsx
```

Files land in `data/exports/`. Open the `.xlsx` in Excel. Excel mangles `+63…` phone numbers in CSV files.

### Commands

| Command | What it does |
|---|---|
| `run --category X --location "Y" [--limit N] [--to csv,xlsx,sheets]` | Full run: search, clean, enrich, export |
| `search --category X --location "Y"` | Search only; continue later with `resume` |
| `resume [--run ID]` | Continue an interrupted or partial run from its last step |
| `enrich [--run ID] [--retry-failed] [--refresh-days N]` | (Re-)enrich a run's leads |
| `export [--run ID] --to sheets,csv` | Export again, e.g. to refresh a client Sheet |
| `runs` | List recent runs |
| `categories` | List categories (edit `config/categories.yaml` to add more) |
| `forget --domain x.com` / `--phone` / `--email` | Delete a business and suppress it from all future runs |
| `purge --not-seen-days 180` | Retention: delete leads not seen for N days |

`--run` accepts a full id, the 8-character prefix shown in output, or `latest` (the default).

Press **Ctrl+C** at any time. The run is marked `partial`, and `leadharvest resume` continues it without re-fetching finished work.

## Google Sheets setup (free, no billing)

1. In Google Cloud Console, create a project and enable the **Google Sheets API**.
2. Create a service account, then create a JSON key and save it as `secrets/service_account.json`.
3. Share your Google Sheet with the service account's email as **Editor**.
4. Copy the Sheet ID from its URL into `GOOGLE_SHEET_ID` in `.env`.
5. Run with `--to sheets`.

Each run writes to a tab named `{category} - {area}`. Columns are matched **by header name**, so clients can add, move, or reorder their own columns freely. Rows a client deletes reappear on the next export.

## How it stays polite and legal

- Honest User-Agent with a contact address. The tool refuses to run with the placeholder.
- robots.txt is checked per origin, at every redirect hop, following RFC 9309.
- At least 2 s between requests to the same host, at most 5 concurrent requests, and `Retry-After` is honored. A host that keeps answering 403/429 is skipped for the rest of the run.
- Never fetches private/internal network addresses (SSRF guard).
- No CAPTCHA solving, proxies, logins, or social-network scraping. Cloudflare-protected emails are left alone and only counted.
- B2B only: published business contact details. `forget` and `purge` support removal requests and retention under the Philippine Data Privacy Act (RA 10173).

If your clients send email to these leads, they must follow anti-spam law (CAN-SPAM in the US, the Spam Act 2003 in Australia, and others).

## Data and attribution

Business listings come from **© OpenStreetMap contributors**, available under the [Open Database License](https://www.openstreetmap.org/copyright). Every export carries this attribution (the XLSX `About` sheet; a `.about.txt` next to each CSV). Coverage is good in Metro Manila and thinner in the provinces.

Expect an email for only part of the leads: many small businesses publish only a Facebook page. Quote clients the hit rate from your own runs.

## Operator runbook

- **Data:** everything lives in `data/` (gitignored): `leads.db`, `exports/`, and `logs/run-<id>.jsonl`.
- **Backups:** copy `data/leads.db` before upgrading. Dedupe across runs depends on it.
- **Upgrades:** run `uv lock --upgrade` monthly, then `uv run pytest`.
- **Client job checklist:** check OSM coverage for the area → `run` → review "possible duplicates" in the summary and log → spot-check 10 leads → deliver with the attribution note.
- **Removal request:** `leadharvest forget --domain their-site.com`, then remove their row from any delivered Sheet.

## Development

```bash
uv run pytest                    # offline; tests never touch the network
uv run pytest -m live            # opt-in smoke test against real OSM (needs .env)
uv run ruff check . && uv run ruff format --check .
```

The full specification is in [docs/BLUEPRINT.md](docs/BLUEPRINT.md).
