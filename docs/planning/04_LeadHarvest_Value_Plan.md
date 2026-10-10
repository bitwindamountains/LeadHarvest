# LeadHarvest — Value Plan

2026-10-11 · What to build next to make LeadHarvest worth more, and what to do instead of building. Research sources are at the end.

## 1. Where LeadHarvest stands

**The market prices raw lists near zero.** Hosted Google Maps scrapers sell places for about $3–4 per 1,000, and enrichment costs about as much again (Outscraper, Apify). Selling "a list of N businesses" on price is a losing game.

**LeadHarvest's real edges are things those tools don't sell:**
- **Compliant sources:** no Google Maps scraping, robots.txt obeyed, and an honest User-Agent.
- **Philippine-aware cleaning:** E.164 phones, dedupe, and barangay/city handling.
- **A Google Sheet that survives re-exports:** columns the client added are kept, and new leads are appended.
- **"New since last run" monitoring.**
- **Privacy commands:** `forget`/`purge` (RA 10173).
- **Agency sales signals:** no website, no HTTPS, site platform, not mobile-friendly.

**The biggest gaps:**
1. **No live run has happened yet.** Hit rates for email, phone and website are unknown, and the blueprint's honesty rule says to quote them. Everything below is a guess until one real run is done.
2. **Source coverage.** OSM is thin outside Metro Manila, and many PH SMEs exist mainly on Facebook. The most-cited figure is that about 1% of PH MSMEs had a website (Google, 2015, old). In 2020, 51% used social and messaging apps as their main channel (GoDaddy).
3. **The licence question (D2).** Deliverables built from OSM are probably ODbL derivative databases with share-alike obligations. That clashes with selling exclusive lists.

## 2. Ranked features

Value is what it adds to what you can sell. Cost is build effort for this codebase.

| # | Feature | Value | Cost | Why |
|---|---|---|---|---|
| 0 | **Live verification run** (roadmap items 1–6) | Unblocks everything | Hours | Gives you real hit rates for proposals and the README. It is also the first real test of the SSRF checks and MX batching. |
| 1 | **Overture Maps places source** | Very high | 2–4 days | Free monthly open data with about 81M places. Records carry **websites, phones, emails, socials**, a confidence score and categories. It holds **no OSM data**: it is CDLA-Permissive-2.0 or Apache-2.0, so there is no share-alike for Overture-only lists. Meta supplies about 59M records, which suits Facebook-first PH SMEs. One source can fix coverage, D2 and the Facebook gap together. |
| 2 | **Zero-request website signals** | High (agency persona) | 1 day | These come from the homepage HTML that is already fetched, with no new requests. Examples: stale copyright year (`© 2017`), no analytics or Meta pixel, no online booking widget, chat links (Messenger, WhatsApp, Viber), no contact form. Each is a ready-made opening line for a web or marketing agency pitch. |
| 3 | **Email type labels** | High (trust and compliance) | ½ day | Label each email as role (`info@`, `sales@`), personal-name (`maria.santos@`) or free provider. Personal-name emails are personal data under RA 10173, so clients can filter them out. It also makes the "verified" story honest without SMTP probing. |
| 4 | **Per-run quality report** | Medium–high | ½ day | One sheet or tab per export: hit rates (email, phone, website, social), duplicates merged, suppressed, blocked by robots.txt. It is proof of work for the client and the source of your honest pitch numbers. Most of the counts already exist in `runs.stats`. |
| 5 | **PageSpeed Insights score** (optional key) | Medium (agency persona) | 1 day | A free API with about 25,000 requests a day per key (third-party figures; confirm in Cloud console). It turns "slow site" into a number (mobile performance 0–100). It runs only for leads that have a website, behind a flag. |
| 6 | **Segment exports** | Medium | ½ day | Named filters on top of existing data: "Facebook-only", "no website", "WordPress and not mobile-friendly", "personal emails removed". The pitch becomes "the 40 dental clinics in Cebu with no website", not "a list". |
| 7 | **Background runs in the UI** (backlog) | Medium (VA-agency persona) | 1–2 days | Needed before a client's VAs run the tool themselves. Today a stray click pauses the run. |
| 8 | **D4: remember rows deleted from the Sheet** (backlog) | Medium (retainers) | 1 day | Weekly-monitor clients will notice deleted leads coming back. |
| 9 | **AI opening line per lead** (optional) | Medium, but risky | 1 day | Summarize the business from text already fetched and draft one personalized opener. Use a small model (for example Claude Haiku 5.5), opt-in, with cost shown first. Keep it a *draft column*. Sending stays a non-goal, and anti-spam rules (CAN-SPAM, the AU Spam Act) are the client's to follow. |

