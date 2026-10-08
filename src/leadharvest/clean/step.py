"""The clean step: raw records → normalized, suppressed, deduped leads linked to the run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from leadharvest.clean.dedupe import find_match, merge
from leadharvest.clean.normalize import (
    city_key,
    format_address,
    name_key,
    normalize_email,
    normalize_phones,
    normalize_url,
    registered_domain,
    social_platform,
    split_website,
    street_key,
)
from leadharvest.config import Settings
from leadharvest.logging_setup import get_logger
from leadharvest.models import Lead, RawBusiness, Run, new_lead_id, utcnow_iso
from leadharvest.storage.repository import Repository

log = get_logger("clean")


@dataclass
class CleanStats:
    found: int = 0
    unnamed: int = 0
    suppressed: int = 0
    linked_records: int = 0
    truncated: bool = False
    possible_duplicates: list[list[str]] = field(default_factory=list)

    def as_dict(self, repo: Repository, run_id: str) -> dict[str, Any]:
        leads = repo.count_run_leads(run_id)
        new = repo.count_new_leads(run_id)
        return {
            "found": self.found,
            "unnamed_skipped": self.unnamed,
            "suppressed": self.suppressed,
            "leads": leads,
            "new": new,
            "existing": leads - new,
            "duplicates_merged": max(0, self.linked_records - leads),
            "truncated": self.truncated,
            "possible_duplicates": self.possible_duplicates,
        }


def _social_url(value: str | None, platform: str) -> str | None:
    """OSM social tags hold either a profile URL or a bare handle ("@smile.ph", "SmilePH")."""
    if not value:
        return None
    value = value.strip()
    url = normalize_url(value) if "/" in value else None
    if url and social_platform(url) == platform:
        return url
    if "/" in value or " " in value:
        return None
    handle = value.lstrip("@")
    base = {"facebook": "facebook.com", "instagram": "instagram.com"}[platform]
    return f"https://www.{base}/{handle}" if handle else None


def candidate_from_raw(raw: RawBusiness, run: Run, region: str = "PH") -> Lead | None:
    name = (raw.name or "").strip()
    key = name_key(name)
    if not name or not key:
        return None
    phones = normalize_phones(raw.phones_raw, region)
    website, socials = split_website(raw.website_raw)
    emails = list(dict.fromkeys(e for e in (normalize_email(x) for x in raw.emails_raw) if e))
    city = raw.city.strip() if raw.city and raw.city.strip() else None
    city_source = "osm" if city else None
    if city is None and run.area_name:
        city, city_source = run.area_name, "run_area"
    street_line = " ".join(p for p in (raw.housenumber, raw.street) if p and p.strip()) or None
    now = utcnow_iso()
    return Lead(
        business_name=name,
        name_key=key,
        categories=[run.category],
        address=format_address(street_line, raw.suburb, raw.city),
        city=city,
        city_key=city_key(city),
        city_source=city_source,
        province=raw.province,
        street_key=street_key(raw.street),
        country=region,
        lat=raw.lat,
        lon=raw.lon,
        phone=phones[0] if phones else None,
        phones_extra=phones[1:],
        email=emails[0] if emails else None,
        emails_extra=emails[1:],
        website=website,
        domain=registered_domain(website),
        facebook=socials.get("facebook") or _social_url(raw.facebook, "facebook"),
        instagram=socials.get("instagram") or _social_url(raw.instagram, "instagram"),
        linkedin=socials.get("linkedin"),
        tiktok=socials.get("tiktok"),
        opening_hours=raw.opening_hours,
        sources=[raw.source],
        enrich_status="pending",
        first_seen_at=now,
        last_seen_at=now,
        updated_at=now,
        source=raw.source,
        source_ref=raw.source_ref,
    )


def is_suppressed(cand: Lead, suppressed: dict[str, set[str]]) -> bool:
    if cand.domain and cand.domain in suppressed["domain"]:
        return True
    phones = {p for p in [cand.phone, *cand.phones_extra] if p}
    emails = {e for e in [cand.email, *cand.emails_extra] if e}
    if phones & suppressed["phone"] or emails & suppressed["email"]:
        return True
    return any(e.split("@", 1)[1] in suppressed["domain"] for e in emails)


def run_clean_step(repo: Repository, run: Run, settings: Settings) -> dict[str, Any]:
    """Idempotent: re-running over the same raw records links the same leads, creates none."""
    stats = CleanStats()
    suppressed = repo.suppressions()
    linked = repo.count_run_leads(run.id)
    for raw in repo.raw_for_run(run.id):
        stats.found += 1
        cand = candidate_from_raw(raw, run, settings.default_region)
        if cand is None:
            stats.unnamed += 1
            continue
        if is_suppressed(cand, suppressed):
            stats.suppressed += 1
            continue
        with repo.transaction():
            match = find_match(
                repo,
                cand,
                radius_m=settings.phone_match_radius_m,
                shared_phone_min_names=settings.shared_phone_min_names,
            )
            existing = match.lead
            already_linked = existing is not None and repo.is_linked(run.id, existing.lead_id or "")
            if not already_linked and linked >= run.limit_n:
                stats.truncated = True
                continue
            if existing is not None:
                # A refresh may overwrite only when this record is the lead's sole source;
                # otherwise two records feeding one lead would overwrite each other every run.
                lead_id = existing.lead_id or ""
                sole_source = (
                    repo.is_source_linked(lead_id, raw.source, raw.source_ref)
                    and repo.count_lead_sources(lead_id) == 1
                )
                lead = merge(existing, cand, same_source_record=sole_source)
                repo.update_lead(lead)
            else:
                lead = cand.model_copy(
                    update={"lead_id": new_lead_id(), "first_seen_run_id": run.id}
                )
                repo.insert_lead(lead)
            assert lead.lead_id is not None
            repo.add_lead_source(raw.source, raw.source_ref, lead.lead_id)
            if repo.link_run_lead(run.id, lead.lead_id, run.category):
                linked += 1
            stats.linked_records += 1
            if match.conflict_lead_id:
                pair = [lead.lead_id, match.conflict_lead_id]
                if pair not in stats.possible_duplicates:
                    stats.possible_duplicates.append(pair)
                    log.info("possible duplicate", extra={"data": {"leads": pair}})
    repo.mark_no_website(run.id)
    result = stats.as_dict(repo, run.id)
    if stats.truncated:
        log.warning("Result count above --limit %s; kept the first %s.", run.limit_n, run.limit_n)
    return result
