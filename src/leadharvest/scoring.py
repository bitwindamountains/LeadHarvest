"""Lead scoring and sales flags (V1, blueprint section 10.8)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from leadharvest.clean.normalize import is_shared_domain, registered_domain
from leadharvest.enrich.extractors import FREE_EMAIL_DOMAINS, rank_emails
from leadharvest.enrich.mx import MxChecker
from leadharvest.models import Lead, Run, utcnow_iso
from leadharvest.storage.repository import Repository

POINTS = {
    "email": 30,
    "own_domain_email": 10,
    "phone": 20,
    "website": 15,
    "social": 10,
    "street_address": 10,
    "opening_hours": 5,
}


def own_domain_email(lead: Lead) -> bool:
    if not lead.email or not lead.domain or is_shared_domain(lead.domain):
        return False
    return registered_domain(lead.email.split("@", 1)[1]) == lead.domain


def score_lead(lead: Lead) -> tuple[int, list[str]]:
    has_social = any((lead.facebook, lead.instagram, lead.linkedin, lead.tiktok))
    score = 0
    if lead.email:
        score += POINTS["email"]
        if own_domain_email(lead):
            score += POINTS["own_domain_email"]
    if lead.phone:
        score += POINTS["phone"]
    if lead.website:
        score += POINTS["website"]
    if has_social:
        score += POINTS["social"]
    if lead.street_key:
        score += POINTS["street_address"]
    if lead.opening_hours:
        score += POINTS["opening_hours"]

    flags: list[str] = []
    if not lead.website:
        flags.append("no_website")
        if has_social:
            flags.append("social_only")
    if lead.https_ok is False:
        flags.append("no_https")
    if lead.mobile_viewport is False:
        flags.append("no_mobile_viewport")
    if lead.email and lead.email.split("@", 1)[1] in FREE_EMAIL_DOMAINS:
        flags.append("free_email_provider")
    return min(score, 100), flags


async def run_score_step(repo: Repository, run: Run, mx: MxChecker | None = None) -> dict[str, Any]:
    """Optionally drop emails on dead domains, then score every lead in the run."""
    leads = repo.leads_for_run(run.id)
    flag_counts: Counter[str] = Counter()
    dropped = 0
    total = 0
    all_emails = [e for lead in leads for e in [lead.email, *lead.emails_extra] if e]
    # One concurrent lookup over every domain in the run, not one lead at a time.
    dead = set(await mx.dead_emails(all_emails)) if mx is not None else set()
    for lead in leads:
        emails = [e for e in [lead.email, *lead.emails_extra] if e]
        kept = [e for e in emails if e not in dead]
        if len(kept) < len(emails):
            dropped += len(emails) - len(kept)
            ranked = rank_emails(kept, lead.domain)
            lead = lead.model_copy(
                update={"email": ranked[0] if ranked else None, "emails_extra": ranked[1:]}
            )
        score, flags = score_lead(lead)
        flag_counts.update(flags)
        total += score
        repo.update_lead(
            lead.model_copy(update={"score": score, "flags": flags, "updated_at": utcnow_iso()})
        )
    return {
        "scored": len(leads),
        "average_score": round(total / len(leads), 1) if leads else 0,
        "flags": dict(flag_counts),
        "emails_dropped_dead_domain": dropped,  # a count: stats outlive `forget`
        "mx_checked": mx is not None,
    }