**Do not build** (these keep the blueprint's non-goals):
- **SMTP mailbox probing:** it damages IP reputation and is often blocked. Use type labels and MX instead.
- **Google Maps scraping.**
- **Decision-maker or LinkedIn enrichment.**
- **Multi-tenant SaaS and billing.**
- **Google Places (F14), until D1 is settled.** Overture probably makes it unnecessary for most jobs. Places Pro or Enterprise also costs $17–40 per 1,000 calls after the free caps.

## 3. Feature notes

### 1. Overture source (`sources/overture.py`)
- **Query:** read the Places GeoParquet for the resolved area's bounding box from the latest release, either with DuckDB over S3/Azure or with the `overturemaps` CLI. Filter on `taxonomy`/`basic_category`, mapped from `categories.yaml`. Add an `overture:` key next to `osm_tags`.
- **Release:** find the latest one through the STAC catalog. Don't hard-code a date; releases are monthly.
- **Mapping:** map to `RawBusiness`, drop rows below a confidence threshold (tune it on the first runs) and rows whose `operating_status` is closed, and keep the GERS `id` as `source_ref`. GERS IDs are stable across releases, which suits `lead_sources` and monitoring.
- **Licence handling** (decide as D6):
  - An **Overture-only run** has no share-alike. Its attribution names Overture and lists the sources; Foursquare records need their NOTICE.
  - A **mixed OSM+Overture run** merges rows, so treat it as an ODbL derivative database.
  - Add `--sources overture` as the "licence-clean" option, and print the licence that applies in the run summary and in each export.
- **Dependency:** `duckdb` as an optional extra (`uv sync --extra overture`), like `js`.
- **Gate:** a fixture parquet in `tests/fixtures`, plus one `-m live` test for a small bounding box in Makati.
- **Compare:** run Overture against OSM for the same Makati dentist run. Count matches, rows unique to each source, and contact fields per source. Decide the default sources from that.

### 2. Zero-request signals (`enrich/signals.py`)
- **New pure functions, the same as `detect_tech`:**
  - `copyright_year(html)`: the latest 4-digit year after ©/Copyright in the footer. Flag `stale_site` if it is 3 or more years old.
  - `marketing_tags(html)`: GA4/gtag, GTM, Meta pixel and TikTok pixel. Flag `no_analytics`.
  - `booking(html)`: Calendly, SimplyBook, Setmore, Fresha, or a booking link. Flag `no_online_booking`, but only for categories where it matters (clinics, salons, gyms).
  - `chat_links`: m.me, wa.me, viber://.
- **Labels:** add each flag to `FLAG_LABELS` and the scoring docs.
- **Migration:** add a `signals` JSON column, or reuse `tech` and `flags`.

### 3. Email labels
- **Function:** `email_kind(email, business_name)` returns `role`, `personal` or `free`. Use a role-prefix list. Call it `personal` when the local part looks like a first name or a first-dot-last pattern and isn't a role prefix.
- **Export:** add an `email_kind` export column, and a `--no-personal-emails` export option.

### 4. Quality report
- **Build it from `runs.stats`:** add a "Summary" tab in the Sheet and XLSX, and a `-summary.txt` next to the CSV.
- **Show the attribution and licence line there too.**

## 4. Other suggestions (not features)

1. **Push and verify CI now.** Three local commits (`7561a40`, `486d8e8` and this plan) are not on GitHub. CI has never run on the real-browser tests.
2. **Raise the Streamlit floor** to the version you test on (1.64) and run `uv lock`. The UI uses APIs that `>=1.36` doesn't have, such as `st.container(horizontal=True)` and `st.context.timezone`.
3. **Positioning:** sell **outcomes for a niche**, not volume. For example: "weekly new no-website dental clinics in Metro Cebu, in your Sheet, with an opening line". Compete on PH accuracy, freshness, compliance and the Sheet workflow; tools at $3/1,000 win on raw volume.
4. **Pricing:** keep the blueprint's starter prices for proof and reviews. Push **retainers** (weekly monitor plus Sheet) as the main product; one-off lists sit at commodity price. Charge for custom adapters and segment definitions, not for rows.
5. **Timely hook, carefully:** Aug 2026 reports said PH regulators were *considering* a nationwide Facebook block. A Facebook-only segment (#6) is an obvious offer for web agencies if that moves. Treat it as a possible hook only, not a promise.
6. **Settle D1 and D2 in writing** before the first paid list. With Overture, D2 can become "Overture-only deliverables by default; OSM-blended lists carry the ODbL notice".
7. **Phase 7 packaging still matters most for winning work:** the 90-second demo plus real hit rates. Record the demo *after* features 1–2. "No website, stale site, no booking" makes a better demo than a plain list.

## 5. Suggested order

**Status (2026-10-11):** steps B (Overture) and C (signals, email labels, quality report) are built. Step A's live run and step D's demo need the owner.

| Step | Work | Gate |
|---|---|---|
| A | Live run, CI, Streamlit floor (#0, suggestions 1–2) | Real hit rates written into PROGRESS and the README |
| B | Overture source plus a comparison with OSM (#1) | Comparison numbers for Makati; D6 written down |
| C | Zero-request signals, email labels, quality report (#2–4) | Unit tests on saved HTML; one live run showing the new flags |
| D | Segments plus demo video (#6, Phase 7) | Demo recorded with blurred contacts |
| E | Build on demand: PageSpeed (#5), background UI runs (#7), D4 (#8), AI opener (#9) | Only once a paying client asks |

Steps A–D are about 1–1.5 weeks of focused work. They turn the pitch from "I can scrape a list" into "I deliver a licence-clean, PH-accurate, weekly-refreshed prospect list with reasons to call".

## Sources

- **Google Maps scraper pricing:** [Outscraper review](https://www.leadscrape.com/outscraper-vs-lead-scrape.html), [Apify Google Maps scraper review](https://www.leadscrape.com/apify-google-maps-scraper-vs-lead-scrape.html), [best Google Maps scrapers 2026](https://brightdata.com/blog/web-data/best-google-maps-scrapers). Vendor and affiliate figures; indicative only.
- **Places API pricing and free caps:** [openplacesapi.com](https://openplacesapi.com/blog/google-places-api-pricing), [basedonb.com](https://www.basedonb.com/en/blog/google-places-api-pricing), [woosmap.com](https://www.woosmap.com/blog/google-places-api-pricing). Third-party; confirm on Google's pricing page.
- **Places storage terms (D1):** [Google Maps Platform Service Specific Terms](https://cloud.google.com/maps-platform/terms/maps-service-terms/index-20240522).
- **ODbL (D2):** [OSMF Produced Work guideline](https://osmfoundation.org/wiki/Community_Guidelines/Produced_Work_-_Guideline), [OSMF Licence and Legal FAQ](https://osmfoundation.org/wiki/Licence_and_Legal_FAQ).
- **Overture places (licences, fields, counts, download):** [Overture Places guide](https://docs.overturemaps.org/guides/places/), [overturemaps on PyPI](https://pypi.python.org/pypi/overturemaps).
- **PageSpeed Insights quota:** [Unlighthouse rate-limit guide](https://unlighthouse.dev/learn-lighthouse/pagespeed-insights-api/rate-limits). Third-party; confirm in Cloud console.
- **PH SMEs online:** [BusinessWorld: half use social media as their main channel](https://www.bworldonline.com/?p=310872), [Newsbytes: 1% have a website (2015)](https://newsbytes.ph/2017/02/12/small-businesses-urged-to-go-digital-join-e-commerce-revolution-2/), [Manila Bulletin: Facebook ban considered (Aug 2026)](https://mb.com.ph/2026/08/26/philippines-contemplates-nationwide-facebook-ban-over-safety-concerns-igniting-fears-for-local-msmes-and-the-digital-economy).
- **Agency audit-led outreach:** [Overloop playbook](https://overloop.com/blog/lead-generation-for-web-design-agencies), [CazaLead](https://yourstory.com/companies/cazalead).
