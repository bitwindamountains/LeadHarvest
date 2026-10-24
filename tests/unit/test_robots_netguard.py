import httpcore
import httpx
import pytest

from leadharvest.enrich.netguard import (
    BlockedAddress,
    PublicOnlyBackend,
    assert_public_host,
    is_public_ip,
    public_only_transport,
)
from leadharvest.enrich.robots import (
    RobotsChecker,
    origin_of,
    origin_to_robots_url,
    parse_robots,
    rules_for_status,
)
from tests.conftest import fake_resolver

ROBOTS = """
User-agent: Googlebot
Disallow: /

User-agent: *
Disallow: /private
Allow: /private/contact
Disallow: /*.pdf$

User-agent: LeadHarvest
User-agent: OtherBot
Disallow: /no-leadharvest
"""


def test_specific_group_wins_over_star() -> None:
    rules = parse_robots(ROBOTS, "LeadHarvest")
    assert not rules.allows("/no-leadharvest/page")
    assert rules.allows("/private")  # star group does not apply to us


def test_star_group_longest_match_and_wildcards() -> None:
    rules = parse_robots(ROBOTS, "SomeOtherBot")
    assert not rules.allows("/private/x")
    assert rules.allows("/private/contact")
    assert not rules.allows("/files/a.pdf")
    assert rules.allows("/files/a.pdf?x=1")
    assert rules.allows("/")


def test_allow_wins_ties_and_empty_disallow_allows() -> None:
    rules = parse_robots("User-agent: *\nDisallow: /page\nAllow: /page\n", "x")
    assert rules.allows("/page")
    assert parse_robots("User-agent: *\nDisallow:\n", "x").allows("/anything")


@pytest.mark.parametrize(
    ("status", "allowed"), [(200, None), (404, True), (403, True), (410, True), (429, False),
                            (500, False), (503, False), (0, False)],
)  # fmt: skip
def test_status_handling_rfc9309(status: int, allowed: bool | None) -> None:
    rules = rules_for_status(status, "User-agent: *\nDisallow: /x", "LeadHarvest")
    if allowed is None:
        assert not rules.allows("/x") and rules.allows("/")
    else:
        assert rules.allows("/") is allowed


def test_origin_helpers() -> None:
    assert origin_of("https://WWW.Clinic.ph/a?b") == "https://www.clinic.ph:443"
    assert origin_of("http://clinic.ph:8080/") == "http://clinic.ph:8080"
    assert origin_to_robots_url("https://clinic.ph:443") == "https://clinic.ph/robots.txt"
    assert origin_to_robots_url("http://clinic.ph:8080") == "http://clinic.ph:8080/robots.txt"


async def test_checker_caches_per_origin(repo) -> None:
    calls: list[str] = []

    async def fetch(url: str) -> tuple[int, str | None]:
        calls.append(url)
        return 200, "User-agent: *\nDisallow: /secret"

    checker = RobotsChecker(repo, "LeadHarvest", fetch)
    assert await checker.allowed("https://a.ph/")
    assert not await checker.allowed("https://a.ph/secret")
    assert await checker.allowed("https://shop.a.ph/secret") is False
    assert calls == ["https://a.ph/robots.txt", "https://shop.a.ph/robots.txt"]
    # A fresh checker reads the SQLite cache instead of fetching.
    checker2 = RobotsChecker(repo, "LeadHarvest", fetch)
    assert not await checker2.allowed("https://a.ph/secret")
    assert len(calls) == 2


@pytest.mark.parametrize(
    ("ip", "public"),
    [("93.184.216.34", True), ("10.1.2.3", False), ("192.168.1.1", False), ("127.0.0.1", False),
     ("169.254.169.254", False), ("0.0.0.0", False), ("::1", False), ("fe80::1", False),
     ("::ffff:10.0.0.1", False), ("224.0.0.1", False), ("100.64.0.1", False)],
)  # fmt: skip
def test_is_public_ip(ip: str, public: bool) -> None:
    assert is_public_ip(ip) is public


async def test_assert_public_host() -> None:
    await assert_public_host("clinic.ph", 443, fake_resolver)
    for host in (
        "private.test",
        "loopback.test",
        "metadata.test",
        "localhost",
        "10.0.0.1",
        "printer.local",
    ):
        with pytest.raises(BlockedAddress):
            await assert_public_host(host, 80, fake_resolver)


class RecordingBackend(httpcore.AsyncNetworkBackend):
    """Stands in for httpcore's real backend: records connects, fails the listed addresses."""

    def __init__(self, failing: tuple[str, ...] = ()) -> None:
        self.calls: list[str] = []
        self.failing = failing

    async def connect_tcp(self, host, port, timeout=None, local_address=None,
                          socket_options=None):  # fmt: skip
        self.calls.append(host)
        if host in self.failing:
            raise httpcore.ConnectError(f"refused by {host}")
        return "stream"

    async def sleep(self, seconds: float) -> None:
        pass


def _resolving_to(*addresses: str):
    async def resolver(host: str, port: int) -> list[str]:
        return list(addresses)

    return resolver


async def test_backend_refuses_private_addresses_before_connecting() -> None:
    inner = RecordingBackend()
    backend = PublicOnlyBackend(inner, _resolving_to("93.184.216.34", "10.0.0.5"))
    with pytest.raises(BlockedAddress, match=r"10.0.0.5"):
        await backend.connect_tcp("rebind.ph", 443)
    with pytest.raises(BlockedAddress):
        await backend.connect_tcp("127.0.0.1", 80)  # an IP in the URL itself
    with pytest.raises(BlockedAddress):
        await backend.connect_unix_socket("/var/run/docker.sock")
    assert inner.calls == []


async def test_backend_connects_to_the_address_it_checked() -> None:
    inner = RecordingBackend(failing=("2606:2800::1",))
    backend = PublicOnlyBackend(inner, _resolving_to("2606:2800::1", "93.184.216.34"))
    assert await backend.connect_tcp("site.ph", 443) == "stream"
    assert inner.calls == ["2606:2800::1", "93.184.216.34"]  # IPs, not the name; next on failure


async def test_backend_reports_dns_failure_as_a_connect_error() -> None:
    async def no_dns(host: str, port: int) -> list[str]:
        raise OSError("getaddrinfo failed")

    with pytest.raises(httpcore.ConnectError, match="DNS lookup failed"):
        await PublicOnlyBackend(RecordingBackend(), no_dns).connect_tcp("gone.ph", 443)


async def test_client_never_connects_to_a_private_address() -> None:
    """End to end through httpx, no network: the host resolves to loopback."""
    transport = public_only_transport(_resolving_to("127.0.0.1"))
    assert isinstance(transport._pool._network_backend, PublicOnlyBackend)  # httpx upgrades
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(BlockedAddress, match=r"127.0.0.1"):
            await client.get("http://rebind.test/")
