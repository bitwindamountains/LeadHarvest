# Changelog

## Unreleased

- Web UI colour theme is now "harvest ledger":
  - **Paper and ink:** sage-tinted paper ruled like a ledger, with espresso ink.
  - **Sidebar:** dark olive.
  - **Accent:** ochre palay gold.
  - **Type:** headings and the big figures on the number cards are set in Fraunces, a serif.
  - **Sign-in panel:** recoloured to match.
- Web UI finish, built to a high-end visual standard:
  - **Canvas:** near-black, with emerald and gold glows and fine film grain.
  - **Cards:** double-bezel, an inner panel set into a tray.
  - **Buttons:** pills, with the icon in its own circle that moves on hover.
  - **Icons:** drawn at a light stroke weight.
  - **Context pills:** small uppercase pills above titles, such as "Run a1b2c3d4".
  - **Motion:** a soft spring fade-up.
  - **Phones:** the number cards pair up instead of stacking.
- Web UI theme, "night harvest": the whole app now follows the LeadHarvest brand instead of a generic light dashboard look.
  - **Canvas and accent:** a dark paddy-field canvas with a faint grid of gold grain dots, and palay gold as the only accent.
  - **Surfaces:** glass cards with gold edges, and number cards with uppercase labels.
  - **Sidebar:** the open run is marked in gold.
  - **Motion:** short entrance and hover motion, off when the system asks for reduced motion.
- Web UI engineering pass:
  - **Headings:** each page has one H1 (the page or run name) and H2 sections, with no skipped levels.
  - **Empty segment:** choosing a segment with no matching leads shows a note instead of an empty table.
  - **Code:** the app is split into one module per screen under `app/views/`.
  - **Design contract:** `docs/UI.md` records the screens, their states and the responsive rules.
  - **Widths checked:** 320, 768, 1024 and 1440 px.
- Web UI redesign:
  - **Look:** a calmer, more polished workspace. Text is set in Geist with Outfit headings, on a light green-tinted canvas with a dark sidebar, and harvest green is the only accent. Every emoji is replaced by a Material icon.
  - **Sign-in:** a split screen, with a brand panel beside a sign-in card. On phones only the card shows.
  - **Navigation:** the sidebar holds the logo, a **New search** button, the run history with status icons, and sign-out. The main area shows either the search page or the selected run, replacing the old collapsible "New search" box.
  - **Search page:** a sectioned form ("What and where", "Size and delivery", "Advanced options") next to a "What happens next" guide.
  - **Run page:** a status badge with the run details, the numbers as bordered cards, then the downloads, segment picker and table.
- Segments, the lists agencies buy: `no-website`, `facebook-only`, `website-upgrade`, `no-booking` and `business-email`.
  - **Command line:** `export --segment NAME` writes each as its own CSV/XLSX.
  - **Web UI:** a **Show** picker filters the results table to a segment and downloads it as CSV. It replaces the "Only leads with an email" toggle, which lives on as "Has an email".
- New sales flags, read from the homepage already fetched (no extra requests):
  - `stale_site`: the footer copyright is 3 or more years old.
  - `no_analytics`: no Google Analytics, Tag Manager, Meta or TikTok pixel.
  - `no_online_booking`: appointment-based businesses with no booking platform, PH ones included (SeriousMD, NowServing).
