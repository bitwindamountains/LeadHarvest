"""OpenStreetMap source via the Overpass API (blueprint section 10.2).

One Overpass query at a time; retries with backoff, then the next fallback URL.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from leadharvest.config import Settings
from leadharvest.http import Sleep, request_with_retry
from leadharvest.logging_setup import get_logger
from leadharvest.models import RawBusiness, ResolvedArea, SearchQuery
from leadharvest.sources.base import SourceError

log = get_logger("overpass")

OVERPASS_TIMEOUT_S = 90


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_query(area: ResolvedArea, osm_tags: list[str], *, out: str) -> str:
    """Build an Overpass QL query. `out` is e.g. 'count' or 'center tags 300'."""
    if area.kind == "area" and area.area_id is not None:
        header = f"area(id:{area.area_id})->.searchArea;\n"
        scope = "(area.searchArea)"
    elif area.bbox is not None:
        s, w, n, e = area.bbox
        header = ""
        scope = f"({s},{w},{n},{e})"
    else:
        raise ValueError("area has neither an area id nor a bbox")
    filters = []
    for tag in osm_tags:
        key, _, value = tag.partition("=")
        filters.append(f'  nwr["{_escape(key)}"="{_escape(value)}"]{scope};')
    body = "\n".join(filters)
    return f"[out:json][timeout:{OVERPASS_TIMEOUT_S}];\n{header}(\n{body}\n);\nout {out};"


def parse_count(data: dict[str, Any]) -> int:
    for element in data.get("elements", []):
        if element.get("type") == "count":
            return int(element.get("tags", {}).get("total", 0))
    return 0


def _first(tags: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = tags.get(key)
        if value and value.strip():
            return value.strip()
    return None


def parse_elements(data: dict[str, Any]) -> list[RawBusiness]:
    """Overpass JSON → RawBusiness. Records without a name are skipped."""
    records: list[RawBusiness] = []
    seen: set[str] = set()
    for el in data.get("elements", []):
        tags: dict[str, str] = el.get("tags") or {}
        name = _first(tags, "name", "name:en", "brand")
        el_type, el_id = el.get("type"), el.get("id")
        if not name or el_type not in ("node", "way", "relation") or el_id is None:
            continue
        ref = f"{el_type}/{el_id}"
        if ref in seen:
            continue
        seen.add(ref)
        if el_type == "node":
            lat, lon = el.get("lat"), el.get("lon")
        else:
            center = el.get("center") or {}
            lat, lon = center.get("lat"), center.get("lon")
        phones = [
            v for k in ("phone", "contact:phone", "contact:mobile", "mobile") if (v := tags.get(k))
        ]
        emails = [v for k in ("email", "contact:email") if (v := tags.get(k))]
        records.append(
            RawBusiness(
                source="osm",
                source_ref=ref,
                name=name,
                phones_raw=phones,
                website_raw=_first(tags, "website", "contact:website", "url"),
                emails_raw=emails,
                housenumber=_first(tags, "addr:housenumber"),
                street=_first(tags, "addr:street"),
                suburb=_first(tags, "addr:suburb", "addr:district"),
                city=_first(tags, "addr:city"),
                province=_first(tags, "addr:province", "addr:state"),
                facebook=_first(tags, "contact:facebook", "facebook"),
                instagram=_first(tags, "contact:instagram", "instagram"),
                opening_hours=_first(tags, "opening_hours"),
                lat=float(lat) if lat is not None else None,
                lon=float(lon) if lon is not None else None,
                payload={"type": el_type, "id": el_id, "tags": tags},
            )
        )
    return records


class OverpassClient:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient,
        *,
        sleep: Sleep = asyncio.sleep,
        base_delay: float = 2.0,
    ) -> None:
        self.urls = settings.overpass_url_list
        self.client = client
        self._sleep = sleep
        self._base_delay = base_delay
        self._lock = asyncio.Lock()  # one Overpass query at a time

    async def query(self, ql: str) -> dict[str, Any]:
        errors: list[str] = []
        async with self._lock:
            for url in self.urls:
                try:
                    response = await request_with_retry(
                        self.client,
                        "POST",
                        url,
                        data={"data": ql},
                        timeout=OVERPASS_TIMEOUT_S + 30,
                        sleep=self._sleep,
                        base_delay=self._base_delay,
                    )
                    response.raise_for_status()
                    data = response.json()
                    if "remark" in data and not data.get("elements"):
                        # Overpass reports runtime errors (e.g. timeouts) as a 200 with a remark.
                        raise SourceError(f"Overpass remark: {data['remark']}")
                    return data
                except (httpx.HTTPError, ValueError, SourceError) as exc:
                    log.warning("Overpass endpoint failed: %s (%s)", url, exc)
                    errors.append(f"{url}: {exc}")
        raise SourceError("All Overpass endpoints failed: " + "; ".join(errors))


class OsmOverpassSource:
    name = "osm"

    def __init__(self, client: OverpassClient) -> None:
        self.client = client
        self.last_total: int | None = None

    async def search(self, query: SearchQuery) -> list[RawBusiness]:
        area = query.area
        total = parse_count(await self.client.query(build_query(area, query.osm_tags, out="count")))
        if total == 0 and area.kind == "area" and area.bbox is not None:
            # A way that isn't a closed area yields nothing; fall back to its bounding box.
            area = ResolvedArea(
                kind="bbox", bbox=area.bbox, name=area.name, display_name=area.display_name
            )
            total = parse_count(
                await self.client.query(build_query(area, query.osm_tags, out="count"))
            )
        self.last_total = total
        if total == 0:
            return []
        data = await self.client.query(
            build_query(area, query.osm_tags, out=f"center tags {query.fetch_n}")
        )
        return parse_elements(data)
