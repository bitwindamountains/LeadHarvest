import httpx
import pytest
import respx

from leadharvest.config import ConfigError, Settings, load_settings
from leadharvest.http import (
    MinIntervalLimiter,
    RetryableStatus,
    make_client,
    parse_retry_after,
    request_with_retry,
)
from leadharvest.logging_setup import redact


def _settings(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "ua",
    ["", "LeadHarvest/0.1 (+mailto:you@example.com)", "LeadHarvest/0.1"],
)
def test_user_agent_guard_rejects_placeholders(ua: str) -> None:
    with pytest.raises(ConfigError):
        _settings(user_agent=ua).require_network_identity()


def test_user_agent_guard_accepts_real_contact() -> None:
    s = _settings(user_agent="LeadHarvest/0.1 (+mailto:ops@realagency.ph)")
    s.require_network_identity()
    assert s.ua_product == "LeadHarvest"


def test_delay_floor_and_sheets_requirements(tmp_path) -> None:
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, per_domain_delay_seconds=0.5)
    s = _settings(google_sheet_id="")
    with pytest.raises(ConfigError):
        s.require_sheets()
    s2 = _settings(GOOGLE_SHEET_ID="abc", GOOGLE_SERVICE_ACCOUNT_FILE=tmp_path / "missing.json")
    with pytest.raises(ConfigError):
        s2.require_sheets()


def test_env_vars_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LH_CONCURRENCY", "3")
    monkeypatch.setenv("GOOGLE_SHEET_ID", "sheet123")
    s = _settings()
    assert s.concurrency == 3
    assert s.google_sheet_id == "sheet123"
    assert _settings(overpass_urls="a, b,").overpass_url_list == ["a", "b"]


def test_parse_retry_after() -> None:
    assert parse_retry_after("5") == 5.0
    assert parse_retry_after("999") == 60.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("garbage") is None
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


@respx.mock
async def test_request_with_retry_honors_retry_after_then_succeeds() -> None:
    waits: list[float] = []

    async def sleep(s: float) -> None:
        waits.append(s)

    respx.get("https://api.test/x").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(503),
        httpx.Response(200, json={"ok": True}),
    ])  # fmt: skip
    async with httpx.AsyncClient() as client:
        resp = await request_with_retry(
            client, "GET", "https://api.test/x", sleep=sleep, base_delay=1
        )
    assert resp.json() == {"ok": True}
    assert waits == [7.0, 2.0]


@respx.mock
async def test_request_with_retry_gives_up() -> None:
    async def sleep(_: float) -> None:
        return None

    respx.get("https://api.test/x").respond(500)
    async with httpx.AsyncClient() as client:
        with pytest.raises(RetryableStatus):
            await request_with_retry(client, "GET", "https://api.test/x", sleep=sleep)


async def test_min_interval_limiter(clock) -> None:
    limiter = MinIntervalLimiter(1.0, clock=clock, sleep=clock.sleep)
    await limiter.wait()
    await limiter.wait()
    await limiter.wait()
    assert clock.sleeps == [1.0, 1.0]


async def test_client_sends_user_agent() -> None:
    s = _settings(user_agent="LeadHarvest/0.1 (+mailto:ops@realagency.ph)")
    async with make_client(s) as client:
        assert client.headers["User-Agent"] == s.user_agent
        assert client.follow_redirects is False


def test_redaction() -> None:
    text = 'Authorization: Bearer abc.def.ghi token="s3cr3t" url?key=AIzaSyA1234567890abcdef'
    out = redact(text)
    assert "abc.def.ghi" not in out and "s3cr3t" not in out and "AIzaSy" not in out
    pem = "-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----"
    assert redact(pem) == "[REDACTED]"
