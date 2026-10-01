"""Real Chromium against a local server. Skipped unless the `js` extra and Chromium are installed.

Chromium maps the test hostnames to 127.0.0.1, so nothing leaves the machine; the SSRF guard
sees them through the fake resolver (site.test → public, metadata.test → 169.254.169.254).
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import respx

from leadharvest.enrich.fetcher import PoliteFetcher
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


def start_server() -> tuple[ThreadingHTTPServer, list[tuple[str, str]]]:
    hits: list[tuple[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            hits.append((self.headers.get("Host", ""), self.path))
            port = self.server.server_address[1]
            body = (PAGE % {"port": port}).encode() if self.path == "/" else b"x"
            self.send_response(200)
            self.send_header("Content-Type", "text/html" if self.path == "/" else "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, hits


@respx.mock
async def test_real_browser_render_with_guards(settings, repo, clock) -> None:
    server, hits = start_server()
    port = server.server_address[1]
    respx.get(f"http://site.test:{port}/robots.txt").respond(404)  # httpx side only
    try:
        async with make_client(settings) as client:
            fetcher = PoliteFetcher(settings, client, repo=repo, resolver=fake_resolver,
                                    clock=clock, sleep=clock.sleep)  # fmt: skip
            rules = "MAP site.test 127.0.0.1, MAP metadata.test 127.0.0.1"
            try:
                renderer = PlaywrightRenderer(
                    settings, fetcher, launch_args=[f"--host-resolver-rules={rules}"]
                )
                async with renderer:
                    html = await renderer.render(f"http://site.test:{port}/")
            except RenderUnavailable as exc:
                pytest.skip(str(exc))
    finally:
        server.shutdown()
    assert "hello@site.test" in html  # content that only exists after JavaScript ran
    paths = [path for _, path in hits]
    assert "/" in paths
    assert "/logo.png" not in paths  # images are never loaded
    assert not any(host.startswith("metadata.test") for host, _ in hits)  # SSRF guard