- New `email_kind` export column: `business` (a role mailbox or the business's name), `personal` (looks like a person's name, so personal data under RA 10173) or `unknown`. It also shows as "Email type" in the UI table.
- Each CSV `.about.txt` and XLSX `About` sheet now has a quality summary: hit rates for email, phone, website and social profiles, plus counts of personal-name emails, duplicates merged, suppressed businesses and websites skipped by robots.txt.
- New source, **Overture Maps** (`--sources overture`, or "Data sources" in the UI's advanced options; install with `uv sync --extra overture`):
  - **What it is:** open places data, mostly from Facebook pages, with phones, emails, websites and social links. A Makati check found about 800 dental clinics, against a few dozen in OpenStreetMap.
  - **Licence:** CDLA Permissive 2.0, Apache 2.0 or CC0 depending on the provider. It holds no OpenStreetMap data, so an Overture-only list has no ODbL share-alike.
  - **Filtering:** places are kept only inside the city's boundary and above a confidence floor; closed places are skipped.
- Exports name the data sources they actually used, and the Google Sheet export now carries attribution too, as a note on the header cell.
- The Streamlit extra now requires 1.64, the version the UI is built and tested on.
- UI polish:
  - **Results first:** once signed in, the page header is one small brand line instead of a large title and tagline, so a run's results start near the top.
  - **Phone layout:** the five numbers above the table wrap two or three to a row instead of one per line, so the table starts on the first screen.
  - **Times:** run times show in the browser's time zone, plus how long ago (`18 h ago`). A run stuck as "running" since yesterday is easy to spot.
  - **Table:** phone numbers are grouped (`+63 917 123 4567`), and websites show only the domain. Exports are unchanged.
- Fix: a run can't be executed twice at once. Resuming a run that another tab or the CLI is still running used to start a second copy, which visited every website twice and exported twice. Now it is refused. The UI offers **Take over and resume** and the CLI offers `resume --force` for a run left "running" by a crash. New runs start as paused until they begin.
- Fix: `purge` keeps the raw records of unfinished runs, so a paused run can still resume.
- Fix: the HubSpot export no longer lets a third lead with the same domain overwrite fields the second one filled.
- Privacy: `forget --domain` and suppressions now also match email addresses on subdomains (`info@mail.smile.ph` for `smile.ph`).
- Security: a wrong UI password waits one second before answering, to slow guessing.
- Web UI redesign:
  - **Recent runs** sidebar: reopen any run, even after a reload.
  - **Resume run** button for paused runs. A click while a run is in progress used to leave it stuck as "running"; now the run is marked paused.
  - Live progress, one line per step, with a website counter.
  - Results first: lead counts, a table sorted by score with readable flags and links, download buttons, and a link to the Google Sheet.
  - Sign-in by pressing Enter.
  - Readable export names, advanced options folded away, a phone-friendly field order, and a green theme without the developer toolbar.
  - Fix: runs of the same search could not be told apart in the run list.
- Security: the `--js` renderer re-checks the page's final URL after redirects, which Playwright's route guard never sees, and the address that served it. The plain fetcher refuses to read a response from a non-public address (DNS rebinding). Neither check applies behind a proxy.
- Privacy: `forget --domain` also deletes leads whose email is on that domain. `forget` deletes the lead's raw source records too, and `purge` deletes raw records older than the cutoff. Score stats store a count of dropped emails instead of the addresses.
- Fix: the HubSpot export no longer creates two companies for two leads with the same domain. HubSpot search shows a new company only after a few seconds.
- Fix: concurrent use (UI plus CLI) no longer fails with "database is locked", because transactions now take the write lock up front.
- Politeness: a 429 response for robots.txt now means "disallow everything" instead of "allow everything".
- Faster scoring: email-domain (MX) lookups for the whole run happen in one concurrent pass.
- Fix: a batch row whose category or location was edited now starts a new run. Before, it was skipped as "already completed", or it resumed the old job.
- Fix: `monitor` now computes "new since last run" against the same monitor's previous run only. Before, a one-off `run` or another monitor over the same area could be used as the baseline.

## 0.3.0 — 2026-10-01

V2 (blueprint Phase 9 / F15–F17).

- Website signals: the platform is detected from the homepage HTML and headers (`tech` column), and a missing mobile viewport adds the `no_mobile_viewport` flag. Schema v3.
- Batch mode: `leadharvest batch jobs.csv` or `--from-sheet TAB`. Rows are resumable and skipped once completed; `--rerun` runs them again.
- Weekly monitoring: `leadharvest monitor` (one batch per ISO week) exports "new since last run" leads to a `... - new` Sheets history tab (with `found_on`) and to `-new` CSV/XLSX files.
- GitHub Actions workflow `monitor.yml`: a weekly schedule, with the lead database carried between runs as an AES-256-encrypted artifact.

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
