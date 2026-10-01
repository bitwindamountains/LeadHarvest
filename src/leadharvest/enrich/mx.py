"""Email domain check (V1, F11): drop emails whose domain cannot receive mail.

A domain can receive mail if it has MX records, or (implicit MX, RFC 5321) an A/AAAA record.
A "null MX" (RFC 7505) or NXDOMAIN means it cannot. DNS errors/timeouts mean "unknown", and
unknown never drops an email.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from leadharvest.enrich.extractors import FREE_EMAIL_DOMAINS
from leadharvest.logging_setup import get_logger
from leadharvest.storage.repository import Repository

log = get_logger("mx")

MxLookup = Callable[[str], Awaitable[bool | None]]


async def dns_mx_lookup(domain: str, timeout: float = 5.0) -> bool | None:
    import dns.asyncresolver
    import dns.exception
    import dns.resolver

    resolver = dns.asyncresolver.Resolver()
    resolver.lifetime = timeout
    try:
        answer = await resolver.resolve(domain, "MX")
        records = list(answer)
        null_mx = len(records) == 1 and str(records[0].exchange) in (".", "")
        return not null_mx  # a null MX (RFC 7505) explicitly accepts no mail
    except dns.resolver.NXDOMAIN:
        return False
    except dns.resolver.NoAnswer:
        for rtype in ("A", "AAAA"):
            try:
                await resolver.resolve(domain, rtype)
                return True
            except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
                continue
            except dns.exception.DNSException:
                return None
        return False
    except dns.exception.DNSException:
        return None


class MxChecker:
    def __init__(
        self, repo: Repository | None, lookup: MxLookup = dns_mx_lookup, concurrency: int = 10
    ) -> None:
        self.repo = repo
        self.lookup = lookup
        self._memory: dict[str, bool | None] = {}
        self._semaphore = asyncio.Semaphore(concurrency)

    async def has_mail(self, domain: str) -> bool | None:
        domain = domain.lower().rstrip(".")
        if domain in FREE_EMAIL_DOMAINS:
            return True
        if domain in self._memory:
            return self._memory[domain]
        cached = self.repo.mx_cache_get(domain) if self.repo else None
        if cached is not None:
            self._memory[domain] = cached
            return cached
        async with self._semaphore:
            result = await self.lookup(domain)
        self._memory[domain] = result
        if result is not None and self.repo:
            self.repo.mx_cache_put(domain, result)
        log.debug("mx %s -> %s", domain, result)
        return result

    async def dead_emails(self, emails: list[str]) -> list[str]:
        """Emails whose domain definitely cannot receive mail."""
        domains = sorted({e.split("@", 1)[1] for e in emails if "@" in e})
        results = await asyncio.gather(*(self.has_mail(d) for d in domains))
        dead = {d for d, ok in zip(domains, results, strict=True) if ok is False}
        return [e for e in emails if e.split("@", 1)[-1] in dead]
