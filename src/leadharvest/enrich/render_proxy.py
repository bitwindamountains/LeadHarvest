"""A local forward proxy for the JS renderer's Chromium: the browser's only way out, so every
connection it makes, redirect hops included, passes the SSRF guard at connect time. Like
`netguard.PublicOnlyBackend` for httpx, it resolves the host itself, refuses non-public
addresses and connects to the very address it checked.

https goes through CONNECT tunnels (the proxy never sees inside); plain http requests are
forwarded one per connection (`Connection: close`), so a reused browser connection can't
switch hosts behind the check. Playwright sends loopback traffic through the proxy too.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from leadharvest.enrich.netguard import (
    BlockedAddress,
    Resolver,
    assert_public_host,
    system_resolver,
)
from leadharvest.logging_setup import get_logger

log = get_logger("render.proxy")

BLOCKED_HEADER = "X-LeadHarvest-Blocked"  # on the proxy's 403, read by the renderer
_MAX_HEAD = 64 * 1024
_DROP_HEADERS = (b"proxy-connection", b"proxy-authorization", b"connection", b"keep-alive")

Streams = tuple[asyncio.StreamReader, asyncio.StreamWriter]
Connect = Callable[[str, int], Awaitable[Streams]]


class GuardProxy:
    def __init__(
        self,
        *,
        resolver: Resolver = system_resolver,
        connect: Connect = asyncio.open_connection,
        timeout: float = 15,
    ) -> None:
        self._resolver = resolver
        self._connect = connect
        self._timeout = timeout
        self._server: asyncio.Server | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self.url = ""

    async def __aenter__(self) -> GuardProxy:
        self._server = await asyncio.start_server(self._accept, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._server is not None:
            self._server.close()
        for task in list(self._tasks):  # open tunnels; wait_closed would wait for them
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._server is not None:
            await self._server.wait_closed()

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        self._tasks.add(task)
        try:
            await self._handle(reader, writer)
        except (OSError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError):
            pass  # the browser gave up, or sent something we don't proxy
        finally:
            self._tasks.discard(task)
            writer.close()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), self._timeout)
        if len(head) > _MAX_HEAD:
            return
        request_line, _, rest = head.partition(b"\r\n")
        method, target, version = request_line.decode("latin-1").split(" ")
        if method == "CONNECT":
            host, _, port_text = target.rpartition(":")
            port, forward = int(port_text), None
        else:
            parts = urlsplit(target)
            if parts.scheme != "http" or not parts.hostname:
                return
            host, port = parts.hostname, parts.port or 80
            path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
            forward = _origin_request(method, path, version, rest)
        try:
            upstream_reader, upstream_writer = await self._open(host.strip("[]"), port)
        except BlockedAddress as exc:
            log.info("render proxy blocked %s: %s", host, exc)
            reason = str(exc).encode("latin-1", "replace")
            writer.write(
                b"HTTP/1.1 403 Forbidden\r\n" + BLOCKED_HEADER.encode() + b": " + reason
                + b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            )  # fmt: skip
            await writer.drain()
            return
        try:
            if forward is None:
                writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                await writer.drain()
            else:
                upstream_writer.write(forward)
                await upstream_writer.drain()
            await asyncio.gather(
                _pipe(reader, upstream_writer), _pipe(upstream_reader, writer),
                return_exceptions=True,
            )  # fmt: skip
        finally:
            upstream_writer.close()

    async def _open(self, host: str, port: int) -> Streams:
        """Connect to the first reachable checked address (BlockedAddress if any is private)."""
        try:
            addresses = await assert_public_host(host, port, self._resolver)
        except OSError as exc:
            raise ConnectionError(f"DNS lookup failed for {host}: {exc}") from exc
        error: OSError | None = None
        for address in addresses:
            try:
                return await asyncio.wait_for(self._connect(address, port), self._timeout)
            except (OSError, TimeoutError) as exc:
                error = exc if isinstance(exc, OSError) else ConnectionError(str(exc))
        assert error is not None  # assert_public_host returns at least one address
        raise error


def _origin_request(method: str, path: str, version: str, rest: bytes) -> bytes:
    """The browser's absolute-form proxy request as the server expects it: origin-form, no
    proxy headers, and one request per connection."""
    lines = [
        line for line in rest.split(b"\r\n")
        if line and line.split(b":", 1)[0].strip().lower() not in _DROP_HEADERS
    ]  # fmt: skip
    first = f"{method} {path} {version}".encode("latin-1")
    return b"\r\n".join([first, *lines, b"Connection: close"]) + b"\r\n\r\n"


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    with contextlib.suppress(OSError):
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    with contextlib.suppress(OSError):
        if writer.can_write_eof():
            writer.write_eof()
