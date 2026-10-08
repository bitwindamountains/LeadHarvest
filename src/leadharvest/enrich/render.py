"""Optional JavaScript rendering with Playwright (blueprint 10.5 step 6, `--js` only).

Install with `uv sync --extra js && uv run playwright install chromium`.
The browser obeys the same rules as the plain fetcher: the page URL passes robots.txt, the SSRF
guard and the per-host delay; every sub-request passes the SSRF guard; images, media and fonts
are not loaded; any main-frame navigation to another URL is re-checked against robots.txt.
Redirects bypass the route handler, so the page's final URL and server address are re-checked
before its content is read.
"""

from __future__ import annotations

import asyncio
import importlib.util
from typing import Any, Protocol

from leadharvest.config import Settings
from leadharvest.enrich.fetcher import FetchError, PoliteFetcher
from leadharvest.logging_setup import get_logger

log = get_logger("render")

RENDER_TIMEOUT_S = 20
_SKIP_RESOURCES = {"image", "media", "font"}


class RenderUnavailable(Exception):
    """Playwright (or its browser) is not installed."""


class Renderer(Protocol):
    async def render(self, url: str) -> str: ...


def playwright_installed() -> bool:
    return importlib.util.find_spec("playwright") is not None


class PlaywrightRenderer:
    def __init__(
        self,
        settings: Settings,
        fetcher: PoliteFetcher,
        *,
        concurrency: int = 2,
        launch_args: list[str] | None = None,
    ) -> None:
        self.settings = settings
        self.fetcher = fetcher
        self.launch_args = launch_args or []
        self._semaphore = asyncio.Semaphore(concurrency)
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None

    async def __aenter__(self) -> PlaywrightRenderer:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RenderUnavailable(
                "--js needs Playwright: uv sync --extra js && uv run playwright install chromium"
            ) from exc
        self._pw = await async_playwright().start()
        try:
            self._browser = await self._pw.chromium.launch(headless=True, args=self.launch_args)
        except Exception as exc:
            await self._pw.stop()
            raise RenderUnavailable(
                f"Could not start Chromium ({exc}). Run: uv run playwright install chromium"
            ) from exc
        self._context = await self._browser.new_context(
            user_agent=self.settings.user_agent,
            service_workers="block",
            accept_downloads=False,
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._context is not None:
            await self._context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()

    async def _guard(self, route: Any, target: str) -> None:
        request = route.request
        if request.resource_type in _SKIP_RESOURCES:
            await route.abort()
            return
        url = request.url
        try:
            await self.fetcher.check_public(url)
            other_page = (
                request.is_navigation_request()
                and request.frame.parent_frame is None
                and url.rstrip("/") != target.rstrip("/")
            )
            if other_page and not await self.fetcher.robots.allowed(url):
                raise FetchError("robots_blocked", f"robots.txt disallows {url}")
        except FetchError as exc:
            log.info("render blocked %s: %s", url, exc)
            await route.abort()
            return
        await route.continue_()

    async def _check_landing(self, final_url: str, response: Any) -> None:
        """The route guard never sees redirect hops, so re-check where the page landed and
        the address that actually served it (DNS rebinding)."""
        host = await self.fetcher.check_public(final_url)
        if not await self.fetcher.robots.allowed(final_url):
            raise FetchError("robots_blocked", f"robots.txt disallows {final_url}")
        addr = await response.server_addr() if response is not None else None
        self.fetcher.check_peer(host, addr["ipAddress"] if addr else None)

    async def render(self, url: str) -> str:
        await self.fetcher.admit(url)
        async with self._semaphore:
            page = await self._context.new_page()
            try:
                await page.route("**/*", lambda route: self._guard(route, url))
                timeout = RENDER_TIMEOUT_S * 1000
                response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                await self._check_landing(page.url, response)
                try:
                    await page.wait_for_load_state("networkidle", timeout=timeout)
                except Exception as exc:
                    # Pages that keep polling never go idle; use what has rendered so far.
                    if "Timeout" not in type(exc).__name__:
                        raise
                    log.info("render timed out waiting for idle on %s; using partial DOM", url)
                return await page.content()
            finally:
                await page.close()
