"""The JS renderer's guard proxy, driven over local sockets (no browser, no network)."""

from __future__ import annotations

import asyncio

from leadharvest.enrich.render_proxy import BLOCKED_HEADER, GuardProxy
from tests.conftest import fake_resolver


async def _upstream() -> tuple[asyncio.Server, int, list[bytes]]:
    """A local 'website' that records what it receives and answers once."""
    received: list[bytes] = []

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        received.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1], received


async def _ask(proxy: GuardProxy, request: bytes) -> bytes:
    host, port = proxy.url.removeprefix("http://").split(":")
    reader, writer = await asyncio.open_connection(host, int(port))
    writer.write(request)
    await writer.drain()
    reply = await asyncio.wait_for(reader.read(65536), 5)
    writer.close()
    return reply


async def test_plain_http_is_forwarded_in_origin_form_to_the_checked_address() -> None:
    server, port, received = await _upstream()
    connected: list[str] = []

    async def connect(address: str, _port: int):
        connected.append(address)
        return await asyncio.open_connection("127.0.0.1", port)

    async with GuardProxy(resolver=fake_resolver, connect=connect) as proxy:
        reply = await _ask(proxy, b"GET http://site.test/a?b=1 HTTP/1.1\r\nHost: site.test\r\n"
                                  b"Proxy-Connection: keep-alive\r\n\r\n")  # fmt: skip
    server.close()
    assert reply.endswith(b"ok")
    assert connected == ["93.184.216.34"]  # the address that was checked, not the name
    head = received[0].decode()
    assert head.startswith("GET /a?b=1 HTTP/1.1\r\n")
    assert "Proxy-Connection" not in head and "Connection: close" in head


async def test_private_addresses_are_refused_before_connecting() -> None:
    connected: list[str] = []

    async def connect(address: str, port: int):
        connected.append(address)
        raise AssertionError("must not connect")

    async with GuardProxy(resolver=fake_resolver, connect=connect) as proxy:
        for request in (
            b"GET http://metadata.test/latest HTTP/1.1\r\nHost: metadata.test\r\n\r\n",
            b"CONNECT private.test:443 HTTP/1.1\r\nHost: private.test:443\r\n\r\n",
            b"CONNECT 127.0.0.1:8501 HTTP/1.1\r\nHost: 127.0.0.1:8501\r\n\r\n",
            b"CONNECT [::1]:443 HTTP/1.1\r\nHost: [::1]:443\r\n\r\n",
        ):
            reply = await _ask(proxy, request)
            assert reply.startswith(b"HTTP/1.1 403")
            assert BLOCKED_HEADER.encode() + b": refusing to fetch" in reply
    assert connected == []


async def test_connect_tunnels_bytes_to_a_public_host() -> None:
    async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(await reader.read(100))
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(echo, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    async def connect(address: str, _port: int):
        return await asyncio.open_connection("127.0.0.1", port)

    async with GuardProxy(resolver=fake_resolver, connect=connect) as proxy:
        host, proxy_port = proxy.url.removeprefix("http://").split(":")
        reader, writer = await asyncio.open_connection(host, int(proxy_port))
        writer.write(b"CONNECT site.test:443 HTTP/1.1\r\nHost: site.test:443\r\n\r\n")
        assert await reader.readuntil(b"\r\n\r\n") == b"HTTP/1.1 200 Connection established\r\n\r\n"
        writer.write(b"tls bytes")
        assert await asyncio.wait_for(reader.read(100), 5) == b"tls bytes"
        writer.close()
    server.close()
