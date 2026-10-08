"""robots.txt per origin, following RFC 9309.

- Group selection: the group whose user-agent matches our product token, else `*`.
- Rule selection: the longest matching path wins; on a tie, `allow` wins.
- Status: 2xx → parse; 4xx → everything allowed; 429, 5xx and unreachable → everything
  disallowed (429 means "slow down", never "go ahead", as Google treats it).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urlsplit

from leadharvest.storage.repository import Repository

UNREACHABLE = 0  # status stored when robots.txt could not be fetched at all


@dataclass
class RobotsRules:
    rules: list[tuple[bool, str]] = field(default_factory=list)  # (allow, pattern)
    allow_all: bool = False
    disallow_all: bool = False

    def allows(self, path: str) -> bool:
        if self.disallow_all:
            return False
        if self.allow_all:
            return True
        path = _normalize_path(path)
        best_len, best_allow = -1, True
        for allow, pattern in self.rules:
            if not pattern:
                continue
            if _matches(pattern, path):
                length = len(pattern)
                if length > best_len or (length == best_len and allow):
                    best_len, best_allow = length, allow
        return best_allow


def _normalize_path(path: str) -> str:
    return quote(unquote(path or "/"), safe="/?=&%*$:@!,;~+-._")


def _matches(pattern: str, path: str) -> bool:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in _normalize_path(body))
    return re.match(regex + ("$" if anchored else ""), path) is not None


def parse_robots(text: str, product: str) -> RobotsRules:
    product = product.lower()
    groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[bool, str]] = []
    last_was_agent = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if not last_was_agent and (agents or rules):
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
            last_was_agent = True
        elif key in ("allow", "disallow"):
            rules.append((key == "allow", value))
            last_was_agent = False
        else:
            last_was_agent = False
    if agents or rules:
        groups.append((agents, rules))

    def collect(predicate: Callable[[str], bool]) -> list[tuple[bool, str]] | None:
        matched = [r for a, r in groups if any(predicate(x) for x in a)]
        return [rule for group in matched for rule in group] if matched else None

    selected = collect(lambda a: a.split("/", 1)[0] == product) if product else None
    if selected is None:
        selected = collect(lambda a: a == "*")
    return RobotsRules(rules=selected or [])


def rules_for_status(status: int, text: str | None, product: str) -> RobotsRules:
    if 200 <= status < 300:
        return parse_robots(text or "", product)
    if 400 <= status < 500 and status != 429:
        return RobotsRules(allow_all=True)
    return RobotsRules(disallow_all=True)


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    port = parts.port or (443 if scheme == "https" else 80)
    return f"{scheme}://{(parts.hostname or '').lower()}:{port}"


RobotsFetch = Callable[[str], Awaitable[tuple[int, str | None]]]


class RobotsChecker:
    """Caches parsed rules in memory and raw robots.txt in SQLite (24 h TTL)."""

    def __init__(self, repo: Repository | None, product: str, fetch: RobotsFetch) -> None:
        self.repo = repo
        self.product = product
        self.fetch = fetch
        self._memory: dict[str, RobotsRules] = {}

    async def rules_for(self, url: str) -> RobotsRules:
        origin = origin_of(url)
        if origin in self._memory:
            return self._memory[origin]
        cached = self.repo.robots_cache_get(origin) if self.repo else None
        if cached is not None:
            text, status = cached
        else:
            status, text = await self.fetch(origin_to_robots_url(origin))
            if self.repo:
                self.repo.robots_cache_put(origin, text, status)
        rules = rules_for_status(status, text, self.product)
        self._memory[origin] = rules
        return rules

    async def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        return (await self.rules_for(url)).allows(path)


def origin_to_robots_url(origin: str) -> str:
    scheme, rest = origin.split("://", 1)
    host, port = rest.rsplit(":", 1)
    default = (scheme == "https" and port == "443") or (scheme == "http" and port == "80")
    return f"{scheme}://{host}{'' if default else ':' + port}/robots.txt"
