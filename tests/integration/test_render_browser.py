"""Real Chromium against a local server. Skipped unless the `js` extra and Chromium are installed.

Chromium maps the test hostnames to 127.0.0.1, so nothing leaves the machine; the SSRF guard
sees them through the fake resolver (site.test → public, metadata.test → 169.254.169.254).
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import respx

from leadharvest.enrich import fetcher as fetcher_module
from leadharvest.enrich.fetcher import FetchError, PoliteFetcher
from leadharvest.enrich.netguard import is_public_ip
from leadharvest.enrich.render import PlaywrightRenderer, RenderUnavailable, playwright_installed
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


def start_server() -> tuple[ThreadingHTTPServer, list[tuple[str, str]]]:
    hits: list[tuple[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            hits.append((self.headers.get("Host", ""), self.path))
            port = self.server.server_address[1]
            if self.path == "/go":  # a public page redirecting the browser to a private host
                self.send_response(302)
                self.send_header("Location", f"http://metadata.test:{port}/secret")
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
    return server, hits


async def render(settings, repo, clock, path: str) -> tuple[str, list[tuple[str, str]]]:
    server, hits = start_server()
    port = server.server_address[1]
    respx.get(f"http://site.test:{port}/robots.txt").respond(404)  # httpx side only
    try:
        async with make_client(settings) as client:
            fetcher = PoliteFetcher(settings, client, repo=repo, resolver=fake_resolver,
                                    clock=clock, sleep=clock.sleep)  # fmt: skip
            fetcher.via_proxy = False
            rules = "MAP site.test 127.0.0.1, MAP metadata.test 127.0.0.1"
            try:
                renderer = PlaywrightRenderer(
                    settings, fetcher, launch_args=[f"--host-resolver-rules={rules}"]
                )
                async with renderer:
                    return await renderer.render(f"http://site.test:{port}{path}"), hits
            except RenderUnavailable as exc:
                pytest.skip(str(exc))
    finally:
        server.shutdown()


@pytest.fixture
def loopback_is_public(monkeypatch: pytest.MonkeyPatch) -> None:
    """The test server really is on 127.0.0.1; let the peer check accept it."""
    monkeypatch.setattr(
        fetcher_module, "is_public_ip", lambda a: a == "127.0.0.1" or is_public_ip(a)
    )


@respx.mock
async def test_real_browser_render_with_guards(settings, repo, clock, loopback_is_public) -> None:
    html, hits = await render(settings, repo, clock, "/")
    assert "hello@site.test" in html  # content that only exists after JavaScript ran
    paths = [path for _, path in hits]
    assert "/" in paths
    assert "/logo.png" not in paths  # images are never loaded
    assert not any(host.startswith("metadata.test") for host, _ in hits)  # SSRF guard


@respx.mock
async def test_redirect_to_private_host_is_never_read(
    settings, repo, clock, loopback_is_public
) -> None:
    with pytest.raises(FetchError, match="non-public"):
        await render(settings, repo, clock, "/go")


@respx.mock
async def test_dns_rebinding_to_private_address_is_never_read(settings, repo, clock) -> None:
    # The resolver says site.test is public, but Chromium connects to 127.0.0.1.
    with pytest.raises(FetchError, match=r"non-public 127.0.0.1"):
        await render(settings, repo, clock, "/")
