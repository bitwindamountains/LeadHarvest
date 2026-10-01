"""SSRF guard: never fetch private, loopback, link-local or reserved addresses (section 13)."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable

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


async def assert_public_host(host: str, port: int, resolver: Resolver = system_resolver) -> None:
    """Raise BlockedAddress if the host is (or resolves to) any non-public IP."""
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
