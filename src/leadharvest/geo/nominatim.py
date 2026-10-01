"""Location text → OSM area or bounding box via Nominatim (blueprint section 10.2).

Usage policy: at most 1 request per second, cached, with an identifying User-Agent.
"""

from __future__ import annotations

from typing import Any

import httpx

from leadharvest.config import Settings
from leadharvest.http import MinIntervalLimiter, request_with_retry
from leadharvest.models import ResolvedArea
from leadharvest.storage.repository import Repository

RELATION_AREA_OFFSET = 3_600_000_000
WAY_AREA_OFFSET = 2_400_000_000


class LocationNotFound(Exception):
    def __init__(self, location: str, suggestions: list[str] | None = None) -> None:
        self.location = location
        self.suggestions = suggestions or []
        super().__init__(f"Location not found: {location!r}")


class GeoError(Exception):
    """Nominatim could not be reached or answered with an error."""


def resolve_result(result: dict[str, Any]) -> ResolvedArea:
    """Turn one Nominatim jsonv2 result into an Overpass area or bbox."""
    osm_type = result.get("osm_type")
    osm_id = int(result.get("osm_id") or 0)
    name = result.get("name") or str(result.get("display_name", "")).split(",")[0].strip()
    display = str(result.get("display_name", ""))
    if osm_type == "relation" and osm_id:
        return ResolvedArea(
            kind="area", area_id=RELATION_AREA_OFFSET + osm_id, name=name, display_name=display
        )
    if osm_type == "way" and osm_id:
        return ResolvedArea(
            kind="area",
            area_id=WAY_AREA_OFFSET + osm_id,
            name=name,
            display_name=display,
            bbox=_bbox(result),
        )
    bbox = _bbox(result)
    if bbox is None:
        raise ValueError("result has neither a usable osm_type nor a bounding box")
    return ResolvedArea(kind="bbox", bbox=bbox, name=name, display_name=display)


def _bbox(result: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """Nominatim boundingbox is [south, north, west, east]; we use (south, west, north, east)."""
    box = result.get("boundingbox")
    if not box or len(box) != 4:
        return None
    south, north, west, east = (float(x) for x in box)
    return (south, west, north, east)


class NominatimClient:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient,
        repo: Repository,
        *,
        limiter: MinIntervalLimiter | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self.repo = repo
        self.limiter = limiter or MinIntervalLimiter(1.0)

    async def search(self, location: str, *, any_country: bool = False) -> list[dict[str, Any]]:
        region = "" if any_country else self.settings.default_region.lower()
        key = f"v1|{region}|{' '.join(location.lower().split())}"
        cached = self.repo.geo_cache_get(key)
        if cached is not None:
            return cached
        params = {"q": location, "format": "jsonv2", "limit": "3"}
        if region:
            params["countrycodes"] = region
        await self.limiter.wait()
        try:
            response = await request_with_retry(
                self.client, "GET", self.settings.nominatim_url, params=params
            )
            response.raise_for_status()
            results = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GeoError(f"Nominatim request failed: {exc}") from exc
        if not isinstance(results, list):
            raise GeoError("Nominatim returned an unexpected response")
        if results:
            self.repo.geo_cache_put(key, results)
        return results

    async def resolve(
        self, location: str, *, any_country: bool = False
    ) -> tuple[ResolvedArea, list[str]]:
        """Resolve to the first usable result; also return the other candidates' names."""
        results = await self.search(location, any_country=any_country)
        others: list[str] = []
        for i, result in enumerate(results):
            try:
                area = resolve_result(result)
            except ValueError:
                continue
            others = [str(r.get("display_name", "")) for j, r in enumerate(results) if j != i]
            return area, others
        raise LocationNotFound(location, [str(r.get("display_name", "")) for r in results[:3]])
