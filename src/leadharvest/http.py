"""Shared HTTP building blocks: client factory, retries with Retry-After, rate limiters.

Every outbound client is created here so the User-Agent and timeouts are always set.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
)

from leadharvest.config import Settings

MAX_RETRY_AFTER_SECONDS = 60.0

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


def make_client(settings: Settings, *, timeout: float | None = None) -> httpx.AsyncClient:
    """Async client with our User-Agent. Redirects are off: callers decide how to follow them."""
    return httpx.AsyncClient(
        headers={"User-Agent": settings.user_agent, "Accept-Language": "en,fil;q=0.8"},
        timeout=httpx.Timeout(timeout or settings.request_timeout_seconds),
        follow_redirects=False,
    )


class RetryableStatus(httpx.HTTPError):
    """429/5xx after retries. An httpx.HTTPError, so callers' HTTP error handling catches it."""

    def __init__(self, response: httpx.Response) -> None:
        super().__init__(f"HTTP {response.status_code} from {response.request.url}")
        self.response = response
        self.status_code = response.status_code
        self.retry_after = parse_retry_after(response.headers.get("Retry-After"))


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    """Seconds to wait from a Retry-After header (delta-seconds or HTTP date), capped."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return min(float(value), MAX_RETRY_AFTER_SECONDS)
    try:
        when = parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError):
        return None
    delta = when - (time.time() if now is None else now)
    return max(0.0, min(delta, MAX_RETRY_AFTER_SECONDS))


def is_retryable_status(status: int) -> bool:
    return status == 429 or 500 <= status < 600


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    sleep: Sleep = asyncio.sleep,
    **kwargs: Any,
) -> httpx.Response:
    """Send a request; retry transport errors, 429 and 5xx with exponential backoff.

    429 responses wait for Retry-After when given. Raises the last error after `attempts`.
    """

    def wait(state: RetryCallState) -> float:
        exc = state.outcome.exception() if state.outcome else None
        if isinstance(exc, RetryableStatus) and exc.retry_after is not None:
            return exc.retry_after
        return base_delay * (2 ** (state.attempt_number - 1))

    retrying = AsyncRetrying(
        stop=stop_after_attempt(attempts),
        wait=wait,
        retry=retry_if_exception_type((httpx.TransportError, RetryableStatus)),
        sleep=sleep,
        reraise=True,
    )
    async for attempt in retrying:
        with attempt:
            response = await client.request(method, url, **kwargs)
            if is_retryable_status(response.status_code):
                raise RetryableStatus(response)
            return response
    raise AssertionError("unreachable")  # pragma: no cover


class MinIntervalLimiter:
    """Ensures at least `interval` seconds between acquisitions (e.g. Nominatim 1 req/s)."""

    def __init__(
        self, interval: float, *, clock: Clock = time.monotonic, sleep: Sleep = asyncio.sleep
    ):
        self.interval = interval
        self._clock = clock
        self._sleep = sleep
        self._next_at = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = self._clock()
            if now < self._next_at:
                await self._sleep(self._next_at - now)
                now = self._clock()
            self._next_at = max(now, self._next_at) + self.interval

    def push_back(self, seconds: float) -> None:
        """Delay the next acquisition (used for Retry-After)."""
        self._next_at = max(self._next_at, self._clock() + seconds)


class PerKeyLimiter:
    """One MinIntervalLimiter per key (host). Different keys proceed concurrently."""

    def __init__(
        self, interval: float, *, clock: Clock = time.monotonic, sleep: Sleep = asyncio.sleep
    ):
        self.interval = interval
        self._clock = clock
        self._sleep = sleep
        self._limiters: dict[str, MinIntervalLimiter] = {}

    def for_key(self, key: str) -> MinIntervalLimiter:
        limiter = self._limiters.get(key)
        if limiter is None:
            limiter = MinIntervalLimiter(self.interval, clock=self._clock, sleep=self._sleep)
            self._limiters[key] = limiter
        return limiter

    async def wait(self, key: str) -> None:
        await self.for_key(key).wait()
