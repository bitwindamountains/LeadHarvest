"""Source protocol and registry (blueprint section 7)."""

from __future__ import annotations

from typing import Protocol

from leadharvest.models import RawBusiness, SearchQuery


class SourceError(Exception):
    """A source failed after retries and fallbacks. The run becomes `partial`."""


class Source(Protocol):
    name: str

    async def search(self, query: SearchQuery) -> list[RawBusiness]: ...
