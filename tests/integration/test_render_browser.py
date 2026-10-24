"""Real Chromium against a local server. Skipped unless the `js` extra and Chromium are installed.

Chromium goes through the guard proxy, which resolves names with the fake resolver
(site.test → a public address, metadata.test → 169.254.169.254) and connects every public
address to the local server, so nothing leaves the machine.
"""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import respx

from leadharvest.enrich.fetcher import FetchError, PoliteFetcher
from leadharvest.enrich.render import PlaywrightRenderer, RenderUnavailable, playwright_installed
from leadharvest.enrich.render_proxy import GuardProxy
from leadharvest.http import make_client
from tests.conftest import fake_resolver

pytestmark = pytest.mark.skipif(not playwright_installed(), reason="playwright not installed")

PAGE = """<!doctype html><html><body><div id="root"></div>
<img src="/logo.png">
<script>
  fetch("http://metadata.test:%(port)d/latest/meta-data").catch(() => {});
  document.getElementById("root").innerHTML =
    '<a href="mailto:hello@site.test">Email us</a> Call 0917 123 4567';
</script></body></html>"""
SECRET = b"<html><body>secret@internal.test</body></html>"


def start_server(hits: list[tuple[str, str]]) -> ThreadingHTTPServer:
    """Records (Host header, path) of every request it gets."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            hits.append((self.headers.get("Host", ""), self.path))
            port = self.server.server_address[1]
            if self.path in ("/go", "/go-loopback"):  # a public page redirecting to a private one
                target = "metadata.test" if self.path == "/go" else "127.0.0.1"
                self.send_response(302)
                self.send_header("Location", f"http://{target}:{port}/secret")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if self.path == "/":
                body, kind = (PAGE % {"port": port}).encode(), "text/html"
            elif self.path == "/secret":
                body, kind = SECRET, "text/html"
            else:
                body, kind = b"x", "image/png"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


async def render(
    settings, repo, clock, path: str, hits: list[tuple[str, str]], proxy_resolver=fake_resolver
) -> str:
    server = start_server(hits)
    port = server.server_address[1]

    async def to_local_server(address: str, _port: int):  # every checked address → the server
        return await asyncio.open_connection("127.0.0.1", port)

    respx.get(f"http://site.test:{port}/robots.txt").respond(404)  # httpx side only
    try:
        async with make_client(settings) as client:
            fetcher = PoliteFetcher(settings, client, repo=repo, resolver=fake_resolver,
                                    clock=clock, sleep=clock.sleep)  # fmt: skip
            proxy = GuardProxy(resolver=proxy_resolver, connect=to_local_server)
            try:
                async with PlaywrightRenderer(settings, fetcher, proxy=proxy) as renderer:
                    return await renderer.render(f"http://site.test:{port}{path}")
            except RenderUnavailable as exc:
                pytest.skip(str(exc))
    finally:
        server.shutdown()


@respx.mock
async def test_real_browser_render_with_guards(settings, repo, clock) -> None:
    hits: list[tuple[str, str]] = []
    html = await render(settings, repo, clock, "/", hits)
    assert "hello@site.test" in html  # content that only exists after JavaScript ran
    paths = [path for _, path in hits]
    assert "/" in paths
    assert "/logo.png" not in paths  # images are never loaded
    assert not any(host.startswith("metadata.test") for host, _ in hits)  # SSRF guard


@respx.mock
async def test_redirect_to_private_host_is_never_requested(settings, repo, clock) -> None:
    hits: list[tuple[str, str]] = []
    with pytest.raises(FetchError, match=r"non-public address 169\.254\.169\.254"):
        await render(settings, repo, clock, "/go", hits)
    # Chromium followed the redirect, but the proxy refused metadata.test before connecting.
    assert [path for _, path in hits] == ["/go"]


@respx.mock
async def test_dns_rebinding_to_private_address_is_never_requested(settings, repo, clock) -> None:
    # The fetcher's check saw a public address; at connect time site.test resolves to loopback.
    async def rebound(host: str, port: int) -> list[str]:
        return ["127.0.0.1"]

    hits: list[tuple[str, str]] = []
    with pytest.raises(FetchError, match=r"non-public address 127\.0\.0\.1"):
        await render(settings, repo, clock, "/", hits, proxy_resolver=rebound)
    assert hits == []


@respx.mock
async def test_redirect_to_a_loopback_ip_goes_through_the_proxy_too(settings, repo, clock) -> None:
    # Chromium skips proxies for loopback unless told not to; Playwright tells it not to.
    hits: list[tuple[str, str]] = []
    with pytest.raises(FetchError, match=r"non-public address 127\.0\.0\.1"):
        await render(settings, repo, clock, "/go-loopback", hits)
    assert [path for _, path in hits] == ["/go-loopback"]
