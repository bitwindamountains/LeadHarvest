"""Per-lead website enrichment orchestration (blueprint section 10.5)."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from leadharvest.clean.normalize import registered_domain
from leadharvest.config import Settings
from leadharvest.enrich.discovery import discover_contact_pages
from leadharvest.enrich.extractors import Extracted, extract_all, rank_emails, text_length
from leadharvest.enrich.fetcher import FetchError, PoliteFetcher
from leadharvest.enrich.render import Renderer
from leadharvest.enrich.signals import detect_tech, has_mobile_viewport
from leadharvest.logging_setup import get_logger
from leadharvest.models import EnrichStatus, Lead, utcnow_iso
from leadharvest.storage.repository import Repository

log = get_logger("enrich")

JS_TEXT_THRESHOLD = 500  # visible characters below which a page is probably JS-rendered

_STATUS_FOR_KIND: dict[str, EnrichStatus] = {
    "robots_blocked": "robots_blocked",
    "timeout": "timeout",
    "http_error": "http_error",
    "connect": "http_error",
    "blocked": "http_error",
}


def apply_extraction(
    lead: Lead, found: Extracted, final_url: str, suppressed: dict[str, set[str]]
) -> Lead:
    """Merge what the site published into the lead. Existing values are kept; new ones added."""
    emails = [
        e
        for e in found.emails
        if e not in suppressed["email"] and e.split("@", 1)[1] not in suppressed["domain"]
    ]
    phones = [p for p in found.phones if p not in suppressed["phone"]]
    site_domain = lead.domain or registered_domain(final_url)
    ranked = rank_emails(
        [*([lead.email] if lead.email else []), *lead.emails_extra, *emails], site_domain
    )
    data = lead.model_dump()
    data["email"] = ranked[0] if ranked else None
    data["emails_extra"] = ranked[1:]
    all_phones = list(
        dict.fromkeys([*([lead.phone] if lead.phone else []), *lead.phones_extra, *phones])
    )
    data["phone"] = all_phones[0] if all_phones else None
    data["phones_extra"] = all_phones[1:]
    for platform in ("facebook", "instagram", "linkedin", "tiktok"):
        if not data.get(platform) and platform in found.socials:
            data[platform] = found.socials[platform]
    now = utcnow_iso()
    data.update(
        final_url=final_url,
        https_ok=urlsplit(final_url).scheme == "https",
        enrich_status="ok",
        enrich_error=None,
        enriched_at=now,
        updated_at=now,
    )
    return Lead.model_validate(data)


class Enricher:
    def __init__(
        self,
        settings: Settings,
        repo: Repository,
        fetcher: PoliteFetcher,
        renderer: Renderer | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.fetcher = fetcher
        self.renderer = renderer
        self.suppressed = repo.suppressions()
        self.protected_emails = 0
        self.rendered = 0

    async def _fetch_extra(self, html: str, base_url: str, found: Extracted) -> None:
        region = self.settings.default_region
        for url in discover_contact_pages(html, base_url, self.settings.max_extra_pages):
            try:
                sub = await self.fetcher.get_page(url)
            except FetchError as exc:
                log.info("extra page skipped: %s (%s)", url, exc.kind)
                continue
            found.add(extract_all(sub.text, sub.final_url, region))
            if found.emails and found.phones:
                return

    async def _render_fallback(self, url: str, found: Extracted) -> None:
        """--js only: the page is nearly empty and nothing was found → render it with a browser."""
        assert self.renderer is not None
        try:
            html = await self.renderer.render(url)
        except FetchError as exc:
            log.info("render skipped for %s (%s)", url, exc.kind)
            return
        except Exception as exc:  # browser errors must not fail the lead
            log.warning("render failed for %s: %s", url, exc)
            return
        self.rendered += 1
        found.add(extract_all(html, url, self.settings.default_region))
        if not found.emails or not found.phones:
            await self._fetch_extra(html, url, found)

    async def enrich_lead(self, lead: Lead) -> Lead:
        assert lead.website
        try:
            page = await self.fetcher.get_homepage(lead.website)
        except FetchError as exc:
            status = _STATUS_FOR_KIND.get(exc.kind, "failed")
            now = utcnow_iso()
            return lead.model_copy(
                update={
                    "enrich_status": status,
                    "enrich_error": str(exc)[:300],
                    "enriched_at": now,
                    "updated_at": now,
                }
            )
        found = extract_all(page.text, page.final_url, self.settings.default_region)
        if not found.emails or not found.phones:
            await self._fetch_extra(page.text, page.final_url, found)
        if (
            self.renderer is not None
            and not found.emails
            and not found.phones
            and text_length(page.text) < JS_TEXT_THRESHOLD
        ):
            await self._render_fallback(page.final_url, found)
        self.protected_emails += found.protected_emails
        enriched = apply_extraction(lead, found, page.final_url, self.suppressed)
        return enriched.model_copy(
            update={
                "tech": detect_tech(page.text, page.headers),
                "mobile_viewport": has_mobile_viewport(page.text),
            }
        )

    async def enrich_run(
        self,
        run_id: str,
        *,
        retry_failed: bool = False,
        refresh_days: int | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> dict[str, Any]:
        leads = self.repo.leads_to_enrich(
            run_id, retry_failed=retry_failed, refresh_days=refresh_days
        )
        total = len(leads)
        done = 0
        outcomes: Counter[str] = Counter()
        if on_progress:
            on_progress(0, total)

        async def worker(lead: Lead) -> None:
            nonlocal done
            try:
                updated = await self.enrich_lead(lead)
            except Exception as exc:  # one lead must never stop the run
                log.exception("enrichment crashed for %s", lead.lead_id)
                now = utcnow_iso()
                updated = lead.model_copy(
                    update={
                        "enrich_status": "failed",
                        "enrich_error": f"{type(exc).__name__}: {exc}"[:300],
                        "enriched_at": now,
                        "updated_at": now,
                    }
                )
            self.repo.update_lead(updated)  # saved immediately: resume never re-fetches it
            outcomes[updated.enrich_status] += 1
            done += 1
            if on_progress:
                on_progress(done, total)

        # Concurrency and politeness are enforced inside the fetcher; tasks here just queue up.
        await asyncio.gather(*(worker(lead) for lead in leads))
        return {
            "attempted": total,
            "outcomes": dict(outcomes),
            "protected_emails": self.protected_emails,
            "js_rendered": self.rendered,
            "requests": self.fetcher.request_count,
            "hosts_skipped": sorted(self.fetcher.blocked_hosts),
        }
