"""Polite async fetcher for business websites (blueprint sections 10.5 and 10.6).

Every hop of every request: http(s) only → SSRF guard → robots.txt for that origin →
per-host delay → global concurrency limit → size-capped read. Redirects are followed manually.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from leadharvest.config import Settings
from leadharvest.enrich.netguard import (
    BlockedAddress,
    Resolver,
    assert_public_host,
    system_resolver,
)
from leadharvest.enrich.robots import UNREACHABLE, RobotsChecker
from leadharvest.http import Clock, PerKeyLimiter, Sleep, parse_retry_after
from leadharvest.logging_setup import get_logger
from leadharvest.storage.repository import Repository

log = get_logger("fetcher")

MAX_REDIRECTS = 5
BREAKER_THRESHOLD = 3
_REDIRECT_CODES = {301, 302, 303, 307, 308}
_HTML_TYPES = ("text/html", "application/xhtml+xml")


class FetchError(Exception):
    """kind: robots_blocked | timeout | http_error | connect | blocked | failed"""

    def __init__(self, kind: str, message: str, status: int | None = None) -> None:
        self.kind = kind
        self.status = status
        super().__init__(message)


@dataclass
class Page:
    url: str
    final_url: str
    status: int
    content_type: str
    text: str
    truncated: bool = False


def _decode(body: bytes, content_type: str) -> str:
    match = re.search(r"charset=([\w.-]+)", content_type, re.IGNORECASE)
    charset = match.group(1) if match else None
    if charset is None:
        meta = re.search(rb"<meta[^>]+charset=[\"']?([\w.-]+)", body[:4096], re.IGNORECASE)
        charset = meta.group(1).decode("ascii", "ignore") if meta else "utf-8"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


class PoliteFetcher:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient,
        *,
        repo: Repository | None = None,
        resolver: Resolver = system_resolver,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.settings = settings
        self.client = client
        self.resolver = resolver
        self.max_bytes = settings.max_response_bytes
        self._semaphore = asyncio.Semaphore(settings.concurrency)
        self._hosts = PerKeyLimiter(settings.per_domain_delay_seconds, clock=clock, sleep=sleep)
        self._strikes: dict[str, int] = {}
        self.blocked_hosts: set[str] = set()
        self.robots = RobotsChecker(repo, settings.ua_product, self._fetch_robots)
        self.request_count = 0

    # ---- public API -------------------------------------------------------------------------

    async def get_homepage(self, url: str) -> Page:
        """GET with https→http fallback when the https connection itself fails."""
        try:
            return await self.get_page(url)
        except FetchError as exc:
            parts = urlsplit(url)
            if parts.scheme != "https" or exc.kind not in ("connect", "timeout"):
                raise
            http_url = urlunsplit(("http", *parts[1:]))
            log.info("https failed for %s (%s); trying http", url, exc.kind)
            return await self.get_page(http_url)

    async def get_page(self, url: str) -> Page:
        current = url
        for _hop in range(MAX_REDIRECTS + 1):
            self._check_scheme(current)
            if not await self.robots.allowed(current):
                raise FetchError("robots_blocked", f"robots.txt disallows {current}")
            response, body, truncated = await self._send(current)
            status = response.status_code
            location = response.headers.get("location")
            if status in _REDIRECT_CODES and location:
                current = urljoin(current, location)
                continue
            if status >= 400:
                raise FetchError("http_error", f"HTTP {status} for {current}", status)
            content_type = response.headers.get("content-type", "").lower()
            if content_type and not content_type.startswith(_HTML_TYPES):
                raise FetchError("failed", f"not HTML ({content_type}) at {current}", status)
            return Page(url, current, status, content_type, _decode(body, content_type), truncated)
        raise FetchError("failed", f"more than {MAX_REDIRECTS} redirects from {url}")

    # ---- internals --------------------------------------------------------------------------

    @staticmethod
    def _check_scheme(url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise FetchError("failed", f"refusing non-http(s) URL: {url}")

    async def _send(self, url: str) -> tuple[httpx.Response, bytes, bool]:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if host in self.blocked_hosts:
            raise FetchError("blocked", f"skipping {host}: repeated 403/429 responses")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        try:
            await assert_public_host(host, port, self.resolver)
        except BlockedAddress as exc:
            raise FetchError("failed", str(exc)) from exc
        except OSError as exc:
            raise FetchError("connect", f"DNS lookup failed for {host}: {exc}") from exc
        limiter = self._hosts.for_key(host)
        await limiter.wait()
        async with self._semaphore:
            self.request_count += 1
            try:
                async with self.client.stream("GET", url) as response:
                    body, truncated = await self._read_capped(response)
            except httpx.TimeoutException as exc:
                raise FetchError("timeout", f"timeout fetching {url}") from exc
            except (httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                raise FetchError("connect", f"connection failed for {url}: {exc}") from exc
            except httpx.HTTPError as exc:
                raise FetchError("http_error", f"HTTP error for {url}: {exc}") from exc
        self._record_status(host, response, limiter)
        return response, body, truncated

    async def _read_capped(self, response: httpx.Response) -> tuple[bytes, bool]:
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            chunks.append(chunk)
            size += len(chunk)
            if size >= self.max_bytes:
                return b"".join(chunks)[: self.max_bytes], True
        return b"".join(chunks), False

    def _record_status(self, host: str, response: httpx.Response, limiter: object) -> None:
        status = response.status_code
        if status in (403, 429):
            self._strikes[host] = self._strikes.get(host, 0) + 1
            if status == 429:
                wait = parse_retry_after(response.headers.get("Retry-After"))
                if wait:
                    limiter.push_back(wait)  # type: ignore[attr-defined]
            if self._strikes[host] >= BREAKER_THRESHOLD:
                self.blocked_hosts.add(host)
                log.warning("Skipping %s for the rest of the run (repeated %s)", host, status)
        else:
            self._strikes[host] = 0

    async def _fetch_robots(self, robots_url: str) -> tuple[int, str | None]:
        """Fetch robots.txt (redirects followed, SSRF-checked).

        If the origin itself can't be reached (connection/timeout on the first hop), the error
        propagates: the page can't be fetched either, and get_homepage may retry over http.
        Any other failure → UNREACHABLE, which means "disallow everything".
        """
        current = robots_url
        try:
            for hop in range(MAX_REDIRECTS + 1):
                self._check_scheme(current)
                try:
                    response, body, _ = await self._send(current)
                except FetchError as exc:
                    if hop == 0 and exc.kind in ("connect", "timeout"):
                        raise
                    log.info("robots.txt unreachable at %s: %s", robots_url, exc)
                    return UNREACHABLE, None
                location = response.headers.get("location")
                if response.status_code in _REDIRECT_CODES and location:
                    current = urljoin(current, location)
                    continue
                if 200 <= response.status_code < 300:
                    return response.status_code, _decode(body, "text/plain; charset=utf-8")
                return response.status_code, None
        except FetchError as exc:
            if exc.kind in ("connect", "timeout"):
                raise
            log.info("robots.txt unreachable at %s: %s", robots_url, exc)
            return UNREACHABLE, None
        return UNREACHABLE, None
