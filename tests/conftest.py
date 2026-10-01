"""Shared fixtures. Tests never touch the network (except `-m live`)."""

from __future__ import annotations

import ipaddress
import socket
from pathlib import Path

import pytest

from leadharvest.config import Settings
from leadharvest.storage.db import connect
from leadharvest.storage.repository import Repository

FIXTURES = Path(__file__).parent / "fixtures"
PUBLIC_IP = "93.184.216.34"
TEST_UA = "LeadHarvest/0.1 (+mailto:ops@leadharvest.test)"

_FAKE_DNS = {
    "private.test": ["10.0.0.5"],
    "loopback.test": ["127.0.0.1"],
    "metadata.test": ["169.254.169.254"],
    "evil-redirect.test": [PUBLIC_IP],
}


async def fake_resolver(host: str, port: int) -> list[str]:
    return _FAKE_DNS.get(host, [PUBLIC_IP])


class FakeClock:
    """Monotonic clock + sleep that advance virtual time instantly."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += max(0.0, seconds)


@pytest.fixture(autouse=True)
def _block_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if any test tries to reach a non-loopback address."""
    if request.node.get_closest_marker("live"):
        return
    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: object) -> object:
        host = address[0] if isinstance(address, tuple) else None
        if isinstance(host, str):
            try:
                if not ipaddress.ip_address(host).is_loopback:
                    raise RuntimeError(f"network access in tests: {address}")
            except ValueError:
                raise RuntimeError(f"network access in tests: {address}") from None
        return real_connect(self, address)

    real_getaddrinfo = socket.getaddrinfo

    def guarded_getaddrinfo(host: object, *args: object, **kwargs: object) -> object:
        if host not in (None, "localhost", "127.0.0.1", "::1"):
            raise RuntimeError(f"DNS lookup in tests: {host}")
        return real_getaddrinfo(host, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        user_agent=TEST_UA,
        db_path=tmp_path / "leads.db",
        export_dir=tmp_path / "exports",
        log_dir=tmp_path / "logs",
        per_domain_delay_seconds=2,
        overpass_urls="https://overpass.test/api/interpreter,https://overpass2.test/api/interpreter",
        nominatim_url="https://nominatim.test/search",
    )


@pytest.fixture
def repo(settings: Settings) -> Repository:
    conn = connect(settings.db_path)
    yield Repository(conn)
    conn.close()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def read_fixture(*parts: str) -> str:
    return FIXTURES.joinpath(*parts).read_text(encoding="utf-8")
