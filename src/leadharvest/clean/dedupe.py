"""Dedupe match rules and merge rules (blueprint section 10.4)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from leadharvest.clean.normalize import is_shared_domain
from leadharvest.models import Lead, utcnow_iso
from leadharvest.storage.repository import Repository

LIST_FIELDS = ("phones_extra", "emails_extra", "sources", "categories")
SOURCE_FIELDS = (
    "business_name", "name_key", "address", "city", "city_key", "city_source", "province",
    "street_key", "lat", "lon", "phone", "email", "website", "domain", "facebook", "instagram",
    "linkedin", "tiktok", "opening_hours",
)  # fmt: skip


@dataclass
class MatchResult:
    lead: Lead | None
    rule: int | None = None
    conflict_lead_id: str | None = None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def names_similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    ta, tb = set(a.split()), set(b.split())
    return len(ta & tb) / len(ta | tb) >= 0.5


def near_or_unknown(a: Lead, b: Lead, radius_m: float) -> bool:
    """True if both have coordinates within radius, or either lacks coordinates."""
    if None in (a.lat, a.lon, b.lat, b.lon):
        return True
    return haversine_m(a.lat, a.lon, b.lat, b.lon) <= radius_m  # type: ignore[arg-type]


def find_match(
    repo: Repository,
    cand: Lead,
    *,
    radius_m: float = 250.0,
    shared_phone_min_names: int = 3,
) -> MatchResult:
    """Return the first matching existing lead (rules 0-3) and any conflicting later match."""
    matches: list[tuple[int, Lead]] = []

    if cand.source and cand.source_ref:
        hit = repo.lead_by_source_ref(cand.source, cand.source_ref)
        if hit:
            return MatchResult(hit, 0)

    if cand.phone and repo.distinct_names_for_phone(cand.phone) < shared_phone_min_names:
        for lead in repo.leads_by_phone(cand.phone):
            if names_similar(cand.name_key, lead.name_key) and near_or_unknown(
                cand, lead, radius_m
            ):
                matches.append((1, lead))
                break

    if cand.domain and cand.city_key and not is_shared_domain(cand.domain):
        found = repo.leads_by_domain_city(cand.domain, cand.city_key)
        if found:
            matches.append((2, found[0]))

    if cand.name_key and cand.street_key and cand.city_key:
        for lead in repo.leads_by_name_street_city(cand.name_key, cand.street_key, cand.city_key):
            if near_or_unknown(cand, lead, radius_m):
                matches.append((3, lead))
                break

    if not matches:
        return MatchResult(None)
    rule, first = matches[0]
    conflict = next((m.lead_id for _, m in matches[1:] if m.lead_id != first.lead_id), None)
    return MatchResult(first, rule, conflict)


def post_enrich_duplicates(
    repo: Repository, run_id: str, *, radius_m: float = 250.0
) -> list[list[str]]:
    """Report (not merge) run leads that now look like another lead after enrichment."""
    pairs: list[list[str]] = []
    seen: set[frozenset[str]] = set()
    for lead in repo.leads_for_run(run_id):
        if lead.enrich_status != "ok":
            continue
        others: list[Lead] = []
        if lead.phone:
            others += [
                o
                for o in repo.leads_by_phone(lead.phone)
                if names_similar(lead.name_key, o.name_key) and near_or_unknown(lead, o, radius_m)
            ]
        if lead.domain and lead.city_key and not is_shared_domain(lead.domain):
            others += repo.leads_by_domain_city(lead.domain, lead.city_key)
        for other in others:
            key = frozenset({lead.lead_id or "", other.lead_id or ""})
            if other.lead_id != lead.lead_id and key not in seen:
                seen.add(key)
                pairs.append([lead.lead_id or "", other.lead_id or ""])
    return pairs


def merge(existing: Lead, cand: Lead, *, same_source_record: bool) -> Lead:
    """Merge a candidate into an existing lead. lead_id never changes.

    A refresh of the same (source, source_ref) overwrites source fields with its non-empty
    values; otherwise existing non-empty values win and empty ones are filled.
    """
    data = existing.model_dump()
    new = cand.model_dump()
    for field in SOURCE_FIELDS:
        value = new.get(field)
        if value in (None, ""):
            continue
        if same_source_record or data.get(field) in (None, ""):
            data[field] = value
    for field in LIST_FIELDS:
        data[field] = _union(data.get(field) or [], new.get(field) or [])
    if data.get("website") != existing.website:
        data["enrich_status"] = "pending"
    if data.get("phone"):
        data["phones_extra"] = [p for p in data["phones_extra"] if p != data["phone"]]
    if data.get("email"):
        data["emails_extra"] = [e for e in data["emails_extra"] if e != data["email"]]
    now = utcnow_iso()
    data["last_seen_at"] = now
    data["updated_at"] = now
    merged = Lead.model_validate(data)
    merged.source, merged.source_ref = cand.source, cand.source_ref
    return merged


def _union(a: list[str], b: list[str]) -> list[str]:
    return list(dict.fromkeys([*a, *b]))
