"""SSRF guard: never fetch private, loopback, link-local or reserved addresses (section 13).

Two layers: callers check a URL's host before requesting it (`assert_public_host`), and every
client from `http.make_client` connects only through `PublicOnlyBackend`, which checks again
and then connects to the very address it checked, so DNS rebinding can't send a request to a
private address in between."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

import httpcore
import httpx

Resolver = Callable[[str, int], Awaitable[list[str]]]


class BlockedAddress(Exception):
    def __init__(self, host: str, address: str) -> None:
        self.host = host
        self.address = address
        super().__init__(f"refusing to fetch {host}: resolves to non-public address {address}")


def is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


async def system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(info[4][0] for info in infos))


async def assert_public_host(
    host: str, port: int, resolver: Resolver = system_resolver
) -> list[str]:
    """The host's addresses; raises BlockedAddress if it is (or resolves to) any non-public IP."""
    host = host.strip("[]")
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        addresses = [host]
    except ValueError:
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise BlockedAddress(host, host) from None
        addresses = await resolver(host, port)
    if not addresses:
        raise BlockedAddress(host, "(no address)")
    for address in addresses:
        if not is_public_ip(address):
            raise BlockedAddress(host, address)
    return addresses


class PublicOnlyBackend(httpcore.AsyncNetworkBackend):
    """httpcore's connection layer, refusing non-public addresses at connect time. TLS still
    verifies the certificate against the URL's host name, which httpcore passes separately."""

    def __init__(self, inner: httpcore.AsyncNetworkBackend, resolver: Resolver) -> None:
        self._inner = inner
        self._resolver = resolver

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            addresses = await assert_public_host(host, port, self._resolver)
        except OSError as exc:  # DNS failure: what httpx reports for an unknown host
            raise httpcore.ConnectError(f"DNS lookup failed for {host}: {exc}") from exc
        error: Exception | None = None
        for address in addresses:  # each one checked above; try them in DNS order
            try:
                return await self._inner.connect_tcp(
                    address, port, timeout=timeout, local_address=local_address,
                    socket_options=socket_options,
                )  # fmt: skip
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                error = exc
        assert error is not None  # assert_public_host returns at least one address
        raise error

    async def connect_unix_socket(
        self, path: str, timeout: float | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:  # fmt: skip
        raise BlockedAddress(path, "(unix socket)")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def public_only_transport(resolver: Resolver = system_resolver) -> httpx.AsyncHTTPTransport:
    """httpx's transport, connecting through PublicOnlyBackend. Requests that go through an
    environment proxy use httpx's own proxy transport (the proxy is usually on the local
    network) and rely on the callers' host check."""
    transport = httpx.AsyncHTTPTransport()
    # httpx has no option for the backend; its pool keeps it here (httpx 0.28, httpcore 1.0).
    pool = transport._pool
    pool._network_backend = PublicOnlyBackend(pool._network_backend, resolver)
    return transport
