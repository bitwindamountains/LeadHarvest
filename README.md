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
| `run --category X --location "Y" [--limit N] [--to csv,xlsx,sheets,hubspot] [--sources osm,directory:NAME] [--js] [--no-mx]` | Full run: search, clean, enrich, score, export |
| `search --category X --location "Y" [--sources ...]` | Search only; continue later with `resume` |
| `resume [--run ID]` | Continue an interrupted or partial run from its last step |
| `enrich [--run ID] [--retry-failed] [--refresh-days N]` | (Re-)enrich a run's leads |
| `export [--run ID] --to sheets,csv` | Export again, e.g. to refresh a client Sheet |
| `runs` | List recent runs |
| `categories` | List categories (edit `config/categories.yaml` to add more) |
| `adapters` / `test-adapter NAME [--pages 1]` | List directory adapters / print 5 parsed records from one |
| `batch jobs.csv` / `batch --from-sheet TAB` | Many categories × locations; re-run the same command to resume |
| `monitor jobs.csv --to sheets` | Weekly refresh: fresh runs each ISO week plus a "New since last run" export |
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

## Optional features

**Lead scoring (always on).** Every lead gets a 0–100 score (email 30, own-domain email +10, phone 20, website 15, social profile 10, street address 10, opening hours 5) and sales flags: `no_website`, `social_only`, `no_https`, `free_email_provider`. Filter by score in the Sheet. "No website" lists sell well to web design agencies.

**Email domain check (on by default).** Emails whose domain has no mail server (no MX or A record, or a "null MX") are dropped before export. Results are cached for 30 days. Turn it off with `--no-mx` or `LH_MX_CHECK=false`.

**JavaScript sites (`--js`).** Some sites render everything with JavaScript. With `--js`, a page that is nearly empty and yielded nothing is rendered in headless Chromium, under the same robots.txt, rate-limit and SSRF rules. One-time setup:

```bash
uv sync --extra js && uv run playwright install chromium
```

**Directory adapters (`--sources directory:NAME`).** Add a public business directory you're allowed to scrape: copy `config/directories/_template.yaml`, confirm every item on its scraping checklist (the adapter refuses to load otherwise), fill in CSS selectors, then check it with `leadharvest test-adapter NAME --pages 1`. Combine sources with `--sources osm,directory:NAME`.

**HubSpot (`--to hubspot`).** Create a HubSpot private app with the `crm.objects.companies.read` and `.write` scopes and put its token in `HUBSPOT_ACCESS_TOKEN`. Companies are matched by domain (or exact name when there's no domain). Existing companies only get fields that are empty in HubSpot; your team's edits are never overwritten.

**Web UI.** A password-protected Streamlit page for non-technical users. Start a search with live progress, then browse the results: lead counts, a table sorted by score, and download buttons. **Recent runs** in the sidebar reopens any earlier run, including after a page reload. A paused run, for example one stopped by an Overpass error or by clicking around mid-run, gets a **Resume run** button.

```bash
uv sync --extra ui
uv run streamlit run app/streamlit_app.py      # from the repo root; needs LH_UI_PASSWORD in .env
```

Run it from the repo root so Streamlit picks up `.streamlit/config.toml`. That file sets the colour theme, hides the developer toolbar and turns off Streamlit's usage statistics.

If you deploy it (e.g. Streamlit Community Cloud), put the `.env` values in the app's secrets. The SQLite file is lost when the app restarts there, so download exports right away.

## Batch mode and weekly monitoring

**Batch.** Put one job per row in a CSV (or a tab of your Google Sheet) with the columns `category`, `location`, and optionally `limit` and `sources` (`osm;directory:NAME`). Rows starting with `#` are skipped. See [config/monitor.example.csv](config/monitor.example.csv).

```bash
uv run leadharvest batch jobs.csv --to sheets
uv run leadharvest batch --from-sheet Jobs --to sheets   # reads the "Jobs" tab of GOOGLE_SHEET_ID
```

Every row becomes a normal run. If you stop a batch with Ctrl+C or a row fails, run the same command again: completed rows are skipped and unfinished ones resume. Rows are identified by their position, so add new rows at the end. Use `--rerun` to run completed rows again.

**Monitor.** `leadharvest monitor jobs.csv --to sheets` runs the batch as fresh runs once per ISO week. It also exports the leads that the previous run of the same category and area did not have:
- **Sheets:** a `<category> - <area> - new` tab. It is a running log with a `found_on` date column, and client columns there are kept too.
- **Files:** `...-new.csv` and `...-new.xlsx`.

The first run for an area counts every lead as new.

**Website signals.** Enrichment records each site's platform in the `tech` column (WordPress, Shopify, Wix, Squarespace, Webflow, Joomla, Drupal, GoDaddy, Weebly, Blogger). Sites without a mobile viewport get the `no_mobile_viewport` flag. Combined with `no_https` and `no_website`, these make good prospect lists for web agencies.

### Weekly monitoring on GitHub Actions

[.github/workflows/monitor.yml](.github/workflows/monitor.yml) runs `monitor` every Monday at 01:00 UTC (09:00 Manila) and can also be started by hand.

1. Commit your jobs as `config/monitor.csv` (copy the example).
2. Add these repository secrets (Settings → Secrets and variables → Actions):
   - `LH_USER_AGENT`
   - `GOOGLE_SHEET_ID`
   - `GOOGLE_SERVICE_ACCOUNT_JSON`: the whole JSON key file's contents
   - `LH_DB_PASSPHRASE`: a long random passphrase
3. Run the workflow once from the Actions tab.

Between runs the lead database is kept as an **encrypted** workflow artifact (AES-256 with your passphrase, kept 90 days). Artifacts of public repositories are downloadable by any signed-in GitHub user, so never remove that encryption step. A private repository is better still. If you lose the passphrase, the next run starts fresh and reports every lead as new.

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
